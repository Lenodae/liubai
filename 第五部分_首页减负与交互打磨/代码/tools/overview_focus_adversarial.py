"""Disposable-browser probes for account epochs and denied preference storage."""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

expect.set_options(timeout=15000)
ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "LocalProbe!12345"


def wait_server(server, base):
    for _ in range(100):
        assert server.poll() is None, "Temporary probe server exited"
        try:
            if urllib.request.urlopen(base, timeout=1).status == 200:
                return
        except OSError:
            time.sleep(0.1)
    raise AssertionError("Temporary probe server did not become ready")


def run_browser(base):
    with sync_playwright() as playwright:
        options = {"headless": True}
        if Path("/Applications/Google Chrome.app").exists():
            options["channel"] = "chrome"
        browser = playwright.chromium.launch(**options)
        context = browser.new_context(
            viewport={"width": 390, "height": 844}, timezone_id="Asia/Shanghai"
        )
        page = context.new_page()
        errors, external = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def local_only(route):
            if route.request.url.startswith(base):
                route.continue_()
            else:
                external.append(route.request.url)
                route.abort()

        context.route("**/*", local_only)

        def register(name):
            page.locator("#register-tab").click()
            page.locator("#username").fill(name)
            page.locator("#password").fill(PASSWORD)
            page.locator("#auth-submit").click()
            expect(page.locator("#workspace")).to_be_visible()
            expect(page.locator("#overview-focus")).not_to_have_attribute("data-state", "loading")

        def api(path, body=None):
            return page.evaluate(
                """([path, body]) => api(path, body === null ? {} : {
                method:'POST', body, headers:{'Idempotency-Key':crypto.randomUUID()}})""",
                [path, body],
            )

        def open_and_return(task):
            page.evaluate('(id) => LoadWorkspace.openTask(id, "steps")', task["id"])
            expect(page.locator("#execution-dialog")).to_be_visible()
            page.locator("#ex-close").click()
            expect(page.locator("#overview-focus")).to_have_attribute("data-task-id", task["id"])

        page.goto(base)
        register("focus_probe_alpha")
        first = api(
            "/api/tasks",
            {
                "title": "优先事项 Alpha",
                "status": "in_progress",
                "priority": "high",
                "weekly_minutes": 360,
            },
        )["task"]
        recent = api(
            "/api/tasks",
            {
                "title": "继续事项 Beta",
                "status": "in_progress",
                "priority": "normal",
                "weekly_minutes": 60,
            },
        )["task"]
        owner = page.evaluate("state.user.id")
        key = f"liubai.phase5.overview.last-task.{owner}"
        fold = f"liubai.phase5.footprints.expanded.{owner}"
        page.evaluate("LoadWorkspace.invalidate()")
        expect(page.locator("#overview-focus")).to_have_attribute("data-task-id", first["id"])
        open_and_return(recent)
        assert page.evaluate("(key) => localStorage.getItem(key)", key) == json.dumps(recent["id"])
        page.locator("#footprints-toggle").click()
        expect(page.locator("#footprints-expanded-content")).to_be_visible()
        page.reload()
        expect(page.locator("#overview-focus")).to_have_attribute("data-task-id", recent["id"])
        expect(page.locator("#footprints-toggle")).to_have_attribute("aria-expanded", "true")
        page.evaluate(
            """([key,fold]) => {
            localStorage.setItem(key, JSON.stringify({id:'broken'}));
            localStorage.setItem(fold, JSON.stringify('true'));
            }""",
            [key, fold],
        )
        page.reload()
        expect(page.locator("#overview-focus")).to_have_attribute("data-task-id", first["id"])
        expect(page.locator("#footprints-toggle")).to_have_attribute("aria-expanded", "false")
        page.add_init_script(
            """Storage.prototype.getItem = function() {
              throw new DOMException('blocked','SecurityError');
            };
            Storage.prototype.setItem = function() {
              throw new DOMException('blocked','SecurityError');
            };"""
        )
        page.reload()
        expect(page.locator("#overview-focus")).to_have_attribute("data-task-id", first["id"])
        page.locator("#footprints-toggle").click()
        expect(page.locator("#footprints-expanded-content")).to_be_visible()
        open_and_return(recent)
        old_epoch = page.evaluate("state.epoch")
        page.locator("#logout").click()
        expect(page.locator("#auth-screen")).to_be_visible()
        assert page.locator("#overview-focus-title").text_content() == ""
        register("focus_probe_beta")
        expect(page.locator("#overview-focus")).to_have_attribute("data-state", "empty")
        expect(page.locator("#footprints-toggle")).to_have_attribute("aria-expanded", "false")
        page.evaluate(
            """([task, owner, epoch]) => OverviewFocus.remember(task, {owner,epoch})""",
            [first, owner, old_epoch],
        )
        assert page.locator("#overview-focus-title").text_content() == ""
        delayed = api(
            "/api/tasks",
            {
                "title": "旧账号迟到的事项",
                "status": "in_progress",
                "priority": "normal",
                "weekly_minutes": 60,
            },
        )["task"]
        held = []

        def hold(route):
            held.append((route, route.fetch()))

        page.route(f"**/api/tasks/{delayed['id']}/workspace", hold)
        page.evaluate('(id) => LoadWorkspace.openTask(id, "steps")', delayed["id"])
        for _ in range(50):
            if held:
                break
            page.wait_for_timeout(100)
        assert held, "Expected to intercept the old account's execution response"
        page.locator("#logout").click()
        expect(page.locator("#auth-screen")).to_be_visible()
        register("focus_probe_gamma")
        route, response = held.pop()
        route.fulfill(response=response)
        page.wait_for_timeout(300)
        assert page.locator("#overview-focus-title").text_content() == ""
        expect(page.locator("#execution-dialog")).not_to_be_visible()
        assert not errors, errors
        assert not external, external
        assert page.evaluate("document.documentElement.scrollWidth") <= 390
        browser.close()
        return {
            "stored_id_only_and_reload": "pass",
            "corrupt_preferences_fall_back": "pass",
            "storage_denied_get_and_set_keeps_memory_navigation_and_folding": "pass",
            "logout_clears_names_account_switch_does_not_reuse_preferences": "pass",
            "previous_owner_epoch_callback": "ignored",
            "real_delayed_execution_response_after_account_switch": "ignored",
            "mobile_horizontal_overflow": "none",
            "page_errors": errors,
            "external_requests": external,
        }


def main():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="liubai-focus-probe-") as temporary:
        env = {
            **os.environ,
            "TASKFLOW_STATE_DIR": temporary,
            "TASKFLOW_DB": f"{temporary}/tasks.sqlite3",
            "DEEPSEEK_API_KEY": "",
        }
        subprocess.run(
            [sys.executable, "manage.py", "migrate", "--noinput"],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
        )
        with open(f"{temporary}/server.log", "w") as log:
            server = subprocess.Popen(
                [
                    sys.executable,
                    str(ROOT / "tools/isolated_server.py"),
                    temporary,
                    f"127.0.0.1:{port}",
                ],
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=log,
            )
            try:
                wait_server(server, base)
                result = run_browser(base)
                (ROOT / "evidence").mkdir(exist_ok=True)
                (ROOT / "evidence/overview-focus-adversarial.json").write_text(
                    json.dumps(result, indent=2, ensure_ascii=False) + "\n"
                )
                print(json.dumps(result, ensure_ascii=False))
            finally:
                server.terminate()
                server.wait(timeout=10)


if __name__ == "__main__":
    main()
