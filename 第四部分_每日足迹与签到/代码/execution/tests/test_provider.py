import io
import json
import ssl
import urllib.error
from unittest.mock import patch

from django.test import SimpleTestCase

from execution import provider
from tasks.services import ApiError


class ProviderCase(SimpleTestCase):
    def test_tls_without_system_ca(self):
        with (
            patch.object(provider, "configuration", return_value={"key": "secret", "model": "x"}),
            patch.dict(
                "os.environ", {"SSL_CERT_FILE": "/missing/ca.pem", "SSL_CERT_DIR": "/missing"}
            ),
            patch("urllib.request.urlopen", return_value=io.BytesIO(b"{}")) as net,
        ):
            with self.assertRaises(ApiError):
                provider.generate({}, "x")
            context = net.call_args.kwargs.get("context")
            self.assertIsInstance(context, ssl.SSLContext)
            self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
            self.assertTrue(context.check_hostname)
            self.assertGreater(len(context.get_ca_certs()), 0)

    def test_distinct_safe_connection_errors(self):
        for error, message in [
            (ssl.SSLCertVerificationError("secret"), "证书校验失败"),
            (urllib.error.URLError(ssl.SSLCertVerificationError("secret")), "证书校验失败"),
            (TimeoutError("secret"), "请求超时"),
            (urllib.error.URLError(TimeoutError("secret")), "请求超时"),
            (urllib.error.URLError("secret"), "网络连接失败"),
            (OSError("secret"), "网络连接失败"),
        ]:
            with (
                self.subTest(error=type(error).__name__, message=message),
                patch.object(
                    provider, "configuration", return_value={"key": "secret", "model": "x"}
                ),
                patch("urllib.request.urlopen", side_effect=error) as net,
            ):
                with self.assertRaises(ApiError) as result:
                    provider.generate({}, "x")
                self.assertIn(message, result.exception.message)
                self.assertNotIn("secret", result.exception.message)
                self.assertEqual(net.call_count, 1)

    def test_response_format_error_is_distinct(self):
        with (
            patch.object(provider, "configuration", return_value={"key": "secret", "model": "x"}),
            patch("urllib.request.urlopen", return_value=io.BytesIO(b"secret")) as net,
        ):
            with self.assertRaises(ApiError) as result:
                provider.generate({}, "x")
            self.assertIn("响应格式异常", result.exception.message)
            self.assertNotIn("超时", result.exception.message)
            self.assertNotIn("secret", result.exception.message)
            self.assertEqual(net.call_count, 1)

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
