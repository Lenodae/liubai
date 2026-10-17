from copy import deepcopy
from unittest import TestCase

from hypothesis import given
from hypothesis import strategies as st

from load_analysis.rules import analyze, deadline_checks
from load_analysis.tests.test_rules import slices, task, window


class LoadProperties(TestCase):
    @given(st.integers(0, 10000), st.integers(0, 10000), st.integers(0, 20000))
    def test_buffer_is_reserved_exactly_once(self, capacity, buffer, demand):
        result = analyze(
            window(budget_minutes=capacity + buffer, buffer_minutes=buffer),
            [task(progress_low=demand, progress_high=demand)],
        )
        self.assertEqual(result["capacity"], capacity)
        self.assertEqual(result["deficit_low"], max(0, demand - capacity))
        self.assertEqual(result["total_budget_deficit"], max(0, demand - capacity - buffer))

    @given(
        st.lists(st.tuples(st.integers(0, 10000), st.integers(0, 10000)), max_size=20),
        st.integers(0, 20000),
    )
    def test_sum_interval_and_order(self, intervals, capacity):
        tasks = [
            task(str(i), progress_low=low, progress_high=low + extra)
            for i, (low, extra) in enumerate(intervals)
        ]
        original = deepcopy(tasks)
        result = analyze(window(budget_minutes=capacity, buffer_minutes=0), tasks)
        low, high = sum(item[0] for item in intervals), sum(sum(item) for item in intervals)
        expected = "conflict" if capacity < low else "conditional" if capacity < high else "fits"
        self.assertEqual((result["low"], result["high"], result["known_low"]), (low, high, low))
        self.assertEqual(result["verdict"], expected)
        reversed_result = analyze(
            window(budget_minutes=capacity, buffer_minutes=0), list(reversed(tasks))
        )
        for key in ("low", "high", "verdict", "known_low", "deficit_low", "deficit_high"):
            self.assertEqual(result[key], reversed_result[key])
        self.assertEqual(tasks, original)

    @given(
        st.integers(0, 10000), st.integers(0, 10000), st.integers(0, 10000), st.integers(0, 10000)
    )
    def test_capacity_growth_never_worsens_and_actual_is_not_subtracted(
        self, low, extra, capacity, growth
    ):
        tasks = [task(progress_low=low, progress_high=low + extra)]
        before = analyze(window(budget_minutes=capacity, buffer_minutes=0), tasks)
        after = analyze(window(budget_minutes=capacity + growth, buffer_minutes=0), tasks)
        rank = {"fits": 0, "conditional": 1, "conflict": 2}
        self.assertLessEqual(rank[after["verdict"]], rank[before["verdict"]])
        self.assertLessEqual(after["deficit_low"], before["deficit_low"])
        tasks[0]["actual_minutes"] = growth
        self.assertEqual(before, analyze(window(budget_minutes=capacity, buffer_minutes=0), tasks))

    @given(st.integers(0, 10000), st.integers(0, 10000))
    def test_unknown_keeps_known_lower(self, known, capacity):
        result = analyze(
            window(budget_minutes=capacity, buffer_minutes=0),
            [
                task("a", progress_low=known, progress_high=known),
                task("b", progress_low=None, progress_high=None),
            ],
        )
        self.assertEqual(result["verdict"], "unknown")
        self.assertEqual(result["known_low"], known)
        self.assertEqual(result["deficit_low"], max(0, known - capacity))
        self.assertIsNone(result["low"])
        self.assertIsNone(result["high"])

    @given(
        st.sampled_from(["planned", "paused", "completed", "abandoned"]),
        st.integers(0, 10000),
        st.integers(0, 10000),
    )
    def test_nonrunning_status_zeroes_all_current_demand(self, status, maintenance, extra):
        result = analyze(
            window(),
            [
                task(
                    status=status,
                    maintenance_active=True,
                    maintenance_low=maintenance,
                    maintenance_high=maintenance + extra,
                )
            ],
        )
        self.assertEqual((result["low"], result["high"]), (0, 0))


class DeadlineProperties(TestCase):
    @given(st.lists(st.integers(0, 500), min_size=1, max_size=12), st.integers(0, 240))
    def test_shared_capacity_is_not_reused_per_task(self, requirements, other):
        portions = slices()
        portions[0]["other_minutes"] = other
        work = [
            task(str(i), remaining_low=value, remaining_high=value)
            for i, value in enumerate(requirements)
        ]
        result = deadline_checks(window(), portions, work)[0]
        expected_capacity = 240 - other
        self.assertEqual(result["low"], sum(requirements))
        self.assertEqual(result["capacity"], expected_capacity)
        self.assertEqual(result["deficit_low"], max(0, sum(requirements) - expected_capacity))
        self.assertEqual(
            result["verdict"], "conflict" if sum(requirements) > expected_capacity else "fits"
        )

    @given(st.lists(st.integers(0, 500), min_size=1, max_size=12))
    def test_ended_parent_work_never_consumes_remaining_capacity(self, requirements):
        work = [
            task(str(i), status="completed", remaining_low=value, remaining_high=value)
            for i, value in enumerate(requirements)
        ]
        self.assertEqual(deadline_checks(window(), slices(), work), [])
