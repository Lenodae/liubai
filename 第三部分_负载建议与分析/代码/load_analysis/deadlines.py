"""Read-only assembly of four confirmed weekly capacity windows for deadline checks."""

import datetime as dt
from typing import Any

from django.db import transaction
from django.utils import timezone

from tasks.services import ApiError

from . import validation, workspace
from .models import CapacityWindow, TaskPlan
from .rules import analyze, deadline_checks


def source_token(user_id: int, window: CapacityWindow) -> str:
    """Capacity revisions are excluded so saving slices cannot invalidate itself."""
    plans = list(
        TaskPlan.objects.filter(window_id=window.pk, window__owner_id=user_id)
        .order_by("id")
        .values_list("id", "task_id", "version")
    )
    return workspace.digest({"tasks": workspace.facts_token(user_id), "plans": plans})


def _candidate_ids(tasks: list[dict[str, Any]], end: dt.date) -> set[str]:
    return {
        task["id"]
        for task in tasks
        if task["status"] not in {"completed", "abandoned"}
        and task["deadline"]
        and dt.date.fromisoformat(task["deadline"]) <= end
    }


def _validate_other(portions: list, other: dict[str, Any]) -> None:
    values = [portion["other_minutes"] for portion in portions]
    if other["high"] is None:
        if any(value is not None for value in values):
            raise ApiError("维护或其他承诺尚未确认；请先补齐投入，或将每段其他占用均留空。")
    elif all(value is not None for value in values) and sum(values) < other["high"]:
        raise ApiError(f"分段其他占用合计不能少于已确认的维护与其他承诺上界 {other['high']} 分钟。")


def validate_other(
    user_id: int, week: dt.date, mode: str, portions: list, current: dict[str, Any]
) -> None:
    """Do not let manual segment allocation erase confirmed competing commitments."""
    candidates = _candidate_ids(current["tasks"], week + dt.timedelta(days=27))
    _validate_other(portions, _other_demand(current["tasks"], candidates))


def _other_demand(tasks: list[dict[str, Any]], candidates: set[str]) -> dict[str, Any]:
    # A goal's weekly progress and its remaining goal estimate are alternate views.
    # Running maintenance remains independent; nonrunning tasks occupy no current budget.
    inputs = []
    for task in tasks:
        item = task.copy()
        if task["id"] in candidates:
            item["exclude_progress"] = True
            item["budget_committed"] = False
            if task.get("allocation_source") == "auto":
                # Whole reservations cannot establish the independent upkeep
                # component of a goal whose remaining work is checked separately.
                item.update(
                    allocation_source="none",
                    reservation_active=None,
                    reservation_minutes=None,
                    maintenance_active=None,
                )
        inputs.append(item)
    return analyze(
        {"budget_minutes": 0, "buffer_minutes": 0, "confirmed": True, "stale": False},
        inputs,
    )


def _saved_slices(
    user_id: int, window: CapacityWindow | None, snapshot: dict[str, Any], other: dict[str, Any]
) -> list:
    if not window or not window.slices or not snapshot["window"]["confirmed"]:
        return []
    if window.slices_source != source_token(user_id, window):
        return []
    try:
        # Changing capacity must not reuse old segment totals, even if a caller
        # incremented only the capacity version and left the old token intact.
        portions = validation.slices(window.slices, window.week, window.mode, snapshot["window"])
        _validate_other(portions, other)
        return portions
    except ApiError:
        return []


def _overflow_check(end: str, other: dict[str, Any], capacity: int) -> dict[str, Any]:
    low, high = other["low"], other["high"]
    return {
        "deadline": end,
        "task_ids": [],
        "titles": ["本段维护与其他承诺"],
        "verdict": "conflict" if low > capacity else "conditional",
        "low": low,
        "high": high,
        "known_low": low,
        "unknown_count": 0,
        "capacity": capacity,
        "deficit_low": max(0, low - capacity),
        "deficit_high": max(0, high - capacity),
        "reason": "维护及其他承诺本身已超出本段净容量；尚未计入待检查目标的剩余工作。",
        "kind": "other_commitments",
    }


def _week_slices(
    user_id: int,
    week: dt.date,
    mode: str,
    candidates: set[str],
    snapshot: dict[str, Any],
) -> tuple[list, list, list, list]:
    record = CapacityWindow.objects.filter(owner_id=user_id, week=week, mode=mode).first()
    other = _other_demand(snapshot["tasks"], candidates)
    saved = _saved_slices(user_id, record, snapshot, other)
    if saved:
        return saved, saved, saved, []
    window = snapshot["window"]
    confirmed = window["confirmed"]
    portion = {
        "end": (week + dt.timedelta(days=6)).isoformat(),
        "budget_minutes": window["budget_minutes"] if confirmed else None,
        "buffer_minutes": window["buffer_minutes"] if confirmed else None,
        "other_minutes": other["high"],
    }
    capacity = snapshot["analysis"]["capacity"]
    if capacity is not None and other["high"] is not None and other["high"] > capacity:
        # Keep the real figure visible. An overcommitted derived slice is not
        # malformed user input and must never become a server error or a false fit.
        checks = [_overflow_check(portion["end"], other, capacity)]
        return [], [portion], [{**portion, "other_minutes": None}], checks
    return [], [portion], [portion], []


@transaction.atomic
def get(user_id: int, week: dt.date, mode: str) -> dict[str, Any]:
    current = workspace.build(user_id, week, mode)
    today = timezone.localdate(workspace.now())
    current_week = today - dt.timedelta(days=today.weekday())
    start = today if mode == "remaining" and week == current_week else week
    end = week + dt.timedelta(days=27)
    work = [
        {
            key: task[key]
            for key in (
                "id",
                "title",
                "status",
                "deadline",
                "remaining_low",
                "remaining_high",
                "remaining_confirmed",
            )
        }
        for task in current["tasks"]
        if task["status"] not in {"completed", "abandoned"}
    ]
    candidates = _candidate_ids(work, end)
    editable: list = []
    forecast: list = []
    inputs: list = []
    overflow: list = []
    for offset in range(4):
        period = week + dt.timedelta(weeks=offset)
        period_mode = mode if offset == 0 else "week"
        snapshot = current if offset == 0 else workspace.build(user_id, period, period_mode)
        saved, visible, portions, checks = _week_slices(
            user_id, period, period_mode, candidates, snapshot
        )
        if offset == 0:
            editable = saved
        forecast.extend(visible)
        inputs.extend(portions)
        overflow.extend(checks)
    window = {**current["window"], "start": start.isoformat(), "end": end.isoformat()}
    checks = deadline_checks(window, inputs, work) + overflow
    return {
        "window": window,
        "fingerprint": current["fingerprint"],
        "capacity": current["analysis"]["capacity"],
        "buffer": current["analysis"]["buffer"],
        "slices": editable,
        "forecast_slices": forecast,
        "work": work,
        "checks": checks,
    }
