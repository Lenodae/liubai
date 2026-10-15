"""Independent regression examples discovered during final service review."""

from django.test import TestCase

from execution.models import Profile
from load_analysis.models import CapacityWindow

from . import test_adversarial as fixture


class ReviewRegressions(TestCase):
    setUp = fixture.LoadAdversarialTests.setUp
    create_task = fixture.LoadAdversarialTests.create_task
    workspace = fixture.LoadAdversarialTests.workspace
    body = fixture.LoadAdversarialTests.body
    write = fixture.LoadAdversarialTests.write
    ready = fixture.LoadAdversarialTests.ready

    def save_slices(self):
        Profile.objects.create(task_id=self.task["id"], deadline="2026-10-18")
        self.ready()
        portions = [
            {"end": "2026-10-15", "budget_minutes": 200, "buffer_minutes": 20, "other_minutes": 0},
            {"end": "2026-10-18", "budget_minutes": 400, "buffer_minutes": 40, "other_minutes": 0},
        ]
        result = self.write("deadlines", self.body(slices=portions))
        self.assertEqual(result["slices"], portions)
        return portions

    def apply_and_undo(self):
        applied = self.write(
            "apply", self.body(changes=[{"task_id": self.task["id"], "progress_low": 60}])
        )
        event = next(event for event in applied["history"] if event["kind"] == "apply")
        return self.write("undo", self.body(event_id=event["id"]))

    def test_preview_matches_apply_when_scope_remains_unconfirmed(self):
        self.ready()
        body = self.body(changes=[{"task_id": self.task["id"], "scope_confirmed": False}])
        before = self.workspace()
        preview = self.write("preview", body)
        self.assertEqual(self.workspace()["fingerprint"], before["fingerprint"])
        applied = self.write("apply", body)
        self.assertEqual(preview["after"], applied["analysis"])
        self.assertEqual(applied["analysis"]["verdict"], "unknown")

    def test_undo_restores_previously_valid_segment_input_and_confirmation(self):
        original = self.save_slices()
        before = self.client.get("/api/load/deadlines", self.scope).json()
        self.apply_and_undo()
        window = CapacityWindow.objects.get(owner=self.owner, **self.scope)
        self.assertEqual(window.slices, original)
        after = self.client.get("/api/load/deadlines", self.scope).json()
        self.assertEqual(after["slices"], original)
        self.assertEqual(after["checks"], before["checks"])

    def test_undo_preserves_stale_segments_without_reconfirming_them(self):
        original = self.save_slices()
        changed = self.client.patch(
            f"/api/tasks/{self.task['id']}",
            {"version": self.task["version"], "title": "安排已经发生变化"},
            content_type="application/json",
        )
        self.assertEqual(changed.status_code, 200, changed.content)
        window = CapacityWindow.objects.get(owner=self.owner, **self.scope)
        stale_token = window.slices_source
        before = self.client.get("/api/load/deadlines", self.scope).json()
        self.assertEqual(before["slices"], [])
        self.apply_and_undo()
        window.refresh_from_db()
        self.assertEqual(window.slices, original)
        self.assertEqual(window.slices_source, stale_token)
        after = self.client.get("/api/load/deadlines", self.scope).json()
        self.assertEqual(after["slices"], [])
        self.assertTrue(self.workspace()["window"]["stale"])
