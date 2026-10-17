import uuid
from unittest.mock import patch

from django.test import TestCase

from execution import validation as v
from execution.models import Step
from execution.tests import test_execution as helpers
from tasks.services import ApiError


class BoundaryCase(TestCase):
    setUp = helpers.ExecutionCase.setUp
    get = helpers.ExecutionCase.get
    call = helpers.ExecutionCase.call
    profile = helpers.ExecutionCase.profile
    draft = helpers.ExecutionCase.draft
    steps = helpers.ExecutionCase.steps

    def test_draft_revision_and_stale_apply(self):
        draft = self.draft()
        self.call("time_add", step_id=None, minutes=5, date="2026-10-13", note="")
        self.call("apply", draft_id=draft["id"], revision=1, selected=[0], expected=409)
        updated = self.call("draft", draft_id=draft["id"], revision=1, nodes=draft["nodes"])[
            "drafts"
        ][0]
        self.assertEqual(updated["revision"], 2)
        self.call("draft", draft_id=draft["id"], revision=1, nodes=draft["nodes"], expected=409)
        self.call("apply", draft_id=draft["id"], revision=2, selected=[0, 1])
        self.call("apply", draft_id=draft["id"], revision=2, selected=[0, 1], expected=409)
        self.call(
            "draft", draft_id=str(uuid.uuid4()), revision=1, nodes=draft["nodes"], expected=404
        )
        self.call("apply", draft_id=str(uuid.uuid4()), revision=1, selected=[0], expected=404)

    def test_dependency_schema_and_selection(self):
        self.profile()
        for nodes in [
            None,
            [],
            [42],
            [{"title": "x", "criterion": "y", "depends": [True]}],
            [
                {"title": "x", "criterion": "y", "depends": [1]},
                {"title": "y", "criterion": "z", "depends": [0]},
            ],
            [{"title": "x", "criterion": "y", "low": 10, "high": None}],
        ]:
            self.call("draft", nodes=nodes, expected=400)
        draft = self.draft()
        for selected in [[], [True], [0, 0], [9], None]:
            self.call("apply", draft_id=draft["id"], revision=1, selected=selected, expected=400)
        self.call("apply", draft_id=draft["id"], revision=1, selected=[0])
        self.assertEqual(len(self.get()["steps"]), 1)

    def test_completed_without_time_and_legacy_patch(self):
        result = self.call(
            "complete",
            step_id=None,
            note="",
            link="",
            extra_minutes=None,
            verified=False,
            allow_unfinished=False,
        )
        self.assertEqual(result["task"]["status"], "completed")
        self.assertIsNone(result["summary"]["actual_minutes"])
        self.assertFalse(result["summary"]["time_verified"])
        self.call("complete", step_id=None, expected=409)
        self.call("verify_time", step_id=None, verified=True, expected=400)
        self.call("undo", step_id=None)
        self.call("undo", step_id=None, expected=409)
        steps = self.steps()
        r = self.a.patch(
            f"/api/tasks/{self.task['id']}",
            {"version": self.get()["task"]["version"], "status": "completed"},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.get()["task"]["status"], "in_progress")
        self.call("complete", step_id=steps[0]["id"], verified=False)
        self.call("complete", step_id=steps[1]["id"], verified=False)
        self.assertTrue(self.get()["summary"]["all_steps_completed"])
        self.assertEqual(self.get()["task"]["status"], "in_progress")

    def test_reestimate_restore_and_verify(self):
        steps = self.steps()
        a = steps[0]["id"]
        self.call("step_status", step_id=a, low=10, high=20)
        self.assertEqual(self.get()["steps"][0]["low"], 10)
        self.call("complete", step_id=a)
        self.call("step_status", step_id=a, status="in_progress", expected=400)
        self.call("complete", step_id=None, allow_unfinished=True)
        self.call("undo", step_id=a, expected=409)
        self.call("step_status", step_id=steps[1]["id"], status="paused", expected=409)
        self.call("undo", step_id=None)
        self.call("undo", step_id=a)
        self.call("step_status", step_id=a, status="abandoned")
        self.assertIn("有已放弃步骤", str(self.get()["analysis"]))
        self.call("step_status", step_id=a, status="planned")
        self.call("time_add", step_id=a, minutes=10, date="2026-10-13", note="")
        self.call("verify_time", step_id=a, verified=True)
        self.assertTrue(self.get()["steps"][0]["time_verified"])
        self.call("verify_time", step_id=a, verified=False)
        self.assertFalse(self.get()["steps"][0]["time_verified"])

    def test_entry_conflicts_and_cross_resource(self):
        self.call("time_add", step_id=None, minutes=10, date="2026-10-13", note="")
        entry = self.get()["entries"][0]
        self.call(
            "time_edit",
            entry_id=entry["id"],
            entry_version=9,
            step_id=None,
            minutes=20,
            date="2026-10-13",
            note="",
            expected=409,
        )
        self.call("time_delete", entry_id=str(uuid.uuid4()), entry_version=1, expected=404)
        self.call("time_add", step_id=None, minutes=1, date="2999-01-01", expected=400)
        steps = self.steps()
        # An actual existing step from another task must be rejected, not just random IDs.
        other = self.a.post(
            "/api/tasks",
            {"title": "other"},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        ).json()["task"]
        old = self.url
        self.url = f"/api/tasks/{other['id']}/workspace"
        r = self.a.post(
            self.url,
            {
                "action": "time_add",
                "version": 1,
                "step_id": steps[0]["id"],
                "minutes": 9,
                "date": "2026-10-13",
                "note": "",
            },
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        self.assertEqual(r.status_code, 404)
        self.url = old
        self.assertEqual(self.get()["summary"]["actual_minutes"], 10)

    def test_bad_ids_unknown_actions_and_config(self):
        self.call("not_an_action", expected=400)
        self.call("time_add", key="bad", expected=400)
        self.call("step_status", step_id="not-uuid", status="planned", expected=400)
        with patch(
            "execution.provider.configuration", return_value={"key": "", "model": "deepseek-flash"}
        ):
            self.call("analyze", consent=True, expected=503)
        self.call("cancel_analysis", run_id=str(uuid.uuid4()), expected=404)
        with patch(
            "execution.provider.configuration",
            return_value={"key": "test", "model": "deepseek-flash"},
        ):
            run = self.call("analyze", consent=True)["runs"][0]
            self.call("cancel_analysis", run_id=run["id"])
            self.call("cancel_analysis", run_id=run["id"], expected=409)
        for value in [False, 1, [], None]:
            with self.assertRaises(ApiError):
                v.text(value)
        with self.assertRaises(ApiError):
            v.boolean("yes")
        with self.assertRaises(ApiError):
            v.date(3)
        with self.assertRaises(ApiError):
            v.link("https://[malformed")
        self.assertEqual(v.date(None, nullable=True), None)

    def test_step_limit_and_time_unknown(self):
        draft = self.draft()
        Step.objects.bulk_create(
            [
                Step(task_id=self.task["id"], title=str(i), criterion="x", position=i)
                for i in range(100)
            ]
        )
        self.call("apply", draft_id=draft["id"], revision=1, selected=[0], expected=400)
        self.assertEqual(self.get()["analysis"]["time"], "unknown")
        self.assertIn("未估计", str(self.get()["analysis"]))
