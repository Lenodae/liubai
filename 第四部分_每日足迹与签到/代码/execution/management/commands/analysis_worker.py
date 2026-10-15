import fcntl
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from execution.jobs import recover, run_once


class Command(BaseCommand):
    help = "Process persisted DeepSeek analysis jobs with a single local worker."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, **options):
        with (settings.STATE_DIR / "analysis-worker.lock").open("w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                self.stdout.write("Analysis worker is already running.")
                return
            count = recover()
            self.stdout.write(f"Analysis worker ready; interrupted jobs: {count}")
            while True:
                worked = run_once()
                if options["once"]:
                    return
                if not worked:
                    time.sleep(1)
