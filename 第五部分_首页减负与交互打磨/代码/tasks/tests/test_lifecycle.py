"""Public deletion contract: reversible, scoped, atomic and budget-aware."""

import datetime as dt
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.test import Client, TestCase, TransactionTestCase
from django.utils import timezone
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.extra.django import TestCase as PropertyTestCase

from execution.jobs import run_once
from execution.models import AnalysisRun, Draft, Event, Profile, Receipt, Step, TimeEntry
from load_analysis.models import BudgetPolicy, CapacityWindow, LoadEvent, LoadReceipt, LoadSnapshot
from load_analysis.workspace import build, facts_token
from tasks.models import STATUSES, Task, TaskEvent
from tasks.services import create_task


class LifecycleHelpers:
    def setUp(self):
        self.user = get_user_model().objects.create_user("trash_owner")
        self.other = get_user_model().objects.create_user("trash_other")
        self.client.force_login(self.user)
        self.foreign = Client()
        self.foreign.force_login(self.other)
        today = timezone.localdate()
        self.week = today - dt.timedelta(days=today.weekday())
        self.task, _ = create_task(
            self.user.pk,
            {
                "title": "保留全部资料",
                "status": "in_progress",
                "weekly_minutes": 180,
                "budget_schedule": "recurring",
            },
            str(uuid.uuid4()),
        )

    def call(self, action="trash", version=None, key=None, client=None, task=None, extra=None):
        task = task or self.task
        return (client or self.client).post(
            f"/api/tasks/{task.pk}/lifecycle",
            {
                "action": action,
                "version": task.version if version is None else version,
                **(extra or {}),
            },
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=key or str(uuid.uuid4()),
        )

    def success(self, *args, **kwargs):
        response = self.call(*args, **kwargs)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["task"]

    def workspace(self, week=None, mode="week"):
        return build(self.user.pk, week or self.week, mode)


class LifecycleCase(LifecycleHelpers, TestCase):
    def historical_policy(self):
        past = self.week - dt.timedelta(days=7)
        policy = BudgetPolicy.objects.get(task=self.task)
        policy.start_week = past
        policy.revisions = [
            {
                "effective_week": past.isoformat(),
                "start_week": past.isoformat(),
                "schedule": "recurring",
                "minutes": 180,
                "status": "in_progress",
                "ended": False,
            }
        ]
        policy.save()
        return past

    @contextmanager
    def at_day(self, offset):
        with patch(
            "django.utils.timezone.now",
            return_value=timezone.make_aware(
                dt.datetime.combine(self.week + dt.timedelta(days=offset), dt.time(12))
            ),
        ):
            self.client.force_login(self.user)
            yield

    def test_historical_deleted_full_week_stays_zero_after_time_passes(self):
        past = self.historical_policy()
        with self.at_day(2):
            self.success()
            self.assertEqual(self.workspace(self.week + dt.timedelta(days=7))["analysis"]["low"], 0)
        with self.at_day(14):
            self.assertEqual(self.workspace(self.week + dt.timedelta(days=7))["analysis"]["low"], 0)
            before_delete = self.workspace(past)
            self.assertEqual(before_delete["analysis"]["low"], 180)
            self.assertIsNotNone(before_delete["tasks"][0]["deleted_at"])

    def test_restore_does_not_rewrite_prior_deleted_weeks(self):
        past = self.historical_policy()
        with self.at_day(2):
            self.success()
        with self.at_day(14):
            self.success("restore", version=2)
            self.assertEqual(
                self.workspace(self.week + dt.timedelta(days=14))["analysis"]["low"], 180
            )
            self.assertEqual(self.workspace(self.week + dt.timedelta(days=7))["analysis"]["low"], 0)
            self.assertEqual(self.workspace(past)["analysis"]["low"], 180)

    def test_historical_week_uses_last_delete_or_restore_before_week_end(self):
        self.historical_policy()
        with self.at_day(2):
            self.success()
        with self.at_day(4):
            self.success("restore", version=2)
        with self.at_day(9):
            self.success(version=3)
        with self.at_day(14):
            self.assertEqual(self.workspace(self.week)["analysis"]["low"], 180)
            self.assertEqual(self.workspace(self.week + dt.timedelta(days=7))["analysis"]["low"], 0)
        with self.at_day(16):
            self.success("restore", version=4)
        with self.at_day(21):
            self.assertEqual(
                self.workspace(self.week + dt.timedelta(days=14))["analysis"]["low"], 180
            )
            self.assertEqual(self.workspace(self.week + dt.timedelta(days=7))["analysis"]["low"], 0)

    def test_legacy_deleted_timestamp_survives_restore_for_historical_week(self):
        past = self.historical_policy()
        stamp = timezone.make_aware(
            dt.datetime.combine(self.week + dt.timedelta(days=2), dt.time(12))
        )
        Task.objects.filter(pk=self.task.pk).update(deleted_at=stamp)
        with self.at_day(14):
            self.assertEqual(self.workspace(past)["analysis"]["low"], 180)
            self.assertEqual(self.workspace(self.week + dt.timedelta(days=7))["analysis"]["low"], 0)
            self.success("restore", version=1)
            self.assertEqual(self.workspace(self.week + dt.timedelta(days=7))["analysis"]["low"], 0)

    def test_delete_and_restore_all_statuses_and_list_counts(self):
        for status in STATUSES:
            task, _ = create_task(
                self.user.pk, {"title": status, "status": status}, str(uuid.uuid4())
            )
            deleted = self.success(task=task)
            self.assertIsNotNone(deleted["deleted_at"])
            self.assertEqual(deleted["status"], status)
            self.assertEqual(deleted["version"], 2)
            normal = self.client.get("/api/tasks").json()
            self.assertNotIn(str(task.pk), [row["id"] for row in normal["tasks"]])
            self.assertEqual(normal["counts"]["trash"], 1)
            self.assertEqual(sum(normal["counts"][s] for s in STATUSES), Task.objects.count() - 1)
            trash = self.client.get("/api/tasks?status=trash").json()["tasks"]
            self.assertEqual([row["id"] for row in trash], [str(task.pk)])
            restored = self.success("restore", version=2, task=task)
            self.assertIsNone(restored["deleted_at"])
            self.assertEqual(restored["status"], status)
            self.assertEqual(restored["version"], 3)
            self.assertEqual(self.client.get("/api/tasks?status=trash").json()["tasks"], [])

    def test_deleted_task_rejects_normal_read_write_and_execution(self):
        deleted = self.success()
        base = f"/api/tasks/{self.task.pk}"
        for suffix in ("", "/events", "/workspace"):
            self.assertEqual(self.client.get(base + suffix).status_code, 404)
        self.assertEqual(
            self.client.patch(
                base,
                {"version": deleted["version"], "title": "bad"},
                content_type="application/json",
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                base + "/workspace",
                {"action": "complete", "version": 2},
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
            ).status_code,
            404,
        )
        self.assertEqual(Event.objects.filter(kind="complete").count(), 0)
        self.assertEqual(TaskEvent.objects.count(), 0)

    def test_idempotency_collision_and_stale_version(self):
        key = str(uuid.uuid4())
        first = self.success(key=key)
        second = self.success(key=key)
        self.assertEqual(second, first)
        self.assertEqual(Receipt.objects.filter(owner=self.user).count(), 1)
        self.assertEqual(self.call("restore", version=2, key=key).status_code, 409)
        self.assertEqual(self.call("restore", version=1).status_code, 409)
        self.assertEqual(self.call("trash", version=2).status_code, 409)
        restored = self.success("restore", version=2)
        self.assertEqual(restored["version"], 3)
        self.assertEqual(self.success(key=key), first)
        self.task.refresh_from_db()
        self.assertIsNone(self.task.deleted_at)
        # The shared Receipt store may not alias an execution request.
        collision = self.client.post(
            f"/api/tasks/{self.task.pk}/workspace",
            {"action": "profile", "version": 3, "criterion": "criterion"},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=key,
        )
        self.assertEqual(collision.status_code, 409)

    def test_owner_scope_auth_csrf_and_hostile_fields(self):
        self.success()
        self.assertEqual(self.call("restore", version=2, client=self.foreign).status_code, 404)
        self.assertEqual(
            Client()
            .post(f"/api/tasks/{self.task.pk}/lifecycle", {}, content_type="application/json")
            .status_code,
            401,
        )
        self.assertEqual(self.foreign.get("/api/tasks?status=trash").json()["tasks"], [])
        self.assertEqual(
            self.client.post(
                f"/api/tasks/{uuid.uuid4()}/lifecycle", {}, content_type="application/json"
            ).status_code,
            404,
        )
        for extra in ({"status": "completed"}, {"deleted_at": None}, {"owner_id": self.other.pk}):
            self.assertEqual(self.call("restore", version=2, extra=extra).status_code, 400)
        for version in (True, 0, -1, "2", [], None):
            response = self.client.post(
                f"/api/tasks/{self.task.pk}/lifecycle",
                {"action": "restore", "version": version},
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
            )
            self.assertEqual(response.status_code, 400)
        for action in ("delete", "", None, [], {}):
            self.assertEqual(self.call(action, version=2).status_code, 400)
        self.assertEqual(self.call("restore", version=2, key="bad").status_code, 400)
        self.assertEqual(self.client.get(f"/api/tasks/{self.task.pk}/lifecycle").status_code, 405)
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.user)
        self.assertEqual(self.call("restore", version=2, client=strict).status_code, 403)
        strict.get("/")
        valid = strict.post(
            f"/api/tasks/{self.task.pk}/lifecycle",
            {"action": "restore", "version": 2},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
            HTTP_X_CSRFTOKEN=strict.cookies["taskflow5_csrf"].value,
        )
        self.assertEqual(valid.status_code, 200)

    def test_preserves_relations_completion_ledger_verification_and_snapshots(self):
        profile = Profile.objects.create(
            task=self.task, criterion="完成标准", ledger_revision=2, verified_revision=2
        )
        step = Step.objects.create(
            task=self.task,
            title="步骤",
            criterion="产物",
            position=0,
            status="completed",
            ledger_revision=1,
            verified_revision=1,
        )
        entry = TimeEntry.objects.create(
            task=self.task, step=step, date=self.week, minutes=45, note="既有耗时"
        )
        event = Event.objects.create(
            task=self.task,
            step=step,
            actor=self.user,
            kind="complete",
            data={"note": "既有成果", "from": "in_progress"},
        )
        draft = Draft.objects.create(task=self.task, nodes=[], original=[], base_version=1)
        window = CapacityWindow.objects.create(owner=self.user, week=self.week, mode="week")
        snapshot = LoadSnapshot.objects.create(
            owner=self.user, window=window, data=self.workspace()
        )
        before = {
            "profile": Profile.objects.get(pk=profile.pk).__dict__.copy(),
            "step": Step.objects.get(pk=step.pk).__dict__.copy(),
            "entry": TimeEntry.objects.get(pk=entry.pk).__dict__.copy(),
            "event": event.data,
            "snapshot": snapshot.data,
            "policy": BudgetPolicy.objects.get(task=self.task).revisions,
        }
        for value in before.values():
            if isinstance(value, dict):
                value.pop("_state", None)
        self.success()
        deleted = self.workspace()
        self.assertEqual(deleted["analysis"]["low"], 0)
        self.assertEqual(deleted["actual"], {"minutes": 45, "entry_count": 1, "verified": True})
        history = self.client.get(
            "/api/load/history", {"week": self.week.isoformat(), "mode": "week"}
        ).json()
        self.assertEqual(history["tasks"][0]["minutes"], 45)
        self.assertEqual(history["tasks"][0]["id"], str(self.task.pk))
        self.assertIsNotNone(history["tasks"][0]["deleted_at"])
        Profile.objects.filter(pk=profile.pk).update(verified_revision=None)
        self.assertFalse(self.workspace()["actual"]["verified"])
        Profile.objects.filter(pk=profile.pk).update(verified_revision=2)
        self.success("restore", version=2)
        restored_history = self.client.get(
            "/api/load/history", {"week": self.week.isoformat(), "mode": "week"}
        ).json()
        self.assertIsNone(restored_history["tasks"][0]["deleted_at"])
        for label, model, pk in (
            ("profile", Profile, profile.pk),
            ("step", Step, step.pk),
            ("entry", TimeEntry, entry.pk),
        ):
            after = model.objects.get(pk=pk).__dict__.copy()
            after.pop("_state", None)
            self.assertEqual(after, before[label])
        self.assertEqual(Event.objects.get(pk=event.pk).data, before["event"])
        self.assertEqual(LoadSnapshot.objects.get(pk=snapshot.pk).data, before["snapshot"])
        self.assertEqual(BudgetPolicy.objects.get(task=self.task).revisions, before["policy"])
        self.assertTrue(Draft.objects.filter(pk=draft.pk).exists())
        self.assertEqual(Event.objects.filter(kind="complete").count(), 1)
        self.assertEqual(TaskEvent.objects.count(), 0)
        self.assertEqual(self.workspace()["analysis"]["low"], 180)

    def test_current_future_release_historical_preservation_and_token_consistency(self):
        past = self.week - dt.timedelta(days=7)
        policy = BudgetPolicy.objects.get(task=self.task)
        policy.start_week = past
        policy.revisions = [
            {
                "effective_week": past.isoformat(),
                "start_week": past.isoformat(),
                "schedule": "recurring",
                "minutes": 180,
                "status": "in_progress",
                "ended": False,
            }
        ]
        policy.save()
        original = self.workspace(past)["analysis"]
        self.success()
        self.assertEqual(self.workspace()["tasks"], [])
        self.assertEqual(self.workspace(self.week + dt.timedelta(days=7))["analysis"]["low"], 0)
        self.assertEqual(self.workspace(past)["analysis"], original)
        window = CapacityWindow.objects.create(
            owner=self.user,
            week=self.week,
            mode="remaining",
            as_of=timezone.now(),
            budget_minutes=120,
            buffer_minutes=0,
            source_token=facts_token(self.user.pk),
        )
        self.assertTrue(self.workspace(mode="remaining")["window"]["confirmed"])
        self.success("restore", version=2)
        self.assertTrue(self.workspace(mode="remaining")["window"]["stale"])
        self.assertEqual(self.workspace(self.week + dt.timedelta(days=7))["analysis"]["low"], 180)
        self.assertEqual(CapacityWindow.objects.get(pk=window.pk).budget_minutes, 120)

    def test_create_retry_after_deletion_returns_same_task(self):
        key = str(uuid.uuid4())
        data = {"title": "创建回执"}
        created = self.client.post(
            "/api/tasks", data, content_type="application/json", HTTP_IDEMPOTENCY_KEY=key
        )
        task = Task.objects.get(pk=created.json()["task"]["id"])
        self.success(task=task)
        retried = self.client.post(
            "/api/tasks", data, content_type="application/json", HTTP_IDEMPOTENCY_KEY=key
        )
        self.assertEqual(retried.status_code, 200)
        self.assertEqual(retried.json()["task"]["id"], str(task.pk))
        self.assertIsNotNone(retried.json()["task"]["deleted_at"])
        self.assertEqual(Task.objects.count(), 2)

    def test_receipt_failure_rolls_back_task_and_ai_cancellation(self):
        run = AnalysisRun.objects.create(task=self.task, snapshot={}, base_version=1, model="test")
        before = self.workspace()
        with patch(
            "execution.models.Receipt.objects.create", side_effect=RuntimeError("receipt failure")
        ):
            with self.assertRaises(RuntimeError):
                self.call()
        self.task.refresh_from_db()
        run.refresh_from_db()
        self.assertIsNone(self.task.deleted_at)
        self.assertEqual(self.task.version, 1)
        self.assertEqual(run.status, "queued")
        self.assertEqual(self.workspace()["fingerprint"], before["fingerprint"])
        self.assertEqual(Receipt.objects.count(), 0)

    def test_cancel_queued_running_and_reject_late_provider_result(self):
        queued = AnalysisRun.objects.create(
            task=self.task, snapshot={}, base_version=1, model="test"
        )
        running = AnalysisRun.objects.create(
            task=self.task, snapshot={}, base_version=1, model="test", status="running"
        )
        self.success()
        self.assertEqual(set(AnalysisRun.objects.values_list("status", flat=True)), {"cancelled"})
        with patch("execution.provider.generate") as provider:
            self.assertFalse(run_once())
            provider.assert_not_called()
        self.success("restore", version=2)
        with patch("execution.provider.generate") as provider:
            self.assertFalse(run_once())
            provider.assert_not_called()
        run = AnalysisRun.objects.create(task=self.task, snapshot={}, base_version=3, model="test")
        output = {
            "nodes": [
                {"title": "晚到建议", "criterion": "产物", "low": None, "high": None, "depends": []}
            ]
        }

        def delete_during_call(*args):
            self.success(version=3)
            return output

        with patch("execution.provider.generate", side_effect=delete_during_call):
            self.assertTrue(run_once())
        self.assertFalse(Draft.objects.filter(run=run).exists())
        self.assertEqual(AnalysisRun.objects.get(pk=run.pk).status, "cancelled")
        self.assertTrue(AnalysisRun.objects.get(pk=queued.pk).finished_at)
        self.assertTrue(AnalysisRun.objects.get(pk=running.pk).finished_at)

    def test_old_load_preview_undo_and_receipt_cannot_resurrect_deleted_tasks(self):
        current = self.workspace()
        key = str(uuid.uuid4())
        data = {
            "week": self.week.isoformat(),
            "mode": "week",
            "fingerprint": current["fingerprint"],
            "action": "capacity",
            "budget_minutes": 600,
            "buffer_minutes": 60,
        }
        original = self.client.post(
            "/api/load/settings", data, content_type="application/json", HTTP_IDEMPOTENCY_KEY=key
        )
        self.assertEqual(original.status_code, 200)
        preview_data = {
            "week": self.week.isoformat(),
            "mode": "week",
            "fingerprint": original.json()["fingerprint"],
            "changes": [{"task_id": str(self.task.pk), "status": "paused"}],
        }
        applied = self.client.post(
            "/api/load/apply",
            preview_data,
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        self.assertEqual(applied.status_code, 200)
        event_id = applied.json()["history"][0]["id"]
        self.task.refresh_from_db()
        self.success()
        retried = self.client.post(
            "/api/load/settings", data, content_type="application/json", HTTP_IDEMPOTENCY_KEY=key
        )
        self.assertEqual(retried.status_code, 200)
        self.assertEqual(retried.json()["tasks"], [])
        self.assertEqual(
            self.client.post(
                "/api/load/apply",
                preview_data,
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
            ).status_code,
            409,
        )

        undo_data = {
            "week": self.week.isoformat(),
            "mode": "week",
            "fingerprint": self.workspace()["fingerprint"],
            "event_id": event_id,
        }
        self.assertEqual(
            self.client.post(
                "/api/load/undo",
                undo_data,
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
            ).status_code,
            409,
        )

    def test_unchanged_load_retry_is_identical_and_refresh_keeps_original_window(self):
        current = self.workspace()
        key = str(uuid.uuid4())
        data = {
            "mode": "week",
            "fingerprint": current["fingerprint"],
            "action": "capacity",
            "budget_minutes": 600,
            "buffer_minutes": 60,
        }

        def request():
            return self.client.post(
                "/api/load/settings",
                data,
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY=key,
            )

        first = request()
        self.assertEqual(first.status_code, 200)
        self.assertEqual(request().json(), first.json())
        self.success()
        later = timezone.now() + dt.timedelta(days=7)
        with patch("load_analysis.workspace.now", return_value=later):
            refreshed = request()
        self.assertEqual(refreshed.status_code, 200)
        self.assertEqual(refreshed.json()["window"]["week"], self.week.isoformat())

    def test_deadline_receipt_retry_keeps_forecast_contract_after_trash_and_restore(self):
        Profile.objects.create(task=self.task, deadline=self.week + dt.timedelta(days=6))
        scope = {"week": self.week.isoformat(), "mode": "week"}
        capacity = self.client.post(
            "/api/load/settings",
            {
                **scope,
                "fingerprint": self.workspace()["fingerprint"],
                "action": "capacity",
                "budget_minutes": 600,
                "buffer_minutes": 60,
            },
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        self.assertEqual(capacity.status_code, 200, capacity.content)
        key = str(uuid.uuid4())
        data = {
            **scope,
            "fingerprint": capacity.json()["fingerprint"],
            "slices": [
                {
                    "end": (self.week + dt.timedelta(days=6)).isoformat(),
                    "budget_minutes": 600,
                    "buffer_minutes": 60,
                    "other_minutes": None,
                }
            ],
        }

        def request():
            return self.client.post(
                "/api/load/deadlines",
                data,
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY=key,
            )

        original = request()
        self.assertEqual(original.status_code, 200, original.content)
        self.assertEqual([row["id"] for row in original.json()["work"]], [str(self.task.pk)])
        before = (
            LoadEvent.objects.count(),
            LoadReceipt.objects.count(),
            CapacityWindow.objects.get(owner=self.user, **scope).version,
        )
        self.success()
        for restored in (False, True):
            if restored:
                self.success("restore", version=2)
            response = request()
            self.assertEqual(response.status_code, 200, response.content)
            result = response.json()
            self.assertTrue({"work", "checks", "forecast_slices", "slices"} <= result.keys())
            self.assertEqual(
                [row["id"] for row in result["work"]], [str(self.task.pk)] if restored else []
            )
            self.assertEqual(result, self.client.get("/api/load/deadlines", scope).json())
            self.assertEqual(
                LoadReceipt.objects.get(owner=self.user, key=key).response, original.json()
            )
            self.assertEqual(
                (
                    LoadEvent.objects.count(),
                    LoadReceipt.objects.count(),
                    CapacityWindow.objects.get(owner=self.user, **scope).version,
                ),
                before,
            )


class LifecycleProperties(LifecycleHelpers, PropertyTestCase):
    def setUp(self):
        pass

    @settings(max_examples=20, deadline=None, report_multiple_bugs=False)
    @given(deleted_day=st.integers(0, 6), restored_day=st.integers(14, 20))
    def test_time_passage_preserves_deleted_whole_weeks(self, deleted_day, restored_day):
        LifecycleHelpers.setUp(self)
        past = LifecycleCase.historical_policy(self)
        with LifecycleCase.at_day(self, deleted_day):
            self.success()
        with LifecycleCase.at_day(self, restored_day):
            self.success("restore", version=2)
            self.assertEqual(self.workspace(self.week + dt.timedelta(days=7))["analysis"]["low"], 0)
            self.assertEqual(
                self.workspace(self.week + dt.timedelta(days=14))["analysis"]["low"], 180
            )
        with LifecycleCase.at_day(self, restored_day + 7):
            self.assertEqual(self.workspace(self.week + dt.timedelta(days=7))["analysis"]["low"], 0)
            self.assertEqual(
                self.workspace(self.week + dt.timedelta(days=14))["analysis"]["low"], 180
            )
            self.assertEqual(self.workspace(past)["analysis"]["low"], 180)

    @settings(max_examples=20, deadline=None, report_multiple_bugs=False)
    @given(
        status=st.sampled_from(STATUSES),
        minutes=st.one_of(st.none(), st.integers(0, 10080)),
        repetitions=st.integers(1, 4),
    )
    def test_round_trip_preserves_facts_and_releases_exact_contribution(
        self, status, minutes, repetitions
    ):
        LifecycleHelpers.setUp(self)
        task, _ = create_task(
            self.user.pk,
            {"title": "性质任务", "status": status, "weekly_minutes": minutes},
            str(uuid.uuid4()),
        )
        entry = TimeEntry.objects.create(task=task, date=self.week, minutes=37, note="保留账本")
        initial = self.workspace()["analysis"]
        key = str(uuid.uuid4())
        for _ in range(repetitions):
            deleted = self.success(task=task, key=key)
            self.assertEqual(deleted["version"], 2)
        hidden = self.workspace()
        self.assertEqual(hidden["analysis"]["known_low"], 180)
        self.assertNotIn(str(task.pk), [row["id"] for row in hidden["tasks"]])
        self.assertEqual(hidden["actual"]["minutes"], 37)
        restored = self.success("restore", version=2, task=task)
        self.assertEqual(restored["status"], status)
        self.assertEqual(restored["weekly_minutes"], minutes)
        self.assertEqual(self.workspace()["analysis"], initial)
        self.assertEqual(TimeEntry.objects.get(pk=entry.pk).minutes, 37)
        self.assertEqual(self.workspace()["actual"]["minutes"], 37)
        self.assertEqual(TaskEvent.objects.filter(task=task).count(), 0)
        self.assertEqual(Event.objects.filter(task=task, kind="complete").count(), 0)


class LifecycleConcurrency(LifecycleHelpers, TransactionTestCase):
    def test_competing_delete_versions_commit_once(self):
        gate = threading.Barrier(2)

        def attempt(_):
            close_old_connections()
            client = Client()
            client.force_login(self.user)
            try:
                gate.wait(timeout=10)
                return self.call(client=client).status_code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(2) as pool:
            codes = list(pool.map(attempt, [1, 2]))
        self.assertEqual(sorted(codes), [200, 409])
        self.task.refresh_from_db()
        self.assertEqual(self.task.version, 2)
        self.assertIsNotNone(self.task.deleted_at)
        self.assertEqual(Receipt.objects.count(), 1)
