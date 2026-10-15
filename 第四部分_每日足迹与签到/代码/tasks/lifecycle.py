"""Reversible task removal, sharing the execution receipt store without aliasing it."""

import hashlib
import json
import uuid
from typing import Any

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from execution import validation as v
from execution.models import AnalysisRun, Event, Receipt

from .services import ApiError, owned_task, owned_tasks, serialize_task


@transaction.atomic
def mutate(user_id: int, task_id: uuid.UUID, data: dict[str, Any], key: str) -> dict[str, Any]:
    task = owned_task(user_id, task_id, include_deleted=True)
    request_key = v.ident(key)
    fingerprint = hashlib.sha256(
        json.dumps(
            {"namespace": "task-lifecycle", "task": str(task_id), "data": data},
            sort_keys=True,
            ensure_ascii=True,
        ).encode()
    ).hexdigest()
    prior = Receipt.objects.filter(owner_id=user_id, key=request_key).first()
    if prior:
        if prior.fingerprint != fingerprint:
            raise ApiError("同一请求标识已用于其他内容。", 409)
        return prior.response
    v.fields(data, ["action", "version"])
    version = v.integer(data.get("version"), minimum=1)
    action = data.get("action")
    if not isinstance(action, str) or action not in ("trash", "restore"):
        raise ApiError("请选择删除或恢复任务。")
    if task.version != version:
        raise ApiError("任务已变化。请载入最新任务后重新操作。", 409)
    deleting = action == "trash"
    if deleting == (task.deleted_at is not None):
        raise ApiError("任务已在回收站。" if deleting else "任务已经恢复。", 409)
    stamp = timezone.now()
    changed = (
        owned_tasks(user_id, include_deleted=True)
        .filter(id=task_id, version=version, deleted_at__isnull=deleting)
        .update(deleted_at=stamp if deleting else None, version=F("version") + 1, updated_at=stamp)
    )
    if changed != 1:
        raise ApiError("任务已变化。请载入最新任务后重新操作。", 409)
    if deleting:
        AnalysisRun.objects.filter(task=task, status__in=["queued", "running"]).update(
            status="cancelled", error="任务已移入回收站，生成已取消。", finished_at=stamp
        )
    Event.objects.create(
        task=task,
        actor_id=user_id,
        kind=f"task_{action}",
        data={
            "status": task.status,
            "previous_deleted_at": task.deleted_at.isoformat() if task.deleted_at else None,
        },
    )
    task.refresh_from_db()
    response = {"task": serialize_task(task)}
    Receipt.objects.create(
        owner_id=user_id, key=request_key, fingerprint=fingerprint, response=response
    )
    return response
