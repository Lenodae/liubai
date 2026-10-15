import datetime as dt
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from execution.models import Profile
from load_analysis import deadlines, workspace
from load_analysis.models import CapacityWindow, TaskPlan
from tasks.models import Task
from tasks.services import ApiError


class DeadlineBridgeTests(TestCase):
    def setUp(self):
        self.clock = timezone.make_aware(dt.datetime(2026, 10, 14, 12))
        self.mock_clock = patch("load_analysis.workspace.now", return_value=self.clock)
        self.mock_clock.start()
        self.addCleanup(self.mock_clock.stop)
        self.user = get_user_model().objects.create_user("deadline_bridge")
        self.other = get_user_model().objects.create_user("deadline_other")
        self.week = dt.date(2026, 10, 12)
        self.task = self.new_task("有限目标", self.week + dt.timedelta(days=6))
        self.window = self.new_window(self.week)
        self.plan = self.new_plan(self.window, self.task)

    def new_task(self, title, deadline=None):
        task = Task.objects.create(
            owner=self.user,
            title=title,
            status="in_progress",
            request_key=uuid.uuid4(),
            request_fingerprint="fixture",
        )
        if deadline:
            Profile.objects.create(task=task, deadline=deadline)
        return task

    def new_window(self, week, mode="week"):
        return CapacityWindow.objects.create(
            owner=self.user,
            week=week,
            mode=mode,
            budget_minutes=600,
            buffer_minutes=120,
            as_of=self.clock,
            source_token=workspace.facts_token(self.user.pk),
        )

    def new_plan(self, window, task, **overrides):
        values = {
            "progress_low": 420,
            "progress_high": 600,
            "maintenance_low": 0,
            "maintenance_high": 0,
            "maintenance_active": False,
            "scope_confirmed": True,
            "remaining_low": 600,
            "remaining_high": 600,
            "source_version": task.version,
            "source_status": task.status,
            "confirmed_at": self.clock,
            "remaining_source_version": task.version,
            "remaining_confirmed_at": self.clock,
        }
        return TaskPlan.objects.create(window=window, task=task, **(values | overrides))

    def check_for(self, result, target):
        return next(item for item in result["checks"] if item["deadline"] == target.isoformat())

    def test_default_forecast_is_readonly_and_sunday_capacity_is_shared(self):
        counts = (CapacityWindow.objects.count(), TaskPlan.objects.count(), Task.objects.count())
        result = deadlines.get(self.user.pk, self.week, "week")
        self.assertEqual(
            (CapacityWindow.objects.count(), TaskPlan.objects.count(), Task.objects.count()), counts
        )
        self.assertEqual(len(result["forecast_slices"]), 4)
        self.assertEqual(result["slices"], [])
        check = self.check_for(result, self.week + dt.timedelta(days=6))
        self.assertEqual(
            (check["verdict"], check["capacity"], check["deficit_low"]), ("conflict", 480, 120)
        )
        self.assertEqual(result["work"][0]["status"], "in_progress")

    def test_cross_week_counts_maintenance_once_and_does_not_add_goal_progress(self):
        target = self.week + dt.timedelta(days=13)
        Profile.objects.filter(task=self.task).update(deadline=target)
        self.plan.remaining_low = self.plan.remaining_high = 800
        self.plan.maintenance_active = True
        self.plan.maintenance_low = self.plan.maintenance_high = 30
        self.plan.save()
        future = self.new_window(self.week + dt.timedelta(days=7))
        self.new_plan(
            future, self.task, maintenance_active=True, maintenance_low=30, maintenance_high=30
        )
        result = deadlines.get(self.user.pk, self.week, "week")
        check = self.check_for(result, target)
        self.assertEqual((check["verdict"], check["low"], check["capacity"]), ("fits", 800, 900))
        future.budget_minutes = None
        future.save()
        result = deadlines.get(self.user.pk, self.week, "week")
        self.assertEqual(self.check_for(result, target)["verdict"], "unknown")

    def test_saved_slices_expire_when_task_or_plan_sources_change(self):
        target = self.week + dt.timedelta(days=4)
        Profile.objects.filter(task=self.task).update(deadline=target)
        self.window.slices = [
            {
                "end": target.isoformat(),
                "budget_minutes": 300,
                "buffer_minutes": 60,
                "other_minutes": 0,
            },
            {
                "end": (self.week + dt.timedelta(days=6)).isoformat(),
                "budget_minutes": 300,
                "buffer_minutes": 60,
                "other_minutes": 0,
            },
        ]
        original = deadlines.source_token(self.user.pk, self.window)
        self.window.slices_source = original
        self.window.save()
        result = deadlines.get(self.user.pk, self.week, "week")
        self.assertEqual(self.check_for(result, target)["capacity"], 240)
        self.window.version += 1
        self.window.save()
        self.assertEqual(deadlines.source_token(self.user.pk, self.window), original)
        self.plan.version += 1
        self.plan.save()
        self.assertNotEqual(deadlines.source_token(self.user.pk, self.window), original)
        self.assertEqual(
            self.check_for(deadlines.get(self.user.pk, self.week, "week"), target)["verdict"],
            "unknown",
        )
        fresh = deadlines.source_token(self.user.pk, self.window)
        self.task.version += 1
        self.task.save()
        self.assertNotEqual(deadlines.source_token(self.user.pk, self.window), fresh)

    def test_unknown_other_and_overcommitment_never_become_false_fit(self):
        self.plan.remaining_low = self.plan.remaining_high = 30
        self.plan.save()
        other = self.new_task("其他承诺")
        other_plan = self.new_plan(
            self.window,
            other,
            progress_low=600,
            progress_high=600,
            remaining_low=None,
            remaining_high=None,
        )
        result = deadlines.get(self.user.pk, self.week, "week")
        self.assertTrue(any(item["verdict"] == "conflict" for item in result["checks"]))
        self.assertTrue(
            any(item["deficit_low"] and item["deficit_low"] >= 120 for item in result["checks"])
        )
        other_plan.scope_confirmed = False
        other_plan.save()
        result = deadlines.get(self.user.pk, self.week, "week")
        self.assertEqual(
            self.check_for(result, self.week + dt.timedelta(days=6))["verdict"], "unknown"
        )

    def test_completed_parent_uses_real_status_and_current_remaining_estimate(self):
        self.task.status = "completed"
        self.task.version += 1
        self.task.save()
        result = deadlines.get(self.user.pk, self.week, "week")
        self.assertFalse(any(str(self.task.id) in item["task_ids"] for item in result["checks"]))
        self.task.status = "in_progress"
        self.task.save()
        result = deadlines.get(self.user.pk, self.week, "week")
        self.assertEqual(
            self.check_for(result, self.week + dt.timedelta(days=6))["verdict"], "unknown"
        )

    def test_remaining_without_saved_timestamp_and_other_account_are_safe(self):
        result = deadlines.get(self.user.pk, self.week, "remaining")
        self.assertEqual(result["window"]["start"], "2026-10-14")
        self.assertTrue(all(item["verdict"] == "unknown" for item in result["checks"]))
        other = deadlines.get(self.other.pk, self.week, "week")
        self.assertEqual(other["work"], [])
        self.assertEqual(other["checks"], [])

    def test_manual_segments_cannot_erase_known_maintenance_or_unknown_occupancy(self):
        self.plan.maintenance_active = True
        self.plan.maintenance_low = self.plan.maintenance_high = 180
        self.plan.save()
        portion = {
            "end": "2026-10-18",
            "budget_minutes": 600,
            "buffer_minutes": 120,
            "other_minutes": 0,
        }
        current = workspace.build(self.user.pk, self.week, "week")
        with self.assertRaises(ApiError):
            deadlines.validate_other(self.user.pk, self.week, "week", [portion], current)
        portion["other_minutes"] = 180
        self.assertIsNone(
            deadlines.validate_other(self.user.pk, self.week, "week", [portion], current)
        )
        self.plan.maintenance_high = self.plan.maintenance_low = None
        self.plan.save()
        current = workspace.build(self.user.pk, self.week, "week")
        with self.assertRaises(ApiError):
            deadlines.validate_other(self.user.pk, self.week, "week", [portion], current)
        portion["other_minutes"] = None
        self.assertIsNone(
            deadlines.validate_other(self.user.pk, self.week, "week", [portion], current)
        )

    def test_future_saved_segments_are_rechecked_against_current_horizon(self):
        Profile.objects.filter(task=self.task).update(deadline=self.week + dt.timedelta(days=34))
        future = self.new_window(self.week + dt.timedelta(days=7))
        self.new_plan(future, self.task, progress_low=300, progress_high=300)
        future.slices = [
            {"end": "2026-10-25", "budget_minutes": 600, "buffer_minutes": 120, "other_minutes": 0}
        ]
        future.slices_source = deadlines.source_token(self.user.pk, future)
        future.save()
        own = workspace.build(self.user.pk, future.week, "week")
        self.assertIsNone(
            deadlines.validate_other(self.user.pk, future.week, "week", future.slices, own)
        )
        result = deadlines.get(self.user.pk, self.week, "week")
        future_slice = next(
            item for item in result["forecast_slices"] if item["end"] == "2026-10-25"
        )
        self.assertEqual(future_slice["other_minutes"], 300)
