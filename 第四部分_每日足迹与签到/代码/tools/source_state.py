"""Reproducible source identity, excluding runtime data and generated evidence."""

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDE = {
    ".venv",
    ".local",
    "__pycache__",
    ".hypothesis",
    ".mypy_cache",
    ".ruff_cache",
    ".git",
    "evidence",
    ".pytest_cache",
}


def is_source(path):
    relative = path.relative_to(ROOT)
    return (
        path.is_file()
        and not any(part in EXCLUDE for part in relative.parts)
        and path.name not in {".coverage", "EVIDENCE.md", ".DS_Store"}
        and not path.name.startswith(".env")
        and path.suffix not in {".sqlite3", ".db", ".pem", ".key", ".pyc"}
    )


def source_hash():
    digest = hashlib.sha256()
    for path in sorted(ROOT.rglob("*")):
        relative = path.relative_to(ROOT)
        if not is_source(path):
            continue
        digest.update(str(relative).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


if __name__ == "__main__":
    print(source_hash())
