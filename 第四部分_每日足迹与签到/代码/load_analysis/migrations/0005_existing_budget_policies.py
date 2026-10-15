"""Reserve existing unfinished tasks with a known weekly budget from this week."""

import datetime as dt

from django.db import migrations
from django.utils import timezone


def forward(apps, schema_editor):
    Task = apps.get_model("tasks", "Task")
    Policy = apps.get_model("load_analysis", "BudgetPolicy")
    today = timezone.localdate()
    week = today - dt.timedelta(days=today.weekday())
    alias = schema_editor.connection.alias
    rows = Task.objects.using(alias).filter(
        weekly_minutes__isnull=False,
        status__in=["planned", "in_progress", "paused"],
        budget_policy__isnull=True,
    )
    batch = []
    for task in rows.iterator():
        batch.append(
            Policy(
                task_id=task.pk,
                schedule="recurring",
                start_week=week,
                revisions=[
                    {
                        "effective_week": week.isoformat(),
                        "schedule": "recurring",
                        "start_week": week.isoformat(),
                        "minutes": task.weekly_minutes,
                        "ended": False,
                        "origin": "legacy_migration",
                    }
                ],
            )
        )
        if len(batch) >= 500:
            Policy.objects.using(alias).bulk_create(batch)
            batch = []
    if batch:
        Policy.objects.using(alias).bulk_create(batch)


def reverse(apps, schema_editor):
    Policy = apps.get_model("load_analysis", "BudgetPolicy")
    alias = schema_editor.connection.alias
    ids = [
        policy.pk
        for policy in Policy.objects.using(alias).iterator()
        if len(policy.revisions) == 1 and policy.revisions[0].get("origin") == "legacy_migration"
    ]
    Policy.objects.using(alias).filter(pk__in=ids).delete()


class Migration(migrations.Migration):
    dependencies = [("load_analysis", "0004_budgetpolicy")]
    operations = [migrations.RunPython(forward, reverse)]
