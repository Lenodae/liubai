import datetime as dt
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from execution.models import Event, Profile, Receipt, Step, TimeEntry
from execution.overview import step_preview
from tasks.models import Task


class OverviewStepCase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("overview_steps")
        self.other = get_user_model().objects.create_user("overview_other")
        self.client.force_login(self.user)
        self.task = Task.objects.create(
            owner=self.user,
            title="实现一个小功能",
            status="in_progress",
            weekly_minutes=120,
            request_key=uuid.uuid4(),
        )
        self.provider = patch(
            "execution.provider.configuration", return_value={"key": "", "model": "test-model"}
        )
        self.provider.start()
        self.addCleanup(self.provider.stop)

    def step(self, position, *, status="planned", depends=(), task=None):
        item = Step.objects.create(
            task=task or self.task,
            title=f"步骤 {position + 1}",
            criterion=f"检查第 {position + 1} 个结果",
            position=position,
            status=status,
        )
        item.depends.set(depends)
        return item

    def load_url(self):
        today = timezone.localdate()
        monday = today - dt.timedelta(days=today.weekday())
        return f"/api/load/workspace?week={monday}&mode=week"

    def test_current_third_and_next_unlock_after_completion(self):
        first = self.step(0, status="completed")
        second = self.step(1, status="completed", depends=[first])
        current = self.step(2, status="in_progress", depends=[second])
        following = self.step(3, depends=[current])
        result = step_preview(self.task)
        self.assertEqual((result["total"], result["completed"], result["state"]), (4, 2, "ready"))
        self.assertEqual(
            result["current"],
            {
                "id": str(current.id),
                "title": current.title,
                "criterion": current.criterion,
                "status": "in_progress",
                "number": 3,
            },
        )
        self.assertEqual(result["next"]["id"], str(following.id))
        self.assertEqual(result["next"]["number"], 4)
        self.assertIs(result["next"]["after_current"], True)

    def test_started_step_precedes_ready_planned_and_next_can_already_be_ready(self):
        planned = self.step(0)
        current = self.step(4, status="in_progress")
        result = step_preview(self.task)
        self.assertEqual(result["current"]["id"], str(current.id))
        self.assertEqual(result["current"]["number"], 2)
        self.assertEqual(result["next"]["id"], str(planned.id))
        self.assertIs(result["next"]["after_current"], False)

    def test_next_does_not_skip_other_incomplete_prerequisites(self):
        current = self.step(0)
        paused = self.step(1, status="paused")
        self.step(2, depends=[current, paused])
        result = step_preview(self.task)
        self.assertEqual(result["current"]["id"], str(current.id))
        self.assertIsNone(result["next"])

    def test_paused_abandoned_and_blocked_started_steps_are_not_actionable(self):
        paused = self.step(0, status="paused")
        abandoned = self.step(1, status="abandoned")
        self.step(2, status="in_progress", depends=[paused])
        self.step(3, depends=[abandoned])
        result = step_preview(self.task)
        self.assertEqual(result["state"], "blocked")
        self.assertIsNone(result["current"])
        self.assertIsNone(result["next"])
        self.assertEqual(result["completed"], 0)

    def test_empty_finished_and_inactive_states(self):
        self.assertEqual(step_preview(self.task)["state"], "empty")
        self.step(0, status="completed")
        self.assertEqual(step_preview(self.task)["state"], "finished")
        self.step(1)
        for status in ["planned", "paused", "completed", "abandoned"]:
            with self.subTest(status=status):
                self.task.status = status
                result = step_preview(self.task)
                self.assertEqual(result["state"], "inactive")
                self.assertIsNone(result["current"])
                self.assertIsNone(result["next"])
        self.task.status = "in_progress"
        self.task.deleted_at = timezone.now()
        self.assertEqual(step_preview(self.task)["state"], "inactive")

    def test_stable_position_and_id_order(self):
        later = self.step(9)
        first = self.step(1)
        tie = self.step(1)
        expected = sorted([first, tie], key=lambda item: item.id)
        result = step_preview(self.task)
        self.assertEqual(result["current"]["id"], str(expected[0].id))
        self.assertEqual(result["next"]["id"], str(expected[1].id))
        self.assertNotEqual(result["current"]["id"], str(later.id))
        self.assertEqual(result["next"]["number"], 2)

    def test_list_and_budget_include_owner_scoped_summary_without_private_records(self):
        current = self.step(0)
        foreign = Task.objects.create(
            owner=self.other, title="其他人的任务", status="in_progress", request_key=uuid.uuid4()
        )
        self.step(0, task=foreign)
        Event.objects.create(
            task=self.task,
            step=current,
            actor=self.user,
            kind="complete",
            data={"note": "不应进入摘要的完成说明"},
        )
        before = (Profile.objects.count(), Event.objects.count(), Receipt.objects.count())
        for url in ["/api/tasks?status=in_progress", self.load_url()]:
            with self.subTest(url=url):
                with CaptureQueriesContext(connection) as captured:
                    response = self.client.get(url)
                self.assertEqual(response.status_code, 200, response.content)
                tasks = response.json()["tasks"]
                self.assertEqual([item["id"] for item in tasks], [str(self.task.id)])
                self.assertEqual(tasks[0]["step_preview"]["current"]["id"], str(current.id))
                self.assertNotIn("不应进入摘要的完成说明", response.content.decode())
                writes = [
                    item["sql"]
                    for item in captured
                    if item["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
                ]
                self.assertEqual(writes, [])
        self.assertEqual(
            before, (Profile.objects.count(), Event.objects.count(), Receipt.objects.count())
        )
        outsider = Client()
        outsider.force_login(self.other)
        self.assertEqual(outsider.get(f"/api/tasks/{self.task.id}/workspace").status_code, 404)

    def test_list_and_budget_queries_do_not_grow_per_task(self):
        self.step(0)
        counts = {}
        for url in ["/api/tasks?status=in_progress", self.load_url()]:
            with CaptureQueriesContext(connection) as captured:
                response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertIn("step_preview", response.json()["tasks"][0])
            counts[url] = len(captured)
        for index in range(15):
            task = Task.objects.create(
                owner=self.user,
                title=f"更多任务 {index}",
                status="in_progress",
                request_key=uuid.uuid4(),
            )
            first = self.step(0, task=task)
            self.step(1, depends=[first], task=task)
        for url, count in counts.items():
            with self.subTest(url=url):
                with CaptureQueriesContext(connection) as captured:
                    response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(response.json()["tasks"]), 16)
                self.assertEqual(len(captured), count)

    def test_inline_completion_is_idempotent_preserves_time_and_parent(self):
        current = self.step(0)
        following = self.step(1, depends=[current])
        preview = step_preview(self.task)
        body = {
            "action": "complete",
            "version": self.task.version,
            "step_id": preview["current"]["id"],
        }
        key = str(uuid.uuid4())
        url = f"/api/tasks/{self.task.id}/workspace"
        first = self.client.post(
            url, body, content_type="application/json", HTTP_IDEMPOTENCY_KEY=key
        )
        self.assertEqual(first.status_code, 200, first.content)
        replay = self.client.post(
            url, body, content_type="application/json", HTTP_IDEMPOTENCY_KEY=key
        )
        self.assertEqual(replay.status_code, 200, replay.content)
        self.assertEqual(replay.json(), first.json())
        self.assertEqual(first.json()["task"]["step_preview"]["current"]["id"], str(following.id))
        self.assertEqual(first.json()["task"]["status"], "in_progress")
        self.assertEqual(Event.objects.filter(kind="complete").count(), 1)
        self.assertEqual(Receipt.objects.count(), 1)
        self.assertFalse(TimeEntry.objects.exists())
        stale = self.client.post(
            url,
            {**body, "step_id": str(following.id)},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        self.assertEqual(stale.status_code, 409)
        following.refresh_from_db()
        self.assertEqual(following.status, "planned")

    def test_foreign_missing_dependency_fails_closed(self):
        foreign = Task.objects.create(
            owner=self.other, title="其他人的任务", status="in_progress", request_key=uuid.uuid4()
        )
        dependency = self.step(0, task=foreign, status="completed")
        self.step(0, depends=[dependency])
        result = step_preview(self.task)
        self.assertEqual(result["state"], "blocked")
        self.assertIsNone(result["current"])
        self.assertNotIn(str(dependency.id), str(result))
