import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import Client, TestCase, TransactionTestCase

PASSWORD = "Moss!River84Corner"


class ApiCase(TestCase):
    def setUp(self):
        cache.clear()
        users = get_user_model()
        self.alice = users.objects.create_user("alice", password=PASSWORD)
        self.bob = users.objects.create_user("bob", password=PASSWORD)
        self.a, self.b = Client(), Client()
        self.a.force_login(self.alice)
        self.b.force_login(self.bob)

    def create(self, client=None, **extra):
        response = (client or self.a).post(
            "/api/tasks",
            {"title": "修改实验图", **extra},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()["task"]

    def update(self, task, client=None, **extra):
        return (client or self.a).patch(
            f"/api/tasks/{task['id']}",
            {"version": task["version"], **extra},
            content_type="application/json",
        )

    def test_register_login_logout(self):
        c = Client()
        response = c.post(
            "/api/auth/register",
            {"username": "NewUser", "password": PASSWORD},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(c.get("/api/me").json()["user"]["username"], "newuser")
        user = get_user_model().objects.get(username="newuser")
        self.assertNotEqual(user.password, PASSWORD)
        self.assertTrue(user.check_password(PASSWORD))
        self.assertEqual(
            c.post(
                "/api/auth/register",
                {"username": "newuser", "password": PASSWORD},
                content_type="application/json",
            ).status_code,
            400,
        )
        self.assertEqual(c.post("/api/auth/logout").status_code, 200)
        self.assertEqual(c.get("/api/me").status_code, 401)
        self.assertEqual(
            c.post(
                "/api/auth/login",
                {"username": "newuser", "password": "wrong"},
                content_type="application/json",
            ).status_code,
            401,
        )
        self.assertEqual(
            c.post(
                "/api/auth/login",
                {"username": "NEWUSER", "password": PASSWORD},
                content_type="application/json",
            ).status_code,
            200,
        )
        self.assertEqual(c.get("/api/me").json()["user"]["id"], user.id)

    def test_registration_validation(self):
        for payload in [
            {"username": "ab", "password": PASSWORD},
            {"username": "abc", "password": "123"},
            {"username": "abc", "password": PASSWORD, "is_staff": True},
            {"username": 5, "password": PASSWORD},
            {"username": "abc", "password": 6},
        ]:
            with self.subTest(payload=payload):
                self.assertEqual(
                    Client()
                    .post("/api/auth/register", payload, content_type="application/json")
                    .status_code,
                    400,
                )

    def test_anonymous_denied(self):
        c = Client()
        tid = str(uuid.uuid4())
        for method, url in [
            ("get", "/api/tasks"),
            ("post", "/api/tasks"),
            ("get", f"/api/tasks/{tid}"),
            ("patch", f"/api/tasks/{tid}"),
            ("get", f"/api/tasks/{tid}/events"),
        ]:
            self.assertEqual(
                getattr(c, method)(url, "{}", content_type="application/json").status_code
                if method != "get"
                else c.get(url).status_code,
                401,
            )

    def test_isolation(self):
        task = self.create()
        self.assertEqual(self.b.get("/api/tasks").json()["tasks"], [])
        for suffix in ["", "/events"]:
            self.assertEqual(self.b.get(f"/api/tasks/{task['id']}{suffix}").status_code, 404)
        self.assertEqual(
            self.update(task, self.b, title="stolen", status="completed").status_code, 404
        )
        own = self.a.get(f"/api/tasks/{task['id']}").json()["task"]
        self.assertEqual(own["title"], "修改实验图")
        self.assertEqual(own["version"], 1)

    def test_forged_owner(self):
        for field in ["owner", "owner_id", "user_id", "id"]:
            with self.subTest(field=field):
                r = self.a.post(
                    "/api/tasks",
                    {"title": "private", field: self.bob.id},
                    content_type="application/json",
                    HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
                )
                self.assertEqual(r.status_code, 400)
        task = self.create()
        self.assertEqual(self.update(task, owner_id=self.bob.id).status_code, 400)
        self.assertEqual(self.b.get("/api/tasks", {"owner": self.alice.id}).json()["tasks"], [])

    def test_create_persist_and_zero(self):
        task = self.create()
        self.assertEqual(task["status"], "planned")
        self.assertIsNone(task["weekly_minutes"])
        self.assertEqual(self.create(weekly_minutes=0)["weekly_minutes"], 0)
        self.a.post("/api/auth/logout")
        self.a.post(
            "/api/auth/login",
            {"username": "alice", "password": PASSWORD},
            content_type="application/json",
        )
        self.assertEqual(
            self.a.get(f"/api/tasks/{task['id']}").json()["task"]["title"], "修改实验图"
        )

    def test_validation(self):
        bad = [
            {"title": "  "},
            {"title": "a" * 121},
            {"description": "x" * 5001},
            {"weekly_minutes": -1},
            {"weekly_minutes": 1.5},
            {"weekly_minutes": True},
            {"weekly_minutes": 10081},
            {"weekly_minutes": "8"},
            {"status": "fake"},
            {"kind": "fake"},
            {"priority": "urgent"},
            {"title": None},
            {"description": []},
        ]
        for payload in bad:
            with self.subTest(payload=str(payload)[:60]):
                response = self.a.post(
                    "/api/tasks",
                    {"title": "Valid", **payload},
                    content_type="application/json",
                    HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
                )
                self.assertEqual(response.status_code, 400)
        for body in ["{", "[]", "null", "3"]:
            self.assertEqual(
                self.a.post("/api/tasks", body, content_type="application/json").status_code, 400
            )
        self.assertEqual(self.a.get("/api/tasks").json()["tasks"], [])

    def test_status_history(self):
        task = self.create()
        initial_id = task["id"]
        states = ["in_progress", "paused", "in_progress", "completed", "abandoned"]
        for state in states:
            r = self.update(task, status=state)
            self.assertEqual(r.status_code, 200)
            task = r.json()["task"]
            self.assertEqual(task["id"], initial_id)
        events = self.a.get(f"/api/tasks/{initial_id}/events").json()["events"]
        self.assertEqual([x["to_status"] for x in events], states)
        r = self.update(task, status="abandoned", title="已决定结束")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(self.a.get(f"/api/tasks/{initial_id}/events").json()["events"]), 5)
        self.assertEqual(
            self.a.get("/api/tasks?status=history").json()["tasks"][0]["title"], "已决定结束"
        )
        self.assertEqual(self.a.get("/api/tasks?status=in_progress").json()["tasks"], [])

    def test_optimistic_conflict(self):
        task = self.create()
        self.assertEqual(self.update(task, title="新内容").status_code, 200)
        self.assertEqual(self.update(task, title="过时的内容", status="completed").status_code, 409)
        self.assertEqual(self.a.get(f"/api/tasks/{task['id']}").json()["task"]["title"], "新内容")
        self.assertEqual(self.a.get(f"/api/tasks/{task['id']}/events").json()["events"], [])
        for version in [None, 0, True, "1"]:
            self.assertEqual(
                self.a.patch(
                    f"/api/tasks/{task['id']}",
                    {"version": version, "title": "x"},
                    content_type="application/json",
                ).status_code,
                400,
            )

    def test_idempotency(self):
        key = str(uuid.uuid4())

        def send(client, title="once"):
            return client.post(
                "/api/tasks",
                {"title": title},
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY=key,
            )

        first, second = send(self.a), send(self.a)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["task"]["id"], second.json()["task"]["id"])
        self.assertEqual(send(self.a, "different").status_code, 409)
        other = send(self.b)
        self.assertEqual(other.status_code, 201)
        self.assertNotEqual(first.json()["task"]["id"], other.json()["task"]["id"])
        self.assertEqual(len(self.a.get("/api/tasks").json()["tasks"]), 1)
        self.assertEqual(len(self.b.get("/api/tasks").json()["tasks"]), 1)

    def test_idempotency_key_required(self):
        for key in ["", "bad-key"]:
            self.assertEqual(
                self.a.post(
                    "/api/tasks",
                    {"title": "once"},
                    content_type="application/json",
                    HTTP_IDEMPOTENCY_KEY=key,
                ).status_code,
                400,
            )

    def test_atomic_rollback(self):
        task = self.create()
        with patch(
            "tasks.models.TaskEvent.objects.create",
            side_effect=RuntimeError("simulated write failure"),
        ):
            with self.assertRaises(RuntimeError):
                self.update(task, status="completed")
        saved = self.a.get(f"/api/tasks/{task['id']}").json()["task"]
        self.assertEqual(saved["status"], "planned")
        self.assertEqual(saved["version"], 1)
        self.assertEqual(self.a.get(f"/api/tasks/{task['id']}/events").json()["events"], [])

    def test_csrf(self):
        c = Client(enforce_csrf_checks=True)
        self.assertEqual(c.get("/").status_code, 200)
        for path in ["/api/auth/register", "/api/auth/login"]:
            self.assertEqual(
                c.post(
                    path,
                    {"username": "charlie", "password": PASSWORD},
                    content_type="application/json",
                ).status_code,
                403,
            )
        r = c.post(
            "/api/auth/register",
            {"username": "charlie", "password": PASSWORD},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value,
        )
        self.assertEqual(r.status_code, 201)
        self.assertTrue(c.cookies["sessionid"]["httponly"])
        self.assertEqual(c.cookies["sessionid"]["samesite"], "Lax")
        self.assertEqual(
            c.post("/api/tasks", {"title": "blocked"}, content_type="application/json").status_code,
            403,
        )
        self.assertEqual(c.post("/api/auth/logout").status_code, 403)
        r = c.post(
            "/api/tasks",
            {"title": "allowed"},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value,
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        self.assertEqual(r.status_code, 201)
        self.assertEqual(
            c.patch(
                f"/api/tasks/{r.json()['task']['id']}",
                {"version": 1, "title": "blocked"},
                content_type="application/json",
            ).status_code,
            403,
        )

    def test_brute_force(self):
        c = Client()
        for _ in range(5):
            self.assertEqual(
                c.post(
                    "/api/auth/login",
                    {"username": "alice", "password": "wrong"},
                    content_type="application/json",
                ).status_code,
                401,
            )
        self.assertEqual(
            c.post(
                "/api/auth/login",
                {"username": "alice", "password": PASSWORD},
                content_type="application/json",
            ).status_code,
            429,
        )
        cache.clear()
        self.assertEqual(
            c.post(
                "/api/auth/login",
                {"username": "alice", "password": PASSWORD},
                content_type="application/json",
            ).status_code,
            200,
        )

    def test_query_and_methods(self):
        task = self.create(
            title="  科研 <script>  ", weekly_minutes=480, kind="work", priority="high"
        )
        self.create(title="散步", status="in_progress")
        result = self.a.get("/api/tasks?q=科研").json()
        self.assertEqual([x["title"] for x in result["tasks"]], ["科研 <script>"])
        self.assertEqual(result["counts"]["in_progress"], 1)
        self.assertEqual(self.a.get("/api/tasks?status=wrong").status_code, 400)
        self.assertEqual(self.a.delete(f"/api/tasks/{task['id']}").status_code, 405)
        self.assertEqual(self.a.get(f"/api/tasks/{task['id']}").status_code, 200)
        self.assertEqual(self.a.get(f"/api/tasks/{uuid.uuid4()}").status_code, 404)
        self.assertEqual(self.a.get("/api/auth/login").status_code, 405)
        self.assertEqual(self.a.get("/api/tasks").headers["Cache-Control"], "no-store")


class PersistenceCase(TransactionTestCase):
    def test_connection_reopen(self):
        user = get_user_model().objects.create_user("persist", password=PASSWORD)
        c = Client()
        c.force_login(user)
        r = c.post(
            "/api/tasks",
            {"title": "跨连接保留"},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        self.assertEqual(r.status_code, 201)
        connection.close()
        self.assertEqual(
            c.get(f"/api/tasks/{r.json()['task']['id']}").json()["task"]["title"], "跨连接保留"
        )
