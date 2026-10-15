"""Task rows and reservation policies must commit together under competing tabs."""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.test import TransactionTestCase

from load_analysis import policies, workspace
from load_analysis.models import BudgetPolicy
from tasks.models import Task
from tasks.services import ApiError, create_task, update_task


class BudgetPolicyConcurrency(TransactionTestCase):
    def setUp(self):
        self.uid = get_user_model().objects.create_user("reservation_race").pk

    def parallel(self, operation):
        barrier = threading.Barrier(2)

        def attempt(value):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return operation(value)
            except ApiError as error:
                return error.status
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(attempt, [180, 240]))

    def test_two_old_versions_cannot_partially_replace_policy(self):
        task, _ = create_task(
            self.uid,
            {"title": "同时编辑", "status": "in_progress", "weekly_minutes": 60},
            str(uuid.uuid4()),
        )

        def change(minutes):
            update_task(
                self.uid,
                task.pk,
                {
                    "version": task.version,
                    "weekly_minutes": minutes,
                    "budget_schedule": "recurring",
                },
            )
            return 200

        self.assertEqual(sorted(self.parallel(change)), [200, 409])
        task.refresh_from_db()
        policy = BudgetPolicy.objects.get(task=task)
        self.assertEqual(task.version, 2)
        self.assertEqual(policy.schedule, "recurring")
        self.assertEqual(policy.revisions[-1]["minutes"], task.weekly_minutes)
        self.assertEqual(
            workspace.build(self.uid, policies.monday(), "week")["analysis"]["low"],
            task.weekly_minutes,
        )

    def test_same_creation_key_reserves_once(self):
        key = str(uuid.uuid4())

        def create(_minutes):
            _, created = create_task(
                self.uid,
                {
                    "title": "只创建一次",
                    "status": "in_progress",
                    "weekly_minutes": 180,
                    "budget_schedule": "recurring",
                },
                key,
            )
            return created

        self.assertEqual(sorted(self.parallel(create)), [False, True])
        self.assertEqual(Task.objects.count(), 1)
        self.assertEqual(BudgetPolicy.objects.count(), 1)
        self.assertEqual(
            workspace.build(self.uid, policies.monday(), "week")["analysis"]["low"], 180
        )
