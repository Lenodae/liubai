import datetime as dt
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone


class LoadApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("load_a")
        self.other = get_user_model().objects.create_user("load_b")
        self.a, self.b = Client(), Client()
        self.a.force_login(self.user)
        self.b.force_login(self.other)
        today = timezone.localdate()
        self.week = (today - dt.timedelta(days=today.weekday())).isoformat()
        self.scope = {"week": self.week, "mode": "week"}
        self.task = self.a.post(
            "/api/tasks",
            {"title": "论文", "status": "in_progress", "weekly_minutes": 600},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        ).json()["task"]

    def get(self, client=None, **scope):
        r = (client or self.a).get("/api/load/workspace", {**self.scope, **scope})
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def post(self, operation="settings", expected=200, client=None, key=None, **data):
        fingerprint = data.pop("fingerprint", None) or self.get(client)["fingerprint"]
        r = (client or self.a).post(
            f"/api/load/{operation}",
            {**self.scope, "fingerprint": fingerprint, **data},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=key or str(uuid.uuid4()),
        )
        self.assertEqual(r.status_code, expected, r.content)
        return r.json()

    def capacity(self):
        return self.post(action="capacity", budget_minutes=600, buffer_minutes=120)

    def plan(self, **fields):
        return self.post(
            action="plan",
            task_id=self.task["id"],
            progress_low=fields.pop("progress_low", 420),
            progress_high=fields.pop("progress_high", 600),
            maintenance_low=fields.pop("maintenance_low", 0),
            maintenance_high=fields.pop("maintenance_high", 0),
            maintenance_active=fields.pop("maintenance_active", False),
            scope_confirmed=True,
            remaining_low=fields.pop("remaining_low", None),
            remaining_high=fields.pop("remaining_high", None),
            **fields,
        )

    def ready(self):
        self.capacity()
        return self.plan()

    def test_get_unknown_and_readonly(self):
        from load_analysis.models import CapacityWindow

        w = self.get()
        self.assertIsNone(w["window"]["budget_minutes"])
        self.assertEqual(w["analysis"]["verdict"], "unknown")
        self.assertEqual(w["tasks"][0]["weekly_minutes"], 600)
        self.assertFalse(w["tasks"][0]["plan_confirmed"])
        self.assertEqual(CapacityWindow.objects.count(), 0)

    def test_capacity_intervals_and_invalid_fields(self):
        w = self.ready()
        self.assertEqual(w["analysis"]["capacity"], 480)
        self.assertEqual(w["analysis"]["verdict"], "conditional")
        self.assertEqual(w["analysis"]["deficit_high"], 120)
        for bad in [True, -1, 10081, "100"]:
            self.post(action="capacity", budget_minutes=bad, buffer_minutes=0, expected=400)
        self.post(action="capacity", budget_minutes=30, buffer_minutes=31, expected=400)
        self.post(
            action="capacity",
            budget_minutes=600,
            buffer_minutes=0,
            owner=self.other.pk,
            expected=400,
        )
        self.plan(progress_low=600, progress_high=200, expected=400)

    def test_owner_and_account_header(self):
        self.ready()
        self.post(action="plan", task_id=self.task["id"], client=self.b, expected=404)
        self.assertEqual(self.get(self.b)["tasks"], [])
        self.assertEqual(Client().get("/api/load/workspace").status_code, 401)
        self.assertEqual(
            self.a.get("/api/load/workspace", HTTP_X_WORKSPACE_USER=str(self.other.pk)).status_code,
            401,
        )

    def test_preview_apply_idempotency_and_undo(self):
        from load_analysis.models import LoadEvent

        w = self.ready()
        original = w["fingerprint"]
        changes = [
            {
                "task_id": self.task["id"],
                "progress_low": 300,
                "progress_high": 300,
                "maintenance_low": 0,
                "maintenance_high": 0,
            }
        ]
        preview = self.post("preview", fingerprint=original, changes=changes)
        self.assertEqual(preview["after"]["verdict"], "fits")
        self.assertEqual(self.get()["tasks"][0]["progress_low"], 420)
        key = str(uuid.uuid4())
        applied = self.post("apply", fingerprint=original, changes=changes, key=key)
        retry = self.post("apply", fingerprint=original, changes=changes, key=key)
        self.assertEqual(applied, retry)
        self.assertEqual(LoadEvent.objects.filter(kind="apply").count(), 1)
        self.assertEqual(applied["tasks"][0]["weekly_minutes"], 600)
        event = LoadEvent.objects.get(kind="apply")
        undone = self.post("undo", event_id=event.pk)
        self.assertEqual(undone["tasks"][0]["progress_low"], 420)
        self.post("undo", event_id=event.pk, expected=409)

    def test_new_task_and_versions_expire_preview(self):
        old = self.ready()["fingerprint"]
        self.a.post(
            "/api/tasks",
            {"title": "新想法"},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        self.post(
            "apply",
            fingerprint=old,
            changes=[{"task_id": self.task["id"], "progress_low": 0, "progress_high": 0}],
            expected=409,
        )

    def test_atomic_rollback(self):
        from load_analysis.models import LoadEvent

        old = self.ready()
        count = LoadEvent.objects.count()
        with patch("load_analysis.services.save_receipt", side_effect=RuntimeError("fault")):
            with self.assertRaises(RuntimeError):
                self.post(
                    "apply",
                    fingerprint=old["fingerprint"],
                    changes=[
                        {
                            "task_id": self.task["id"],
                            "progress_low": 0,
                            "progress_high": 0,
                            "status": "paused",
                        }
                    ],
                )
        current = self.get()
        self.assertEqual(current["fingerprint"], old["fingerprint"])
        self.assertEqual(current["tasks"][0]["status"], "in_progress")
        self.assertEqual(LoadEvent.objects.count(), count)

    def test_remaining_separate_and_clock_expiry(self):
        self.ready()
        self.scope["mode"] = "remaining"
        self.assertIsNone(self.get()["window"]["budget_minutes"])
        self.ready()
        old = self.get()
        nextday = timezone.now() + dt.timedelta(days=1)
        with patch("load_analysis.workspace.now", return_value=nextday):
            self.assertTrue(self.get()["window"]["stale"])
            self.post(
                "apply",
                fingerprint=old["fingerprint"],
                changes=[{"task_id": self.task["id"], "progress_low": 0, "progress_high": 0}],
                expected=409,
            )

    def test_actual_history_not_deducted_and_notes(self):
        from execution.models import TimeEntry
        from tasks.models import Task

        task = Task.objects.get(pk=self.task["id"])
        for minutes in [90, 30, 20]:
            TimeEntry.objects.create(task=task, minutes=minutes, date=self.week)
        self.ready()
        w = self.get()
        self.assertEqual(w["actual"]["minutes"], 140)
        self.assertEqual(w["analysis"]["capacity"], 480)
        self.post(action="save_snapshot")
        history = self.a.get("/api/load/history", {"week": self.week}).json()
        self.assertEqual(history["actual"]["minutes"], 140)
        self.assertEqual(len(history["snapshots"]), 1)
        TimeEntry.objects.filter(task=task, minutes=30).update(voided_at=timezone.now())
        self.assertEqual(self.get()["actual"]["minutes"], 110)

    def test_paused_maintenance_and_completion(self):
        w = self.ready()
        self.plan(
            progress_low=120,
            progress_high=120,
            maintenance_active=True,
            maintenance_low=180,
            maintenance_high=180,
        )
        w = self.post("apply", changes=[{"task_id": self.task["id"], "status": "paused"}])
        self.assertEqual(w["analysis"]["low"], 0)
        self.assertEqual(w["tasks"][0]["status"], "paused")

    def test_deadline_shared_capacity_and_segment_validation(self):
        from execution.models import Profile
        from tasks.models import Task

        sunday = (dt.date.fromisoformat(self.week) + dt.timedelta(days=6)).isoformat()
        Profile.objects.create(task_id=self.task["id"], deadline=sunday)
        self.capacity()
        self.plan(remaining_low=600, remaining_high=600)
        result = self.a.get("/api/load/deadlines", self.scope)
        self.assertEqual(result.status_code, 200, result.content)
        checks = result.json()["checks"]
        self.assertTrue(any(x["verdict"] == "conflict" for x in checks), checks)
        self.post(
            "deadlines",
            slices=[
                {"end": sunday, "budget_minutes": 600, "buffer_minutes": 120, "other_minutes": 0}
            ],
        )
        self.post(
            "deadlines",
            slices=[
                {"end": sunday, "budget_minutes": 600, "buffer_minutes": 121, "other_minutes": 0}
            ],
            expected=400,
        )
        self.assertEqual(Task.objects.count(), 1)
