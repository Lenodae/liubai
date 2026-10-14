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
}


def source_hash():
    digest = hashlib.sha256()
    for path in sorted(ROOT.rglob("*")):
        relative = path.relative_to(ROOT)
        if (
            not path.is_file()
            or any(part in EXCLUDE for part in relative.parts)
            or path.name in {".coverage", "EVIDENCE.md"}
        ):
            continue
        digest.update(str(relative).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


if __name__ == "__main__":
    print(source_hash())
