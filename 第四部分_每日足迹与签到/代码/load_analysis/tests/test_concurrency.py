import datetime as dt
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.test import TransactionTestCase
from django.utils import timezone

from load_analysis import services, workspace
from load_analysis.models import LoadEvent, LoadReceipt
from tasks.services import ApiError


class ConcurrentLoadTests(TransactionTestCase):
    def test_two_tabs_one_source_can_only_write_once(self):
        uid = get_user_model().objects.create_user("race_load").pk
        today = timezone.localdate()
        week = today - dt.timedelta(days=today.weekday())
        fingerprint = workspace.build(uid, week, "week")["fingerprint"]
        barrier = threading.Barrier(2)

        def attempt(budget):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                services.mutate(
                    uid,
                    "settings",
                    {
                        "week": week.isoformat(),
                        "mode": "week",
                        "fingerprint": fingerprint,
                        "action": "capacity",
                        "budget_minutes": budget,
                        "buffer_minutes": 0,
                    },
                    str(uuid.uuid4()),
                )
                return 200
            except ApiError as exc:
                return exc.status
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(attempt, [600, 900]))
        self.assertEqual(sorted(outcomes), [200, 409])
        self.assertEqual(LoadEvent.objects.count(), 1)
        self.assertEqual(LoadReceipt.objects.count(), 1)
