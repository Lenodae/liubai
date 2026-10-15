import uuid
from concurrent.futures import ThreadPoolExecutor

from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.test import Client, TransactionTestCase
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.extra.django import TestCase

from .test_api import PASSWORD


class PropertyCase(TestCase):
    @settings(max_examples=20, deadline=None)
    @given(
        title=st.text(alphabet=st.characters(categories=("L", "N")), min_size=1, max_size=100),
        minutes=st.one_of(st.none(), st.integers(min_value=0, max_value=10080)),
    )
    def test_property_isolation(self, title, minutes):
        users = get_user_model()
        a = users.objects.create_user("prop_a")
        b = users.objects.create_user("prop_b")
        ca, cb = Client(), Client()
        ca.force_login(a)
        cb.force_login(b)
        r = ca.post(
            "/api/tasks",
            {"title": title, "weekly_minutes": minutes},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        self.assertEqual(r.status_code, 201)
        task = r.json()["task"]
        self.assertEqual(task["title"], title)
        self.assertEqual(task["weekly_minutes"], minutes)
        url = f"/api/tasks/{task['id']}"
        self.assertEqual(cb.get(url).status_code, 404)
        self.assertEqual(
            cb.patch(
                url, {"version": 1, "title": "bad"}, content_type="application/json"
            ).status_code,
            404,
        )
        self.assertEqual(ca.get(url).json()["task"], task)
        self.assertEqual(cb.get("/api/tasks").json()["tasks"], [])


class ConcurrencyCase(TransactionTestCase):
    def test_concurrent_version_updates(self):
        user = get_user_model().objects.create_user("race", password=PASSWORD)
        a, b = Client(), Client()
        a.force_login(user)
        b.force_login(user)
        r = a.post(
            "/api/tasks",
            {"title": "原始"},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        self.assertEqual(r.status_code, 201)
        task = r.json()["task"]
        from threading import Barrier

        gate = Barrier(2)

        def update(client, title):
            close_old_connections()
            gate.wait()
            try:
                return client.patch(
                    f"/api/tasks/{task['id']}",
                    {"version": 1, "title": title},
                    content_type="application/json",
                ).status_code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(2) as pool:
            jobs = [pool.submit(update, a, "A"), pool.submit(update, b, "B")]
            codes = sorted(job.result() for job in jobs)
        self.assertEqual(codes, [200, 409])
        self.assertEqual(a.get(f"/api/tasks/{task['id']}").json()["task"]["version"], 2)
