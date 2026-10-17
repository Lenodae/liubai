"""Whole-task reservations and their weekly revision history; no writes on reads."""

import datetime as dt
import re

from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone

from tasks.services import ApiError

from . import workspace as w
from .models import BudgetPolicy

POLICY_FIELDS = ("budget_schedule", "budget_week")
ENDED = {"completed", "abandoned"}


def monday(value=None):
    value = value or timezone.localdate(w.now())
    return value - dt.timedelta(days=value.weekday())


def validate(fields, *, creating):
    if creating:
        fields.setdefault("budget_schedule", "weekly")
        fields.setdefault("budget_week", monday().isoformat())
    if "budget_schedule" in fields and fields["budget_schedule"] not in ("weekly", "recurring"):
        raise ApiError("预算类型须为本周任务或长期任务。")
    if "budget_week" in fields:
        value = fields["budget_week"]
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ApiError("预算周须为有效周一日期。")
        try:
            date = dt.date.fromisoformat(value)
        except ValueError:
            raise ApiError("预算周须为有效周一日期。") from None
        if date.weekday() or not 2000 <= date.year <= 2100:
            raise ApiError("预算周须为 2000–2100 年间的周一。")


def get(task):
    try:
        return task.budget_policy
    except ObjectDoesNotExist:
        return None


def revision(policy, task):
    return {
        "effective_week": monday().isoformat(),
        "schedule": policy.schedule,
        "start_week": policy.start_week.isoformat(),
        "minutes": task.weekly_minutes,
        "status": task.status,
        "ended": task.status in ENDED,
    }


def synchronize(task, fields=None, *, create=False):
    """Called inside the task/receipt transaction, including every parent completion."""
    fields = fields or {}
    policy = get(task)
    if policy is None:
        if not create and not any(key in fields for key in (*POLICY_FIELDS, "weekly_minutes")):
            return
        policy = BudgetPolicy(
            task=task,
            schedule=fields.get("budget_schedule", "weekly"),
            start_week=dt.date.fromisoformat(fields.get("budget_week", monday().isoformat())),
        )
    if "budget_schedule" in fields:
        policy.schedule = fields["budget_schedule"]
    if "budget_week" in fields:
        policy.start_week = dt.date.fromisoformat(fields["budget_week"])
    if task.status in ENDED:
        policy.end_at = policy.end_at or w.now()
    else:
        policy.end_at = None
    row = revision(policy, task)
    if not policy.revisions or policy.revisions[-1] != row:
        # Past weeks retain their final commitment. Within one week the last
        # explicit revision wins, preventing every edit from growing the JSON.
        policy.revisions = [
            prior for prior in policy.revisions if prior["effective_week"] != row["effective_week"]
        ] + [row]
    policy.save()
    # A newly created reverse OneToOne may previously have cached absence.
    task.budget_policy = policy


def reservation_state(task, week):
    """Return weekly amount and its contemporaneous status; never rewrite history."""
    policy = get(task)
    current_week = monday()
    if getattr(task, "deleted_at", None) is not None and week >= current_week:
        return False, None, task.status, "deleted"
    if policy is None:
        active = week == current_week and task.status == "in_progress"
        return active, task.weekly_minutes if active else None, task.status, "legacy_current"
    if week < current_week:
        rows = [row for row in policy.revisions if row["effective_week"] <= week.isoformat()]
        if not rows:
            # A backdated declaration lacks contemporaneous amount/state facts.
            # Keep its possible commitment unknown instead of inventing zero.
            covered = week >= policy.start_week and (
                policy.schedule == "recurring" or week == policy.start_week
            )
            return covered, None, "in_progress", "historical_unknown"
        row = max(enumerate(rows), key=lambda item: (item[1]["effective_week"], item[0]))[1]
        status = row.get("status", "completed" if row["ended"] else "in_progress")
        basis = "recorded_status" if "status" in row else "legacy_reservation"
    else:
        row = {
            "schedule": policy.schedule,
            "start_week": policy.start_week.isoformat(),
            "minutes": task.weekly_minutes,
            "status": task.status,
            "ended": task.status in ENDED or policy.end_at is not None,
        }
        status, basis = task.status, "current_status"
    start = dt.date.fromisoformat(row["start_week"])
    active = (
        status == "in_progress"
        and not row["ended"]
        and week >= start
        and (row["schedule"] == "recurring" or week == start)
    )
    return active, row["minutes"] if active else None, status, basis


def reservation(task, week):
    active, minutes, _, _ = reservation_state(task, week)
    return active, minutes


def metadata(task, week=None):
    policy = get(task)
    active, minutes, status, basis = reservation_state(task, week or monday())
    return {
        "budget_schedule": policy.schedule if policy else "weekly",
        "budget_week": (
            policy.start_week if policy else monday(timezone.localdate(task.created_at))
        ).isoformat(),
        "allocation_source": "auto" if active else "none",
        "reservation_minutes": minutes,
        "reservation_status": status,
        "reservation_basis": "running_weekly_time"
        if basis == "legacy_current" and active
        else basis,
        "history_basis": basis,
    }
