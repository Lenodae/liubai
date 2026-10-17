"""Calendar invariants over automatic whole-task commitments."""

import datetime as dt
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from django.utils import timezone
from hypothesis import given
from hypothesis import strategies as st

from load_analysis import policies


class BudgetReservationProperties(TestCase):
    @given(
        st.sampled_from(["weekly", "recurring"]),
        st.integers(-12, 12),
        st.integers(0, 24),
        st.integers(0, 10080),
        st.sampled_from(["planned", "in_progress", "paused", "completed", "abandoned"]),
    )
    def test_schedule_has_exact_week_scope(
        self, schedule, start_offset, query_offset, minutes, status
    ):
        week = dt.date(2026, 10, 12)
        start = week + dt.timedelta(weeks=start_offset)
        query = week + dt.timedelta(weeks=query_offset)
        policy = SimpleNamespace(schedule=schedule, start_week=start, end_at=None, revisions=[])
        task = SimpleNamespace(budget_policy=policy, weekly_minutes=minutes, status=status)
        with patch(
            "load_analysis.workspace.now",
            return_value=timezone.make_aware(dt.datetime(2026, 10, 14)),
        ):
            active, amount = policies.reservation(task, query)
        expected = (
            status == "in_progress"
            and query >= start
            and (schedule == "recurring" or query == start)
        )
        self.assertEqual(active, expected)
        self.assertEqual(amount, minutes if expected else None)

    @given(st.integers(0, 10080), st.integers(0, 10080))
    def test_closed_week_stays_released_after_a_later_restore(self, before, after):
        week = dt.date(2026, 10, 12)
        revisions = [
            {
                "effective_week": (week + dt.timedelta(weeks=i)).isoformat(),
                "schedule": "recurring",
                "start_week": week.isoformat(),
                "minutes": before if i < 2 else after,
                "ended": i == 1,
            }
            for i in range(3)
        ]
        policy = SimpleNamespace(
            schedule="recurring", start_week=week, end_at=None, revisions=revisions
        )
        task = SimpleNamespace(budget_policy=policy, weekly_minutes=after, status="in_progress")
        with patch(
            "load_analysis.workspace.now",
            return_value=timezone.make_aware(dt.datetime(2026, 11, 4)),
        ):
            outputs = [policies.reservation(task, week + dt.timedelta(weeks=i)) for i in range(3)]
        self.assertEqual(outputs, [(True, before), (False, None), (True, after)])
