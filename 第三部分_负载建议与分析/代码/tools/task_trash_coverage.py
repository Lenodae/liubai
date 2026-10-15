"""Report executable changed Python lines against the persisted pre-change source snapshot."""

import difflib
import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    baseline = json.loads((root / "evidence/task-trash-before.json").read_text())["files"]
    coverage = json.loads((root / "evidence/task-trash-coverage.json").read_text())["files"]
    result = {}
    for name, data in coverage.items():
        current = (root / name).read_text().splitlines()
        previous = baseline.get(name, "").splitlines()
        changed = set()
        for operation, _, _, start, end in difflib.SequenceMatcher(
            a=previous, b=current, autojunk=False
        ).get_opcodes():
            if operation in {"insert", "replace"}:
                changed.update(range(start + 1, end + 1))
        executed, missing = set(data["executed_lines"]), set(data["missing_lines"])
        executable = changed & (executed | missing)
        if executable:
            result[name] = {
                "changed_executable_lines": len(executable),
                "covered_changed_lines": len(executable & executed),
                "missing_changed_lines": sorted(executable & missing),
                "missing_branches_from_changed_lines": [
                    branch for branch in data.get("missing_branches", []) if branch[0] in changed
                ],
            }
    report = {
        "changed_executable_lines": sum(x["changed_executable_lines"] for x in result.values()),
        "covered_changed_lines": sum(x["covered_changed_lines"] for x in result.values()),
        "files": result,
        "scope": "Python application code; excludes migrations, browser JavaScript, and tools.",
    }
    (root / "evidence/task-trash-changed-coverage.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
