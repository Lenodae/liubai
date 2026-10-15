"""Public-interface checks for lost responses, hostile scopes and stale facts."""

import datetime as dt
import uuid
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from load_analysis.models import CapacityWindow, LoadEvent, LoadReceipt, LoadSnapshot, TaskPlan


class LoadAdversarialTests(TestCase):
    def setUp(self):
        self.stamp = timezone.make_aware(dt.datetime(2026, 10, 14, 12))
        clock = patch("load_analysis.workspace.now", return_value=self.stamp)
        clock.start()
        self.addCleanup(clock.stop)
        self.owner = get_user_model().objects.create_user("adversarial_owner")
        self.other = get_user_model().objects.create_user("adversarial_other")
        self.client.force_login(self.owner)
        self.foreign = Client()
        self.foreign.force_login(self.other)
        self.scope = {"week": "2026-10-12", "mode": "remaining"}
        self.task = self.create_task(self.client, "本账号任务")
        self.foreign_task = self.create_task(self.foreign, "他人隐私任务")

    def create_task(self, client, title):
        response = client.post(
            "/api/tasks",
            {"title": title, "status": "in_progress"},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()["task"]

    def workspace(self, client=None):
        response = (client or self.client).get("/api/load/workspace", self.scope)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def body(self, **fields):
        return {**self.scope, "fingerprint": self.workspace()["fingerprint"], **fields}

    def write(self, operation, body, status=200, key=None, client=None, **headers):
        response = (client or self.client).post(
            f"/api/load/{operation}",
            body,
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=key or str(uuid.uuid4()),
            **headers,
        )
        self.assertEqual(response.status_code, status, response.content)
        return response.json()

    def ready(self):
        self.write("settings", self.body(action="capacity", budget_minutes=600, buffer_minutes=60))
        return self.write(
            "settings",
            self.body(
                action="plan",
                task_id=self.task["id"],
                progress_low=120,
                progress_high=180,
                maintenance_low=0,
                maintenance_high=0,
                maintenance_active=False,
                scope_confirmed=True,
                remaining_low=480,
                remaining_high=600,
            ),
        )

    def counts(self):
        return tuple(
            model.objects.count()
            for model in (CapacityWindow, TaskPlan, LoadEvent, LoadReceipt, LoadSnapshot)
        )

    def test_session_csrf_account_header_and_scoped_reads(self):
        self.ready()
        original = self.workspace()["fingerprint"]
        counts = self.counts()
        for operation in ("workspace", "history", "deadlines"):
            with self.subTest(operation=operation):
                response = self.client.get(f"/api/load/{operation}", self.scope)
                self.assertEqual(response.status_code, 200, response.content)
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                self.assertNotIn("他人隐私任务", response.content.decode())
                self.assertEqual(Client().get(f"/api/load/{operation}").status_code, 401)
                switched = self.client.get(
                    f"/api/load/{operation}",
                    self.scope,
                    HTTP_X_WORKSPACE_USER=str(self.other.pk),
                )
                self.assertEqual(switched.status_code, 401)
        guarded = Client(enforce_csrf_checks=True)
        guarded.force_login(self.owner)
        body = self.body(action="capacity", budget_minutes=900, buffer_minutes=0)
        self.write("settings", body, 403, client=guarded)
        guarded.get("/")
        token = guarded.cookies[settings.CSRF_COOKIE_NAME].value
        self.write(
            "settings",
            body,
            401,
            client=guarded,
            HTTP_X_CSRFTOKEN=token,
            HTTP_X_WORKSPACE_USER=str(self.other.pk),
        )
        self.assertEqual(self.workspace()["fingerprint"], original)
        self.assertEqual(self.counts(), counts)

    def test_foreign_task_in_batch_cannot_commit_earlier_capacity(self):
        original = self.ready()
        counts = self.counts()
        changes = [
            {"budget_minutes": 900, "buffer_minutes": 0},
            {"task_id": self.foreign_task["id"], "progress_low": 0, "progress_high": 0},
        ]
        for operation in ("preview", "apply"):
            self.write(operation, self.body(changes=changes), 404)
        self.assertEqual(self.workspace()["fingerprint"], original["fingerprint"])
        self.assertEqual(self.counts(), counts)
        applied = self.write(
            "apply", self.body(changes=[{"task_id": self.task["id"], "progress_low": 60}])
        )
        event = next(item for item in applied["history"] if item["kind"] == "apply")
        foreign_body = {
            **self.scope,
            "fingerprint": self.workspace(self.foreign)["fingerprint"],
            "event_id": event["id"],
        }
        self.write("undo", foreign_body, 404, client=self.foreign)

    def test_lost_response_retry_reuses_receipt_without_overwriting_newer_facts(self):
        self.ready()
        key = str(uuid.uuid4())
        body = self.body(changes=[{"task_id": self.task["id"], "progress_low": 60}])
        saved = self.write("apply", body, key=key)
        self.create_task(self.client, "在结果丢失后新增的想法")
        actual = self.workspace()
        before_counts = self.counts()
        repeated = self.write("apply", body, key=key)
        self.assertEqual(repeated, saved)
        self.assertEqual(self.counts(), before_counts)
        self.assertEqual(self.workspace()["fingerprint"], actual["fingerprint"])
        self.assertEqual(len(self.workspace()["tasks"]), 2)
        changed = {**body, "changes": [{"task_id": self.task["id"], "progress_low": 30}]}
        self.write("apply", changed, 409, key=key)
        self.write("preview", body, 409)

    def test_task_edit_and_day_rollover_reject_old_preview_without_writes(self):
        original = self.ready()
        body = self.body(changes=[{"task_id": self.task["id"], "progress_low": 60}])
        preview = self.write("preview", body)
        self.assertEqual(preview["fingerprint"], original["fingerprint"])
        changed = self.client.patch(
            f"/api/tasks/{self.task['id']}",
            {"version": self.task["version"], "title": "实际任务已有新信息"},
            content_type="application/json",
        )
        self.assertEqual(changed.status_code, 200, changed.content)
        counts = self.counts()
        self.write("apply", body, 409)
        self.assertEqual(self.counts(), counts)
        fresh_body = self.body(changes=[{"budget_minutes": 480, "buffer_minutes": 0}])
        with patch("load_analysis.workspace.now", return_value=self.stamp + dt.timedelta(days=1)):
            self.write("apply", fresh_body, 409)
            current = self.workspace()
            self.assertTrue(current["window"]["stale"])
            self.assertEqual(current["analysis"]["verdict"], "unknown")
        self.assertEqual(self.counts(), counts)

    def test_hostile_fields_duplicate_changes_and_invalid_intervals_are_atomic(self):
        original = self.ready()
        counts = self.counts()
        invalid = [
            [{"task_id": self.task["id"], "progress_low": -1}],
            [{"task_id": self.task["id"], "progress_low": True}],
            [{"task_id": self.task["id"], "progress_high": 1}],
            [{"task_id": self.task["id"], "progress_low": None}],
            [{"task_id": self.task["id"], "owner": self.other.pk}],
            [{"task_id": self.task["id"], "status": "completed"}],
            [{"task_id": self.task["id"], "progress_low": 60}] * 2,
            [{"budget_minutes": 900}, {"buffer_minutes": 20}],
            [{"budget_minutes": 300, "buffer_minutes": 301}],
            [{"task_id": self.task["id"], "maintenance_active": "false"}],
            [{"task_id": self.task["id"], "scope_confirmed": 1}],
        ]
        for changes in invalid:
            with self.subTest(changes=changes):
                self.write("apply", self.body(changes=changes), 400)
        self.write(
            "settings",
            self.body(action="capacity", budget_minutes=10, buffer_minutes=0, owner=self.other.pk),
            400,
        )
        self.assertEqual(self.workspace()["fingerprint"], original["fingerprint"])
        self.assertEqual(self.counts(), counts)

    def test_maintenance_unknown_is_never_silently_disabled(self):
        self.ready()
        response = self.write(
            "apply",
            self.body(
                changes=[
                    {
                        "task_id": self.task["id"],
                        "maintenance_active": True,
                        "maintenance_low": None,
                        "maintenance_high": None,
                    }
                ]
            ),
        )
        row = response["tasks"][0]
        self.assertTrue(row["maintenance_active"])
        self.assertIsNone(row["maintenance_low"])
        self.assertEqual(response["analysis"]["verdict"], "unknown")
        preview = self.write(
            "preview", self.body(changes=[{"task_id": self.task["id"], "progress_low": 60}])
        )
        self.assertEqual(preview["after"]["verdict"], "unknown")
        changed = self.write(
            "apply", self.body(changes=[{"task_id": self.task["id"], "maintenance_active": None}])
        )
        self.assertIsNone(changed["tasks"][0]["maintenance_active"])
        self.assertEqual(changed["analysis"]["verdict"], "unknown")

    def test_window_adjustment_keeps_remaining_goal_confirmation_stale(self):
        self.ready()
        response = self.client.patch(
            f"/api/tasks/{self.task['id']}",
            {"version": self.task["version"], "title": "完成范围已有变化"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(self.workspace()["tasks"][0]["remaining_confirmed"])
        applied = self.write(
            "apply",
            self.body(
                changes=[
                    {
                        "task_id": self.task["id"],
                        "progress_low": 60,
                        "scope_confirmed": True,
                    }
                ]
            ),
        )
        self.assertFalse(applied["tasks"][0]["remaining_confirmed"])
        self.assertEqual(applied["tasks"][0]["remaining_low"], 480)

    def test_saved_week_plan_is_kept_but_current_pause_releases_occupancy(self):
        self.scope["mode"] = "week"
        self.ready()
        response = self.client.patch(
            f"/api/tasks/{self.task['id']}",
            {"version": self.task["version"], "status": "paused"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        current = self.workspace()
        self.assertEqual(current["tasks"][0]["status"], "paused")
        self.assertEqual(current["tasks"][0]["load_status"], "paused")
        self.assertEqual(current["analysis"]["low"], 0)
        self.assertEqual(current["tasks"][0]["progress_low"], 120)
        applied = self.write(
            "apply", self.body(changes=[{"task_id": self.task["id"], "progress_low": 60}])
        )
        self.assertEqual(applied["tasks"][0]["load_status"], "paused")
        self.assertEqual(applied["tasks"][0]["status"], "paused")
        self.assertEqual(applied["analysis"]["low"], 0)
        self.assertEqual(applied["tasks"][0]["progress_low"], 60)
