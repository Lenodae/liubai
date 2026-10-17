"""One local-day mark per account, optimistic versioning, and atomic receipts."""

import hashlib
import json

from django.db import transaction

from execution import validation as v
from tasks.services import ApiError

from . import dates
from .models import DayMark, MarkReceipt
from .reading import mark_data


def validate(data):
    v.fields(data, ["date", "kind", "version"])
    day = dates.parse(data.get("date"))
    version = v.integer(data.get("version"), maximum=2147483647)
    kind = data.get("kind")
    if not isinstance(kind, str) or kind not in ("checkin", "rest", "clear"):
        raise ApiError("请选择签到、休息或撤销标记。")
    return day, version, None if kind == "clear" else kind


@transaction.atomic
def mark(uid, data, key):
    request_key = v.ident(key)
    fingerprint = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    prior = MarkReceipt.objects.filter(owner_id=uid, key=request_key).first()
    if prior:
        if prior.fingerprint != fingerprint:
            raise ApiError("同一请求标识已用于其他内容。", 409)
        return prior.response
    day, version, kind = validate(data)
    current = dates.today()
    if day != current:
        raise ApiError("日期已变化，请刷新今天的足迹后重新操作；不能补签或标记未来日期。", 409)
    row = DayMark.objects.select_for_update().filter(owner_id=uid, date=day).first()
    if version != (row.version if row else 0):
        raise ApiError("今天的标记已变化，请刷新后再操作。", 409)
    if row is None:
        row = DayMark.objects.create(owner_id=uid, date=day, kind=kind)
    elif row.kind != kind:
        row.kind = kind
        row.version += 1
        row.save(update_fields=["kind", "version", "updated_at"])
    response = {**dates.envelope(current), "day": mark_data(day, row)}
    MarkReceipt.objects.create(
        owner_id=uid, key=request_key, fingerprint=fingerprint, response=response
    )
    return response
