from django.db.models import Sum

from tasks.services import serialize_task

from .models import Profile
from .rules import evaluate


def entry_data(entry):
    return {
        "id": str(entry.id),
        "step_id": str(entry.step_id) if entry.step_id else None,
        "date": entry.date.isoformat(),
        "minutes": entry.minutes,
        "note": entry.note,
        "version": entry.version,
    }


def actual(query):
    return query.filter(voided_at__isnull=True).aggregate(total=Sum("minutes"))["total"]


def view(task):
    from .provider import configuration

    profile, _ = Profile.objects.get_or_create(task=task)
    p = {
        k: getattr(profile, k)
        for k in ["criterion", "foundation", "constraints", "available_minutes"]
    }
    p["deadline"] = profile.deadline.isoformat() if profile.deadline else ""
    steps = []
    for step in task.steps.prefetch_related("depends"):
        steps.append(
            {
                "id": str(step.id),
                "title": step.title,
                "criterion": step.criterion,
                "status": step.status,
                "effective_status": "paused"
                if task.status == "paused" and step.status not in ("completed", "abandoned")
                else step.status,
                "low": step.low,
                "high": step.high,
                "depends": [str(d.id) for d in step.depends.all()],
                "version": step.version,
                "actual_minutes": actual(step.time_entries),
                "time_verified": step.verified_revision is not None
                and step.verified_revision == step.ledger_revision,
            }
        )
    drafts = [
        {
            "id": str(d.id),
            "nodes": d.nodes,
            "revision": d.revision,
            "base_version": d.base_version,
            "stale": d.base_version != task.version,
            "applied": d.applied_at is not None,
            "source": "DeepSeek" if d.run_id else "手工",
            "rationale": d.rationale,
        }
        for d in task.plan_drafts.all()[:30]
    ]
    runs = [
        {
            "id": str(r.id),
            "status": r.status,
            "model": r.model,
            "error": r.error,
            "created_at": r.created_at.isoformat(),
        }
        for r in task.analysis_runs.all()[:20]
    ]
    history = [
        {
            "id": e.id,
            "kind": e.kind,
            "step_id": str(e.step_id) if e.step_id else None,
            "data": e.data,
            "at": e.created_at.isoformat(),
        }
        for e in task.execution_events.all()[:200]
    ]
    total = actual(task.time_entries)
    config = configuration()
    return {
        "task": serialize_task(task),
        "profile": p,
        "steps": steps,
        "drafts": drafts,
        "runs": runs,
        "history": history,
        "entries": [entry_data(e) for e in task.time_entries.filter(voided_at__isnull=True)],
        "summary": {
            "actual_minutes": total,
            "time_verified": total is not None
            and profile.verified_revision is not None
            and profile.verified_revision == profile.ledger_revision,
            "all_steps_completed": bool(steps) and all(s["status"] == "completed" for s in steps),
        },
        "analysis": evaluate(steps, p),
        "provider": {
            "name": "DeepSeek",
            "model": config["model"],
            "configured": bool(config["key"]),
        },
    }
