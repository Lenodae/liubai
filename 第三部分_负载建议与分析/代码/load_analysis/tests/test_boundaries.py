"""Invalid boundary requests cannot write; recovery preserves explicit unknowns."""

import datetime as dt

from django.test import TestCase

from execution.models import Profile, TimeEntry
from load_analysis.models import LoadEvent, TaskPlan
from load_analysis.tests import test_api as helpers


class LoadBoundaryTests(TestCase):
    setUp = helpers.LoadApiTests.setUp
    get = helpers.LoadApiTests.get
    post = helpers.LoadApiTests.post
    capacity = helpers.LoadApiTests.capacity
    plan = helpers.LoadApiTests.plan
    ready = helpers.LoadApiTests.ready

    def test_invalid_dates_and_readonly_windows(self):
        for data in [
            {"week": "yesterday"},
            {"week": "2026-02-30"},
            {"mode": "hours"},
            {"week": "1800-01-06"},
        ]:
            r = self.a.get("/api/load/workspace", {**self.scope, **data})
            self.assertEqual(r.status_code, 400, r.content)
        original = self.get()["fingerprint"]
        past = (dt.date.fromisoformat(self.week) - dt.timedelta(days=7)).isoformat()
        self.post(
            action="capacity",
            week=past,
            fingerprint=self.get(week=past)["fingerprint"],
            budget_minutes=1,
            buffer_minutes=0,
            expected=409,
        )
        future = (dt.date.fromisoformat(self.week) + dt.timedelta(days=7)).isoformat()
        self.post(
            action="capacity",
            week=future,
            mode="remaining",
            fingerprint=self.get(week=future, mode="remaining")["fingerprint"],
            budget_minutes=1,
            buffer_minutes=0,
            expected=409,
        )
        self.assertEqual(self.get()["fingerprint"], original)

    def test_empty_and_malformed_requests_are_not_noop_successes(self):
        original = self.ready()["fingerprint"]
        for changes in [[], None, 42, [None], [{"budget_minutes": 0}] * 101]:
            self.post("preview", changes=changes, expected=400)
        self.plan(maintenance_active=False, maintenance_low=30, maintenance_high=30, expected=400)
        self.post(
            "preview",
            changes=[
                {
                    "task_id": self.task["id"],
                    "maintenance_low": 30,
                    "maintenance_high": 30,
                    "maintenance_active": False,
                }
            ],
            expected=400,
        )
        self.post(action="nonsense", expected=400)
        self.post("workspace", expected=405)
        self.assertEqual(self.a.get("/api/load/undo", self.scope).status_code, 405)
        self.assertEqual(self.get()["fingerprint"], original)

    def test_segments_cannot_invent_capacity_or_reverse_dates(self):
        self.post("deadlines", slices=[], expected=409)
        self.ready()
        original = self.get()["fingerprint"]
        for portions in [
            [],
            [None],
            [{"end": self.week, "budget_minutes": 600, "buffer_minutes": 120, "other_minutes": 0}]
            * 2,
            [
                {
                    "end": (dt.date.fromisoformat(self.week) + dt.timedelta(days=7)).isoformat(),
                    "budget_minutes": 600,
                    "buffer_minutes": 120,
                    "other_minutes": 0,
                }
            ],
        ]:
            self.post("deadlines", slices=portions, expected=400)
        self.assertEqual(self.get()["fingerprint"], original)

    def test_budget_and_new_task_plan_can_be_reversed_to_unknown(self):
        original = self.get()
        changes = [
            {"budget_minutes": 600, "buffer_minutes": 60},
            {
                "task_id": self.task["id"],
                "status": "paused",
                "progress_low": 0,
                "progress_high": 0,
                "maintenance_low": 0,
                "maintenance_high": 0,
                "maintenance_active": False,
                "scope_confirmed": True,
            },
        ]
        expected = self.post("preview", changes=changes)
        applied = self.post("apply", changes=changes)
        self.assertEqual(expected["after"], applied["analysis"])
        self.assertEqual(applied["tasks"][0]["status"], "paused")
        self.assertEqual(applied["analysis"]["capacity"], 540)
        reverted = self.post("undo", event_id=LoadEvent.objects.get(kind="apply").pk)
        self.assertEqual(reverted["analysis"], original["analysis"])
        self.assertEqual(reverted["tasks"][0]["status"], "in_progress")
        self.assertEqual(TaskPlan.objects.count(), 0)

    def test_actual_verification_is_not_inferred_from_record_presence(self):
        p = Profile.objects.create(
            task_id=self.task["id"], ledger_revision=2, verified_revision=None
        )
        TimeEntry.objects.create(task_id=self.task["id"], date=self.week, minutes=90)
        self.assertFalse(self.get()["actual"]["verified"])
        p.verified_revision = 2
        p.save()
        self.assertTrue(self.get()["actual"]["verified"])
        p.ledger_revision = 3
        p.save()
        self.assertFalse(self.get()["actual"]["verified"])
