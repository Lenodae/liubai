"""Offline property and mutation checks for the read-only step preview contract.

Extracts only the pure selection function: no Django settings, database, key,
network, or on-disk product mutations are involved.
"""

import ast
import copy
import json
import random
from pathlib import Path
from types import SimpleNamespace
from typing import Any

SOURCE = Path(__file__).resolve().parents[1] / "execution" / "overview.py"
STATUSES = ["planned", "in_progress", "paused", "completed", "abandoned"]


class Related:
    def __init__(self, items):
        self.items = items

    def all(self):
        return self.items


def load_function(source):
    module = ast.parse(source)
    function = next(node for node in module.body if isinstance(node, ast.FunctionDef))
    namespace = {"Task": object, "Any": Any}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(SOURCE), "exec"), namespace)
    return namespace["step_preview"]


def fixtures():
    rng = random.Random(20261017)
    cases = []
    for index in range(500):
        steps = []
        for number in range(rng.randrange(16)):
            # Missing/foreign dependency IDs can never be treated as completed.
            dependencies = rng.sample(range(number), k=rng.randrange(min(number, 3) + 1))
            if rng.randrange(12) == 0:
                dependencies.append(1000)
            steps.append(
                SimpleNamespace(
                    id=number,
                    title=f"步骤 {number + 1}",
                    criterion="核对结果",
                    status=rng.choice(STATUSES),
                    depends=Related([SimpleNamespace(id=item) for item in dependencies]),
                )
            )
        status = "in_progress" if index % 3 else rng.choice(STATUSES)
        cases.append(
            SimpleNamespace(status=status, deleted_at=index % 31 == 0, steps=Related(steps))
        )
    return cases


def verify(function, cases):
    for task in cases:
        steps = task.steps.all()
        before = copy.deepcopy(vars(task))
        result = function(task)
        done = {step.id for step in steps if step.status == "completed"}
        assert result["total"] == len(steps)
        assert result["completed"] == len(done)
        # Compare serializable object state to detect any mutation by the reader.
        assert json.dumps(vars(task), default=vars, sort_keys=True) == json.dumps(
            before, default=vars, sort_keys=True
        )
        if task.status != "in_progress" or task.deleted_at:
            assert result["state"] == "inactive"
            assert result["current"] is None and result["next"] is None
            continue
        if not steps or len(done) == len(steps):
            assert result["state"] == ("empty" if not steps else "finished")
            assert result["current"] is None and result["next"] is None
            continue
        executable = [step for step in steps if step.status in ["in_progress", "planned"]]
        ready = [step for step in executable if all(item.id in done for item in step.depends.all())]
        if not ready:
            assert result["state"] == "blocked"
            assert result["current"] is None and result["next"] is None
            continue
        assert result["state"] == "ready"
        pick = min(ready, key=lambda step: (step.status != "in_progress", step.id))
        assert result["current"] == {
            "id": str(pick.id),
            "title": pick.title,
            "criterion": pick.criterion,
            "status": pick.status,
            "number": steps.index(pick) + 1,
        }
        after = [
            step
            for step in executable
            if step.id != pick.id
            and all(item.id in done or item.id == pick.id for item in step.depends.all())
        ]
        if not after:
            assert result["next"] is None
            continue
        next_step = min(after, key=lambda step: (step.status != "in_progress", step.id))
        assert result["next"] is not None
        assert result["next"]["id"] == str(next_step.id)
        assert result["next"]["number"] == steps.index(next_step) + 1
        assert result["next"]["after_current"] == any(
            dependency.id not in done for dependency in next_step.depends.all()
        )


def main():
    source = SOURCE.read_text()
    cases = fixtures()
    verify(load_function(source), cases)
    mutants = {
        "inactive_parent_actionable": (
            'if task.status != "in_progress" or task.deleted_at:',
            "if False:",
        ),
        "skip_current_dependencies": ("if item[1] <= completed), None)", "if True), None)"),
        "resume_paused_implicitly": (
            'if step.status in ("in_progress", "planned")',
            'if step.status in ("in_progress", "planned", "paused")',
        ),
        "ignore_started_priority": (
            'key=lambda item: item[0]["status"] != "in_progress"',
            "key=lambda item: 0",
        ),
        "never_unlock_next": (
            "after_current = completed | {current[2]}",
            "after_current = completed",
        ),
        "zero_based_step_number": ('"number": index + 1', '"number": index'),
    }
    killed = []
    for name, (before, after) in mutants.items():
        assert source.count(before) == 1, name
        mutated = source.replace(before, after)
        try:
            verify(load_function(mutated), cases)
        except AssertionError:
            killed.append(name)
        else:
            raise AssertionError(f"Surviving mutant: {name}")
    print(
        json.dumps(
            {
                "seed": 20261017,
                "property_cases": len(cases),
                "mutants_killed": len(killed),
                "mutants": killed,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
