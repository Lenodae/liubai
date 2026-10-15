"""Read actual facts without copying estimates, altering tasks, or hiding trash history."""

import datetime as dt

from django.db import transaction
from django.db.models import Exists, OuterRef, Q, Subquery
from django.utils import timezone

from execution.models import Event, TimeEntry
from tasks.services import ApiError

from . import dates
from .models import DayMark


def mark_data(day, row=None):
    return {
        "date": str(day),
        "mark": row.kind if row else None,
        "version": row.version if row else 0,
    }


def empty_day(day):
    return {
        **mark_data(day),
        "minutes": 0,
        "completed_steps": 0,
        "completed_tasks": 0,
        "has_activity": False,
    }


def entries(uid, start, end):
    return (
        TimeEntry.objects.filter(
            task__owner_id=uid, date__gte=start, date__lte=end, voided_at__isnull=True
        )
        .select_related("task", "step")
        .order_by("date", "created_at", "id")
    )


def completions(uid, start, end):
    later = Event.objects.filter(task_id=OuterRef("task_id"), id__gt=OuterRef("id"))
    task_undo = later.filter(kind="undo", step__isnull=True)
    step_undo = later.filter(kind="undo", step_id=OuterRef("step_id"))
    result = Event.objects.filter(
        task__owner_id=uid,
        kind="complete",
        created_at__gte=dates.midnight(start),
        created_at__lt=dates.midnight(end + dt.timedelta(days=1)),
    )
    return (
        result.annotate(task_undone=Exists(task_undo), step_undone=Exists(step_undo))
        .filter(Q(step__isnull=True, task_undone=False) | Q(step__isnull=False, step_undone=False))
        .select_related("task", "step")
        .order_by("created_at", "id")
    )


def day_rows(uid, start, end, current):
    rows = {
        str(start + dt.timedelta(days=offset)): empty_day(start + dt.timedelta(days=offset))
        for offset in range((end - start).days + 1)
    }
    factual_end = min(end, current)
    for mark in DayMark.objects.filter(owner_id=uid, date__gte=start, date__lte=factual_end):
        rows[str(mark.date)].update(mark_data(mark.date, mark))
    for entry in entries(uid, start, factual_end):
        rows[str(entry.date)]["minutes"] += entry.minutes
    for event in completions(uid, start, factual_end):
        day = str(timezone.localdate(event.created_at, timezone.get_default_timezone()))
        field = "completed_steps" if event.step_id else "completed_tasks"
        rows[day][field] += 1
    for row in rows.values():
        row["has_activity"] = bool(
            row["minutes"] or row["completed_steps"] or row["completed_tasks"]
        )
    return list(rows.values())


@transaction.atomic
def calendar(uid, query):
    current = dates.today()
    view = query.get("view", "recent")
    year = query.get("year", current.year)
    start, end = dates.bounds(view, year, current)
    days = day_rows(uid, start, end, current)
    summary = {
        "checkin_days": sum(row["mark"] == "checkin" for row in days),
        "rest_days": sum(row["mark"] == "rest" for row in days),
        "active_days": sum(row["has_activity"] for row in days),
    }
    return {
        **dates.envelope(current),
        "view": view,
        "year": int(year) if view == "year" else current.year,
        "start": str(start),
        "end": str(end),
        "days": days,
        "summary": summary,
        "today_mark": mark_data(
            current, DayMark.objects.filter(owner_id=uid, date=current).first()
        ),
    }


def entry_data(entry):
    return {
        "id": str(entry.pk),
        "task_id": str(entry.task_id),
        "task_title": entry.task.title,
        "step_title": entry.step.title if entry.step else None,
        "minutes": entry.minutes,
        "note": entry.note,
        "deleted": entry.task.deleted_at is not None,
    }


def completion_rows(uid, day):
    later = Event.objects.filter(
        task_id=OuterRef("task_id"), id__gt=OuterRef("id"), kind="completion_edit"
    ).order_by("-id")
    events = completions(uid, day, day).annotate(
        task_edit=Subquery(later.filter(step__isnull=True).values("data")[:1]),
        step_edit=Subquery(later.filter(step_id=OuterRef("step_id")).values("data")[:1]),
    )
    result = []
    for event in events:
        edited = event.step_edit if event.step_id else event.task_edit
        note = edited.get("after", {}).get("note", "") if edited else event.data.get("note", "")
        result.append(
            {
                "event_id": event.pk,
                "task_id": str(event.task_id),
                "task_title": event.task.title,
                "step_title": event.step.title if event.step else None,
                "kind": "step" if event.step_id else "task",
                "at": event.created_at.isoformat(),
                "note": note,
                "deleted": event.task.deleted_at is not None,
            }
        )
    return result


@transaction.atomic
def detail(uid, query):
    current = dates.today()
    day = dates.parse(query.get("date"))
    if day > current:
        raise ApiError("未来日期还没有足迹。")
    return {
        **dates.envelope(current),
        "day": day_rows(uid, day, day, current)[0],
        "entries": [entry_data(entry) for entry in entries(uid, day, day)],
        "completions": completion_rows(uid, day),
    }
