"""Calendar boundaries use the server's configured civil timezone."""

import datetime as dt
import re

from django.conf import settings
from django.utils import timezone

from tasks.services import ApiError


def today():
    return timezone.localdate(timezone.now(), timezone.get_default_timezone())


def envelope(current):
    return {"today": current.isoformat(), "timezone": settings.TIME_ZONE}


def parse(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ApiError("请填写 YYYY-MM-DD 格式的日期。")
    try:
        result = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ApiError("请填写有效日期。") from exc
    if result.year < 1900:
        raise ApiError("日期不能早于 1900 年。")
    return result


def bounds(view, year, current):
    if view == "recent":
        monday = current - dt.timedelta(days=current.weekday())
        return monday - dt.timedelta(weeks=11), monday + dt.timedelta(days=6)
    if view != "year":
        raise ApiError("请选择近期或全年足迹。")
    if not re.fullmatch(r"[0-9]{4}", str(year)) or not 1900 <= int(year) <= current.year:
        raise ApiError("年份应介于 1900 年与今年之间。")
    return dt.date(int(year), 1, 1), dt.date(int(year), 12, 31)


def midnight(day):
    return timezone.make_aware(dt.datetime.combine(day, dt.time()), timezone.get_default_timezone())
