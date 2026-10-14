import uuid

from django.conf import settings
from django.db import models

STATUSES = ("planned", "in_progress", "paused", "completed", "abandoned")
KINDS = ("general", "study", "work", "life")
PRIORITIES = ("low", "normal", "high")


class Task(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.CharField(max_length=120)
    description = models.TextField(blank=True, default="")
    kind = models.CharField(max_length=12, default="general")
    priority = models.CharField(max_length=12, default="normal")
    status = models.CharField(max_length=16, default="planned")
    weekly_minutes = models.PositiveIntegerField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    request_key = models.UUIDField()
    request_fingerprint = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "request_key"], name="unique_creation_per_owner"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=STATUSES), name="valid_task_status"
            ),
            models.CheckConstraint(
                condition=models.Q(weekly_minutes__isnull=True)
                | models.Q(weekly_minutes__lte=10080),
                name="valid_weekly_minutes",
            ),
        ]
        indexes = [models.Index(fields=["owner", "status"])]


class TaskEvent(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="events")
    from_status = models.CharField(max_length=16)
    to_status = models.CharField(max_length=16)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
