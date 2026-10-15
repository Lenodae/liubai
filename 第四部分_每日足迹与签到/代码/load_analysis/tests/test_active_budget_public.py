"""Only running work occupies the live budget; recording ideas is free."""

import datetime as dt
import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone


class ActiveBudgetPublicTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("active_budget_owner")
        self.client.force_login(self.user)
        today = timezone.localdate()
        self.week = (today - dt.timedelta(days=today.weekday())).isoformat()

    def workspace(self):
        response = self.client.get("/api/load/workspace", {"week": self.week, "mode": "week"})
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def capacity(self):
        current = self.workspace()
        response = self.client.post(
            "/api/load/settings",
            {
                "week": self.week,
                "mode": "week",
                "fingerprint": current["fingerprint"],
                "action": "capacity",
                "budget_minutes": 600,
                "buffer_minutes": 60,
            },
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        self.assertEqual(response.status_code, 200, response.content)

    def create(self, minutes=180, status="planned"):
        response = self.client.post(
            "/api/tasks",
            {
                "title": "时间承诺验证",
                "weekly_minutes": minutes,
                "status": status,
                "budget_schedule": "recurring",
                "budget_week": self.week,
            },
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()["task"]

    def state(self, task, status):
        response = self.client.patch(
            f"/api/tasks/{task['id']}",
            {"version": task["version"], "status": status},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["task"]

    def test_ideas_do_not_occupy_or_block_known_budget(self):
        self.capacity()
        idea = self.create(180)
        self.create(None)
        data = self.workspace()
        self.assertEqual(idea["status"], "planned")
        self.assertEqual(data["analysis"]["low"], 0)
        self.assertEqual(data["analysis"]["verdict"], "fits")
        self.assertEqual(data["analysis"]["available_low"], 540)

    def test_start_pause_resume_complete_recomputes_time(self):
        self.capacity()
        idea = self.create(180)
        active = self.state(idea, "in_progress")
        self.assertEqual(self.workspace()["analysis"]["low"], 180)
        self.assertEqual(self.workspace()["analysis"]["available_low"], 360)
        paused = self.state(active, "paused")
        self.assertEqual(self.workspace()["analysis"]["low"], 0)
        resumed = self.state(paused, "in_progress")
        self.assertEqual(self.workspace()["analysis"]["low"], 180)
        self.state(resumed, "completed")
        self.assertEqual(self.workspace()["analysis"]["low"], 0)

    def test_only_running_items_enter_total_and_unknown_is_not_zero(self):
        self.capacity()
        self.create(180, "in_progress")
        self.create(240, "planned")
        self.create(300, "paused")
        self.assertEqual(self.workspace()["analysis"]["low"], 180)
        active = self.create(None, "in_progress")
        unknown = self.workspace()
        self.assertEqual(unknown["analysis"]["known_low"], 180)
        self.assertEqual(unknown["analysis"]["verdict"], "unknown")
        self.assertIsNone(unknown["analysis"]["available_low"])
        response = self.client.patch(
            f"/api/tasks/{active['id']}",
            {"version": active["version"], "weekly_minutes": 0},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.workspace()["analysis"]["verdict"], "fits")
        self.assertEqual(self.workspace()["analysis"]["available_low"], 360)

    def test_paused_manual_plan_does_not_keep_old_running_load(self):
        self.capacity()
        task = self.create(180, "in_progress")
        current = self.workspace()
        response = self.client.post(
            "/api/load/settings",
            {
                "week": self.week,
                "mode": "week",
                "fingerprint": current["fingerprint"],
                "action": "plan",
                "task_id": task["id"],
                "progress_low": 120,
                "progress_high": 120,
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
        self.assertEqual(self.workspace()["analysis"]["low"], 150)
        self.state(task, "paused")
        self.assertEqual(self.workspace()["analysis"]["low"], 0)

    def test_legacy_running_task_with_time_is_included_without_duplicate_steps(self):
        from execution.models import Step, TimeEntry
        from tasks.models import Task

        self.capacity()
        task = Task.objects.create(
            owner=self.user,
            title="旧进行中任务",
            status="in_progress",
            weekly_minutes=180,
            request_key=uuid.uuid4(),
            request_fingerprint="legacy",
        )
        Step.objects.create(
            task=task, title="步骤估时", criterion="完成", position=0, low=180, high=240
        )
        TimeEntry.objects.create(task=task, minutes=30, date=self.week)
        data = self.workspace()
        self.assertEqual(data["analysis"]["low"], 180)
        self.assertEqual(data["analysis"]["available_low"], 360)
        self.assertEqual(data["actual"]["minutes"], 30)

    def test_current_running_work_is_not_hidden_by_an_old_or_future_policy_week(self):
        self.capacity()
        task = self.create(180, "in_progress")
        for offset in [-7, 7]:
            with self.subTest(offset=offset):
                selected = (
                    dt.date.fromisoformat(self.week) + dt.timedelta(days=offset)
                ).isoformat()
                response = self.client.patch(
                    f"/api/tasks/{task['id']}",
                    {
                        "version": task["version"],
                        "budget_schedule": "weekly",
                        "budget_week": selected,
                    },
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, 200, response.content)
                task = response.json()["task"]
                self.assertEqual(self.workspace()["analysis"]["low"], 180)
                self.assertEqual(self.workspace()["analysis"]["available_low"], 360)
