import datetime
import uuid
from urllib.parse import urlsplit

from tasks.services import ApiError


def fields(data, allowed):
    if set(data) - set(allowed):
        raise ApiError("包含不支持的字段。")


def text(value, limit=2000, required=False):
    if (
        not isinstance(value, str)
        or len(value.strip()) > limit
        or any(ord(x) == 0 or 0xD800 <= ord(x) <= 0xDFFF for x in value)
    ):
        raise ApiError("文字格式不正确或超过长度限制。")
    value = value.strip()
    if required and not value:
        raise ApiError("请填写名称和完成标准。")
    return value


def integer(value, minimum=0, maximum=525600, nullable=False):
    if value is None and nullable:
        return None
    if type(value) is not int or not minimum <= value <= maximum:
        raise ApiError(f"时间或版本需要是 {minimum}–{maximum} 的整数。")
    return value


def boolean(value):
    if type(value) is not bool:
        raise ApiError("确认字段需要是布尔值。")
    return value


def ident(value):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ApiError("记录编号不正确。") from exc


def date(value, nullable=False):
    if value in ("", None) and nullable:
        return None
    if not isinstance(value, str):
        raise ApiError("请填写有效日期。")
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise ApiError("请填写 YYYY-MM-DD 格式的日期。") from exc


def link(value):
    value = text(value, 1000)
    if value:
        try:
            parts = urlsplit(value)
            if parts.scheme not in ("http", "https") or not parts.netloc:
                raise ValueError
        except ValueError as exc:
            raise ApiError("成果链接仅支持 http 或 https 地址。") from exc
    return value


def nodes(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 12:
        raise ApiError("每份草稿包含 1–12 个步骤。")
    result = []
    for item in value:
        if not isinstance(item, dict):
            raise ApiError("步骤必须是一个对象。")
        fields(item, ["title", "criterion", "low", "high", "depends"])
        low = integer(item.get("low"), nullable=True)
        high = integer(item.get("high"), nullable=True)
        if (low is None) != (high is None) or (low is not None and low > high):
            raise ApiError("预计时间上下限需一起填写，且下限不大于上限。")
        deps = item.get("depends", [])
        if (
            not isinstance(deps, list)
            or any(type(i) is not int or not 0 <= i < len(value) for i in deps)
            or len(deps) != len(set(deps))
        ):
            raise ApiError("前置步骤编号不正确或重复。")
        result.append(
            {
                "title": text(item.get("title"), 120, True),
                "criterion": text(item.get("criterion"), 2000, True),
                "low": low,
                "high": high,
                "depends": deps,
            }
        )
    visited = set()

    def visit(index, path):
        if index in path:
            raise ApiError("步骤不能自我依赖或循环依赖。")
        if index in visited:
            return
        for dep in result[index]["depends"]:
            visit(dep, path | {index})
        visited.add(index)

    for i in range(len(result)):
        visit(i, set())
    return result
