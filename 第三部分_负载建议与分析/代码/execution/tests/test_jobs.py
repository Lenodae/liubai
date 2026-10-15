from unittest.mock import patch

from django.test import TestCase

from execution.jobs import recover, run_once
from execution.models import AnalysisRun
from execution.tests import test_execution as helpers


class JobCase(TestCase):
    setUp = helpers.ExecutionCase.setUp
    get = helpers.ExecutionCase.get
    call = helpers.ExecutionCase.call
    profile = helpers.ExecutionCase.profile

    def test_worker_results_and_restart(self):
        self.profile()
        with patch(
            "execution.provider.configuration",
            return_value={"key": "test", "model": "deepseek-flash"},
        ):
            result = self.call("analyze", consent=True)
        run = AnalysisRun.objects.get(pk=result["runs"][0]["id"])
        self.assertEqual(run.snapshot["title"], self.task["title"])
        output = {
            "nodes": [
                {"title": "核对", "criterion": "给出结果", "low": None, "high": None, "depends": []}
            ],
            "rationale": "待核对",
        }
        with patch("execution.provider.generate", return_value=output):
            self.assertTrue(run_once())
        self.assertFalse(run_once())
        result = self.get()
        self.assertEqual(result["runs"][0]["status"], "succeeded")
        self.assertEqual(len(result["drafts"]), 1)
        self.assertFalse(result["steps"])
        run.status = "running"
        run.save()
        self.assertEqual(recover(), 1)
        self.assertEqual(self.get()["runs"][0]["status"], "interrupted")

    def test_worker_cancel_and_fail(self):
        self.profile()
        with patch(
            "execution.provider.configuration",
            return_value={"key": "test", "model": "deepseek-flash"},
        ):
            runid = self.call("analyze", consent=True)["runs"][0]["id"]

        def cancel(*args):
            AnalysisRun.objects.filter(pk=runid).update(status="cancelled")
            return {
                "nodes": [
                    {"title": "x", "criterion": "y", "low": None, "high": None, "depends": []}
                ],
                "rationale": "",
            }

        with patch("execution.provider.generate", side_effect=cancel):
            run_once()
        self.assertFalse(self.get()["drafts"])
        with patch(
            "execution.provider.configuration",
            return_value={"key": "test", "model": "deepseek-flash"},
        ):
            self.call("analyze", consent=True)
        with patch("execution.provider.generate", side_effect=RuntimeError("SECRET")):
            run_once()
        self.assertEqual(self.get()["runs"][0]["status"], "failed")
        self.assertNotIn("SECRET", str(self.get()))

    def test_worker_command_singleton_and_idle(self):
        import fcntl
        import io
        import tempfile
        from pathlib import Path

        from django.core.management import call_command
        from django.test import override_settings

        with (
            tempfile.TemporaryDirectory() as directory,
            override_settings(STATE_DIR=Path(directory)),
        ):
            output = io.StringIO()
            call_command("analysis_worker", once=True, stdout=output)
            self.assertIn("ready", output.getvalue())
            with (Path(directory) / "analysis-worker.lock").open("w") as handle:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                output = io.StringIO()
                call_command("analysis_worker", once=True, stdout=output)
                self.assertIn("already running", output.getvalue())
            with patch(
                "execution.management.commands.analysis_worker.time.sleep",
                side_effect=KeyboardInterrupt,
            ) as pause:
                with self.assertRaises(KeyboardInterrupt):
                    call_command("analysis_worker", stdout=io.StringIO())
                pause.assert_called_once_with(1)

    def test_worker_command_processes_persisted_queue(self):
        import io
        import tempfile
        from pathlib import Path

        from django.core.management import call_command
        from django.test import override_settings

        with patch(
            "execution.provider.configuration",
            return_value={"key": "test", "model": "deepseek-flash"},
        ):
            self.call("analyze", consent=True)
        output = {
            "nodes": [{"title": "x", "criterion": "y", "low": None, "high": None, "depends": []}],
            "rationale": "",
        }
        with (
            tempfile.TemporaryDirectory() as directory,
            override_settings(STATE_DIR=Path(directory)),
            patch("execution.provider.generate", return_value=output) as net,
            patch(
                "execution.management.commands.analysis_worker.time.sleep",
                side_effect=KeyboardInterrupt,
            ),
        ):
            with self.assertRaises(KeyboardInterrupt):
                call_command("analysis_worker", stdout=io.StringIO())
            self.assertEqual(net.call_count, 1)
        self.assertEqual(self.get()["runs"][0]["status"], "succeeded")
