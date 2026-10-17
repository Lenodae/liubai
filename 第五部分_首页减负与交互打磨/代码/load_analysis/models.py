import uuid

from django.conf import settings
from django.db import models

from tasks.models import Task


class BudgetPolicy(models.Model):
    """A task's whole-budget commitment, independent of execution status."""

    task = models.OneToOneField(Task, on_delete=models.CASCADE, related_name="budget_policy")
    schedule = models.CharField(max_length=12, default="weekly")
    start_week = models.DateField()
    end_at = models.DateTimeField(null=True)
    revisions = models.JSONField(default=list)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(schedule__in=["weekly", "recurring"]),
                name="load_budget_schedule",
            )
        ]


class CapacityWindow(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    week = models.DateField()
    mode = models.CharField(max_length=12)
    budget_minutes = models.PositiveIntegerField(null=True)
    buffer_minutes = models.PositiveIntegerField(null=True)
    as_of = models.DateTimeField(null=True)
    source_token = models.CharField(max_length=64, blank=True)
    version = models.PositiveIntegerField(default=1)
    slices = models.JSONField(default=list)
    slices_source = models.CharField(max_length=64, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["owner", "week", "mode"], name="load_unique_window"),
            models.CheckConstraint(
                condition=models.Q(mode__in=["week", "remaining"]), name="load_mode"
            ),
            models.CheckConstraint(
                condition=models.Q(buffer_minutes__isnull=True)
                | models.Q(budget_minutes__isnull=True)
                | models.Q(buffer_minutes__lte=models.F("budget_minutes")),
                name="load_buffer_within_budget",
            ),
        ]


class TaskPlan(models.Model):
    window = models.ForeignKey(CapacityWindow, on_delete=models.CASCADE, related_name="plans")
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="load_plans")
    progress_low = models.PositiveIntegerField(null=True)
    progress_high = models.PositiveIntegerField(null=True)
    maintenance_low = models.PositiveIntegerField(null=True)
    maintenance_high = models.PositiveIntegerField(null=True)
    maintenance_active = models.BooleanField(null=True)
    scope_confirmed = models.BooleanField(default=False)
    remaining_low = models.PositiveIntegerField(null=True)
    remaining_high = models.PositiveIntegerField(null=True)
    remaining_source_version = models.PositiveIntegerField(default=0)
    remaining_confirmed_at = models.DateTimeField(null=True)
    source_version = models.PositiveIntegerField(default=0)
    source_status = models.CharField(max_length=16, default="planned")
    confirmed_at = models.DateTimeField(null=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["window", "task"], name="load_unique_task_plan"),
            *[
                models.CheckConstraint(
                    condition=models.Q(
                        **{f"{prefix}_low__isnull": True, f"{prefix}_high__isnull": True}
                    )
                    | models.Q(
                        **{
                            f"{prefix}_low__isnull": False,
                            f"{prefix}_high__isnull": False,
                            f"{prefix}_high__gte": models.F(f"{prefix}_low"),
                        }
                    ),
                    name=f"load_{prefix}_interval",
                )
                for prefix in ["progress", "maintenance", "remaining"]
            ],
        ]


class LoadEvent(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    window = models.ForeignKey(CapacityWindow, on_delete=models.CASCADE)
    kind = models.CharField(max_length=24)
    summary = models.TextField()
    before = models.JSONField(default=dict)
    after = models.JSONField(default=dict)
    after_fingerprint = models.CharField(max_length=64)
    valid_until = models.DateTimeField()
    undone_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]


class LoadSnapshot(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    window = models.ForeignKey(CapacityWindow, on_delete=models.CASCADE)
    data = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)


class LoadReceipt(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    key = models.UUIDField(default=uuid.uuid4)
    fingerprint = models.CharField(max_length=64)
    response = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["owner", "key"], name="load_unique_receipt")]
