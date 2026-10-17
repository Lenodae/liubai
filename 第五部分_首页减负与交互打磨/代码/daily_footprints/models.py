from django.conf import settings
from django.db import models


class DayMark(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    date = models.DateField()
    kind = models.CharField(max_length=8, null=True)
    version = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["owner", "date"], name="footprints_unique_day"),
            models.CheckConstraint(
                condition=models.Q(kind__isnull=True) | models.Q(kind__in=["checkin", "rest"]),
                name="footprints_valid_mark",
            ),
            models.CheckConstraint(condition=models.Q(version__gte=1), name="footprints_version"),
        ]


class MarkReceipt(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    key = models.UUIDField()
    fingerprint = models.CharField(max_length=64)
    response = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["owner", "key"], name="footprints_unique_request")
        ]
