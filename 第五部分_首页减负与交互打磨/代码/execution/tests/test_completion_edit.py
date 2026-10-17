import uuid
from unittest.mock import patch

from django.test import TestCase

from execution.models import Event, Profile, Receipt, Step, TimeEntry
from execution.tests import test_execution as helpers
from tasks.models import Task, TaskEvent


class CompletionEditCase(TestCase):
    setUp = helpers.ExecutionCase.setUp
    call = helpers.ExecutionCase.call
    get = helpers.ExecutionCase.get
    profile = helpers.ExecutionCase.profile
    draft = helpers.ExecutionCase.draft
    steps = helpers.ExecutionCase.steps

    def finish(self, step_id=None):
        self.call(
            "complete",
            step_id=step_id,
            note="原说明",
            link="https://example.com/original",
            extra_minutes=30,
            date="2026-10-14",
            verified=True,
            allow_unfinished=True,
        )
        return Event.objects.filter(
            task_id=self.task["id"], step_id=step_id, kind="complete"
        ).first()

    def edit(self, original, **kwargs):
        return self.call(
            "completion_edit",
            step_id=str(original.step_id) if original.step_id else None,
            event_id=original.id,
            note="补充后的说明",
            link="https://example.com/revised",
            **kwargs,
        )

    def test_edit_parent_keeps_state_time_and_original_event(self):
        original = self.finish()
        data = original.data.copy()
        before = self.get()
        entries = list(TimeEntry.objects.values())
        status_events = TaskEvent.objects.count()
        result = self.edit(original)
        self.assertEqual(result["task"]["status"], "completed")
        self.assertEqual(result["task"]["version"], before["task"]["version"] + 1)
        self.assertEqual(result["summary"], before["summary"])
        self.assertEqual(list(TimeEntry.objects.values()), entries)
        self.assertEqual(TaskEvent.objects.count(), status_events)
        original.refresh_from_db()
        self.assertEqual(original.data, data)
        current = result["completion"]
        self.assertEqual(current["event_id"], original.id)
        self.assertEqual(current["completed_at"], original.created_at.isoformat())
        self.assertEqual(current["note"], "补充后的说明")
        self.assertEqual(current["link"], "https://example.com/revised")
        edit = Event.objects.get(kind="completion_edit")
        self.assertEqual(
            edit.data["before"], {"note": "原说明", "link": "https://example.com/original"}
        )
        self.assertEqual(edit.data["after"]["note"], "补充后的说明")
        self.assertEqual(self.get()["completion"], current)

    def test_edit_step_even_when_parent_completed_and_preserve_undo(self):
        step = self.steps()[0]
        original = self.finish(step["id"])
        self.finish()
        ledger = list(Profile.objects.values())
        result = self.edit(original)
        self.assertEqual(result["steps"][0]["status"], "completed")
        self.assertEqual(result["steps"][0]["completion"]["note"], "补充后的说明")
        self.assertEqual(result["steps"][0]["actual_minutes"], 30)
        self.assertEqual(result["task"]["status"], "completed")
        self.assertEqual(list(Profile.objects.values()), ledger)
        self.call("undo", step_id=None)
        undone = self.call("undo", step_id=step["id"])
        self.assertEqual(undone["steps"][0]["status"], "planned")
        self.assertIsNone(undone["steps"][0]["completion"])
        newer = self.finish(step["id"])
        self.edit(original, expected=409)
        self.assertNotEqual(newer.id, original.id)
        self.assertEqual(self.get()["steps"][0]["completion"]["note"], "原说明")

    def test_only_current_completed_target_and_valid_content(self):
        self.call("completion_edit", step_id=None, event_id=None, note="x", link="", expected=409)
        original = self.finish()
        for changes in [
            {"link": "javascript:alert(1)"},
            {"note": "x" * 2001},
            {"extra_minutes": 2},
            {"event_id": original.id + 1},
            {"step_id": str(uuid.uuid4())},
        ]:
            data = {"step_id": None, "event_id": original.id, "note": "x", "link": "", **changes}
            expected = 404 if "step_id" in changes else 409 if "event_id" in changes else 400
            self.call("completion_edit", expected=expected, **data)
        self.assertFalse(Event.objects.filter(kind="completion_edit").exists())
        result = self.call("completion_edit", step_id=None, event_id=original.id, note="", link="")
        self.assertEqual(result["completion"]["note"], "")
        self.assertEqual(result["completion"]["link"], "")

    def test_idempotency_stale_version_isolation_and_rollback(self):
        original = self.finish()
        version = self.get()["task"]["version"]
        self.edit(original, client=self.b, expected=404)
        key = str(uuid.uuid4())
        result = self.edit(original, version=version, key=key)
        self.assertEqual(self.edit(original, version=version, key=key), result)
        self.edit(original, version=version, expected=409)
        self.assertEqual(Event.objects.filter(kind="completion_edit").count(), 1)
        before = self.get()
        receipts = Receipt.objects.count()
        with patch("execution.services.save_receipt", side_effect=RuntimeError("injected")):
            with self.assertRaises(RuntimeError):
                self.edit(original)
        self.assertEqual(self.get(), before)
        self.assertEqual(Receipt.objects.count(), receipts)
        self.assertEqual(Event.objects.filter(kind="completion_edit").count(), 1)

    def test_legacy_completed_task_can_add_note_without_inventing_time(self):
        Task.objects.filter(pk=self.task["id"]).update(status="completed")
        result = self.call(
            "completion_edit", step_id=None, event_id=None, note="补记旧任务", link=""
        )
        self.assertEqual(result["completion"]["note"], "补记旧任务")
        self.assertIsNone(result["completion"]["event_id"])
        self.assertIsNone(result["completion"]["completed_at"])
        self.assertIsNone(result["summary"]["actual_minutes"])
        self.assertFalse(Event.objects.filter(kind="complete").exists())
        self.assertFalse(Step.objects.exists())
        self.assertEqual(self.get()["completion"], result["completion"])
