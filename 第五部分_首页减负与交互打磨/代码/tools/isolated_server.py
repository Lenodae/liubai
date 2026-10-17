"""Serve real application assets while resolving provider files in disposable state."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def serve(directory, address):
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from django.core.management import call_command
    from django.test import override_settings

    # Settings already resolved template/static paths against the application root.
    # Provider configuration uses BASE_DIR dynamically and must never reach its .local.
    with override_settings(BASE_DIR=Path(directory)):
        call_command("runserver", address, use_reloader=False, insecure=True)


if __name__ == "__main__":
    serve(sys.argv[1], sys.argv[2])
