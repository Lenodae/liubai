import json
import uuid

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase


class AdversarialCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_user("hostile_owner")
        cls.other = get_user_model().objects.create_user("hostile_other")

    def setUp(self):
        cache.clear()
        self.client.force_login(self.owner)

    def test_hostile_unicode_and_shapes(self):
        for payload in [
            {"title": "\ud800"},
            {"title": "\x00"},
            {"title": {}},
            {"status": {}},
            {"priority": []},
            {"kind": True},
        ]:
            with self.subTest(payload=repr(payload)):
                r = self.client.post(
                    "/api/tasks",
                    json.dumps({"title": "valid", **payload}),
                    content_type="application/json",
                    HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
                )
                self.assertEqual(r.status_code, 400)
        self.assertEqual(self.client.get("/api/tasks").json()["tasks"], [])

    def test_cross_tab_identity_mismatch(self):
        self.assertEqual(
            self.client.get("/api/me", HTTP_X_WORKSPACE_USER=str(self.other.id)).status_code, 401
        )
        self.assertEqual(
            self.client.post(
                "/api/tasks",
                {"title": "wrong account draft"},
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
                HTTP_X_WORKSPACE_USER=str(self.other.id),
            ).status_code,
            401,
        )
        self.assertEqual(self.client.get("/api/tasks").json()["tasks"], [])
        self.assertEqual(
            self.client.get("/api/me", HTTP_X_WORKSPACE_USER=str(self.owner.id)).status_code, 200
        )

    def test_body_limit_and_empty_patch(self):
        self.assertEqual(
            self.client.post(
                "/api/tasks", json.dumps({"title": "x" * 40000}), content_type="application/json"
            ).status_code,
            400,
        )
        r = self.client.post(
            "/api/tasks",
            {"title": "safe"},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        self.assertEqual(r.status_code, 201)
        tid = r.json()["task"]["id"]
        self.assertEqual(
            self.client.patch(
                f"/api/tasks/{tid}", {"version": 1}, content_type="application/json"
            ).status_code,
            400,
        )
        self.assertEqual(self.client.get(f"/api/tasks/{tid}").json()["task"]["version"], 1)

    def test_overlong_credentials_and_unknown_fields(self):
        for value in [
            {"username": "abc", "password": "x" * 257},
            {"username": "abc"},
            {"username": "abc", "password": "x", "owner": 1},
        ]:
            self.assertEqual(
                Client()
                .post("/api/auth/login", value, content_type="application/json")
                .status_code,
                400,
            )

    def test_login_cache_eviction_and_reset(self):
        from unittest.mock import patch

        from .test_api import PASSWORD

        self.owner.set_password(PASSWORD)
        self.owner.save()
        cache.set("login:127.0.0.1", 1, timeout=900)
        with patch("tasks.views.cache.incr", side_effect=ValueError("evicted")):
            response = Client().post(
                "/api/auth/login",
                {"username": self.owner.username, "password": "wrong"},
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(cache.get("login:127.0.0.1"), 1)
        response = Client().post(
            "/api/auth/login",
            {"username": self.owner.username, "password": PASSWORD},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(cache.get("login:127.0.0.1"))

    def test_deep_json_rejected_without_server_error(self):
        response = self.client.post(
            "/api/tasks", "[" * 1500 + "0" + "]" * 1500, content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get("/api/tasks").json()["tasks"], [])
