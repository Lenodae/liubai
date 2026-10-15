import fcntl
import io
import json
import os
import ssl
import tempfile
import urllib.error
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings

URL = "/api/settings/deepseek"


class SettingsCase(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.override = override_settings(BASE_DIR=self.root)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.env = patch.dict(os.environ, {"DEEPSEEK_API_KEY": "", "DEEPSEEK_MODEL": ""})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.user = get_user_model().objects.create_user(username="settings_owner")
        self.client.force_login(self.user)
        self.file = self.root / ".local/deepseek.json"

    def packet(self, **changes):
        data = {
            "api_key": "private-new-key",
            "model": "deepseek-flash",
            "revision": self.client.get(URL).json().get("revision", ""),
        }
        return {**data, **changes}

    def post(self, data):
        return self.client.post(URL, data=json.dumps(data), content_type="application/json")

    def network(self, ids=None):
        raw = json.dumps({"data": [{"id": x} for x in (ids or ["deepseek-flash"])]}).encode()
        return patch("urllib.request.urlopen", return_value=io.BytesIO(raw))

    def existing(self):
        self.file.parent.mkdir(exist_ok=True)
        self.file.write_text(json.dumps({"api_key": "private-old-key", "model": "deepseek-flash"}))
        return self.file.read_bytes()

    def test_auth_owner_csrf_and_no_key_disclosure(self):
        self.existing()
        status = self.client.get(URL)
        self.assertEqual(status.status_code, 200)
        self.assertTrue(status.json()["can_manage"])
        self.assertIsNone(status.json()["verified_at"])
        self.assertNotIn("private-old-key", status.content.decode())
        self.assertEqual(status.headers["Cache-Control"], "no-store")
        self.assertEqual(Client().get(URL).status_code, 401)
        self.assertEqual(self.client.get(URL, HTTP_X_WORKSPACE_USER="999").status_code, 401)
        guarded = Client(enforce_csrf_checks=True)
        guarded.force_login(self.user)
        self.assertEqual(
            guarded.post(URL, data="{}", content_type="application/json").status_code, 403
        )
        other = get_user_model().objects.create_user(username="other_settings")
        self.client.force_login(other)
        self.assertFalse(self.client.get(URL).json()["can_manage"])
        with self.network() as net:
            self.assertEqual(self.post(self.packet()).status_code, 403)
            net.assert_not_called()

    def test_validate_save_and_verify_existing(self):
        with self.network() as net:
            response = self.post(self.packet())
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["configured"])
        self.assertTrue(response.json()["verified_at"])
        self.assertNotIn("private-new-key", response.content.decode())
        request = net.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.deepseek.com/models")
        self.assertEqual(request.get_method(), "GET")
        self.assertIsNone(request.data)
        self.assertEqual(request.get_header("Authorization"), "Bearer private-new-key")
        self.assertEqual(net.call_count, 1)
        context = net.call_args.kwargs["context"]
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertEqual(self.file.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.file.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(json.loads(self.file.read_text())["api_key"], "private-new-key")
        self.assertTrue(self.client.get(URL).json()["verified_at"])
        with self.network() as net:
            self.assertEqual(self.post(self.packet(api_key="")).status_code, 200)
            self.assertEqual(
                net.call_args.args[0].get_header("Authorization"), "Bearer private-new-key"
            )

    def test_failed_validation_preserves_previous_config(self):
        original = self.existing()
        for error, phrase in [
            (urllib.error.HTTPError("url", 401, "private-new-key", {}, None), "密钥无效"),
            (urllib.error.HTTPError("url", 429, "private-new-key", {}, None), "频率"),
            (urllib.error.HTTPError("url", 500, "private-new-key", {}, None), "服务"),
            (urllib.error.URLError(ssl.SSLCertVerificationError("private-new-key")), "证书"),
            (TimeoutError("private-new-key"), "超时"),
            (urllib.error.URLError("private-new-key"), "网络"),
        ]:
            with (
                self.subTest(phrase=phrase),
                patch("urllib.request.urlopen", side_effect=error) as net,
            ):
                response = self.post(self.packet())
                self.assertGreaterEqual(response.status_code, 400)
                self.assertNotEqual(response.status_code, 401)
                self.assertIn(phrase, response.json()["error"])
                self.assertNotIn("private-new-key", response.content.decode())
                self.assertEqual(self.file.read_bytes(), original)
                self.assertEqual(net.call_count, 1)

    def test_invalid_input_and_missing_key(self):
        for data in [
            self.packet(api_key=""),
            self.packet(api_key="a\nb"),
            self.packet(api_key="x" * 513),
            self.packet(api_key=3),
            self.packet(model="https://evil.test"),
            {**self.packet(), "endpoint": "https://evil.test"},
        ]:
            with self.network() as net:
                self.assertEqual(self.post(data).status_code, 400)
                net.assert_not_called()
                self.assertFalse(self.file.exists())

    def test_bad_models_and_response(self):
        original = self.existing()
        for raw in [
            b"broken private-new-key",
            b"{}",
            b'{"data":[{}]}',
            b'{"data":[]}',
            b"x" * 262145,
        ]:
            with patch("urllib.request.urlopen", return_value=io.BytesIO(raw)):
                response = self.post(self.packet())
                self.assertGreaterEqual(response.status_code, 400)
                self.assertNotIn("private-new-key", response.content.decode())
                self.assertEqual(self.file.read_bytes(), original)

    def test_stale_and_concurrent_requests(self):
        original = self.existing()
        stale = self.packet()
        with self.network():
            self.assertEqual(self.post(self.packet()).status_code, 200)
        with self.network() as net:
            self.assertEqual(self.post(stale).status_code, 409)
            net.assert_not_called()
        with (self.file.parent / "deepseek-settings.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.network() as net:
                self.assertEqual(self.post(self.packet()).status_code, 409)
                net.assert_not_called()

        def external_change(*args, **kwargs):
            self.file.write_bytes(original)
            return io.BytesIO(b'{"data":[{"id":"deepseek-flash"}]}')

        with patch("urllib.request.urlopen", side_effect=external_change):
            self.assertEqual(self.post(self.packet()).status_code, 409)
        self.assertEqual(self.file.read_bytes(), original)

    def test_storage_failure_is_atomic(self):
        original = self.existing()
        with self.network(), patch("os.replace", side_effect=OSError("private-new-key")):
            response = self.post(self.packet())
        self.assertEqual(response.status_code, 503)
        self.assertIn("保存", response.json()["error"])
        self.assertNotIn("private-new-key", response.content.decode())
        self.assertEqual(self.file.read_bytes(), original)
        self.assertFalse(list(self.file.parent.glob("*.tmp")))

    def test_environment_override_is_readonly(self):
        original = self.existing()
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "env-private-key"}):
            self.assertTrue(self.client.get(URL).json()["managed_by_env"])
            with self.network() as net:
                self.assertEqual(self.post(self.packet()).status_code, 409)
                net.assert_not_called()
            with self.network() as net:
                response = self.post(self.packet(api_key=""))
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()["verified_at"])
                self.assertEqual(
                    net.call_args.args[0].get_header("Authorization"), "Bearer env-private-key"
                )
            self.assertEqual(self.file.read_bytes(), original)

    def test_unreadable_configuration_has_safe_message(self):
        with patch("execution.settings_service.stored", side_effect=PermissionError("private-key")):
            response = self.client.get(URL)
        self.assertEqual(response.status_code, 503)
        self.assertIn("配置无法读取", response.json()["error"])
        self.assertNotIn("private-key", response.content.decode())

    def test_hostile_deep_json_preserves_configuration(self):
        original = self.existing()
        raw = b"[" * 2000 + b"0" + b"]" * 2000
        with patch("urllib.request.urlopen", return_value=io.BytesIO(raw)):
            response = self.post(self.packet())
        self.assertEqual(response.status_code, 502)
        self.assertIn("格式异常", response.json()["error"])
        self.assertEqual(self.file.read_bytes(), original)
