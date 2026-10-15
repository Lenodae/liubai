from copy import deepcopy
from unittest import TestCase

from load_analysis.rules import analyze, deadline_checks


def window(**overrides):
    result = {
        "week": "2026-10-12",
        "mode": "week",
        "as_of": "2026-10-12T09:00:00+08:00",
        "budget_minutes": 600,
        "buffer_minutes": 120,
        "confirmed": True,
        "stale": False,
        "other_minutes": 0,
    }
    return result | overrides


def task(identifier="a", **overrides):
    result = {
        "id": identifier,
        "title": f"任务 {identifier}",
        "status": "in_progress",
        "priority": "medium",
        "weekly_minutes": 9999,
        "progress_low": 420,
        "progress_high": 600,
        "maintenance_low": None,
        "maintenance_high": None,
        "maintenance_active": False,
        "scope_confirmed": True,
        "plan_confirmed": True,
        "remaining_low": 180,
        "remaining_high": 180,
        "remaining_confirmed": True,
        "deadline": "2026-10-13",
        "actual_minutes": 300,
    }
    return result | overrides


def slices():
    return [
        {"end": "2026-10-13", "budget_minutes": 300, "buffer_minutes": 60, "other_minutes": 0},
        {"end": "2026-10-18", "budget_minutes": 300, "buffer_minutes": 60, "other_minutes": 0},
    ]


class LoadRulesTests(TestCase):
    def test_capacity_and_exact_deficits(self):
        result = analyze(
            window(budget_minutes=1200),
            [
                task(
                    progress_low=960,
                    progress_high=960,
                    maintenance_active=True,
                    maintenance_low=360,
                    maintenance_high=360,
                )
            ],
        )
        self.assertEqual(result["capacity"], 1080)
        self.assertEqual((result["low"], result["high"], result["known_low"]), (1320, 1320, 1320))
        self.assertEqual(result["verdict"], "conflict")
        self.assertEqual((result["deficit_low"], result["deficit_high"]), (240, 240))
        self.assertEqual(result["total_budget_deficit"], 120)

    def test_intervals_and_zero_capacity(self):
        self.assertEqual(analyze(window(), [task()])["verdict"], "conditional")
        self.assertEqual(analyze(window(), [task()])["deficit_high"], 120)
        self.assertEqual(analyze(window(buffer_minutes=0), [task()])["verdict"], "fits")
        self.assertEqual(analyze(window(budget_minutes=500), [task()])["verdict"], "conflict")
        empty = analyze(window(budget_minutes=0, buffer_minutes=0), [])
        self.assertEqual((empty["verdict"], empty["low"], empty["high"]), ("fits", 0, 0))
        self.assertIsNone(empty["ratio_low"])
        self.assertIsNone(empty["ratio_high"])
        self.assertEqual(
            analyze(window(budget_minutes=0, buffer_minutes=0), [task()])["verdict"], "conflict"
        )

    def test_unknown_retains_known_lower_conflict(self):
        result = analyze(
            window(),
            [
                task("a", progress_low=540, progress_high=540),
                task("b", progress_low=None, progress_high=None),
            ],
        )
        self.assertEqual(result["verdict"], "unknown")
        self.assertIsNone(result["low"])
        self.assertIsNone(result["high"])
        self.assertEqual((result["known_low"], result["deficit_low"]), (540, 60))
        self.assertIsNone(result["deficit_high"])
        self.assertEqual(result["unknown_count"], 1)
        self.assertEqual(result["unknowns"][0]["task_id"], "b")
        partial = analyze(window(), [task(progress_low=540, progress_high=None)])
        self.assertEqual((partial["known_low"], partial["deficit_low"]), (540, 60))

    def test_unknown_capacity_and_stale_confirmation(self):
        for capacity in (
            window(budget_minutes=None),
            window(buffer_minutes=None),
            window(confirmed=False),
            window(stale=True),
        ):
            with self.subTest(capacity=capacity):
                result = analyze(capacity, [task()])
                self.assertEqual(result["verdict"], "unknown")
                self.assertEqual((result["low"], result["high"]), (420, 600))
                self.assertIsNone(result["capacity"])
                self.assertIsNone(result["deficit_low"])
                self.assertIsNone(result["ratio_high"])
                self.assertIsNone(result["unknowns"][0]["task_id"])

    def test_confirmation_and_independent_maintenance(self):
        for status in ("planned", "paused", "completed", "abandoned"):
            with self.subTest(status=status):
                result = analyze(
                    window(),
                    [
                        task(
                            status=status,
                            maintenance_active=True,
                            maintenance_low=30,
                            maintenance_high=60,
                        )
                    ],
                )
                self.assertEqual((result["low"], result["high"]), (0, 0))
        result = analyze(
            window(),
            [
                task(
                    status="completed",
                    plan_confirmed=False,
                    scope_confirmed=False,
                    maintenance_active=False,
                )
            ],
        )
        self.assertEqual((result["verdict"], result["low"]), ("fits", 0))
        for changes in (
            {"plan_confirmed": False},
            {"scope_confirmed": False},
            {"maintenance_active": None},
        ):
            with self.subTest(changes=changes):
                self.assertEqual(analyze(window(), [task(**changes)])["verdict"], "unknown")

    def test_no_ledger_subtraction_or_legacy_weekly_import(self):
        original = task(progress_low=420, progress_high=420)
        without_actual = analyze(window(mode="remaining"), [original | {"actual_minutes": 0}])
        with_actual = analyze(window(mode="remaining"), [original | {"actual_minutes": 100000}])
        self.assertEqual(without_actual, with_actual)
        unconfirmed = analyze(
            window(), [task(plan_confirmed=False, progress_low=None, progress_high=None)]
        )
        self.assertIsNone(unconfirmed["low"])
        self.assertEqual(unconfirmed["known_low"], 0)

    def test_recommendations_are_explanations_and_inputs_are_unchanged(self):
        source = [task(priority="low", progress_low=700, progress_high=700)]
        before = deepcopy(source)
        result = analyze(window(), source)
        self.assertEqual(source, before)
        kinds = {entry["kind"] for entry in result["recommendations"]}
        self.assertTrue({"pause_candidate", "adjust_effort", "buffer"}.issubset(kinds))
        for entry in result["recommendations"]:
            self.assertEqual(set(entry), {"kind", "title", "reason", "task_id"})
            self.assertTrue(entry["reason"])
        missing = analyze(window(), [task(progress_high=None)])
        self.assertIn("missing", {entry["kind"] for entry in missing["recommendations"]})

    def test_invalid_numeric_inputs_are_rejected(self):
        for bad in (-1, True, 1.5, "60"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    analyze(window(budget_minutes=bad), [])
        with self.assertRaises(ValueError):
            analyze(window(buffer_minutes=601), [])
        with self.assertRaises(ValueError):
            analyze(window(), [task(progress_low=601, progress_high=600)])

    def test_malformed_status_and_maintenance_flags_are_rejected(self):
        for changes in ({"status": "missing"}, {"maintenance_active": 1}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    analyze(window(), [task(**changes)])


class DeadlineRulesTests(TestCase):
    def test_shared_cumulative_capacity(self):
        result = deadline_checks(window(), slices(), [task("a"), task("b")])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["verdict"], "conflict")
        self.assertEqual(set(result[0]["task_ids"]), {"a", "b"})
        self.assertEqual(
            (result[0]["low"], result[0]["capacity"], result[0]["deficit_low"]), (360, 240, 120)
        )

    def test_other_commitments_subtracted_once_and_progress_not_added(self):
        portions = slices()
        portions[0]["other_minutes"] = 60
        result = deadline_checks(
            window(),
            portions,
            [
                task("a", remaining_low=100, remaining_high=100),
                task("b", remaining_low=100, remaining_high=100),
                task("c", deadline="2026-10-18", remaining_low=200, remaining_high=200),
            ],
        )
        self.assertEqual(
            (result[0]["capacity"], result[0]["low"], result[0]["deficit_low"]), (180, 200, 20)
        )
        self.assertEqual((result[1]["capacity"], result[1]["low"]), (420, 400))
        self.assertEqual(result[1]["verdict"], "fits")

    def test_mid_segment_unknown_and_weekend_fallback(self):
        work = [task("a"), task("b", deadline="2026-10-18")]
        result = deadline_checks(window(), [], work)
        self.assertEqual(result[0]["verdict"], "unknown")
        self.assertIsNone(result[0]["capacity"])
        self.assertEqual((result[1]["verdict"], result[1]["capacity"]), ("fits", 480))
        interior = deadline_checks(window(), slices(), [task(deadline="2026-10-14")])
        self.assertEqual(interior[0]["verdict"], "unknown")
        self.assertIsNone(interior[0]["capacity"])

    def test_unknown_remaining_keeps_minimum_deficit(self):
        result = deadline_checks(
            window(),
            slices(),
            [
                task("a", remaining_low=300, remaining_high=300),
                task("b", remaining_confirmed=False),
            ],
        )
        self.assertEqual(result[0]["verdict"], "unknown")
        self.assertEqual((result[0]["known_low"], result[0]["deficit_low"]), (300, 60))
        self.assertIsNone(result[0]["high"])
        self.assertEqual(result[0]["unknown_count"], 1)

    def test_ended_parents_are_excluded_and_bounds_are_explicit(self):
        result = deadline_checks(
            window(),
            slices(),
            [
                task("finished", status="completed"),
                task("abandoned", status="abandoned"),
                task("old", deadline="2026-10-11"),
                task("future", deadline="2026-10-20"),
                task("undated", deadline=None),
            ],
        )
        ids = [item for check in result for item in check["task_ids"]]
        self.assertNotIn("finished", ids)
        self.assertNotIn("abandoned", ids)
        by_deadline = {check["deadline"]: check for check in result}
        self.assertEqual(by_deadline["2026-10-11"]["verdict"], "expired")
        self.assertEqual(by_deadline["2026-10-20"]["verdict"], "outside_window")
        self.assertEqual(by_deadline[None]["verdict"], "unknown")

    def test_cross_week_unknown_and_confirmed_capacity(self):
        multiple = window(end="2026-10-25")
        all_slices = slices() + [
            {"end": "2026-10-25", "budget_minutes": 600, "buffer_minutes": 120, "other_minutes": 60}
        ]
        result = deadline_checks(
            multiple,
            all_slices,
            [
                task("a", remaining_low=300, remaining_high=300),
                task("b", deadline="2026-10-25", remaining_low=500, remaining_high=500),
            ],
        )
        self.assertEqual(
            (result[1]["low"], result[1]["capacity"], result[1]["verdict"]), (800, 900, "fits")
        )
        all_slices[-1]["budget_minutes"] = None
        result = deadline_checks(multiple, all_slices, [task(deadline="2026-10-25")])
        self.assertEqual(result[0]["verdict"], "unknown")
        self.assertIsNone(result[0]["capacity"])

    def test_unknown_capacity_or_other_occupancy_never_claims_fit(self):
        for source in (window(stale=True), window(confirmed=False), window(other_minutes=None)):
            with self.subTest(source=source):
                result = deadline_checks(source, [], [task(deadline="2026-10-18")])
                self.assertEqual(result[0]["verdict"], "unknown")
                self.assertIsNone(result[0]["capacity"])
        portions = slices()
        portions[0]["other_minutes"] = None
        self.assertEqual(deadline_checks(window(), portions, [task()])[0]["verdict"], "unknown")

    def test_deadline_intervals_and_remaining_start(self):
        result = deadline_checks(window(), slices(), [task(remaining_low=200, remaining_high=300)])
        self.assertEqual(result[0]["verdict"], "conditional")
        self.assertEqual(result[0]["deficit_high"], 60)
        result = deadline_checks(
            window(mode="remaining", as_of="2026-10-14T12:00:00+08:00"), [], [task()]
        )
        self.assertEqual(result[0]["verdict"], "expired")

    def test_deadline_inputs_are_not_mutated_and_invalid_slices_rejected(self):
        portions, work = slices(), [task()]
        before = deepcopy((portions, work))
        deadline_checks(window(), portions, work)
        self.assertEqual((portions, work), before)
        with self.assertRaises(ValueError):
            deadline_checks(window(), list(reversed(portions)), work)
        with self.assertRaises(ValueError):
            deadline_checks(window(), portions, [task(deadline="2026-02-30")])
        portions[0]["other_minutes"] = 241
        with self.assertRaises(ValueError):
            deadline_checks(window(), portions, work)

    def test_malformed_window_and_work_cannot_claim_feasibility(self):
        for source in (
            window(week="2026-10-13"),
            window(start="2026-10-20"),
            window(week=20261012),
        ):
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    deadline_checks(source, [], [task()])
        with self.assertRaises(ValueError):
            deadline_checks(window(), slices(), [task(status="missing")])

    def test_explicit_start_does_not_require_a_confirmed_timestamp(self):
        source = window(mode="remaining", start="2026-10-14", as_of=None, confirmed=False)
        result = deadline_checks(source, [], [task(deadline="2026-10-18")])
        self.assertEqual(result[0]["verdict"], "unknown")
        self.assertIsNone(result[0]["capacity"])
