"""Check source baselines and independent paths/inodes without reading private data.

Run normally after initializing phase 5, or use --source-only before first startup.
Database contents, keys, configuration contents and account identities are never read.
"""

import argparse
import ast
import hashlib
import json
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PARTS = (
    "第一部分_任务基础",
    "第二部分_分析与执行",
    "第三部分_负载建议与分析",
    "第四部分_每日足迹与签到",
    "第五部分_首页减负与交互打磨",
)
CODE = [ROOT / part / "代码" for part in PARTS]


def independent(paths, required=True):
    for path in paths:
        if required:
            assert path.exists(), f"Missing runtime path: {path.relative_to(ROOT)}"
        assert not path.is_symlink(), f"Runtime path is a symlink: {path.relative_to(ROOT)}"
    for left, right in combinations(paths, 2):
        assert left.resolve() != right.resolve(), "Runtime paths resolve to the same location"
        if left.exists() and right.exists():
            assert not left.samefile(right), "Runtime paths share an inode"


def setting(path, name):
    tree = ast.parse(path.read_text())
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in statement.targets
        ):
            return ast.literal_eval(statement.value)
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-only", action="store_true")
    arguments = parser.parse_args()
    baseline = json.loads((ROOT / PARTS[4] / "规划书/前四部分源码与规划基线.json").read_text())
    for name, expected in baseline.items():
        path = ROOT / name
        assert path.is_file(), f"Original source missing: {name}"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, name

    independent(CODE)
    cookies = []
    for code in CODE:
        path = code / "config/settings.py"
        cookies.append(
            (
                setting(path, "SESSION_COOKIE_NAME") or "sessionid",
                setting(path, "CSRF_COOKIE_NAME") or "csrftoken",
            )
        )
    assert len({item[0] for item in cookies}) == 5, "Session cookies overlap"
    assert len({item[1] for item in cookies}) == 5, "CSRF cookies overlap"
    assert cookies[4] == ("taskflow5_session", "taskflow5_csrf")
    assert "daily_footprints" in setting(CODE[4] / "config/settings.py", "INSTALLED_APPS")
    for part in PARTS:
        assert (ROOT / part / "规划书").is_dir(), "Planning folder missing"

    runtime = "not checked (--source-only)"
    if not arguments.source_only:
        for relative in [".venv", ".local", ".local/tasks.sqlite3", ".local/secret-key"]:
            independent([code / relative for code in CODE])
        for relative in [".env", ".local/deepseek.json"]:
            independent([code / relative for code in CODE], required=False)
        for relative in [
            ".local",
            ".local/secret-key",
            ".local/tasks.sqlite3",
            ".local/phase4-import-backup.sqlite3",
            ".local/deepseek.json",
        ]:
            if relative.endswith("deepseek.json") and not (CODE[4] / relative).exists():
                continue
            assert (CODE[4] / relative).stat().st_mode & 0o077 == 0, "Private permissions widened"
        runtime = "pass (distinct paths/inodes; secret contents not read)"

    print(
        json.dumps(
            {
                "first_four_parts_source_and_planning_baseline": "unchanged",
                "baseline_files": len(baseline),
                "independent_code_and_planning_folders": True,
                "independent_session_and_csrf_cookies": True,
                "runtime_isolation": runtime,
                "real_database_or_secret_contents_read": False,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
