import hashlib
import json
import uuid
from typing import Any

from django.db import transaction
from django.db.models import F, QuerySet
from django.utils import timezone

from .models import KINDS, PRIORITIES, STATUSES, Task, TaskEvent


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        self.message = message
        self.status = status
        super().__init__(message)


def owned_tasks(user_id: int, *, include_deleted: bool = False) -> QuerySet[Task]:
    tasks = Task.objects.filter(owner_id=user_id).select_related("budget_policy")
    return tasks if include_deleted else tasks.filter(deleted_at__isnull=True)


def owned_task(user_id: int, task_id: uuid.UUID, *, include_deleted: bool = False) -> Task:
    task = owned_tasks(user_id, include_deleted=include_deleted).filter(id=task_id).first()
    if task is None:
        raise ApiError("任务不存在或不可访问。", 404)
    return task


def validate_fields(data: dict[str, Any], *, creating: bool) -> dict[str, Any]:
    from load_analysis import policies

    allowed = {
        "title",
        "description",
        "kind",
        "priority",
        "status",
        "weekly_minutes",
        *policies.POLICY_FIELDS,
    }
    if set(data) - allowed:
        raise ApiError("包含不支持的字段。")
    result: dict[str, Any] = {}
    if creating:
        result = {
            "title": "",
            "description": "",
            "kind": "general",
            "priority": "normal",
            "status": "planned",
            "weekly_minutes": None,
        }
    result.update(data)
    for field, limit in [("title", 120), ("description", 5000)]:
        if field not in result:
            continue
        value = result[field]
        if (
            not isinstance(value, str)
            or "\x00" in value
            or len(value.strip()) > limit
            or any(0xD800 <= ord(char) <= 0xDFFF for char in value)
        ):
            raise ApiError("名称最多 120 字，说明最多 5000 字，且必须是有效文字。")
        result[field] = value.strip()
    if "title" in result and not result["title"]:
        raise ApiError("请填写任务名称。")
    for field, choices in [("status", STATUSES), ("kind", KINDS), ("priority", PRIORITIES)]:
        if field in result and result[field] not in choices:
            raise ApiError("状态、类型或优先级不合法。")
    if "weekly_minutes" in result:
        value = result["weekly_minutes"]
        if value is not None and (type(value) is not int or not 0 <= value <= 10080):
            raise ApiError("每周投入需要是 0–10080 的整数分钟，或留空。")
    policies.validate(result, creating=creating)
    return result


def serialize_task(task: Task) -> dict[str, Any]:
    from execution.overview import step_preview
    from load_analysis import policies

    return {
        "id": str(task.id),
        "title": task.title,
        "description": task.description,
        "kind": task.kind,
        "priority": task.priority,
        "status": task.status,
        "weekly_minutes": task.weekly_minutes,
        **policies.metadata(task),
        "version": task.version,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
        "deleted_at": task.deleted_at.isoformat() if task.deleted_at else None,
        "step_preview": step_preview(task),
    }


def serialize_events(task: Task) -> list[dict[str, Any]]:
    return [
        {
            "id": event.id,
            "from_status": event.from_status,
            "to_status": event.to_status,
            "created_at": event.created_at.isoformat(),
        }
        for event in task.events.all()
    ]


def create_task(user_id: int, data: dict[str, Any], key: str) -> tuple[Task, bool]:
    from load_analysis import policies

    fields = validate_fields(data, creating=True)
    try:
        request_key = uuid.UUID(key)
    except (ValueError, AttributeError) as exc:
        raise ApiError("创建任务需要有效的请求标识，请重试。") from exc
    # Defaults tied to today's week must not change the meaning of a retry.
    comparable = {
        key: value
        for key, value in fields.items()
        if key not in policies.POLICY_FIELDS or key in data
    }
    fingerprint = hashlib.sha256(
        json.dumps(comparable, sort_keys=True, ensure_ascii=True).encode()
    ).hexdigest()
    with transaction.atomic():
        previous = (
            owned_tasks(user_id, include_deleted=True).filter(request_key=request_key).first()
        )
        if previous:
            if previous.request_fingerprint != fingerprint:
                raise ApiError("此请求已保存其他内容，请刷新后重新创建。", 409)
            return previous, False
        policy_fields = {key: fields.pop(key) for key in policies.POLICY_FIELDS}
        task = Task.objects.create(
            owner_id=user_id, request_key=request_key, request_fingerprint=fingerprint, **fields
        )
        policies.synchronize(task, policy_fields, create=True)
    return task, True


def update_task(user_id: int, task_id: uuid.UUID, data: dict[str, Any]) -> Task:
    from load_analysis import policies

    data = data.copy()
    version = data.pop("version", None)
    # Check ownership before processing attacker-controlled update fields.
    owned_task(user_id, task_id)
    if type(version) is not int or version < 1:
        raise ApiError("缺少有效版本，请重新打开任务。")
    fields = validate_fields(data, creating=False)
    if not fields:
        raise ApiError("请提供需要修改的内容。")
    with transaction.atomic():
        task = owned_task(user_id, task_id)
        policy_fields = {key: fields.pop(key) for key in policies.POLICY_FIELDS if key in fields}
        changed = (
            owned_tasks(user_id)
            .filter(id=task_id, version=version)
            .update(**fields, version=F("version") + 1, updated_at=timezone.now())
        )
        if not changed:
            raise ApiError("任务已在其他页面更新。你的输入已保留，请重新载入最新版本再编辑。", 409)
        new_status = fields.get("status", task.status)
        if new_status != task.status:
            from execution.models import Profile
            from execution.services import complete, event, mark_verified

            Profile.objects.get_or_create(task=task)
            previous_status = task.status
            if new_status == "completed":
                task.refresh_from_db()
                task.status = previous_status
                complete(task, {"allow_unfinished": False})
            else:
                TaskEvent.objects.create(
                    task=task, from_status=previous_status, to_status=new_status
                )
                if previous_status == "completed":
                    mark_verified(task, None, False)
                    event(task, "undo", {"from": previous_status, "to": new_status})
        task.refresh_from_db()
        policies.synchronize(task, {**fields, **policy_fields})
    return task
