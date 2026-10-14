import io
import json
import urllib.error
from unittest.mock import patch

from django.test import SimpleTestCase

from execution import provider
from tasks.services import ApiError


class ProviderCase(SimpleTestCase):
    def test_provider(self):
        output = {
            "rationale": "需核对基础",
            "nodes": [
                {"title": "写示例", "criterion": "能运行", "low": 30, "high": 60, "depends": []}
            ],
        }
        raw = json.dumps(
            {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(output)}}]}
        ).encode()
        with (
            patch.object(
                provider,
                "configuration",
                return_value={"key": "private-token", "model": "deepseek-flash"},
            ),
            patch("urllib.request.urlopen", return_value=io.BytesIO(raw)) as net,
        ):
            self.assertEqual(
                provider.generate({"title": "only this task"}, "deepseek-flash"), output
            )
            request = net.call_args.args[0]
            self.assertEqual(request.full_url, "https://api.deepseek.com/chat/completions")
            body = json.loads(request.data)
            self.assertEqual(
                json.loads(body["messages"][1]["content"]), {"title": "only this task"}
            )
            self.assertNotIn("private-token", request.data.decode())
            self.assertEqual(net.call_count, 1)
        for value in [
            "garbage",
            "[]",
            json.dumps({"nodes": []}),
            json.dumps({"nodes": output["nodes"], "owner_id": 99}),
        ]:
            with self.assertRaises(ApiError):
                provider.parse_result(value)
        for error in [
            TimeoutError("private-token"),
            urllib.error.HTTPError("url", 401, "private-token", {}, None),
        ]:
            with (
                patch.object(
                    provider, "configuration", return_value={"key": "private-token", "model": "x"}
                ),
                patch("urllib.request.urlopen", side_effect=error),
            ):
                with self.assertRaises(ApiError) as result:
                    provider.generate({}, "x")
                self.assertNotIn("private-token", result.exception.message)

    def test_configuration_and_bad_responses(self):
        import os
        import tempfile
        from pathlib import Path

        from django.test import override_settings

        with (
            tempfile.TemporaryDirectory() as directory,
            override_settings(BASE_DIR=Path(directory)),
            patch.dict(os.environ, {"DEEPSEEK_API_KEY": "", "DEEPSEEK_MODEL": ""}),
        ):
            folder = Path(directory) / ".local"
            folder.mkdir()
            file = folder / "deepseek.json"
            for raw in ["invalid", "[]", '{"api_key": 4, "model": []}']:
                file.write_text(raw)
                self.assertEqual(provider.configuration(), {"key": "", "model": "deepseek-flash"})
            with self.assertRaises(ApiError):
                provider.generate({}, "deepseek-flash")
            file.write_text(json.dumps({"api_key": "local-test", "model": "test-model"}))
            self.assertEqual(provider.configuration(), {"key": "local-test", "model": "test-model"})
        config = {"key": "local-test", "model": "test-model"}
        responses = [
            b"x" * 262145,
            json.dumps(
                {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]}
            ).encode(),
            b"{}",
        ]
        for raw in responses:
            with (
                patch.object(provider, "configuration", return_value=config),
                patch("urllib.request.urlopen", return_value=io.BytesIO(raw)),
            ):
                with self.assertRaises(ApiError):
                    provider.generate({}, "test-model")
