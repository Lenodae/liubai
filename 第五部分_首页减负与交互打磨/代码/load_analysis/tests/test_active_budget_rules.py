"""Current occupancy is gated by execution state, including legacy task rows."""

import datetime as dt
import uuid
from unittest.mock import patch

from django.test import TestCase

from load_analysis.models import BudgetPolicy, LoadSnapshot
from load_analysis.rules import analyze
from load_analysis.tests import test_budget_policy as helpers
from tasks.models import Task


class ActiveBudgetRulesTests(TestCase):
    def test_auto_and_manual_ignore_every_nonrunning_state_even_when_unknown(self):
        capacity = {
            "budget_minutes": 600,
            "buffer_minutes": 60,
            "confirmed": True,
            "stale": False,
        }
        for status in ("planned", "paused", "completed", "abandoned"):
            for source in ("auto", "manual"):
                with self.subTest(status=status, source=source):
                    row = {
                        "id": "idea",
                        "title": "尚未运行",
                        "status": status,
                        "allocation_source": source,
                        "reservation_minutes": None,
                        "maintenance_active": None,
                        "plan_confirmed": False,
                    }
                    result = analyze(capacity, [row])
                    self.assertEqual((result["low"], result["high"]), (0, 0))
                    self.assertEqual(result["verdict"], "fits")
                    self.assertEqual(result["available_low"], 540)
                    self.assertEqual(result["unknown_count"], 0)


class ActiveLegacyBudgetTests(TestCase):
    setUp = helpers.BudgetPolicyTests.setUp
    get = helpers.BudgetPolicyTests.get
    create = helpers.BudgetPolicyTests.create
    change = helpers.BudgetPolicyTests.change
    write = helpers.BudgetPolicyTests.write

    def test_legacy_running_without_policy_is_included_and_get_does_not_write(self):
        Task.objects.create(
            owner=self.owner,
            title="旧运行任务",
            status="in_progress",
            weekly_minutes=125,
            request_key=uuid.uuid4(),
            request_fingerprint="legacy-running",
        )
        Task.objects.create(
            owner=self.owner,
            title="未知想法",
            status="planned",
            weekly_minutes=None,
            request_key=uuid.uuid4(),
            request_fingerprint="legacy-idea",
        )
        data = self.get()
        self.assertEqual(data["analysis"]["low"], 125)
        self.assertEqual(data["analysis"]["unknown_count"], 1)  # only unknown capacity
        self.assertEqual(BudgetPolicy.objects.count(), 0)
        self.assertEqual(self.get(week="2026-10-19")["analysis"]["low"], 0)

    def test_current_manual_plan_obeys_current_status_and_keeps_saved_fields(self):
        task = self.create(status="in_progress")
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
        task = self.change(task, status="paused")
        data = self.get()
        self.assertEqual(data["analysis"]["low"], 0)
        self.assertEqual(data["tasks"][0]["load_status"], "paused")
        self.assertEqual(data["tasks"][0]["maintenance_low"], 30)
        self.assertEqual(data["tasks"][0]["allocation_source"], "none")
        self.change(task, status="in_progress")
        self.assertEqual(self.get()["analysis"]["low"], 90)

    def test_recorded_week_status_and_snapshot_survive_later_pause(self):
        task = self.create(status="in_progress", budget_schedule="recurring")
        self.write("settings", action="save_snapshot")
        snapshot = LoadSnapshot.objects.get()
        saved = snapshot.data
        with patch("load_analysis.workspace.now", return_value=self.clock + dt.timedelta(days=7)):
            self.change(task, status="paused")
            self.assertEqual(self.get()["analysis"]["low"], 180)
            self.assertEqual(self.get(week="2026-10-19")["analysis"]["low"], 0)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.data, saved)

    def test_old_revision_without_status_uses_old_historical_basis(self):
        task = self.create(status="in_progress", budget_schedule="recurring")
        policy = BudgetPolicy.objects.get(task_id=task["id"])
        policy.revisions[0].pop("status", None)
        policy.save()
        with patch("load_analysis.workspace.now", return_value=self.clock + dt.timedelta(days=7)):
            self.change(task, status="completed")
            historical = self.get()
            self.assertEqual(historical["analysis"]["low"], 180)
            self.assertEqual(historical["tasks"][0]["history_basis"], "legacy_reservation")

    def test_current_running_weekly_time_is_counted_outside_policy_week(self):
        for start_week, minutes in (("2026-10-05", 180), ("2026-10-19", 60), ("2026-10-26", None)):
            with self.subTest(start_week=start_week, minutes=minutes):
                task = self.create(
                    status="in_progress", budget_week=start_week, weekly_minutes=minutes
                )
                data = self.get()
                row = next(row for row in data["tasks"] if row["id"] == task["id"])
                self.assertEqual(row["allocation_source"], "auto")
                self.assertEqual(row["reservation_minutes"], minutes)
                self.assertEqual(row["reservation_basis"], "running_weekly_time")
        self.assertEqual(data["analysis"]["known_low"], 240)
        self.assertIsNone(data["analysis"]["low"])
        future = self.get(week="2026-10-19")
        self.assertEqual(future["analysis"]["low"], 60)
        self.assertEqual(
            Task.objects.get(id=task["id"]).budget_policy.start_week.isoformat(), "2026-10-26"
        )
