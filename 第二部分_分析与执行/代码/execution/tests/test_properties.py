import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.test import Client, SimpleTestCase, TransactionTestCase
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.extra.django import TestCase

from execution.rules import evaluate
from execution.tests import test_execution as helpers


class RuleProperties(SimpleTestCase):
    @given(st.integers(0, 10000), st.integers(0, 10000), st.integers(0, 20000))
    def test_interval_boundaries(self, low, extra, available):
        high = low + extra
        result = evaluate(
            [{"low": low, "high": high, "status": "planned"}],
            {"available_minutes": available, "criterion": "x", "foundation": "y"},
        )
        expected = "conflict" if available < low else "conditional" if available < high else "fits"
        self.assertEqual(result["time"], expected)
        self.assertEqual((result["remaining_low"], result["remaining_high"]), (low, high))


class LedgerProperties(TestCase):
    @settings(max_examples=15, deadline=None)
    @given(st.lists(st.integers(1, 1000), min_size=1, max_size=6))
    def test_sum_and_idempotency(self, minutes):
        user = get_user_model().objects.create_user("property_" + uuid.uuid4().hex[:12])
        client = Client()
        client.force_login(user)
        task = client.post(
            "/api/tasks",
            {"title": "property"},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        ).json()["task"]
        url = f"/api/tasks/{task['id']}/workspace"
        self.assertIsNone(client.get(url).json()["summary"]["actual_minutes"])
        total = 0
        for value in minutes:
            key = str(uuid.uuid4())
            version = client.get(url).json()["task"]["version"]
            data = {
                "action": "time_add",
                "version": version,
                "step_id": None,
                "minutes": value,
                "date": "2026-10-13",
                "note": "",
            }
            response = client.post(
                url, data, content_type="application/json", HTTP_IDEMPOTENCY_KEY=key
            )
            self.assertEqual(response.status_code, 200)
            repeat = client.post(
                url, data, content_type="application/json", HTTP_IDEMPOTENCY_KEY=key
            )
            self.assertEqual(repeat.json(), response.json())
            total += value
            self.assertEqual(response.json()["summary"]["actual_minutes"], total)
        entry = client.get(url).json()["entries"][0]
        deleted = client.post(
            url,
            {
                "action": "time_delete",
                "version": client.get(url).json()["task"]["version"],
                "entry_id": entry["id"],
                "entry_version": entry["version"],
            },
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(
            deleted.json()["summary"]["actual_minutes"],
            sum(minutes[:-1]) if len(minutes) > 1 else None,
        )


class RaceCase(TransactionTestCase):
    setUp = helpers.ExecutionCase.setUp
    get = helpers.ExecutionCase.get

    def race(self, same_key):
        a, b = Client(), Client()
        a.force_login(self.user)
        b.force_login(self.user)
        barrier = Barrier(2)
        common = str(uuid.uuid4())

        def work(client, key):
            close_old_connections()
            barrier.wait()
            try:
                return client.post(
                    self.url,
                    {
                        "action": "time_add",
                        "version": 1,
                        "step_id": None,
                        "minutes": 30,
                        "date": "2026-10-13",
                        "note": "",
                    },
                    content_type="application/json",
                    HTTP_IDEMPOTENCY_KEY=key,
                ).status_code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(2) as pool:
            jobs = [pool.submit(work, c, common if same_key else str(uuid.uuid4())) for c in [a, b]]
            return sorted(j.result() for j in jobs)

    def test_concurrent_duplicate(self):
        self.assertEqual(self.race(True), [200, 200])
        self.assertEqual(len(self.get()["entries"]), 1)
        self.assertEqual(self.get()["summary"]["actual_minutes"], 30)

    def test_concurrent_versions(self):
        self.assertEqual(self.race(False), [200, 409])
        self.assertEqual(len(self.get()["entries"]), 1)
