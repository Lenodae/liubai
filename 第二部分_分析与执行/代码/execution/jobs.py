from django.db import transaction
from django.utils import timezone

from tasks.services import ApiError

from . import provider
from .models import AnalysisRun, Draft
from .validation import nodes, text


def recover():
    return AnalysisRun.objects.filter(status="running").update(
        status="interrupted",
        error="上次生成被中断，未自动重复调用；请明确重新生成。",
        finished_at=timezone.now(),
    )


def run_once():
    with transaction.atomic():
        run = AnalysisRun.objects.filter(status="queued").order_by("created_at").first()
        if run is None:
            return False
        run.status = "running"
        run.started_at = timezone.now()
        run.save()
    try:
        result = provider.generate(run.snapshot, run.model)
        checked = nodes(result["nodes"])
        rationale = text(result.get("rationale", ""), 4000)
        with transaction.atomic():
            run.refresh_from_db()
            if run.status != "running":
                return True
            Draft.objects.create(
                task=run.task,
                run=run,
                nodes=checked,
                original=checked,
                rationale=rationale,
                base_version=run.base_version,
            )
            run.status = "succeeded"
            run.finished_at = timezone.now()
            run.save()
    except Exception as exc:
        message = (
            exc.message
            if isinstance(exc, ApiError)
            else "分析遇到内部错误；结果未采纳，请手工拆分或明确重试。"
        )
        AnalysisRun.objects.filter(id=run.id, status="running").update(
            status="failed", error=message, finished_at=timezone.now()
        )
    return True
