"""Atomic, scoped writes; previews never mutate a user's plan."""

import copy
import datetime as dt

from django.db import transaction

from execution import validation as v
from execution.models import Event
from tasks.models import Task
from tasks.services import ApiError, owned_task, update_task

from . import validation as check
from . import workspace as w
from .models import BudgetPolicy, CapacityWindow, LoadEvent, LoadReceipt, LoadSnapshot, TaskPlan

BASE = ["week", "mode", "fingerprint"]
CAPACITY = ["budget_minutes", "buffer_minutes"]


def assert_current(data, current):
    if data.get("fingerprint") != current["fingerprint"]:
        raise ApiError("任务、预算或日期已经变化。请刷新分析并重新预览；本次没有修改。", 409)


def save_receipt(uid, key, fingerprint, response):
    LoadReceipt.objects.create(owner_id=uid, key=key, fingerprint=fingerprint, response=response)


def ensure_window(uid, week, mode):
    return CapacityWindow.objects.get_or_create(owner_id=uid, week=week, mode=mode)[0]


def set_capacity(window, fields):
    for field, value in fields.items():
        setattr(window, field, value)
    window.as_of = w.now()
    window.source_token = w.facts_token(window.owner_id)
    window.version += 1
    window.slices = []
    window.save()


def plan_values(data):
    fields = {}
    for prefix in ["progress", "maintenance", "remaining"]:
        fields.update(check.interval(data, prefix))
    fields["maintenance_active"] = v.boolean(data.get("maintenance_active"))
    fields["scope_confirmed"] = v.boolean(data.get("scope_confirmed"))
    if not fields["maintenance_active"] and any(
        fields[k] for k in ["maintenance_low", "maintenance_high"]
    ):
        raise ApiError("不保留维护时，维护投入须为 0 或留空。")
    return fields


def save_plan(window, task, fields, *, source_status=None, confirm_remaining=False):
    plan, _ = TaskPlan.objects.get_or_create(window=window, task=task)
    for field, value in fields.items():
        setattr(plan, field, value)
    if confirm_remaining:
        plan.remaining_source_version = task.version
        plan.remaining_confirmed_at = w.now()
    plan.source_version = task.version
    plan.source_status = source_status or task.status
    plan.confirmed_at = w.now()
    plan.version += 1
    plan.save()
    return plan


def slices_current(window):
    """Preserve confirmation only for segment inputs still accepted by the reader."""
    from . import deadlines

    if not window.slices or window.slices_source != deadlines.source_token(window.owner_id, window):
        return False
    snapshot = w.build(window.owner_id, window.week, window.mode)
    candidates = deadlines._candidate_ids(snapshot["tasks"], window.week + dt.timedelta(days=27))
    other = deadlines._other_demand(snapshot["tasks"], candidates)
    return bool(deadlines._saved_slices(window.owner_id, window, snapshot, other))


def capture(window, changes):
    from . import policies

    plans = {str(p.task_id): p for p in window.plans.all()}
    tasks = []
    for change in changes:
        if "task_id" not in change:
            continue
        task = owned_task(window.owner_id, v.ident(change["task_id"]))
        plan = plans.get(str(task.id))
        state = None
        if plan:
            state = {
                **{f: getattr(plan, f) for f in w.PLAN_FIELDS},
                "source_status": plan.source_status,
                "confirmed_at": plan.confirmed_at.isoformat() if plan.confirmed_at else None,
                "source_current": plan.source_version == task.version,
                "remaining_confirmed_at": plan.remaining_confirmed_at.isoformat()
                if plan.remaining_confirmed_at
                else None,
                "remaining_current": plan.remaining_source_version == task.version,
            }
        policy = policies.get(task)
        policy_state = (
            None
            if policy is None
            else {
                "schedule": policy.schedule,
                "start_week": policy.start_week.isoformat(),
                "end_at": policy.end_at.isoformat() if policy.end_at else None,
                "revisions": copy.deepcopy(policy.revisions),
            }
        )
        tasks.append(
            {"id": str(task.id), "status": task.status, "plan": state, "policy": policy_state}
        )
    return {
        "budget_minutes": window.budget_minutes,
        "buffer_minutes": window.buffer_minutes,
        "as_of": window.as_of.isoformat() if window.as_of else None,
        "source_current": window.source_token == w.facts_token(window.owner_id),
        "slices": copy.deepcopy(window.slices),
        "slices_source": window.slices_source,
        "slices_current": slices_current(window),
        "tasks": tasks,
    }


def record(uid, window, kind, summary, before, after):
    current = w.build(uid, window.week, window.mode)
    LoadEvent.objects.create(
        owner_id=uid,
        window=window,
        kind=kind,
        summary=summary,
        before=before,
        after=after,
        after_fingerprint=current["fingerprint"],
        valid_until=w.valid_until(),
    )
    return w.build(uid, window.week, window.mode)


def scenario(uid, week, mode, data, current):
    v.fields(data, BASE + ["changes"])
    assert_current(data, current)
    changes = data.get("changes")
    if not isinstance(changes, list) or not 1 <= len(changes) <= 100:
        raise ApiError("请提供 1–100 项方案修改。")
    tasks = copy.deepcopy(current["tasks"])
    by_id = {t["id"]: t for t in tasks}
    window = current["window"].copy()
    normalized, seen = [], set()
    for change in changes:
        if not isinstance(change, dict):
            raise ApiError("方案修改格式不正确。")
        if "task_id" not in change:
            v.fields(change, CAPACITY)
            if not change or "capacity" in seen:
                raise ApiError("预算修改为空或重复。")
            seen.add("capacity")
            fields = check.capacity({**window, **change}, week, mode)
            window.update(fields)
            window.update(
                confirmed=all(value is not None for value in fields.values()), stale=False
            )
            normalized.append(fields)
            continue
        v.fields(
            change,
            [
                "task_id",
                "status",
                "progress_low",
                "progress_high",
                "maintenance_low",
                "maintenance_high",
                "maintenance_active",
                "scope_confirmed",
            ],
        )
        ident = str(v.ident(change["task_id"]))
        if ident not in by_id:
            raise ApiError("任务不存在或不可访问。", 404)
        if ident in seen or len(change) == 1:
            raise ApiError("任务方案为空或重复。")
        seen.add(ident)
        task = by_id[ident]
        # Any explicit window edit creates a manual plan; previews must not
        # keep an automatic whole-task reservation that apply will replace.
        task.update(allocation_source="manual", reservation_minutes=None)
        fields = {key: value for key, value in change.items() if key != "task_id"}
        if "status" in fields:
            if fields["status"] not in ("in_progress", "paused") or task["status"] in (
                "completed",
                "abandoned",
            ):
                raise ApiError("方案只支持开始、继续或暂停任务；完成与归档请在任务界面登记。")
            task["status"] = task["load_status"] = fields["status"]
        merged = {**task, **fields}
        for prefix in ["progress", "maintenance"]:
            if any(f"{prefix}_{bound}" in fields for bound in ["low", "high"]):
                fields.update(check.interval(merged, prefix))
        task.update(fields)
        if "maintenance_active" in fields and fields["maintenance_active"] is not None:
            v.boolean(fields["maintenance_active"])
        if "scope_confirmed" in fields:
            v.boolean(fields["scope_confirmed"])
        if task["maintenance_active"] is False and any(
            task[k] for k in ["maintenance_low", "maintenance_high"]
        ):
            raise ApiError("不保留维护时，维护投入须为 0 或留空。")
        # Saving confirms this input revision, while scope_confirmed separately
        # controls whether its demand can contribute to a valid analysis.
        task["plan_confirmed"] = True
        normalized.append({"task_id": ident, **fields})
    return {
        "before": current["analysis"],
        "after": w.analyze_tasks(window, tasks),
        "changes": normalized,
        "fingerprint": current["fingerprint"],
        "valid_until": current["valid_until"],
    }, tasks


@transaction.atomic
def preview(uid, data):
    week, mode = w.scope(data)
    check.writable(week, mode)
    current = w.build(uid, week, mode)
    return scenario(uid, week, mode, data, current)[0]


def apply(uid, week, mode, data, current):
    proposed, task_rows = scenario(uid, week, mode, data, current)
    window = ensure_window(uid, week, mode)
    before = capture(window, proposed["changes"])
    for change in proposed["changes"]:
        if "task_id" not in change:
            set_capacity(window, change)
            continue
        task = owned_task(uid, v.ident(change["task_id"]))
        row = next(t for t in task_rows if t["id"] == str(task.id))
        if change.get("status", task.status) != task.status:
            task = update_task(uid, task.id, {"version": task.version, "status": change["status"]})
        fields = {key: row[key] for key in w.PLAN_FIELDS}
        save_plan(window, task, fields, source_status=row["load_status"])
    if any("task_id" not in c for c in proposed["changes"]) or (
        mode == "remaining" and not current["window"]["stale"]
    ):
        window.source_token = w.facts_token(uid)
        window.save(update_fields=["source_token"])
    after = capture(window, proposed["changes"])
    return record(
        uid, window, "apply", f"采纳了包含 {len(proposed['changes'])} 项修改的方案。", before, after
    )


def undo(uid, week, mode, data, current):
    v.fields(data, BASE + ["event_id"])
    event = LoadEvent.objects.filter(
        pk=v.integer(data.get("event_id"), minimum=1),
        owner_id=uid,
        window__week=week,
        window__mode=mode,
        kind="apply",
    ).first()
    if event is None:
        raise ApiError("方案记录不存在或不可访问。", 404)
    if (
        event.undone_at
        or event.after_fingerprint != current["fingerprint"]
        or event.valid_until <= w.now()
    ):
        raise ApiError("方案之后已有其他变化或已跨日，不能直接撤回。请重新比较调整方案。", 409)
    window = event.window
    previous = event.before
    for row in previous["tasks"]:
        task = owned_task(uid, v.ident(row["id"]))
        if task.status != row["status"]:
            task = update_task(uid, task.id, {"version": task.version, "status": row["status"]})
        if "policy" in row:
            if row["policy"] is None:
                BudgetPolicy.objects.filter(task=task).delete()
            else:
                BudgetPolicy.objects.update_or_create(task=task, defaults=row["policy"])
        if row["plan"] is None:
            window.plans.filter(task=task).delete()
        else:
            state = row["plan"]
            restored = save_plan(
                window,
                task,
                {key: state[key] for key in w.PLAN_FIELDS},
                source_status=state["source_status"],
            )
            restored.confirmed_at = state["confirmed_at"]
            restored.source_version = task.version if state["source_current"] else 0
            restored.remaining_confirmed_at = state["remaining_confirmed_at"]
            restored.remaining_source_version = task.version if state["remaining_current"] else 0
            restored.save()
    set_capacity(window, {field: previous[field] for field in CAPACITY})
    window.as_of = previous["as_of"]
    window.source_token = w.facts_token(uid) if previous["source_current"] else ""
    window.slices = copy.deepcopy(previous.get("slices", []))
    window.slices_source = previous.get("slices_source", "")
    window.save(update_fields=["as_of", "source_token", "slices", "slices_source"])
    if previous.get("slices_current") and window.slices:
        from . import deadlines

        original_token = window.slices_source
        window.slices_source = deadlines.source_token(uid, window)
        if slices_current(window):
            window.save(update_fields=["slices_source"])
        else:
            window.slices_source = original_token
    event.undone_at = w.now()
    event.save(update_fields=["undone_at"])
    return record(uid, window, "undo", "撤回了此前采纳的方案。", event.after, event.before)


def settings(uid, week, mode, data, current):
    action = data.get("action")
    if action == "capacity":
        v.fields(data, BASE + ["action"] + CAPACITY)
        fields = check.capacity(data, week, mode)
        window = ensure_window(uid, week, mode)
        set_capacity(window, fields)
        return record(
            uid,
            window,
            "capacity",
            "确认了窗口预算与缓冲。",
            current["window"],
            w.build(uid, week, mode)["window"],
        )
    if action == "plan":
        v.fields(data, BASE + ["action", "task_id"] + list(w.PLAN_FIELDS))
        task = owned_task(uid, v.ident(data.get("task_id")))
        fields = plan_values(data)
        window = ensure_window(uid, week, mode)
        before = capture(window, [{"task_id": str(task.id)}])
        save_plan(window, task, fields, confirm_remaining=True)
        return record(
            uid,
            window,
            "plan",
            f"确认了“{task.title}”的窗口投入。",
            before,
            capture(window, [{"task_id": str(task.id)}]),
        )
    if action == "save_snapshot":
        v.fields(data, BASE + ["action"])
        window = ensure_window(uid, week, mode)
        LoadSnapshot.objects.create(owner_id=uid, window=window, data=current)
        return w.build(uid, week, mode)
    raise ApiError("未知的预算设置操作。")


@transaction.atomic
def mutate(uid, operation, data, request_key):
    key = v.ident(request_key)
    fingerprint = w.digest({"operation": operation, "data": data})
    previous = LoadReceipt.objects.filter(owner_id=uid, key=key).first()
    if previous:
        if previous.fingerprint != fingerprint:
            raise ApiError("此请求标识已用于其他内容，请刷新后重试。", 409)
        return replay(uid, operation, data, previous)
    week, mode = w.scope(data)
    check.writable(week, mode)
    current = w.build(uid, week, mode)
    assert_current(data, current)
    if operation == "settings":
        result = settings(uid, week, mode, data, current)
    elif operation == "apply":
        result = apply(uid, week, mode, data, current)
    elif operation == "undo":
        result = undo(uid, week, mode, data, current)
    elif operation == "deadlines":
        from . import deadlines

        v.fields(data, BASE + ["slices"])
        if not current["window"]["confirmed"]:
            raise ApiError("请先确认当前窗口预算与缓冲。", 409)
        portions = check.slices(data.get("slices"), week, mode, current["window"])
        deadlines.validate_other(uid, week, mode, portions, current)
        window = ensure_window(uid, week, mode)
        window.slices = portions
        window.slices_source = deadlines.source_token(uid, window)
        window.version += 1
        window.save()
        record(
            uid, window, "slices", "确认了期限前的分段容量与其他占用。", {}, {"slices": portions}
        )
        result = deadlines.get(uid, week, mode)
    else:
        raise ApiError("此接口不支持写入。", 405)
    save_receipt(uid, key, fingerprint, result)
    return result


def replay(uid, operation, data, previous):
    """Keep receipt semantics, but never replay budget rows across a trash/restore."""
    changed = Event.objects.filter(
        task__owner_id=uid,
        kind__in=["task_trash", "task_restore"],
        created_at__gt=previous.created_at,
    ).exists()
    if not changed:
        return previous.response
    original_window = previous.response.get("window", {})
    week, mode = w.scope({**data, **original_window})
    if operation == "deadlines":
        from . import deadlines

        return deadlines.get(uid, week, mode)
    return w.build(uid, week, mode)


@transaction.atomic
def history(uid, week, mode):
    current = w.build(uid, week, mode)
    rows = {str(r["task_id"]): r for r in w.actual_rows(uid, week)}
    events = LoadEvent.objects.filter(owner_id=uid, window__week=week).order_by("-id")[:200]
    snapshots = LoadSnapshot.objects.filter(owner_id=uid, window__week=week).order_by("-id")[:100]
    return {
        "week": week.isoformat(),
        "actual": current["actual"],
        "tasks": [
            {
                "id": str(t.pk),
                "title": t.title,
                "status": t.status,
                "deleted_at": t.deleted_at.isoformat() if t.deleted_at else None,
                "minutes": rows[str(t.pk)]["minutes"],
                "entry_count": rows[str(t.pk)]["entry_count"],
            }
            for t in Task.objects.filter(owner_id=uid, id__in=rows).order_by("id")
        ],
        "events": [{**w.event_data(e), "before": e.before, "after": e.after} for e in events],
        "snapshots": [
            {
                "id": s.pk,
                "created_at": s.created_at.isoformat(),
                "window": s.data["window"],
                "analysis": s.data["analysis"],
            }
            for s in snapshots
        ],
    }
