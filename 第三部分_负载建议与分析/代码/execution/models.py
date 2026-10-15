import uuid

from django.conf import settings
from django.db import models

from tasks.models import Task


class Profile(models.Model):
    task = models.OneToOneField(Task, on_delete=models.CASCADE, related_name="execution_profile")
    criterion = models.TextField(blank=True)
    foundation = models.TextField(blank=True)
    constraints = models.TextField(blank=True)
    deadline = models.DateField(null=True)
    available_minutes = models.PositiveIntegerField(null=True)
    ledger_revision = models.PositiveIntegerField(default=0)
    verified_revision = models.PositiveIntegerField(null=True)


class Step(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="steps")
    title = models.CharField(max_length=120)
    criterion = models.TextField()
    position = models.PositiveIntegerField()
    status = models.CharField(max_length=16, default="planned")
    low = models.PositiveIntegerField(null=True)
    high = models.PositiveIntegerField(null=True)
    depends = models.ManyToManyField("self", symmetrical=False, blank=True)
    version = models.PositiveIntegerField(default=1)
    ledger_revision = models.PositiveIntegerField(default=0)
    verified_revision = models.PositiveIntegerField(null=True)
    source_draft = models.UUIDField(null=True)

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    status__in=["planned", "in_progress", "paused", "completed", "abandoned"]
                ),
                name="step_status_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(low__isnull=True, high__isnull=True)
                    | models.Q(low__gte=0, high__gte=models.F("low"))
                ),
                name="step_estimate_valid",
            ),
        ]


class TimeEntry(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="time_entries")
    step = models.ForeignKey(Step, on_delete=models.PROTECT, null=True, related_name="time_entries")
    date = models.DateField()
    minutes = models.PositiveIntegerField()
    note = models.TextField(blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    voided_at = models.DateTimeField(null=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(minutes__gte=1, minutes__lte=10080), name="time_minutes_valid"
            )
        ]


class Event(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="execution_events")
    step = models.ForeignKey(Step, on_delete=models.PROTECT, null=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    kind = models.CharField(max_length=32)
    data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]


class Receipt(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    key = models.UUIDField()
    fingerprint = models.CharField(max_length=64)
    response = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["owner", "key"], name="execution_unique_request")
        ]


class AnalysisRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="analysis_runs")
    snapshot = models.JSONField()
    base_version = models.PositiveIntegerField()
    status = models.CharField(max_length=16, default="queued")
    model = models.CharField(max_length=100)
    error = models.TextField(blank=True)
    rules_version = models.CharField(max_length=20, default="rules-1/prompt-1")
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)

    class Meta:
        ordering = ["-created_at"]


class Draft(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="plan_drafts")
    run = models.OneToOneField(AnalysisRun, on_delete=models.PROTECT, null=True)
    nodes = models.JSONField()
    original = models.JSONField()
    rationale = models.TextField(blank=True)
    base_version = models.PositiveIntegerField()
    revision = models.PositiveIntegerField(default=1)
    applied_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
