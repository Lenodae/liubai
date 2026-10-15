"""Pure calculations over confirmed inputs; never infer capacity from elapsed time."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

Record = dict[str, Any]
STATUSES = {"planned", "in_progress", "paused", "completed", "abandoned"}


def _minutes(value: Any) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise ValueError("分钟数必须是非负整数或未知")
    return value


def _interval(record: Record, prefix: str) -> tuple[int | None, int | None]:
    low = _minutes(record.get(f"{prefix}_low"))
    high = _minutes(record.get(f"{prefix}_high"))
    if low is not None and high is not None and low > high:
        raise ValueError("投入下限不能大于上限")
    return low, high


def _capacity(window: Record) -> tuple[int | None, list[str]]:
    budget = _minutes(window.get("budget_minutes"))
    buffer = _minutes(window.get("buffer_minutes"))
    if budget is not None and buffer is not None and buffer > budget:
        raise ValueError("缓冲不能大于预算")
    missing = []
    if budget is None:
        missing.append("budget_minutes")
    if buffer is None:
        missing.append("buffer_minutes")
    if window.get("confirmed") is not True:
        missing.append("confirmed")
    if window.get("stale"):
        missing.append("stale")
    if missing or budget is None or buffer is None:
        return None, missing
    return budget - buffer, []


def _task_demand(task: Record) -> tuple[int, int, list[str]]:
    status = task.get("status")
    if status not in STATUSES:
        raise ValueError("未知任务状态")
    if status != "in_progress" and task.get("historical") is not True:
        return 0, 0, []
    if task.get("allocation_source") == "auto":
        # Running-task totals already include the whole task. Never add upkeep twice.
        minutes = _minutes(task.get("reservation_minutes"))
        return (0, 0, ["reservation_minutes"]) if minutes is None else (minutes, minutes, [])
    if task.get("reservation_active") is False and task.get("allocation_source") != "manual":
        if task.get("maintenance_active") is not True:
            return 0, 0, []
        # Historical maintenance remains a separate recorded component.
        status = "planned"
    maintenance = task.get("maintenance_active")
    if maintenance is not None and type(maintenance) is not bool:
        raise ValueError("是否保留维护必须明确为是、否或未知")
    fields = ["maintenance_active"] if maintenance is None else []
    reserves_progress = (status == "in_progress" and task.get("exclude_progress") is not True) or (
        status == "planned"
        and task.get("historical") is True
        and task.get("budget_committed") is True
        and task.get("allocation_source") == "manual"
    )
    components = (["progress"] if reserves_progress else []) + (
        ["maintenance"] if maintenance is True else []
    )
    ready = task.get("plan_confirmed") is True and task.get("scope_confirmed") is True
    if components and task.get("plan_confirmed") is not True:
        fields.append("plan_confirmed")
    if components and task.get("scope_confirmed") is not True:
        fields.append("scope_confirmed")
    low_sum = high_sum = 0
    for component in components:
        low, high = _interval(task, component)
        if low is None:
            fields.append(f"{component}_low")
        if high is None:
            fields.append(f"{component}_high")
        if ready:
            low_sum += low or 0
            high_sum += high or 0
    return low_sum, high_sum, fields


def _verdict(low: int, high: int, capacity: int | None, unknown: bool) -> str:
    if unknown or capacity is None:
        return "unknown"
    if low > capacity:
        return "conflict"
    return "conditional" if high > capacity else "fits"


def _recommendations(result: Record, tasks: list[Record]) -> list[Record]:
    recommendations: list[Record] = []

    def add(kind: str, title: str, reason: str, task_id: Any = None) -> None:
        recommendations.append({"kind": kind, "title": title, "reason": reason, "task_id": task_id})

    for unknown in result["unknowns"][:5]:
        add(
            "missing",
            f"先确认：{unknown['title']}",
            "尚有投入或预算资料待确认；补齐前不能把当前安排视为可行。",
            unknown["task_id"],
        )
    deficit = result["deficit_low"] or result["deficit_high"] or 0
    if deficit <= 0:
        return recommendations
    certainty = "至少" if result["deficit_low"] else "按投入上界"
    add(
        "adjust_effort",
        "比较减少本窗口投入的方案",
        f"保留当前缓冲需要{certainty}释放 {deficit} 分钟；减少投入也可能缩小本窗口交付范围。",
    )
    candidates = [
        task
        for task in tasks
        if task.get("status") == "in_progress"
        and task.get("priority") == "low"
        and task.get("plan_confirmed") is True
        and task.get("scope_confirmed") is True
        and (task.get("progress_high") or 0) > 0
    ]
    for task in sorted(candidates, key=lambda item: str(item["id"]))[:3]:
        add(
            "pause_candidate",
            f"考虑暂缓：{task['title']}",
            "这是低优先级的进行中任务。暂停后释放当前预算占用，原投入资料继续保留；先比较方案再决定。",
            task["id"],
        )
    if result["buffer"]:
        add(
            "buffer",
            "核对是否需要调整缓冲",
            f"目前预留 {result['buffer']} 分钟。减少缓冲会减少机动时间，不能消除超出总预算的缺口。",
        )
    return recommendations


def analyze(window: Record, tasks: list[Record]) -> Record:
    """Return conservative interval demand, with unknowns distinct from explicit zero."""
    capacity, window_fields = _capacity(window)
    unknowns: list[Record] = []
    if window_fields:
        unknowns.append({"task_id": None, "title": "当前时间窗口", "fields": window_fields})
    known_low = high_sum = 0
    demand_unknown = False
    for task in tasks:
        low, high, fields = _task_demand(task)
        known_low += low
        high_sum += high
        if fields:
            demand_unknown = True
            unknowns.append({"task_id": task["id"], "title": task["title"], "fields": fields})
    budget, buffer = window.get("budget_minutes"), window.get("buffer_minutes")
    result = {
        "verdict": _verdict(known_low, high_sum, capacity, bool(unknowns)),
        "low": None if demand_unknown else known_low,
        "high": None if demand_unknown else high_sum,
        "known_low": known_low,
        "unknown_count": len(unknowns),
        "unknowns": unknowns,
        "capacity": capacity,
        "budget": budget,
        "buffer": buffer,
        "deficit_low": max(0, known_low - capacity) if capacity is not None else None,
        "deficit_high": (
            max(0, high_sum - capacity) if capacity is not None and not demand_unknown else None
        ),
        "total_budget_deficit": (
            max(0, known_low - budget) if capacity is not None and budget is not None else None
        ),
        "ratio_low": known_low / capacity if capacity and not demand_unknown else None,
        "ratio_high": high_sum / capacity if capacity and not demand_unknown else None,
        "available_low": capacity - high_sum
        if capacity is not None and not demand_unknown
        else None,
        "available_high": capacity - known_low
        if capacity is not None and not demand_unknown
        else None,
    }
    result["recommendations"] = _recommendations(result, tasks)
    return result


def _date(value: Any) -> date:
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError("日期必须为 YYYY-MM-DD")
    return date.fromisoformat(value)


def _bounds(window: Record) -> tuple[date, date]:
    week = _date(window["week"])
    if week.weekday() != 0:
        raise ValueError("周窗口必须从周一开始")
    if window.get("start"):
        start = _date(window["start"])
    else:
        start = _date(window["as_of"][:10]) if window.get("mode") == "remaining" else week
    end = _date(window["end"]) if window.get("end") else week + timedelta(days=6)
    if start > end:
        raise ValueError("时间窗口起点不能晚于终点")
    return start, end


def _checkpoints(
    window: Record, slices: list[Record], start: date, end: date
) -> dict[date, int | None]:
    capacity, _ = _capacity(window)
    if not slices:
        slices = [
            {
                "end": (date.fromisoformat(window["week"]) + timedelta(days=6)).isoformat(),
                "budget_minutes": window.get("budget_minutes"),
                "buffer_minutes": window.get("buffer_minutes"),
                "other_minutes": window.get("other_minutes"),
            }
        ]
    checkpoints: dict[date, int | None] = {}
    cumulative = 0
    known = capacity is not None
    previous = start - timedelta(days=1)
    for portion in slices:
        boundary = _date(portion["end"])
        if boundary <= previous or boundary > end:
            raise ValueError("分段必须按日期递增且位于当前窗口内")
        budget = _minutes(portion.get("budget_minutes"))
        buffer = _minutes(portion.get("buffer_minutes"))
        other = _minutes(portion.get("other_minutes"))
        if budget is not None and buffer is not None:
            if buffer > budget or (other is not None and other > budget - buffer):
                raise ValueError("分段缓冲及其他占用不能大于预算")
        if budget is None or buffer is None or other is None:
            known = False
        else:
            cumulative += budget - buffer - other
        checkpoints[boundary] = cumulative if known else None
        previous = boundary
    return checkpoints


def _remaining(work: list[Record]) -> tuple[int, int, int]:
    known_low = high_sum = unknown_count = 0
    for item in work:
        low, high = _interval(item, "remaining")
        confirmed = item.get("remaining_confirmed") is True
        if confirmed:
            known_low += low or 0
            high_sum += high or 0
        if not confirmed or low is None or high is None:
            unknown_count += 1
    return known_low, high_sum, unknown_count


def _deadline_result(
    deadline: date | None, work: list[Record], capacity: int | None, special: str | None = None
) -> Record:
    low, high, unknown_count = _remaining(work)
    verdict = special or _verdict(low, high, capacity, bool(unknown_count))
    reasons = {
        "expired": "目标日期已早于本窗口起点；需要核对延期或剩余目标。",
        "outside_window": "目标日期超出本次检查范围，尚未评估。",
        "conflict": "此前到期目标的累计剩余工作下限已超过共享净容量。",
        "conditional": "只有较低投入情形可容纳；剩余工作上界超过共享净容量。",
        "fits": "已确认的累计剩余工作上界未超过该期限前共享净容量。",
    }
    if verdict == "unknown":
        reason = (
            "缺少目标日期，无法安排期限检查。"
            if deadline is None
            else "截止日前的分段容量或其他承诺占用尚未确认；不能按天平均分配。"
            if capacity is None
            else "部分目标剩余工作尚未确认；已知下限仍参与缺口检查。"
        )
    else:
        reason = reasons[verdict]
    ordered = sorted(work, key=lambda item: str(item["id"]))
    return {
        "deadline": deadline.isoformat() if deadline else None,
        "task_ids": [item["id"] for item in ordered],
        "titles": [item["title"] for item in ordered],
        "verdict": verdict,
        "low": None if unknown_count else low,
        "high": None if unknown_count else high,
        "known_low": low,
        "unknown_count": unknown_count,
        "capacity": capacity,
        "deficit_low": max(0, low - capacity) if capacity is not None else None,
        "deficit_high": max(0, high - capacity)
        if capacity is not None and not unknown_count
        else None,
        "reason": reason,
    }


def deadline_checks(window: Record, slices: list[Record], work: list[Record]) -> list[Record]:
    """Compare all goals due by each date against one cumulative capacity pool."""
    start, end = _bounds(window)
    checkpoints = _checkpoints(window, slices, start, end)
    dated: list[tuple[date, Record]] = []
    undated: list[Record] = []
    for item in work:
        if item.get("status") in {"completed", "abandoned"}:
            continue
        if item.get("status") not in STATUSES:
            raise ValueError("未知任务状态")
        if item.get("deadline"):
            dated.append((_date(item["deadline"]), item))
        else:
            undated.append(item)
    checks = []
    for deadline in sorted({deadline for deadline, _ in dated}):
        cumulative = [item for target, item in dated if target <= deadline]
        special = "expired" if deadline < start else "outside_window" if deadline > end else None
        capacity = checkpoints.get(deadline) if special is None else None
        checks.append(_deadline_result(deadline, cumulative, capacity, special))
    if undated:
        checks.append(_deadline_result(None, undated, None))
    return checks
