import datetime as dt
import hashlib
import json
import re

from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone

from execution.models import Event, TimeEntry
from tasks.models import Task
from tasks.services import ApiError

from .models import CapacityWindow, LoadEvent, TaskPlan
from .rules import analyze

RULES_VERSION = "load-3-active-only"
PLAN_FIELDS = (
    "progress_low",
    "progress_high",
    "maintenance_low",
    "maintenance_high",
    "maintenance_active",
    "scope_confirmed",
    "remaining_low",
    "remaining_high",
)


def now():
    return timezone.now()


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=True, default=str).encode()
    ).hexdigest()


def scope(data):
    today = timezone.localdate(now())
    raw = data.get("week", (today - dt.timedelta(days=today.weekday())).isoformat())
    if not isinstance(raw, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        raise ApiError("请选择有效周一日期。")
    try:
        week = dt.date.fromisoformat(raw)
    except ValueError:
        raise ApiError("请选择有效日期。") from None
    mode = data.get("mode", "remaining")
    if week.weekday() or mode not in ("week", "remaining") or not 2000 <= week.year <= 2100:
        raise ApiError("周窗口需从周一开始，模式为 week 或 remaining。")
    return week, mode


def facts_token(user_id):
    return digest(
        list(Task.objects.filter(owner_id=user_id).order_by("id").values_list("id", "version"))
    )


def window_data(window, week, mode, token):
    stamp = window.as_of if window else None
    today = timezone.localdate(now())
    stale = bool(
        stamp
        and mode == "remaining"
        and (timezone.localdate(stamp) != today or window.source_token != token)
    )
    confirmed = bool(
        stamp
        and not stale
        and window.budget_minutes is not None
        and window.buffer_minutes is not None
    )
    return {
        "week": week.isoformat(),
        "mode": mode,
        "as_of": stamp.isoformat() if stamp else None,
        "budget_minutes": window.budget_minutes if window else None,
        "buffer_minutes": window.buffer_minutes if window else None,
        "version": window.version if window else 0,
        "confirmed": confirmed,
        "stale": stale,
    }


def actual_rows(user_id, week):
    return list(
        TimeEntry.objects.filter(
            task__owner_id=user_id,
            voided_at__isnull=True,
            date__gte=week,
            date__lt=week + dt.timedelta(days=7),
        )
        .values("task_id")
        .annotate(minutes=Sum("minutes"), entry_count=Count("id"))
        .order_by("task_id")
    )


def task_data(task, plan, latest, mode, actual, week=None):
    from . import policies

    try:
        profile = task.execution_profile
    except ObjectDoesNotExist:
        profile = None
    stamp = plan.confirmed_at if plan else None
    confirmed = bool(
        stamp
        and (
            mode == "week"
            or (
                plan.source_version == task.version
                and timezone.localdate(stamp) == timezone.localdate(now())
            )
        )
    )
    values = {k: getattr(plan, k) if plan else None for k in PLAN_FIELDS}
    if not plan:
        values["maintenance_active"] = (
            latest.maintenance_active
            if latest
            else (None if task.status in ("in_progress", "paused") else False)
        )
        values["scope_confirmed"] = False
    policy = policies.metadata(task, week)
    historical = bool(week and week < policies.monday())
    load_status = (
        (plan.source_status if plan else policy["reservation_status"])
        if historical and mode == "week"
        else task.status
    )
    if (
        mode == "week"
        and week == policies.monday()
        and task.status == "in_progress"
        and policy["allocation_source"] != "auto"
    ):
        policy.update(
            allocation_source="auto",
            reservation_minutes=task.weekly_minutes,
            reservation_basis="running_weekly_time",
        )
    if mode != "week":
        policy.update(allocation_source="none", reservation_minutes=None)
    if plan:
        policy.update(
            allocation_source="manual", reservation_minutes=None, reservation_basis="manual_window"
        )
    if not historical and task.status != "in_progress":
        policy.update(allocation_source="none", reservation_minutes=None)
    automatic = policy["allocation_source"] == "auto"
    reservation_active = automatic if mode == "week" else None
    if (
        not plan
        and not automatic
        and mode == "week"
        and not (latest and latest.maintenance_active is True)
    ):
        # An out-of-scope reservation is zero; retain stored upkeep fields.
        values["maintenance_active"] = False
    return {
        "id": str(task.id),
        "title": task.title,
        "status": task.status,
        "deleted_at": task.deleted_at.isoformat() if task.deleted_at else None,
        "load_status": load_status,
        "historical": historical,
        "priority": task.priority,
        "version": task.version,
        "weekly_minutes": task.weekly_minutes,
        **policy,
        "reservation_active": reservation_active,
        "budget_committed": policy["allocation_source"] in {"auto", "manual"},
        "budget_occupies": load_status == "in_progress"
        and policy["allocation_source"] in {"auto", "manual"},
        "deadline": profile.deadline.isoformat() if profile and profile.deadline else None,
        **values,
        "plan_confirmed": confirmed,
        "remaining_confirmed": bool(
            plan
            and plan.remaining_confirmed_at
            and plan.remaining_source_version == task.version
            and timezone.localdate(plan.remaining_confirmed_at) == timezone.localdate(now())
            and plan.remaining_low is not None
        ),
        "actual_minutes": actual.get(task.id, {}).get("minutes"),
        "has_plan": plan is not None,
    }


def analyze_tasks(window, tasks):
    inputs = [{**item, "status": item.get("load_status", item["status"])} for item in tasks]
    return analyze(window, inputs)


def valid_until():
    tomorrow = timezone.localdate(now()) + dt.timedelta(days=1)
    return timezone.make_aware(dt.datetime.combine(tomorrow, dt.time.min))


def event_data(event, fingerprint=None):
    return {
        "id": event.pk,
        "kind": event.kind,
        "created_at": event.created_at.isoformat(),
        "summary": event.summary,
        "can_undo": bool(
            event.kind == "apply"
            and event.undone_at is None
            and event.after_fingerprint == fingerprint
            and event.valid_until > now()
        ),
    }


def visible_tasks(user_id, tasks, week):
    """Historical weeks use the last lifecycle state before the week's end."""
    from . import policies

    if week >= policies.monday():
        return [task for task in tasks if task.deleted_at is None]
    end = timezone.make_aware(dt.datetime.combine(week + dt.timedelta(days=7), dt.time.min))
    states = {}
    events = (
        Event.objects.filter(task__owner_id=user_id, kind__in=["task_trash", "task_restore"])
        .order_by("task_id", "created_at", "id")
        .values("task_id", "kind", "created_at", "data")
    )
    for event in events:
        task_id = event["task_id"]
        if event["created_at"] < end:
            states[task_id] = event["kind"] == "task_trash"
        elif task_id not in states:
            # A legacy soft-deleted row may have its first audit only on restore.
            previous = event["data"].get("previous_deleted_at")
            states[task_id] = bool(previous and dt.datetime.fromisoformat(previous) < end)
    return [
        task
        for task in tasks
        if not states.get(task.id, bool(task.deleted_at and task.deleted_at < end))
    ]


@transaction.atomic
def build(user_id, week, mode):
    tasks = list(
        Task.objects.filter(owner_id=user_id)
        .select_related("execution_profile", "budget_policy")
        .order_by("id")
    )
    token = digest([(t.id, t.version) for t in tasks])
    window = CapacityWindow.objects.filter(owner_id=user_id, week=week, mode=mode).first()
    plans = list(
        TaskPlan.objects.filter(window__owner_id=user_id).select_related("window").order_by("id")
    )
    current, latest = {}, {}
    for plan in plans:
        latest[plan.task_id] = plan
        if window and plan.window_id == window.pk:
            current[plan.task_id] = plan
    rows = actual_rows(user_id, week)
    actual = {r["task_id"]: r for r in rows}
    data = [
        task_data(t, current.get(t.id), latest.get(t.id), mode, actual, week)
        for t in visible_tasks(user_id, tasks, week)
    ]
    w = window_data(window, week, mode, token)
    analysis = analyze_tasks(w, data)
    verified = bool(rows)
    for task in tasks:
        if task.id in actual:
            try:
                p = task.execution_profile
                verified = (
                    verified
                    and p.verified_revision is not None
                    and p.verified_revision == p.ledger_revision
                )
            except ObjectDoesNotExist:
                verified = False
    total = sum(r["minutes"] for r in rows) if rows else None
    actual_data = {
        "minutes": total,
        "entry_count": sum(r["entry_count"] for r in rows),
        "verified": bool(verified),
    }
    revisions = list(
        CapacityWindow.objects.filter(owner_id=user_id).order_by("id").values_list("id", "version")
    )
    fingerprint = digest(
        {
            "user": user_id,
            "window": w,
            "tasks": data,
            "actual": actual_data,
            "windows": revisions,
            "plans": [(p.pk, p.version) for p in plans],
            "date": timezone.localdate(now()),
            "rules": RULES_VERSION,
        }
    )
    events = LoadEvent.objects.filter(owner_id=user_id, window__week=week).order_by("-id")[:20]
    return {
        "window": w,
        "tasks": data,
        "analysis": analysis,
        "actual": actual_data,
        "fingerprint": fingerprint,
        "valid_until": valid_until().isoformat(),
        "history": [event_data(e, fingerprint) for e in events],
    }
