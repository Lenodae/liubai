"""Real UI + backend, temporary DB/config, simulated DeepSeek network boundary only."""

import io
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
from pathlib import Path
from unittest.mock import patch

from browser_check import register, wait_server
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def serve(directory):
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from django.core.management import call_command
    from django.test import override_settings

    def models(request, **kwargs):
        assert request.full_url == "https://api.deepseek.com/models"
        assert request.get_method() == "GET"
        key = request.get_header("Authorization")
        if key == "Bearer fixture-slow-key":
            time.sleep(2)
        elif key != "Bearer fixture-valid-key":
            raise urllib.error.HTTPError(request.full_url, 401, "invalid fixture", {}, None)
        return io.BytesIO(b'{"data":[{"id":"deepseek-flash"}]}')

    with override_settings(BASE_DIR=Path(directory)), patch("urllib.request.urlopen", models):
        call_command("runserver", "127.0.0.1:8017", use_reloader=False, insecure=True)


def run():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1050})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        register(page, "settings_qa")
        expect(page.locator("#deepseek-badge")).to_have_text("未配置")
        page.locator("#deepseek-open").click()
        expect(page.locator("#deepseek-key")).to_be_enabled()
        expect(page.locator("#deepseek-key")).to_have_attribute("type", "password")
        page.locator("#deepseek-key").fill("fixture-invalid-key")
        page.locator("#deepseek-submit").click()
        expect(page.locator("#deepseek-result")).to_contain_text("密钥无效")
        expect(page.locator("#deepseek-key")).to_have_value("")
        expect(page.locator("#deepseek-badge")).to_have_text("未配置")
        page.locator("#deepseek-key").fill("fixture-valid-key")
        page.locator("#deepseek-submit").click()
        expect(page.locator("#deepseek-result")).to_contain_text("验证通过，已保存")
        expect(page.locator("#deepseek-badge")).to_have_text("已验证")
        expect(page.locator("#deepseek-key")).to_have_value("")
        assert "fixture-valid-key" not in page.content()
        assert "fixture-valid-key" not in page.evaluate(
            "JSON.stringify([localStorage,sessionStorage])"
        )
        page.screenshot(path=str(ROOT / "evidence/settings-desktop.png"), full_page=True)
        page.locator("#deepseek-close").click()
        page.reload()
        expect(page.locator("#deepseek-badge")).to_have_text("已验证")
        task = page.evaluate("""async () => (await api('/api/tasks', {method:'POST',
            body:{title:'设置验证示例'},headers:{'Idempotency-Key':crypto.randomUUID()}})).task""")
        page.evaluate("id => window.Execution.open(id)", task["id"])
        page.locator("#ex-foundation").fill("尚未保存的基础资料")
        page.locator("#ex-deepseek-settings").click()
        expect(page.locator("#deepseek-submit")).to_be_enabled()
        page.locator("#deepseek-submit").click()
        expect(page.locator("#deepseek-result")).to_contain_text("验证通过")
        page.locator("#deepseek-close").click()
        expect(page.locator("#ex-foundation")).to_have_value("尚未保存的基础资料")
        page.on("dialog", lambda dialog: dialog.accept())
        page.locator("#ex-close").click()
        page.set_viewport_size({"width": 390, "height": 844})
        page.locator("#deepseek-open").click()
        expect(page.locator("#deepseek-key")).to_be_enabled()
        page.screenshot(path=str(ROOT / "evidence/settings-mobile.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.locator("#deepseek-key").fill("fixture-abandoned-key")
        page.keyboard.press("Escape")
        expect(page.locator("#deepseek-key")).to_have_value("")
        # A response arriving after closing the dialog must not repaint the closed UI.
        page.locator("#deepseek-open").click()
        expect(page.locator("#deepseek-key")).to_be_enabled()
        page.locator("#deepseek-key").fill("fixture-slow-key")
        with page.expect_response(
            lambda response: (
                response.url.endswith("/api/settings/deepseek")
                and response.request.method == "POST"
            )
        ) as late:
            page.locator("#deepseek-submit").click()
            expect(page.locator("#deepseek-submit")).to_be_disabled()
            page.locator("#deepseek-close").click()
            expect(page.locator("#deepseek-key")).to_have_value("")
            page.locator("#logout").click()
            expect(page.locator("#auth-screen")).to_be_visible()
            expect(page.locator("#deepseek-current")).to_have_text("")
        assert late.value.status == 200
        expect(page.locator("#deepseek-result")).to_be_hidden()
        register(page, "settings_other")
        page.locator("#deepseek-open").click()
        expect(page.locator("#deepseek-permission")).to_contain_text("最早创建的账号")
        expect(page.locator("#deepseek-submit")).to_be_disabled()
        expect(page.locator("#deepseek-key")).to_have_value("")
        assert not errors, errors
        browser.close()
        return {
            "desktop_mobile": "pass",
            "validation_save_reload": "pass",
            "secret_cleanup": "pass",
            "existing_task_form_preserved": "pass",
            "other_account_readonly": "pass",
            "page_errors": errors,
        }


def main():
    with tempfile.TemporaryDirectory(prefix="liubai-settings-qa-") as directory:
        env = {
            **os.environ,
            "TASKFLOW_DB": str(Path(directory) / "qa.sqlite3"),
            "DEEPSEEK_API_KEY": "",
            "DEEPSEEK_MODEL": "",
        }
        python = str(ROOT / ".venv/bin/python")
        subprocess.run(
            [python, "manage.py", "migrate", "--noinput"],
            cwd=ROOT,
            env=env,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        with (ROOT / "evidence/settings-browser-server.log").open("w") as log:
            server = subprocess.Popen(
                [python, __file__, "--server", directory], cwd=ROOT, env=env, stdout=log, stderr=log
            )
            try:
                wait_server()
                outcome = run()
                (ROOT / "evidence/settings-browser.json").write_text(json.dumps(outcome, indent=2))
                print(json.dumps(outcome))
            finally:
                server.terminate()
                server.wait(timeout=10)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--server":
        serve(sys.argv[2])
    else:
        main()
