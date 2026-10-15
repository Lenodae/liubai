"""Three reversible TLS regression mutants; no live network or application data."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    path = ROOT / "execution/provider.py"
    original = path.read_bytes()
    source = original.decode()
    mutants = [
        ("missing CA", "cafile=certifi.where()", ""),
        ("unverified TLS", "ssl.create_default_context", "ssl._create_unverified_context"),
        ("hidden certificate error", "isinstance(reason, ssl.SSLCertVerificationError)", "False"),
    ]
    for label, before, after in mutants:
        assert source.count(before) == 1
        try:
            path.write_text(source.replace(before, after))
            result = subprocess.run(
                [sys.executable, "manage.py", "test", "execution.tests.test_provider", "--noinput"],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            (ROOT / "evidence" / f"tls-mutation-{label.replace(' ', '-')}.log").write_text(
                result.stdout + result.stderr
            )
            assert result.returncode != 0 and "FAIL:" in result.stderr, label
            print(f"{label}: killed", flush=True)
        finally:
            path.write_bytes(original)
            assert path.read_bytes() == original


if __name__ == "__main__":
    main()
