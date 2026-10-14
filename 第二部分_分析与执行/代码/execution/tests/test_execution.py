import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase


class ExecutionCase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("exec_a")
        self.other = get_user_model().objects.create_user("exec_b")
        self.a, self.b = Client(), Client()
        self.a.force_login(self.user)
        self.b.force_login(self.other)
        self.task = self.a.post(
            "/api/tasks",
            {"title": "注意力机制", "status": "in_progress", "weekly_minutes": 240},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        ).json()["task"]
        self.url = f"/api/tasks/{self.task['id']}/workspace"

    def get(self):
        r = self.a.get(self.url)
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def call(self, action, expected=200, key=None, version=None, client=None, **data):
        if version is None:
            version = self.a.get(f"/api/tasks/{self.task['id']}").json()["task"]["version"]
        r = (client or self.a).post(
            self.url,
            {"action": action, "version": version, **data},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=key or str(uuid.uuid4()),
        )
        self.assertEqual(r.status_code, expected, r.content)
        return r.json()

    def profile(self):
        return self.call(
            "profile",
            criterion="代码运行且与手算一致",
            foundation="Python 和矩阵基础",
            constraints="",
            deadline="",
            available_minutes=480,
        )

    def draft(self):
        self.profile()
        return self.call(
            "draft",
            nodes=[
                {
                    "title": "手算",
                    "criterion": "给出计算结果",
                    "low": 60,
                    "high": 120,
                    "depends": [],
                },
                {"title": "代码", "criterion": "运行检查", "low": 240, "high": 420, "depends": [0]},
            ],
        )["drafts"][0]

    def steps(self):
        draft = self.draft()
        return self.call(
            "apply", draft_id=draft["id"], revision=draft["revision"], selected=[0, 1]
        )["steps"]

    def test_steps(self):
        draft = self.draft()
        self.call(
            "apply", draft_id=draft["id"], revision=draft["revision"], selected=[1], expected=400
        )
        result = self.call(
            "apply", draft_id=draft["id"], revision=draft["revision"], selected=[0, 1]
        )
        self.assertEqual(len(result["steps"]), 2)
        self.assertEqual(result["task"]["status"], "in_progress")
        self.assertEqual(result["task"]["weekly_minutes"], 240)
        self.assertEqual(result["steps"][1]["depends"], [result["steps"][0]["id"]])
        self.call(
            "draft",
            nodes=[{"title": "环", "criterion": "输出", "low": None, "high": None, "depends": [0]}],
            expected=400,
        )
        self.call(
            "draft",
            nodes=[{"title": "坏", "criterion": "", "low": None, "high": None, "depends": []}],
            expected=400,
        )

    def test_rules(self):
        steps = self.steps()
        self.assertEqual(self.get()["analysis"]["time"], "conditional")
        self.call(
            "profile",
            criterion="运行",
            foundation="",
            constraints="",
            deadline="",
            available_minutes=299,
        )
        self.assertEqual(self.get()["analysis"]["time"], "conflict")
        self.call(
            "profile",
            criterion="运行",
            foundation="",
            constraints="",
            deadline="",
            available_minutes=540,
        )
        self.assertEqual(self.get()["analysis"]["time"], "fits")
        self.call(
            "profile",
            criterion="运行",
            foundation="",
            constraints="",
            deadline="",
            available_minutes=None,
        )
        self.assertEqual(self.get()["analysis"]["time"], "unknown")
        self.assertEqual(steps[0]["actual_minutes"], None)

    def test_ledger(self):
        steps = self.steps()
        for n in [40, 50, 90]:
            self.call("time_add", step_id=steps[0]["id"], minutes=n, date="2026-10-13", note="学习")
        self.assertEqual(self.get()["summary"]["actual_minutes"], 180)
        result = self.call("time_add", step_id=None, minutes=20, date="2026-10-13", note="整理")
        self.assertEqual(result["summary"]["actual_minutes"], 200)
        entry = result["entries"][0]
        self.call(
            "time_edit",
            entry_id=entry["id"],
            entry_version=entry["version"],
            step_id=steps[1]["id"],
            minutes=20,
            date="2026-10-13",
            note="归属修正",
        )
        self.assertEqual(self.get()["summary"]["actual_minutes"], 200)
        current = self.get()["entries"][0]
        result = self.call("time_delete", entry_id=current["id"], entry_version=current["version"])
        self.assertEqual(result["summary"]["actual_minutes"], 180)
        self.assertTrue(any(e["kind"] == "time_delete" for e in result["history"]))
        for invalid in [0, -1, True, 1.2, "20", None, 10081]:
            self.call(
                "time_add", step_id=None, minutes=invalid, date="2026-10-13", note="", expected=400
            )

    def test_completion(self):
        steps = self.steps()
        sid = steps[0]["id"]
        self.call("time_add", step_id=sid, minutes=90, date="2026-10-13", note="")
        result = self.call(
            "complete",
            step_id=sid,
            note="已核对",
            link="https://example.com/result",
            extra_minutes=30,
            date="2026-10-14",
            verified=True,
            allow_unfinished=False,
        )
        self.assertEqual(result["summary"]["actual_minutes"], 120)
        self.assertEqual(result["steps"][0]["status"], "completed")
        self.assertTrue(result["steps"][0]["time_verified"])
        self.assertEqual(result["task"]["status"], "in_progress")
        result = self.call("undo", step_id=sid)
        self.assertEqual(result["steps"][0]["status"], "planned")
        self.assertEqual(result["summary"]["actual_minutes"], 120)
        self.call(
            "complete",
            step_id=None,
            note="",
            link="",
            extra_minutes=None,
            date="2026-10-14",
            verified=False,
            allow_unfinished=False,
            expected=409,
        )
        result = self.call(
            "complete",
            step_id=None,
            note="",
            link="",
            extra_minutes=None,
            date="2026-10-14",
            verified=True,
            allow_unfinished=True,
        )
        self.assertEqual(result["task"]["status"], "completed")
        self.assertTrue(result["summary"]["time_verified"])
        self.call("time_add", step_id=None, minutes=10, date="2026-10-13", note="补记")
        self.assertFalse(self.get()["summary"]["time_verified"])
        result = self.call("undo", step_id=None)
        self.assertEqual(result["task"]["status"], "in_progress")

    def test_isolation(self):
        self.steps()
        self.assertEqual(self.b.get(self.url).status_code, 404)
        self.call(
            "time_add",
            client=self.b,
            step_id=None,
            minutes=10,
            date="2026-10-13",
            note="",
            expected=404,
        )
        self.call(
            "time_add",
            step_id=str(uuid.uuid4()),
            minutes=10,
            date="2026-10-13",
            note="",
            expected=404,
        )
        self.call("profile", owner_id=self.other.id, expected=400)
        self.assertIsNone(self.get()["summary"]["actual_minutes"])

    def test_idempotency(self):
        key = str(uuid.uuid4())
        v = self.task["version"]
        data = dict(step_id=None, minutes=30, date="2026-10-13", note="")
        first = self.call("time_add", key=key, version=v, **data)
        second = self.call("time_add", key=key, version=v, **data)
        self.assertEqual(first, second)
        self.assertEqual(len(self.get()["entries"]), 1)
        self.call("time_add", key=key, version=v, **{**data, "minutes": 40}, expected=409)

    def test_conflict_and_rollback(self):
        self.profile()
        self.call(
            "time_add",
            version=1,
            step_id=None,
            minutes=10,
            date="2026-10-13",
            note="",
            expected=409,
        )
        with patch("execution.services.save_receipt", side_effect=RuntimeError("injected")):
            with self.assertRaises(RuntimeError):
                self.call(
                    "complete",
                    step_id=None,
                    note="",
                    link="",
                    extra_minutes=30,
                    date="2026-10-13",
                    verified=True,
                    allow_unfinished=True,
                )
        result = self.get()
        self.assertIsNone(result["summary"]["actual_minutes"])
        self.assertEqual(result["task"]["status"], "in_progress")
        self.assertFalse(result["history"])

    def test_lifecycle(self):
        steps = self.steps()
        a, b = [s["id"] for s in steps]
        self.call("step_status", step_id=b, status="in_progress", expected=409)
        self.call("step_status", step_id=a, status="in_progress")
        self.a.patch(
            f"/api/tasks/{self.task['id']}",
            {"version": self.get()["task"]["version"], "status": "paused"},
            content_type="application/json",
        )
        self.assertEqual(self.get()["steps"][0]["effective_status"], "paused")
        self.call("step_status", step_id=b, status="in_progress", expected=409)
        self.call("time_add", step_id=a, minutes=20, date="2026-10-13", note="之前的投入")
        self.assertEqual(self.get()["task"]["status"], "paused")

    def test_jobs(self):
        self.profile()
        self.call("analyze", consent=False, expected=400)
        with patch(
            "execution.provider.configuration",
            return_value={"key": "test-key", "model": "deepseek-flash"},
        ):
            result = self.call("analyze", consent=True)
            run = result["runs"][0]
            self.assertEqual(run["status"], "queued")
            self.call("analyze", consent=True, expected=409)
            self.call("cancel_analysis", run_id=run["id"])
            self.assertEqual(self.get()["runs"][0]["status"], "cancelled")
        self.assertFalse(self.get()["drafts"])

    def test_hostile(self):
        self.profile()
        for data in [
            {"criterion": []},
            {"criterion": "\x00"},
            {"criterion": "x", "deadline": "yesterday"},
        ]:
            self.call("profile", expected=400, **data)
        self.call(
            "complete",
            step_id=None,
            note="",
            link="javascript:alert(1)",
            extra_minutes=None,
            date="2026-10-13",
            verified=False,
            allow_unfinished=True,
            expected=400,
        )
        self.call(
            "draft",
            nodes=[{"title": "x", "criterion": "y", "low": 10, "high": 1, "depends": []}],
            expected=400,
        )
        self.assertFalse(self.get()["drafts"])
