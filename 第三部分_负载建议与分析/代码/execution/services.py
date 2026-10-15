import hashlib
import json

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from tasks.models import TaskEvent
from tasks.services import ApiError, owned_task

from . import validation as v
from .models import AnalysisRun, Draft, Event, Profile, Receipt, Step, TimeEntry
from .serialization import completion_data, entry_data, view


def event(task, kind, data, step=None):
    Event.objects.create(task=task, step=step, actor_id=task.owner_id, kind=kind, data=data)


def step_for(task, value, optional=False):
    if value is None and optional:
        return None
    result = task.steps.filter(id=v.ident(value)).first()
    if result is None:
        raise ApiError("步骤不存在或不可访问。", 404)
    return result


def change_status(task, target, status):
    previous = target.status
    target.status = status
    if isinstance(target, Step):
        target.version += 1
    target.save()
    if isinstance(target, Step):
        event(task, "step_status", {"from": previous, "to": status}, target)
    elif previous != status:
        TaskEvent.objects.create(task=task, from_status=previous, to_status=status)
        from load_analysis import policies

        policies.synchronize(task)


def prerequisites(task, step):
    if task.status != "in_progress":
        raise ApiError("请先开始或恢复父任务。", 409)
    if step.depends.exclude(status="completed").exists():
        raise ApiError("请先完成前置步骤。", 409)


def profile_action(task, data):
    v.fields(data, ["criterion", "foundation", "constraints", "deadline", "available_minutes"])
    fields = {k: v.text(data.get(k, "")) for k in ["criterion", "foundation", "constraints"]}
    fields["deadline"] = v.date(data.get("deadline"), nullable=True)
    fields["available_minutes"] = v.integer(data.get("available_minutes"), nullable=True)
    Profile.objects.update_or_create(task=task, defaults=fields)


def draft_action(task, data):
    v.fields(data, ["nodes", "draft_id", "revision"])
    profile = Profile.objects.get(task=task)
    v.text(profile.criterion, required=True)
    nodes = v.nodes(data.get("nodes"))
    if data.get("draft_id"):
        draft = task.plan_drafts.filter(id=v.ident(data["draft_id"])).first()
        if draft is None:
            raise ApiError("草稿不存在。", 404)
        if draft.applied_at or draft.revision != v.integer(data.get("revision"), minimum=1):
            raise ApiError("草稿已被更新或采纳，请重新载入。", 409)
        # Explicit save with the latest parent version is the user's rebase review.
        draft.nodes = nodes
        draft.revision += 1
        draft.base_version = task.version + 1
        draft.save()
    else:
        Draft.objects.create(task=task, nodes=nodes, original=nodes, base_version=task.version + 1)


def apply_action(task, data):
    v.fields(data, ["draft_id", "revision", "selected"])
    draft = task.plan_drafts.filter(id=v.ident(data.get("draft_id"))).first()
    if draft is None:
        raise ApiError("草稿不存在。", 404)
    if (
        draft.applied_at
        or draft.revision != v.integer(data.get("revision"), minimum=1)
        or draft.base_version != task.version
    ):
        raise ApiError("草稿已采纳或任务已变化，请检查后重新保存草稿。", 409)
    nodes = v.nodes(draft.nodes)
    selected = data.get("selected")
    if (
        not isinstance(selected, list)
        or not selected
        or any(type(i) is not int or not 0 <= i < len(nodes) for i in selected)
        or len(selected) != len(set(selected))
    ):
        raise ApiError("请选择有效的步骤。")
    if any(d not in selected for i in selected for d in nodes[i]["depends"]):
        raise ApiError("采纳步骤时必须同时选择其前置步骤。")
    if task.steps.count() + len(selected) > 100:
        raise ApiError("单任务最多保留 100 个步骤，请缩小任务范围。")
    start = task.steps.count()
    created = {}
    for position, index in enumerate(sorted(selected), start):
        n = nodes[index]
        created[index] = Step.objects.create(
            task=task,
            position=position,
            title=n["title"],
            criterion=n["criterion"],
            low=n["low"],
            high=n["high"],
            source_draft=draft.id,
        )
    for index, step in created.items():
        step.depends.set([created[d] for d in nodes[index]["depends"]])
    draft.applied_at = timezone.now()
    draft.save()


def ledger_changed(task, steps):
    Profile.objects.filter(task=task).update(ledger_revision=F("ledger_revision") + 1)
    ids = {s.id for s in steps if s is not None}
    Step.objects.filter(id__in=ids).update(
        ledger_revision=F("ledger_revision") + 1, version=F("version") + 1
    )


def time_fields(task, data):
    step = step_for(task, data.get("step_id"), optional=True)
    minutes = v.integer(data.get("minutes"), minimum=1, maximum=10080)
    date = v.date(data.get("date"))
    if date > timezone.localdate():
        raise ApiError("实际投入日期不能晚于今天。")
    return {"step": step, "minutes": minutes, "date": date, "note": v.text(data.get("note", ""))}


def time_add(task, data):
    v.fields(data, ["step_id", "minutes", "date", "note"])
    fields = time_fields(task, data)
    entry = TimeEntry.objects.create(task=task, **fields)
    ledger_changed(task, [entry.step])
    event(task, "time_add", entry_data(entry), entry.step)


def edit_entry(task, data, delete=False):
    v.fields(
        data,
        ["entry_id", "entry_version"]
        if delete
        else ["entry_id", "entry_version", "step_id", "minutes", "date", "note"],
    )
    entry = task.time_entries.filter(
        id=v.ident(data.get("entry_id")), voided_at__isnull=True
    ).first()
    if entry is None:
        raise ApiError("耗时记录不存在或已删除。", 404)
    if entry.version != v.integer(data.get("entry_version"), minimum=1):
        raise ApiError("耗时记录已更新，请重新载入。", 409)
    before = entry_data(entry)
    old_step = entry.step
    if delete:
        entry.voided_at = timezone.now()
    else:
        for key, value in time_fields(task, data).items():
            setattr(entry, key, value)
    entry.version += 1
    entry.save()
    ledger_changed(task, [old_step, entry.step])
    event(
        task,
        "time_delete" if delete else "time_edit",
        {"before": before, "after": None if delete else entry_data(entry)},
        entry.step,
    )


def mark_verified(task, step, verified):
    target = step if step else Profile.objects.get(task=task)
    target.refresh_from_db()
    if (
        verified
        and not task.time_entries.filter(step=step, voided_at__isnull=True).exists()
        and (step is not None or not task.time_entries.filter(voided_at__isnull=True).exists())
    ):
        raise ApiError("还没有耗时记录，不能确认记录完整。")
    target.verified_revision = target.ledger_revision if verified else None
    target.save()


def complete(task, data):
    v.fields(
        data, ["step_id", "note", "link", "extra_minutes", "date", "verified", "allow_unfinished"]
    )
    step = step_for(task, data.get("step_id"), optional=True)
    target = step or task
    if target.status in ("completed", "abandoned"):
        raise ApiError("请先恢复该任务或步骤。", 409)
    if step:
        prerequisites(task, step)
    if (
        step is None
        and task.steps.exclude(status="completed").exists()
        and not v.boolean(data.get("allow_unfinished", False))
    ):
        raise ApiError("仍有未完成步骤，请确认提前结束父任务。", 409)
    note = v.text(data.get("note", ""))
    link = v.link(data.get("link", ""))
    verified = v.boolean(data.get("verified", False))
    extra = v.integer(data.get("extra_minutes"), minimum=1, maximum=10080, nullable=True)
    previous = target.status
    if extra is not None:
        time_add(
            task,
            {
                "step_id": str(step.id) if step else None,
                "minutes": extra,
                "date": data.get("date"),
                "note": "完成时补记",
            },
        )
        if step:
            step.refresh_from_db()
    change_status(task, target, "completed")
    if verified:
        mark_verified(task, step, True)
    event(
        task, "complete", {"from": previous, "note": note, "link": link, "verified": verified}, step
    )


def completion_edit(task, data):
    v.fields(data, ["step_id", "event_id", "note", "link"])
    step = step_for(task, data.get("step_id"), optional=True)
    if (step or task).status != "completed":
        raise ApiError("只有已完成的任务或步骤可以修改完成记录。", 409)
    current = completion_data(
        task.execution_events.filter(step=step, kind__in=["complete", "completion_edit"]).first()
    )
    expected_id = current["event_id"] if current else None
    if v.integer(data.get("event_id"), minimum=1, nullable=True) != expected_id:
        raise ApiError("完成记录已变化，请重新打开任务后编辑当前记录。", 409)
    after = {"note": v.text(data.get("note", "")), "link": v.link(data.get("link", ""))}
    event(
        task,
        "completion_edit",
        {
            "event_id": expected_id,
            "completed_at": current["completed_at"] if current else None,
            "before": {"note": current["note"], "link": current["link"]}
            if current
            else {"note": "", "link": ""},
            "after": after,
        },
        step,
    )
    if step:
        step.version += 1
        step.save(update_fields=["version"])


def undo(task, data):
    v.fields(data, ["step_id"])
    step = step_for(task, data.get("step_id"), optional=True)
    target = step or task
    if target.status != "completed":
        raise ApiError("当前记录不是已完成状态。", 409)
    if step and task.status in ("completed", "abandoned"):
        raise ApiError("请先恢复父任务，再撤销步骤完成。", 409)
    last = task.execution_events.filter(step=step, kind="complete").first()
    previous = last.data["from"] if last else "in_progress"
    change_status(task, target, previous)
    mark_verified(task, step, False)
    event(task, "undo", {"from": "completed", "to": previous}, step)


def step_status(task, data):
    v.fields(data, ["step_id", "status", "low", "high"])
    step = step_for(task, data.get("step_id"))
    status = data.get("status", step.status)
    if (
        status not in ("planned", "in_progress", "paused", "abandoned")
        or step.status == "completed"
    ):
        raise ApiError("完成与撤销请使用对应的登记操作。")
    if status == "in_progress":
        prerequisites(task, step)
    if task.status in ("completed", "abandoned"):
        raise ApiError("请先恢复父任务。", 409)
    if "low" in data or "high" in data:
        checked = v.nodes(
            [
                {
                    "title": step.title,
                    "criterion": step.criterion,
                    "low": data.get("low"),
                    "high": data.get("high"),
                    "depends": [],
                }
            ]
        )[0]
        step.low = checked["low"]
        step.high = checked["high"]
    change_status(task, step, status)


def verify_time(task, data):
    v.fields(data, ["step_id", "verified"])
    step = step_for(task, data.get("step_id"), optional=True)
    verified = v.boolean(data.get("verified"))
    mark_verified(task, step, verified)
    event(task, "verify_time", {"verified": verified}, step)


def analyze(task, data):
    from .provider import configuration

    v.fields(data, ["consent"])
    if not v.boolean(data.get("consent", False)):
        raise ApiError("请确认将当前任务内容发送给 DeepSeek。")
    config = configuration()
    if not config["key"]:
        raise ApiError("尚未配置 DeepSeek 密钥，请先完成本机配置。", 503)
    if AnalysisRun.objects.filter(
        task__owner_id=task.owner_id, status__in=["queued", "running"]
    ).exists():
        raise ApiError("已有分析正在等待或生成，请完成或取消后重试。", 409)
    snap = analysis_snapshot(task)
    AnalysisRun.objects.create(
        task=task, snapshot=snap, base_version=task.version + 1, model=config["model"]
    )


def analysis_snapshot(task):
    profile = Profile.objects.get(task=task)
    return {
        "title": task.title,
        "description": task.description,
        "weekly_minutes": task.weekly_minutes,
        "criterion": profile.criterion,
        "foundation": profile.foundation,
        "constraints": profile.constraints,
        "deadline": profile.deadline.isoformat() if profile.deadline else None,
        "available_minutes": profile.available_minutes,
        "existing_steps": [
            {"title": s.title, "criterion": s.criterion, "status": s.status}
            for s in task.steps.all()
        ],
    }


def cancel_analysis(task, data):
    v.fields(data, ["run_id"])
    run = task.analysis_runs.filter(id=v.ident(data.get("run_id"))).first()
    if run is None:
        raise ApiError("分析记录不存在。", 404)
    if run.status not in ("queued", "running"):
        raise ApiError("分析已结束。", 409)
    run.status = "cancelled"
    run.finished_at = timezone.now()
    run.save()


ACTIONS = {
    "profile": profile_action,
    "draft": draft_action,
    "apply": apply_action,
    "time_add": time_add,
    "time_edit": edit_entry,
    "time_delete": lambda t, d: edit_entry(t, d, True),
    "complete": complete,
    "completion_edit": completion_edit,
    "undo": undo,
    "step_status": step_status,
    "verify_time": verify_time,
    "analyze": analyze,
    "cancel_analysis": cancel_analysis,
}


def save_receipt(user_id, key, fingerprint, response):
    Receipt.objects.create(owner_id=user_id, key=key, fingerprint=fingerprint, response=response)


def mutate(user_id, task_id, data, key):
    key = v.ident(key)
    fingerprint = hashlib.sha256(
        json.dumps({"task": str(task_id), "data": data}, sort_keys=True, ensure_ascii=True).encode()
    ).hexdigest()
    with transaction.atomic():
        task = owned_task(user_id, task_id)
        prior = Receipt.objects.filter(owner_id=user_id, key=key).first()
        if prior:
            if prior.fingerprint != fingerprint:
                raise ApiError("同一请求标识已用于其他内容。", 409)
            return prior.response
        data = data.copy()
        version = v.integer(data.pop("version", None), minimum=1)
        action = data.pop("action", None)
        if not isinstance(action, str) or action not in ACTIONS:
            raise ApiError("未知的执行操作。")
        if task.version != version:
            raise ApiError("任务已变化。输入已保留，请载入最新版本并重新核对。", 409)
        Profile.objects.get_or_create(task=task)
        ACTIONS[action](task, data)
        task.version += 1
        task.save(update_fields=["version", "updated_at"])
        response = view(task)
        save_receipt(user_id, key, fingerprint, response)
        return response
