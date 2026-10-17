"""Read-only, owner-local step summaries for task lists and the overview."""

from typing import Any

from tasks.models import Task


def step_preview(task: Task) -> dict[str, Any]:
    # Collection callers prefetch steps and dependencies in two shared queries.
    steps = list(task.steps.all())
    completed = {step.id for step in steps if step.status == "completed"}
    result: dict[str, Any] = {
        "total": len(steps),
        "completed": len(completed),
        "state": "inactive",
        "current": None,
        "next": None,
    }
    if task.status != "in_progress" or task.deleted_at:
        return result
    if not steps:
        result["state"] = "empty"
        return result
    if len(completed) == len(steps):
        result["state"] = "finished"
        return result

    candidates = [
        (
            {
                "id": str(step.id),
                "title": step.title,
                "criterion": step.criterion,
                "status": step.status,
                "number": index + 1,
            },
            {dependency.id for dependency in step.depends.all()},
            step.id,
        )
        for index, step in enumerate(steps)
        if step.status in ("in_progress", "planned")
    ]
    # Stable sorting preserves the model's position/id order within each status.
    candidates.sort(key=lambda item: item[0]["status"] != "in_progress")
    current = next((item for item in candidates if item[1] <= completed), None)
    if current is None:
        result["state"] = "blocked"
        return result
    result.update(state="ready", current=current[0])
    after_current = completed | {current[2]}
    following = next(
        (item for item in candidates if item[2] != current[2] and item[1] <= after_current),
        None,
    )
    if following is not None:
        result["next"] = {**following[0], "after_current": not following[1] <= completed}
    return result
