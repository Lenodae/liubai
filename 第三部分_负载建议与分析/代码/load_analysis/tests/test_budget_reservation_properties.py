"""Automatic totals and manual replacements must never be counted twice."""

from unittest import TestCase

from hypothesis import given, seed, settings
from hypothesis import strategies as st

from load_analysis.rules import analyze


def capacity(minutes):
    return {"budget_minutes": minutes, "buffer_minutes": 0, "confirmed": True, "stale": False}


class BudgetReservationProperties(TestCase):
    @seed(20261014)
    @settings(max_examples=100, deadline=None)
    @given(
        total=st.integers(0, 10080),
        net=st.integers(0, 10080),
        status=st.sampled_from(["planned", "in_progress", "paused", "completed", "abandoned"]),
    )
    def test_only_running_whole_task_total_counts_once(self, total, net, status):
        result = analyze(
            capacity(net),
            [
                {
                    "id": "auto",
                    "title": "总承诺",
                    "status": status,
                    "allocation_source": "auto",
                    "reservation_minutes": total,
                    "reservation_active": True,
                    "maintenance_active": True,
                    "maintenance_low": 10080,
                    "maintenance_high": 10080,
                    "progress_low": 10080,
                    "progress_high": 10080,
                    "plan_confirmed": False,
                    "scope_confirmed": False,
                }
            ],
        )
        occupancy = total if status == "in_progress" else 0
        self.assertEqual((result["low"], result["high"]), (occupancy, occupancy))
        self.assertEqual(result["deficit_low"], max(0, occupancy - net))
        self.assertEqual(result["available_low"], net - occupancy)
        self.assertEqual(result["verdict"], "conflict" if occupancy > net else "fits")

    @seed(20261014)
    @settings(max_examples=100, deadline=None)
    @given(
        progress=st.integers(0, 10080),
        maintenance=st.integers(0, 10080),
        old_total=st.integers(0, 10080),
        status=st.sampled_from(["planned", "in_progress", "paused", "completed", "abandoned"]),
    )
    def test_manual_plan_replaces_automatic_value_only_while_running(
        self, progress, maintenance, old_total, status
    ):
        result = analyze(
            capacity(10080),
            [
                {
                    "id": "manual",
                    "title": "手工分配",
                    "status": status,
                    "allocation_source": "manual",
                    "reservation_minutes": old_total,
                    "reservation_active": True,
                    "progress_low": progress,
                    "progress_high": progress,
                    "maintenance_active": True,
                    "maintenance_low": maintenance,
                    "maintenance_high": maintenance,
                    "plan_confirmed": True,
                    "scope_confirmed": True,
                }
            ],
        )
        occupancy = progress + maintenance if status == "in_progress" else 0
        self.assertEqual(result["known_low"], occupancy)
        self.assertEqual(result["high"], occupancy)

    @seed(20261014)
    @settings(max_examples=100, deadline=None)
    @given(net=st.integers(0, 10080), status=st.sampled_from(["planned", "in_progress", "paused"]))
    def test_unknown_reservation_never_becomes_free_capacity(self, net, status):
        result = analyze(
            capacity(net),
            [
                {
                    "id": "unknown",
                    "title": "尚未估时",
                    "status": status,
                    "allocation_source": "auto",
                    "reservation_minutes": None,
                    "reservation_active": True,
                }
            ],
        )
        if status == "in_progress":
            self.assertEqual(result["verdict"], "unknown")
            self.assertIsNone(result["low"])
            self.assertIsNone(result["available_low"])
            self.assertEqual(result["unknown_count"], 1)
        else:
            self.assertEqual(result["verdict"], "fits")
            self.assertEqual(result["low"], 0)
            self.assertEqual(result["available_low"], net)
            self.assertEqual(result["unknown_count"], 0)
