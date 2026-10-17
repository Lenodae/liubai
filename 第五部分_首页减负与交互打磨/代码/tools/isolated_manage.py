"""Run management checks with provider files resolved only in disposable state."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")


def main():
    import django

    django.setup()
    from django.core.management import execute_from_command_line
    from django.test import override_settings

    with override_settings(BASE_DIR=Path(os.environ["TASKFLOW_STATE_DIR"])):
        execute_from_command_line(["manage.py", *sys.argv[1:]])


if __name__ == "__main__":
    main()
