"""Budget promises are distinct from execution state and actual time."""

import datetime as dt
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone


class BudgetPolicyPublicTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("budget_policy_owner")
        self.other = get_user_model().objects.create_user("budget_policy_other")
        self.client.force_login(self.user)
        self.foreign = Client()
        self.foreign.force_login(self.other)
        day = timezone.localdate()
        self.week = (day - dt.timedelta(days=day.weekday())).isoformat()
        self.future = (dt.date.fromisoformat(self.week) + dt.timedelta(days=7)).isoformat()

    def create(self, minutes=120, schedule="weekly", client=None, key=None):
        payload = {
            "title": "预算行为验证",
            "status": "in_progress",
            "weekly_minutes": minutes,
            "budget_schedule": schedule,
            "budget_week": self.week,
        }
        response = (client or self.client).post(
            "/api/tasks",
            payload,
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=key or str(uuid.uuid4()),
        )
        self.assertIn(response.status_code, [200, 201], response.content)
        return response.json()["task"]

    def workspace(self, week=None, mode="week", client=None):
        response = (client or self.client).get(
            "/api/load/workspace", {"week": week or self.week, "mode": mode}
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def capacity(self, budget=600, buffer=60, week=None, mode="week"):
        current = self.workspace(week, mode)
        response = self.client.post(
            "/api/load/settings",
            {
                "week": week or self.week,
                "mode": mode,
                "fingerprint": current["fingerprint"],
                "action": "capacity",
                "budget_minutes": budget,
                "buffer_minutes": buffer,
            },
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def change_status(self, task, status):
        response = self.client.patch(
            f"/api/tasks/{task['id']}",
            {"version": task["version"], "status": status},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["task"]

    def test_running_creation_counts_and_retry_once(self):
        self.capacity()
        key = str(uuid.uuid4())
        first = self.create(key=key)
        second = self.create(key=key)
        self.assertEqual(first["id"], second["id"])
        data = self.workspace()
        self.assertEqual(len(data["tasks"]), 1)
        self.assertEqual(data["tasks"][0]["status"], "in_progress")
        self.assertEqual(data["tasks"][0]["allocation_source"], "auto")
        self.assertEqual(data["analysis"]["low"], 120)
        self.assertEqual(data["analysis"]["available_low"], 420)
        self.assertEqual(self.workspace()["analysis"]["low"], 120)
        from load_analysis.models import TaskPlan

        self.assertEqual(TaskPlan.objects.count(), 0)

    def test_weekly_and_long_term_are_separate_and_complete_releases(self):
        once = self.create(120, "weekly")
        recurring = self.create(180, "recurring")
        self.assertEqual(self.capacity()["analysis"]["low"], 300)
        future = self.capacity(week=self.future)
        self.assertEqual(future["analysis"]["low"], 180)
        recurring = self.change_status(recurring, "completed")
        self.assertEqual(self.workspace()["analysis"]["low"], 120)
        self.assertEqual(self.workspace(self.future)["analysis"]["low"], 0)
        recurring = self.change_status(recurring, "in_progress")
        self.assertEqual(self.workspace(self.future)["analysis"]["low"], 180)
        self.assertEqual(self.workspace()["analysis"]["low"], 300)
        self.assertEqual(once["budget_schedule"], "weekly")

    def test_execution_completion_preserves_ledger_and_releases_future(self):
        task = self.create(180, "recurring")
        self.capacity()
        from execution.models import TimeEntry

        TimeEntry.objects.create(task_id=task["id"], minutes=30, date=self.week)
        response = self.client.post(
            f"/api/tasks/{task['id']}/workspace",
            {"version": task["version"], "action": "complete", "note": "完成登记"},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        self.assertEqual(response.status_code, 200, response.content)
        data = self.workspace()
        self.assertEqual(data["analysis"]["low"], 0)
        self.assertEqual(data["actual"]["minutes"], 30)
        self.assertEqual(TimeEntry.objects.count(), 1)

    def test_manual_override_replaces_total_and_remaining_is_separate(self):
        task = self.create(180, "recurring")
        self.capacity()
        data = self.workspace()
        response = self.client.post(
            "/api/load/settings",
            {
                "week": self.week,
                "mode": "week",
                "fingerprint": data["fingerprint"],
                "action": "plan",
                "task_id": task["id"],
                "progress_low": 60,
                "progress_high": 60,
                "maintenance_low": 30,
                "maintenance_high": 30,
                "maintenance_active": True,
                "scope_confirmed": True,
                "remaining_low": None,
                "remaining_high": None,
            },
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        self.assertEqual(response.status_code, 200, response.content)
        # A manual allocation replaces the running task's automatic total.
        self.assertEqual(response.json()["analysis"]["low"], 90)
        self.assertEqual(response.json()["tasks"][0]["allocation_source"], "manual")
        remaining = self.workspace(mode="remaining")
        self.assertIsNone(remaining["window"]["budget_minutes"])
        self.assertNotEqual(remaining["analysis"]["low"], 180)
        self.assertEqual(self.workspace(self.future)["analysis"]["low"], 180)

    def test_unknown_is_not_zero_and_foreign_tasks_cannot_reserve_my_budget(self):
        self.capacity()
        self.create(180, "recurring", client=self.foreign)
        zero = self.create(0)
        self.assertEqual(self.workspace()["analysis"]["low"], 0)
        self.create(None)
        data = self.workspace()
        self.assertEqual(len(data["tasks"]), 2)
        self.assertEqual(data["analysis"]["verdict"], "unknown")
        self.assertEqual(data["analysis"]["known_low"], 0)
        self.assertIsNone(data["analysis"]["available_low"])
        self.assertEqual(zero["weekly_minutes"], 0)

    def test_failed_completion_does_not_release_reserved_budget(self):
        task = self.create(180, "recurring")
        original = self.capacity()
        with patch(
            "execution.services.save_receipt", side_effect=RuntimeError("injected receipt failure")
        ):
            with self.assertRaises(RuntimeError):
                self.client.post(
                    f"/api/tasks/{task['id']}/workspace",
                    {"version": task["version"], "action": "complete", "note": "故障回滚验证"},
                    content_type="application/json",
                    HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
                )
        after = self.workspace()
        self.assertEqual(after["tasks"][0]["status"], "in_progress")
        self.assertEqual(after["analysis"]["low"], 180)
        self.assertEqual(after["fingerprint"], original["fingerprint"])

    def test_child_completion_keeps_parent_reservation(self):
        task = self.change_status(self.create(180, "recurring"), "in_progress")
        self.capacity()
        from execution.models import Step

        step = Step.objects.create(
            task_id=task["id"],
            title="子步骤",
            criterion="完成此步骤",
            position=0,
            status="in_progress",
        )
        response = self.client.post(
            f"/api/tasks/{task['id']}/workspace",
            {"version": task["version"], "action": "complete", "step_id": str(step.id)},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        self.assertEqual(response.status_code, 200, response.content)
        current = self.workspace()
        self.assertEqual(current["tasks"][0]["status"], "in_progress")
        self.assertEqual(current["analysis"]["low"], 180)
        self.assertEqual(self.workspace(self.future)["analysis"]["low"], 180)
