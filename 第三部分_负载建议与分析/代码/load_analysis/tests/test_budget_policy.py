"""Acceptance examples for weekly reservations, separate from execution progress."""

import datetime as dt
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from load_analysis.models import CapacityWindow, LoadSnapshot, TaskPlan
from tasks.models import Task


class BudgetPolicyTests(TestCase):
    def setUp(self):
        self.clock = timezone.make_aware(dt.datetime(2026, 10, 14, 12))
        self.timer = patch("load_analysis.workspace.now", return_value=self.clock)
        self.timer.start()
        self.addCleanup(self.timer.stop)
        self.owner = get_user_model().objects.create_user("reserve", password="other-person-123")
        self.client.force_login(self.owner)
        self.week = "2026-10-12"

    def create(self, **fields):
        payload = {
            "title": "本周承诺",
            "weekly_minutes": 180,
            "budget_schedule": "weekly",
            "budget_week": self.week,
            "status": "in_progress",
            **fields,
        }
        response = self.client.post(
            "/api/tasks",
            payload,
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()["task"]

    def get(self, week=None, mode="week"):
        response = self.client.get("/api/load/workspace", {"week": week or self.week, "mode": mode})
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def change(self, task, **fields):
        response = self.client.patch(
            f"/api/tasks/{task['id']}",
            {"version": task["version"], **fields},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["task"]

    def write(self, operation, **fields):
        current = self.get()
        response = self.client.post(
            f"/api/load/{operation}",
            {"week": self.week, "mode": "week", "fingerprint": current["fingerprint"], **fields},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_weekly_idea_waits_until_started_before_occupying_budget(self):
        task = self.create(status="planned")
        current = self.get()
        self.assertEqual(task["status"], "planned")
        self.assertEqual(task["budget_schedule"], "weekly")
        self.assertEqual(current["tasks"][0]["allocation_source"], "none")
        self.assertIsNone(current["tasks"][0]["reservation_minutes"])
        self.assertEqual((current["analysis"]["low"], current["analysis"]["high"]), (0, 0))
        self.assertEqual(TaskPlan.objects.count(), 0)
        self.assertEqual(CapacityWindow.objects.count(), 0)

    def test_weekly_and_recurring_are_different_in_next_week(self):
        self.create()
        self.create(title="持续事项", budget_schedule="recurring")
        self.assertEqual(self.get()["analysis"]["low"], 360)
        future = self.get(week="2026-10-19")
        self.assertEqual(future["analysis"]["low"], 180)
        self.assertEqual(sum(t["allocation_source"] == "auto" for t in future["tasks"]), 1)

    def test_start_pause_and_resume_gate_total_reservation(self):
        task = self.create(status="planned", budget_schedule="recurring")
        task = self.change(task, status="in_progress")
        self.assertEqual(self.get()["analysis"]["low"], 180)
        task = self.change(task, status="paused")
        self.assertEqual(self.get()["analysis"]["low"], 0)
        self.change(task, status="in_progress")
        self.assertEqual(self.get()["analysis"]["low"], 180)

    def test_unknown_and_explicit_zero_remain_different(self):
        self.create(weekly_minutes=None)
        self.assertIsNone(self.get()["analysis"]["low"])
        self.assertIn("reservation_minutes", self.get()["analysis"]["unknowns"][1]["fields"])
        self.create(weekly_minutes=0)
        self.assertEqual(self.get()["analysis"]["known_low"], 0)

    def test_remaining_view_does_not_copy_whole_week_or_actual(self):
        self.create(status="in_progress")
        task = self.get(mode="remaining")["tasks"][0]
        self.assertIsNone(task["progress_low"])
        self.assertIsNone(task["remaining_low"])
        self.assertIsNone(task["reservation_minutes"])
        self.assertEqual(task["allocation_source"], "none")
        self.assertIsNone(self.get(mode="remaining")["window"]["as_of"])

    def test_manual_zero_overrides_automatic_without_erasing_task_budget(self):
        task = self.create()
        result = self.write(
            "settings",
            action="plan",
            task_id=task["id"],
            progress_low=0,
            progress_high=0,
            maintenance_low=0,
            maintenance_high=0,
            maintenance_active=False,
            scope_confirmed=True,
            remaining_low=None,
            remaining_high=None,
        )
        self.assertEqual(result["tasks"][0]["allocation_source"], "manual")
        self.assertEqual(result["analysis"]["low"], 0)
        self.assertEqual(Task.objects.get(id=task["id"]).weekly_minutes, 180)

    def test_completion_releases_future_and_undo_restores(self):
        task = self.create(status="in_progress", budget_schedule="recurring")
        finished = self.change(task, status="completed")
        self.assertEqual(self.get()["analysis"]["low"], 0)
        self.assertEqual(self.get(week="2026-10-19")["analysis"]["low"], 0)
        model = Task.objects.get(id=task["id"])
        self.assertIsNotNone(model.budget_policy.end_at)
        self.change(finished, status="in_progress")
        self.assertEqual(self.get()["analysis"]["low"], 180)

    def test_execution_completion_and_undo_use_same_policy_hook(self):
        task = self.create(status="in_progress", budget_schedule="recurring")
        response = self.client.post(
            f"/api/tasks/{task['id']}/workspace",
            {"version": task["version"], "action": "complete", "allow_unfinished": False},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.get()["analysis"]["low"], 0)
        model = Task.objects.get(id=task["id"])
        self.assertIsNotNone(model.budget_policy.end_at)
        response = self.client.post(
            f"/api/tasks/{task['id']}/workspace",
            {"version": model.version, "action": "undo"},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.get()["analysis"]["low"], 180)

    def test_end_does_not_erase_earlier_weeks_and_snapshot(self):
        task = self.create(budget_schedule="recurring", status="in_progress")
        self.write("settings", action="save_snapshot")
        snapshot = LoadSnapshot.objects.get()
        saved = snapshot.data
        with patch("load_analysis.workspace.now", return_value=self.clock + dt.timedelta(days=7)):
            self.change(task, status="completed")
            self.assertEqual(self.get()["analysis"]["low"], 180)
            self.assertEqual(self.get(week="2026-10-19")["analysis"]["low"], 0)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.data, saved)

    def test_amount_edit_preserves_ended_week_and_changes_current_week(self):
        task = self.create(budget_schedule="recurring")
        with patch("load_analysis.workspace.now", return_value=self.clock + dt.timedelta(days=7)):
            self.change(task, weekly_minutes=240)
            self.assertEqual(self.get()["analysis"]["low"], 180)
            self.assertEqual(self.get(week="2026-10-19")["analysis"]["low"], 240)

    def test_policy_fields_validate_and_stale_updates_cannot_partial_write(self):
        task = self.create()
        for fields in (
            {"budget_schedule": "none"},
            {"budget_week": "2026-10-13"},
            {"budget_week": True},
        ):
            response = self.client.patch(
                f"/api/tasks/{task['id']}",
                {"version": task["version"], **fields},
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 400)
        self.change(task, weekly_minutes=200)
        response = self.client.patch(
            f"/api/tasks/{task['id']}",
            {"version": task["version"], "budget_schedule": "recurring", "weekly_minutes": 300},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.get()["analysis"]["low"], 200)
        self.assertEqual(Task.objects.get(id=task["id"]).budget_policy.schedule, "weekly")

    def test_auto_preview_apply_and_undo_have_matching_total(self):
        task = self.create(status="in_progress")
        self.write("settings", action="capacity", budget_minutes=600, buffer_minutes=60)
        changes = [
            {
                "task_id": task["id"],
                "progress_low": 60,
                "progress_high": 60,
                "maintenance_low": 30,
                "maintenance_high": 30,
                "maintenance_active": True,
                "scope_confirmed": True,
            }
        ]
        preview = self.write("preview", changes=changes)
        applied = self.write("apply", changes=changes)
        self.assertEqual(preview["after"], applied["analysis"])
        self.assertEqual(applied["analysis"]["low"], 90)
        event = next(row for row in applied["history"] if row["kind"] == "apply")
        undone = self.write("undo", event_id=event["id"])
        self.assertEqual(undone["analysis"]["low"], 180)
        self.assertEqual(undone["tasks"][0]["allocation_source"], "auto")

    def test_auto_total_does_not_make_unknown_deadline_work_feasible(self):
        from execution.models import Profile

        task = self.create()
        Profile.objects.create(task_id=task["id"], deadline="2026-10-18")
        self.write("settings", action="capacity", budget_minutes=600, buffer_minutes=60)
        result = self.client.get("/api/load/deadlines", {"week": self.week, "mode": "week"}).json()
        self.assertEqual(result["checks"][0]["verdict"], "unknown")
        self.assertFalse(result["work"][0]["remaining_confirmed"])

    def test_available_interval_keeps_negative_deficit(self):
        self.create(weekly_minutes=180)
        result = self.write("settings", action="capacity", budget_minutes=150, buffer_minutes=0)
        self.assertEqual(
            (result["analysis"]["available_low"], result["analysis"]["available_high"]), (-30, -30)
        )

    def test_future_auto_candidate_is_not_added_to_its_remaining_goal(self):
        from execution.models import Profile

        task = self.create(status="in_progress", budget_schedule="recurring")
        Profile.objects.create(task_id=task["id"], deadline="2026-10-25")
        self.write("settings", action="capacity", budget_minutes=180, buffer_minutes=0)
        self.write(
            "settings",
            action="plan",
            task_id=task["id"],
            progress_low=60,
            progress_high=60,
            maintenance_low=0,
            maintenance_high=0,
            maintenance_active=False,
            scope_confirmed=True,
            remaining_low=300,
            remaining_high=300,
        )
        future = self.get(week="2026-10-19")
        response = self.client.post(
            "/api/load/settings",
            {
                "week": "2026-10-19",
                "mode": "week",
                "fingerprint": future["fingerprint"],
                "action": "capacity",
                "budget_minutes": 180,
                "buffer_minutes": 0,
            },
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        self.assertEqual(response.status_code, 200, response.content)
        response = self.client.get("/api/load/deadlines", {"week": self.week, "mode": "week"})
        self.assertEqual(response.status_code, 200, response.content)
        check = next(row for row in response.json()["checks"] if row["deadline"] == "2026-10-25")
        self.assertEqual(check["verdict"], "unknown")
        self.assertIsNone(check["capacity"])

    def test_undo_restores_policy_history_as_well_as_auto_source(self):
        task = self.create(status="in_progress", budget_schedule="recurring")
        model = Task.objects.get(id=task["id"])
        policy = model.budget_policy
        policy.revisions[0]["origin"] = "legacy_migration"
        policy.save()
        before = list(policy.revisions)
        applied = self.write("apply", changes=[{"task_id": task["id"], "status": "paused"}])
        event = next(row for row in applied["history"] if row["kind"] == "apply")
        self.write("undo", event_id=event["id"])
        policy.refresh_from_db()
        self.assertEqual(policy.revisions, before)

    def test_ended_task_excludes_but_preserves_independent_upkeep(self):
        task = self.create(status="in_progress", budget_schedule="recurring")
        self.write(
            "settings",
            action="plan",
            task_id=task["id"],
            progress_low=60,
            progress_high=60,
            maintenance_low=30,
            maintenance_high=30,
            maintenance_active=True,
            scope_confirmed=True,
            remaining_low=None,
            remaining_high=None,
        )
        self.change(task, status="completed")
        future = self.get(week="2026-10-19")
        self.assertEqual(future["analysis"]["low"], 0)
        self.assertTrue(future["tasks"][0]["maintenance_active"])
        self.assertEqual(future["analysis"]["unknown_count"], 1)

    def test_cross_week_restore_does_not_recreate_closed_week_reservation(self):
        task = self.create(status="in_progress", budget_schedule="recurring")
        finished = self.change(task, status="completed")
        with patch("load_analysis.workspace.now", return_value=self.clock + dt.timedelta(days=7)):
            self.change(finished, status="in_progress")
            self.assertEqual(self.get()["analysis"]["low"], 0)
            self.assertEqual(self.get(week="2026-10-19")["analysis"]["low"], 180)

    def test_creation_retry_without_explicit_week_is_identical_after_week_boundary(self):
        key = str(uuid.uuid4())
        packet = {"title": "默认本周", "weekly_minutes": 180}
        first = self.client.post(
            "/api/tasks", packet, content_type="application/json", HTTP_IDEMPOTENCY_KEY=key
        )
        self.assertEqual(first.status_code, 201)
        with patch("load_analysis.workspace.now", return_value=self.clock + dt.timedelta(days=7)):
            retry = self.client.post(
                "/api/tasks", packet, content_type="application/json", HTTP_IDEMPOTENCY_KEY=key
            )
            self.assertEqual(retry.status_code, 200, retry.content)
            self.assertEqual(first.json()["task"]["id"], retry.json()["task"]["id"])
            self.assertEqual(retry.json()["task"]["budget_week"], self.week)
        self.assertEqual(Task.objects.count(), 1)

    def test_policy_failure_rolls_back_task_creation_and_edit(self):
        from load_analysis.models import BudgetPolicy

        with patch(
            "load_analysis.policies.BudgetPolicy.save",
            side_effect=RuntimeError("policy write interrupted"),
        ):
            with self.assertRaisesMessage(RuntimeError, "policy write interrupted"):
                self.create()
        self.assertEqual(Task.objects.count(), 0)
        self.assertEqual(BudgetPolicy.objects.count(), 0)
        task = self.create()
        with patch(
            "load_analysis.policies.BudgetPolicy.save",
            side_effect=RuntimeError("policy write interrupted"),
        ):
            with self.assertRaisesMessage(RuntimeError, "policy write interrupted"):
                self.change(task, weekly_minutes=240)
        self.assertEqual(Task.objects.get(id=task["id"]).version, task["version"])
        self.assertEqual(self.get()["analysis"]["low"], 180)

    def test_historical_start_without_revision_is_unknown_not_zero(self):
        self.create(budget_schedule="recurring", budget_week="2026-10-05")
        historical = self.get(week="2026-10-05")
        self.assertEqual(historical["tasks"][0]["allocation_source"], "auto")
        self.assertIsNone(historical["analysis"]["low"])
