"""Public daily-footprint contract; all data lives in Django's disposable database."""

import calendar
import datetime as dt
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from django.apps import apps
from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.test import Client, TestCase, TransactionTestCase
from django.utils import timezone
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.extra.django import TestCase as PropertyTestCase

from execution.models import Event, Profile, Step, TimeEntry
from load_analysis.models import BudgetPolicy
from load_analysis.workspace import build
from tasks.models import Task, TaskEvent
from tasks.services import create_task


class Helpers:
    def setUp(self):
        self.user = get_user_model().objects.create_user("footprint_owner")
        self.other = get_user_model().objects.create_user("footprint_other")
        self.client.force_login(self.user)
        self.foreign = Client()
        self.foreign.force_login(self.other)
        self.today = timezone.localdate()
        self.task, _ = create_task(
            self.user.pk,
            {"title": "学习", "status": "in_progress", "weekly_minutes": 180},
            str(uuid.uuid4()),
        )
        self.step = Step.objects.create(
            task=self.task, title="第一步", criterion="完成", position=0
        )

    def mark(self, kind="checkin", version=0, date=None, key=None, client=None, extra=None):
        return (client or self.client).post(
            "/api/footprints/mark",
            {"date": str(date or self.today), "kind": kind, "version": version, **(extra or {})},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=key or str(uuid.uuid4()),
        )

    def success(self, *args, **kwargs):
        response = self.mark(*args, **kwargs)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def day(self, date=None, client=None):
        response = (client or self.client).get(
            "/api/footprints/day", {"date": str(date or self.today)}
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def calendar(self, view="recent", year=None):
        query = {"view": view}
        if year is not None:
            query["year"] = year
        response = self.client.get("/api/footprints/calendar", query)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def event(self, kind, day=None, step=None, data=None, hour=12):
        event = Event.objects.create(
            task=self.task, step=step, actor=self.user, kind=kind, data=data or {}
        )
        stamp = timezone.make_aware(dt.datetime.combine(day or self.today, dt.time(hour)))
        Event.objects.filter(pk=event.pk).update(created_at=stamp)
        return event


class FootprintsContract(Helpers, TestCase):
    def test_day_input_floor_missing_date_and_unknown_fields_are_rejected(self):
        for query in (
            {"date": "1899-12-31"},
            {},
            {"date": str(self.today), "owner": self.other.pk},
        ):
            self.assertEqual(self.client.get("/api/footprints/day", query).status_code, 400)
        self.assertEqual(self.mark(date="1899-12-31").status_code, 400)

    def test_mark_rest_clear_versions_and_summary(self):
        self.assertEqual(self.day()["day"]["version"], 0)
        checked = self.success()["day"]
        self.assertEqual(checked, {"date": str(self.today), "mark": "checkin", "version": 1})
        self.assertEqual(self.success(version=1)["day"], checked)
        self.assertEqual(
            self.calendar()["summary"], {"checkin_days": 1, "rest_days": 0, "active_days": 0}
        )
        self.assertEqual(self.success("rest", 1)["day"]["version"], 2)
        self.assertEqual(
            self.calendar()["summary"], {"checkin_days": 0, "rest_days": 1, "active_days": 0}
        )
        self.assertEqual(
            self.success("clear", 2)["day"], {"date": str(self.today), "mark": None, "version": 3}
        )
        self.assertEqual(self.calendar()["today_mark"]["version"], 3)
        self.assertEqual(apps.get_model("daily_footprints", "DayMark").objects.count(), 1)

    def test_receipt_retry_collision_stale_version_and_old_replay(self):
        key = str(uuid.uuid4())
        first = self.success(key=key)
        self.assertEqual(self.success(key=key), first)
        self.assertEqual(self.mark("rest", 1, key=key).status_code, 409)
        self.assertEqual(self.mark("rest", 0).status_code, 409)
        self.success("rest", 1)
        self.assertEqual(self.success(key=key), first)
        self.assertEqual(self.day()["day"]["mark"], "rest")
        self.assertEqual(apps.get_model("daily_footprints", "MarkReceipt").objects.count(), 2)

    def test_mark_does_not_change_task_budget_ledger_or_completion(self):
        TimeEntry.objects.create(task=self.task, step=self.step, date=self.today, minutes=45)
        self.event("complete", step=self.step, data={"note": "做好一小步"})
        week = self.today - dt.timedelta(days=self.today.weekday())
        models = (Task, TaskEvent, Step, Profile, TimeEntry, Event, BudgetPolicy)
        before = {model.__name__: list(model.objects.values()) for model in models}
        budget = build(self.user.pk, week, "week")
        for kind, version in (("checkin", 0), ("rest", 1), ("clear", 2)):
            self.success(kind, version)
            self.assertEqual(
                {model.__name__: list(model.objects.values()) for model in models}, before
            )
            self.assertEqual(build(self.user.pk, week, "week"), budget)

    def test_owner_auth_csrf_and_workspace_fence(self):
        self.success()
        self.assertEqual(self.day(client=self.foreign)["day"]["mark"], None)
        self.assertEqual(
            self.foreign.get("/api/footprints/calendar").json()["summary"]["checkin_days"], 0
        )
        self.assertEqual(self.success(client=self.foreign)["day"]["version"], 1)
        self.assertEqual(Client().get("/api/footprints/calendar").status_code, 401)
        self.assertEqual(
            Client().post("/api/footprints/mark", {}, content_type="application/json").status_code,
            401,
        )
        self.assertEqual(
            self.client.get(
                "/api/footprints/calendar", HTTP_X_WORKSPACE_USER=str(self.other.pk)
            ).status_code,
            401,
        )
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.user)
        self.assertEqual(self.mark("rest", 1, client=csrf).status_code, 403)
        csrf.get("/")
        response = csrf.post(
            "/api/footprints/mark",
            {"date": str(self.today), "kind": "rest", "version": 1},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
            HTTP_X_CSRFTOKEN=csrf.cookies[django_settings.CSRF_COOKIE_NAME].value,
        )
        self.assertEqual(response.status_code, 200)

    def test_hostile_fields_methods_and_dates_are_rejected(self):
        self.assertEqual(self.calendar()["timezone"], "Asia/Shanghai")
        for extra in ({"owner": self.other.pk}, {"minutes": 50}, {"status": "completed"}):
            self.assertEqual(self.mark(extra=extra).status_code, 400)
        for version in (True, -1, "0", None, 1.5):
            self.assertEqual(self.mark(version=version).status_code, 400)
        for kind in ("bad", None, [], {}):
            self.assertEqual(self.mark(kind=kind).status_code, 400)
        for date in ("20261015", "2026-W42-4", "2026-02-30", "1900-01-01x"):
            self.assertEqual(self.mark(date=date).status_code, 400)
        for offset in (-1, 1):
            self.assertEqual(
                self.mark(date=self.today + dt.timedelta(days=offset)).status_code, 409
            )
        for year in ("abcd", 1899, self.today.year + 1, "2024.0"):
            self.assertEqual(
                self.client.get(
                    "/api/footprints/calendar", {"view": "year", "year": year}
                ).status_code,
                400,
            )
        self.assertEqual(
            self.client.get(
                "/api/footprints/day", {"date": str(self.today + dt.timedelta(days=1))}
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.get("/api/footprints/calendar", {"view": "bad"}).status_code, 400
        )
        self.assertEqual(self.client.get("/api/footprints/mark").status_code, 405)
        self.assertEqual(
            self.client.post(
                "/api/footprints/calendar", {}, content_type="application/json"
            ).status_code,
            405,
        )
        self.assertEqual(self.client.get("/api/footprints/missing").status_code, 404)
        self.assertEqual(self.mark(key="bad").status_code, 400)

    def test_recent_84_days_and_leap_year_today_mark(self):
        self.success()
        recent = self.calendar()
        monday = self.today - dt.timedelta(days=self.today.weekday())
        self.assertEqual(recent["start"], str(monday - dt.timedelta(weeks=11)))
        self.assertEqual(recent["end"], str(monday + dt.timedelta(days=6)))
        self.assertEqual(len(recent["days"]), 84)
        for year, length in ((2024, 366), (2025, 365)):
            result = self.calendar("year", year)
            self.assertEqual(len(result["days"]), length)
            self.assertEqual(result["start"], f"{year}-01-01")
            self.assertEqual(result["end"], f"{year}-12-31")
            self.assertEqual(result["today_mark"]["mark"], "checkin")
            self.assertEqual(result["summary"]["checkin_days"], 0)
        for day in recent["days"]:
            if day["date"] > str(self.today):
                self.assertEqual(
                    (day["minutes"], day["completed_steps"], day["mark"]), (0, 0, None)
                )

    def test_parent_child_ledger_sum_edit_void_and_trash_retention(self):
        parent = TimeEntry.objects.create(task=self.task, date=self.today, minutes=30)
        child = TimeEntry.objects.create(
            task=self.task, step=self.step, date=self.today, minutes=45
        )
        TimeEntry.objects.create(
            task=self.task, date=self.today, minutes=99, voided_at=timezone.now()
        )
        self.assertEqual(self.day()["day"]["minutes"], 75)
        Task.objects.filter(pk=self.task.pk).update(deleted_at=timezone.now())
        detail = self.day()
        self.assertEqual(len(detail["entries"]), 2)
        self.assertTrue(all(row["deleted"] for row in detail["entries"]))
        self.assertEqual(detail["day"]["minutes"], 75)
        yesterday = self.today - dt.timedelta(days=1)
        TimeEntry.objects.filter(pk=parent.pk).update(date=yesterday, minutes=20)
        TimeEntry.objects.filter(pk=child.pk).update(voided_at=timezone.now())
        self.assertEqual(self.day()["day"]["minutes"], 0)
        self.assertEqual(self.day(yesterday)["day"]["minutes"], 20)
        self.assertEqual(self.calendar()["summary"]["active_days"], 1)

    def test_completion_edit_undo_redo_use_original_local_day(self):
        yesterday = self.today - dt.timedelta(days=1)
        first = self.event("complete", yesterday, self.step, {"note": "原说明"})
        self.event(
            "completion_edit",
            step=self.step,
            data={"after": {"note": "更新说明"}, "completed_at": "2000-01-01"},
        )
        detail = self.day(yesterday)
        self.assertEqual(detail["day"]["completed_steps"], 1)
        self.assertEqual(detail["completions"][0]["event_id"], first.pk)
        self.assertEqual(detail["completions"][0]["note"], "更新说明")
        self.assertEqual(self.day()["day"]["completed_steps"], 0)
        self.event("undo", step=self.step)
        self.assertEqual(self.day(yesterday)["day"]["completed_steps"], 0)
        self.event("complete", step=self.step, data={"note": "重新完成"})
        self.event("complete", data={"note": "整件事完成"})
        Task.objects.filter(pk=self.task.pk).update(deleted_at=timezone.now())
        detail = self.day()
        self.assertEqual(
            (detail["day"]["completed_steps"], detail["day"]["completed_tasks"]), (1, 1)
        )
        self.assertTrue(all(row["deleted"] for row in detail["completions"]))
        self.event("undo")
        self.assertEqual(self.day()["day"]["completed_steps"], 1)
        self.assertEqual(self.day()["day"]["completed_tasks"], 0)

    def test_foreign_ledger_and_events_do_not_leak(self):
        TimeEntry.objects.create(task=self.task, date=self.today, minutes=35, note="私密")
        self.event("complete", data={"note": "私密完成"})
        detail = self.day(client=self.foreign)
        self.assertEqual((detail["entries"], detail["completions"]), ([], []))
        self.assertFalse(detail["day"]["has_activity"])
        self.assertEqual(
            self.foreign.get("/api/footprints/calendar").json()["summary"]["active_days"], 0
        )

    def test_midnight_retry_is_read_only_new_stale_write_conflicts(self):
        before = dt.datetime(2026, 10, 14, 15, 59, tzinfo=dt.timezone.utc)
        after = before + dt.timedelta(minutes=2)
        key = str(uuid.uuid4())
        with patch("django.utils.timezone.now", return_value=before):
            self.client.force_login(self.user)
            first = self.success(date="2026-10-14", key=key)
        with patch("django.utils.timezone.now", return_value=after):
            self.client.force_login(self.user)
            self.assertEqual(self.success(date="2026-10-14", key=key), first)
            self.assertEqual(self.mark(date="2026-10-14").status_code, 409)
            current = self.calendar()
            self.assertEqual(current["today"], "2026-10-15")
            self.assertEqual(
                current["today_mark"], {"date": "2026-10-15", "mark": None, "version": 0}
            )

    def test_completion_utc_boundary_uses_shanghai_and_future_fact_hidden(self):
        record = self.event("complete", step=self.step)
        Event.objects.filter(pk=record.pk).update(
            created_at=dt.datetime(2026, 10, 14, 16, 1, tzinfo=dt.timezone.utc)
        )
        now = dt.datetime(2026, 10, 15, 2, 0, tzinfo=dt.timezone.utc)
        with patch("django.utils.timezone.now", return_value=now):
            self.client.force_login(self.user)
            TimeEntry.objects.create(task=self.task, date="2026-10-16", minutes=50)
            self.assertEqual(self.day(dt.date(2026, 10, 14))["day"]["completed_steps"], 0)
            self.assertEqual(self.day(dt.date(2026, 10, 15))["day"]["completed_steps"], 1)
            future = next(row for row in self.calendar()["days"] if row["date"] == "2026-10-16")
            self.assertEqual(future["minutes"], 0)

    def test_receipt_failure_rolls_back_mark(self):
        self.assertEqual(self.day()["day"]["version"], 0)
        model = apps.get_model("daily_footprints", "MarkReceipt")
        with patch.object(model.objects, "create", side_effect=RuntimeError("receipt unavailable")):
            with self.assertRaisesRegex(RuntimeError, "receipt unavailable"):
                self.mark()
        self.assertEqual(self.day()["day"]["version"], 0)
        self.assertEqual(apps.get_model("daily_footprints", "DayMark").objects.count(), 0)


class FootprintsProperties(Helpers, PropertyTestCase):
    def setUp(self):
        pass

    @settings(max_examples=18, deadline=None, report_multiple_bugs=False)
    @given(year=st.integers(1900, 2025))
    def test_calendar_is_contiguous_bounded_and_complete(self, year):
        Helpers.setUp(self)
        result = self.calendar("year", year)
        expected = [
            str(dt.date(year, 1, 1) + dt.timedelta(days=i))
            for i in range(366 if calendar.isleap(year) else 365)
        ]
        self.assertEqual([row["date"] for row in result["days"]], expected)
        self.assertEqual(result["summary"], {"checkin_days": 0, "rest_days": 0, "active_days": 0})

    @settings(max_examples=18, deadline=None, report_multiple_bugs=False)
    @given(
        amounts=st.lists(st.integers(1, 120), min_size=1, max_size=8), repetitions=st.integers(1, 4)
    )
    def test_ledger_sum_retry_and_mark_are_independent(self, amounts, repetitions):
        Helpers.setUp(self)
        for index, minutes in enumerate(amounts):
            TimeEntry.objects.create(
                task=self.task,
                step=self.step if index % 2 else None,
                date=self.today,
                minutes=minutes,
            )
        TimeEntry.objects.create(
            task=self.task, date=self.today, minutes=79, voided_at=timezone.now()
        )
        key = str(uuid.uuid4())
        first = self.success(key=key)
        for _ in range(repetitions):
            self.assertEqual(self.success(key=key), first)
        self.assertEqual(first["day"]["version"], 1)
        self.assertEqual(self.day()["day"]["minutes"], sum(amounts))
        self.success("rest", 1)
        self.assertEqual(self.day()["day"]["minutes"], sum(amounts))
        self.assertEqual(
            self.calendar()["summary"], {"checkin_days": 0, "rest_days": 1, "active_days": 1}
        )


class FootprintsConcurrency(Helpers, TransactionTestCase):
    def test_competing_first_marks_commit_once(self):
        gate = threading.Barrier(2)

        def attempt(kind):
            close_old_connections()
            client = Client()
            client.force_login(self.user)
            try:
                gate.wait(timeout=10)
                return self.mark(kind, client=client).status_code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(2) as pool:
            codes = list(pool.map(attempt, ["checkin", "rest"]))
        self.assertEqual(sorted(codes), [200, 409])
        self.assertEqual(apps.get_model("daily_footprints", "DayMark").objects.count(), 1)
        self.assertEqual(apps.get_model("daily_footprints", "MarkReceipt").objects.count(), 1)
