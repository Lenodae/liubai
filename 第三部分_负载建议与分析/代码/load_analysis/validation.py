import datetime as dt

from django.utils import timezone

from execution import validation as v
from tasks.services import ApiError

from . import workspace as w


def writable(week, mode):
    today = timezone.localdate(w.now())
    current = today - dt.timedelta(days=today.weekday())
    if week < current or (mode == "remaining" and week != current):
        raise ApiError("过去的计划只供回顾；剩余窗口只用于当前周。", 409)


def interval(data, prefix):
    low = v.integer(data.get(f"{prefix}_low"), nullable=True)
    high = v.integer(data.get(f"{prefix}_high"), nullable=True)
    if (low is None) != (high is None) or (low is not None and low > high):
        raise ApiError("上下限须同时填写或留空，且下限不能大于上限。")
    return {f"{prefix}_low": low, f"{prefix}_high": high}


def capacity(data, week, mode):
    maximum = 10080
    if mode == "remaining":
        end = timezone.make_aware(dt.datetime.combine(week + dt.timedelta(days=7), dt.time.min))
        maximum = max(0, int((end - w.now()).total_seconds() // 60))
    budget = v.integer(data.get("budget_minutes"), maximum=maximum, nullable=True)
    buffer = v.integer(data.get("buffer_minutes"), maximum=maximum, nullable=True)
    if budget is not None and buffer is not None and buffer > budget:
        raise ApiError("缓冲不能超过可用预算。")
    return {"budget_minutes": budget, "buffer_minutes": buffer}


def slices(value, week, mode, window):
    if not isinstance(value, list) or not 1 <= len(value) <= 7:
        raise ApiError("请填写1–7个不重叠的期限分段。")
    start = timezone.localdate(w.now()) if mode == "remaining" else week
    previous = start - dt.timedelta(days=1)
    last = week + dt.timedelta(days=6)
    result = []
    for part in value:
        if not isinstance(part, dict):
            raise ApiError("分段格式不正确。")
        v.fields(part, ["end", "budget_minutes", "buffer_minutes", "other_minutes"])
        end = v.date(part.get("end"))
        if not previous < end <= last:
            raise ApiError("分段日期必须递增且位于本窗口。")
        budget = v.integer(part.get("budget_minutes"), maximum=(end - previous).days * 1440)
        buffer = v.integer(part.get("buffer_minutes"), maximum=budget)
        other = v.integer(part.get("other_minutes"), maximum=budget - buffer, nullable=True)
        result.append(
            {
                "end": end.isoformat(),
                "budget_minutes": budget,
                "buffer_minutes": buffer,
                "other_minutes": other,
            }
        )
        previous = end
    if (
        previous != last
        or sum(p["budget_minutes"] for p in result) != window["budget_minutes"]
        or sum(p["buffer_minutes"] for p in result) != window["buffer_minutes"]
    ):
        raise ApiError("分段须覆盖到周日；预算和缓冲合计分别等于本窗口值。")
    return result
