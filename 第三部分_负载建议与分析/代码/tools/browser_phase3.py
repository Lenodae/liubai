"""Phase-3 acceptance with a real browser, synthetic accounts and disposable state.

Uses 127.0.0.1:8029, a temporary SQLite database and a temporary BASE_DIR for
provider configuration. Never starts an AI worker or reads the real .local files.
"""

import datetime as dt
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

# Account creation performs the production password hash; allow for local CPU contention.
expect.set_options(timeout=15000)

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8029"
PASSWORD = "Moss!River84Corner"


def serve(directory):
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from django.core.management import call_command
    from django.test import override_settings

    with override_settings(BASE_DIR=Path(directory)):
        call_command("runserver", "127.0.0.1:8029", use_reloader=False, insecure=True)


def wait_server(server):
    for _ in range(100):
        assert server.poll() is None, "Temporary browser server exited"
        try:
            with urllib.request.urlopen(BASE, timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.1)
    raise AssertionError("Temporary browser server did not become ready")


def workspace(page):
    return page.evaluate("""async () => api('/api/load/workspace?' + new URLSearchParams({
        week: document.querySelector('#load-week').value,
        mode: document.querySelector('#load-mode').value
    }))""")


def submit(page, selector, operation="settings"):
    with page.expect_response(
        lambda response: (
            response.url.endswith(f"/api/load/{operation}") and response.request.method == "POST"
        )
    ) as response:
        page.locator(selector).click()
    result = response.value
    assert result.status == 200, f"{operation} returned {result.status}: {result.text()}"
    expect(page.locator(selector)).to_be_enabled()
    return result.json()


def fill_duration(page, field, total):
    hours, minutes = ("", "") if total in (None, "") else map(str, divmod(int(total), 60))
    page.locator(f"#{field}-hours").fill(hours)
    page.locator(f"#{field}-minutes").fill(minutes)


def expect_duration(page, field, total):
    hours, minutes = ("", "") if total in (None, "") else map(str, divmod(int(total), 60))
    expect(page.locator(f"#{field}-hours")).to_have_value(hours)
    expect(page.locator(f"#{field}-minutes")).to_have_value(minutes)


def budget(page, total, buffer):
    expect(page.locator("#load-budget-editor")).to_be_visible()
    fill_duration(page, "load-budget", total)
    fill_duration(page, "load-buffer", buffer)
    return submit(page, '#load-capacity-form button[type="submit"]')


def navigate(page, route):
    page.locator(f'[data-route="{route}"]').click()
    expect(page).to_have_url(re.compile(rf"#{route}\?"))
    expect(page.locator(f'[data-route="{route}"]')).to_have_attribute("aria-current", "page")


def assert_no_overflow(page):
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (
        "Horizontal overflow at the current viewport"
    )


def run_browser():
    with sync_playwright() as playwright:
        options = {"headless": True}
        if Path("/Applications/Google Chrome.app").exists():
            options["channel"] = "chrome"
        browser = playwright.chromium.launch(**options)
        context = browser.new_context(
            viewport={"width": 1440, "height": 1050}, timezone_id="Asia/Shanghai"
        )
        page = context.new_page()
        page.set_default_timeout(15000)
        errors, external = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("dialog", lambda dialog: dialog.accept())

        def local_only(route):
            if route.request.url.startswith(BASE):
                route.continue_()
            else:
                external.append(route.request.url)
                route.abort()

        page.route("**/*", local_only)
        try:
            page.goto(BASE)
            expect(page.locator("#auth-screen")).to_be_visible()
            page.locator("#register-tab").click()
            page.locator("#username").fill("phase3_qa")
            page.locator("#password").fill(PASSWORD)
            page.locator("#auth-submit").click()
            expect(page.locator("#workspace")).to_be_visible()
            expect(page.locator("#page-title")).to_contain_text("预算与任务总览")
            expect(page.locator("#load-summary")).to_contain_text("信息待补全")
            expect(page.locator("#task-dialog")).not_to_be_visible()
            expect(page.locator("#empty")).to_be_visible()
            initial = workspace(page)
            assert initial["window"]["budget_minutes"] is None
            assert initial["tasks"] == []
            assert initial["analysis"]["verdict"] == "unknown"
            assert initial["window"]["mode"] == "week"
            assert initial["actual"]["minutes"] is None
            cookies = {item["name"] for item in context.cookies()}
            assert {"taskflow3_csrf", "taskflow3_session"} <= cookies
            assert not cookies.intersection({"taskflow2_csrf", "taskflow2_session", "sessionid"})
            page.screenshot(path=str(ROOT / "evidence/phase3-empty.png"), full_page=True)

            # The inherited cases exercise remaining-time confirmation explicitly.
            # The new weekly reservation behavior is checked by browser_budget_reservation.py.
            page.locator("#load-mode").select_option("remaining")
            expect(page).to_have_url(re.compile(r"mode=remaining"))
            expect(page.locator("#load-window-help")).to_contain_text("未来剩余安排")

            empty = budget(page, "", "")
            assert empty["window"]["budget_minutes"] is None
            assert empty["analysis"]["capacity"] is None
            zero = budget(page, "0", "0")
            assert zero["analysis"]["capacity"] == 0
            expect(page.locator("#load-summary")).not_to_contain_text("NaN")
            expect(page.locator("#load-summary")).not_to_contain_text("Infinity")

            # A minutes-only entry is known time, even when its hours box is empty.
            page.locator("#load-budget-hours").fill("")
            page.locator("#load-budget-minutes").fill("45")
            page.locator("#load-buffer-hours").fill("")
            page.locator("#load-buffer-minutes").fill("5")
            minutes_only = submit(page, '#load-capacity-form button[type="submit"]')
            assert minutes_only["window"]["budget_minutes"] == 45
            assert minutes_only["window"]["buffer_minutes"] == 5
            assert minutes_only["analysis"]["capacity"] == 40
            expect(page.locator("#load-summary .budget-chart")).to_contain_text("45 分钟")
            expect(page.locator("#load-summary .budget-chart")).to_contain_text("40 分钟")

            # Failed saves retain the same input; retry does not create a second operation.
            expect(page.locator("#load-budget-editor")).to_be_visible()
            fill_duration(page, "load-budget", 600)
            fill_duration(page, "load-buffer", 120)
            page.route("**/api/load/settings", lambda route: route.abort())
            page.locator('#load-capacity-form button[type="submit"]').click()
            expect(page.locator("#load-retry-wrap")).to_be_visible()
            expect_duration(page, "load-budget", 600)
            page.unroute("**/api/load/settings")
            retried = submit(page, "#load-retry")
            assert retried["analysis"]["capacity"] == 480
            expect(page.locator("#load-retry-wrap")).not_to_be_visible()

            page.locator("#new-task").click()
            expect(page.locator("#task-status")).to_have_value("planned")
            page.locator("#task-title").fill("浏览器验收：复现一个实验")
            page.locator("#task-more-settings > summary").click()
            page.locator("#task-status").select_option("in_progress")
            page.locator("#task-hours").fill("10")
            page.locator("#save-task").click()
            expect(page.locator("#task-dialog")).not_to_be_visible()
            expect(page.locator("#budget-reservation-dialog")).to_be_visible()
            expect(page.locator("#budget-reservation-task")).to_contain_text("10 小时")
            page.locator("#budget-reservation-done").click()
            expect(page.locator(".task-card")).to_have_count(1)
            task_id = page.locator(".task-card").get_attribute("data-task-id")
            page.locator(".task-card").click()
            page.get_by_role("button", name="分析与执行 ↗").click()
            expect(page.locator("#execution-dialog")).to_be_visible()
            week = page.locator("#load-week").input_value()
            sunday = (dt.date.fromisoformat(week) + dt.timedelta(days=6)).isoformat()
            page.locator("#ex-criterion").fill("实验运行结果可核对")
            page.locator("#ex-deadline").fill(sunday)
            page.get_by_role("button", name="保存目标与条件", exact=True).click()
            expect(page.locator("#ex-notice")).to_have_text("已保存。")
            page.locator("#ex-close").click()
            navigate(page, "load")
            expect(page.locator(f'[data-load-task="{task_id}"]')).to_contain_text("本窗口待确认")
            assert workspace(page)["tasks"][0]["progress_low"] is None
            # Creating/changing a task invalidates remaining-time confirmation.
            budget(page, "600", "120")
            page.locator(f'[data-load-task="{task_id}"]').get_by_role(
                "button", name="确认 / 修改投入"
            ).click()
            expect(page.locator("#load-plan-dialog")).to_be_visible()
            expect(page.locator("#load-plan-reference")).to_contain_text("10 小时")
            for name, amount in {
                "progress-low": "420",
                "progress-high": "600",
                "maintenance-low": "0",
                "maintenance-high": "0",
                "remaining-low": "600",
                "remaining-high": "600",
            }.items():
                page.locator(f"#load-{name}").fill(amount)
            page.locator("#load-scope-confirmed").check()
            confirmed = submit(page, '#load-plan-form button[type="submit"]')
            expect(page.locator("#load-plan-dialog")).not_to_be_visible()
            assert confirmed["analysis"]["capacity"] == 480
            assert confirmed["analysis"]["verdict"] == "conditional"
            assert confirmed["analysis"]["deficit_high"] == 120
            expect(page.locator("#load-summary .load-feeling-label")).to_have_text("该减一点")
            expect(page.locator("#load-summary .load-feeling-percent")).to_have_text("按上界 125%")
            expect(page.locator("#load-summary")).to_contain_text("预计负载 87.5%–125%")

            original = workspace(page)
            scenario = page.locator(f'#load-scenario-rows [data-task-id="{task_id}"]')
            scenario.locator('[data-change="selected"]').check()
            scenario.locator('[data-change="progress_low"]').fill("300")
            scenario.locator('[data-change="progress_high"]').fill("300")
            preview = submit(page, '#load-scenario-form button[type="submit"]', "preview")
            expect(page.locator("#load-preview")).to_be_visible()
            assert preview["before"]["verdict"] == "conditional"
            assert preview["after"]["verdict"] == "fits"
            unchanged = workspace(page)
            assert unchanged["fingerprint"] == original["fingerprint"]
            assert unchanged["tasks"][0]["progress_low"] == 420
            with page.expect_response(
                lambda response: (
                    response.url.endswith("/api/load/apply") and response.request.method == "POST"
                )
            ) as applied_response:
                page.get_by_role("button", name="确认采纳这份方案", exact=True).click()
            assert applied_response.value.status == 200, applied_response.value.text()
            expect(page.locator("#load-preview")).not_to_be_visible()
            applied = workspace(page)
            assert applied["analysis"]["verdict"] == "fits"
            assert applied["tasks"][0]["progress_low"] == 300
            assert applied["tasks"][0]["weekly_minutes"] == 600
            assert applied["tasks"][0]["status"] == "in_progress"
            with page.expect_response(
                lambda response: (
                    response.url.endswith("/api/load/undo") and response.request.method == "POST"
                )
            ) as undo_response:
                page.get_by_role("button", name="撤回这次方案", exact=True).click()
            assert undo_response.value.status == 200, undo_response.value.text()
            expect(page.locator("#load-summary .load-feeling-label")).to_have_text("该减一点")
            expect(page.locator("#load-summary .load-feeling-percent")).to_have_text("按上界 125%")
            assert workspace(page)["tasks"][0]["progress_low"] == 420
            submit(page, "#load-save-snapshot")

            navigate(page, "overview")
            expect(page.locator(".task-card")).to_have_count(1)
            before_search = workspace(page)
            summary = page.locator("#load-summary").inner_text()
            page.locator("#search").fill("不存在的任务")
            expect(page.locator(".task-card")).to_have_count(0)
            assert page.locator("#load-summary").inner_text() == summary
            after_search = workspace(page)
            assert after_search["analysis"] == before_search["analysis"]
            assert after_search["fingerprint"] == before_search["fingerprint"]
            page.locator("#search").fill("")
            expect(page.locator(".task-card")).to_have_count(1)
            page.evaluate("window.scrollTo(0, 0)")
            page.screenshot(path=str(ROOT / "evidence/phase3-overview-desktop.png"), full_page=True)

            navigate(page, "deadlines")
            expect(page.locator("#load-deadline-result")).to_contain_text(
                "浏览器验收：复现一个实验"
            )
            expect(page.locator("#load-deadline-result")).to_contain_text("2 小时")
            navigate(page, "review")
            expect(page.locator("#load-review-content")).to_contain_text("当时保存的计划与分析")
            expect(page.locator("#load-review-content .load-saved")).not_to_have_count(0)
            expect(page.locator("#load-review-content")).to_contain_text("没有实际耗时记录")

            navigate(page, "overview")
            page.reload()
            expect(page.locator("#load-summary .load-feeling-label")).to_have_text("该减一点")
            expect(page.locator("#load-summary .load-feeling-percent")).to_have_text("按上界 125%")
            expect(page.locator(".task-card")).to_have_count(1)
            page.set_viewport_size({"width": 390, "height": 844})
            assert_no_overflow(page)
            page.evaluate("window.scrollTo(0, 0)")
            page.screenshot(path=str(ROOT / "evidence/phase3-overview-mobile.png"), full_page=True)
            navigate(page, "load")
            assert_no_overflow(page)
            page.locator(f'[data-load-task="{task_id}"]').get_by_role(
                "button", name="确认 / 修改投入"
            ).click()
            expect(page.locator("#load-plan-dialog")).to_be_visible()
            assert_no_overflow(page)
            page.screenshot(path=str(ROOT / "evidence/phase3-plan-mobile.png"), full_page=True)
            page.locator("#load-plan-close").click()

            # A second account must not inherit the first account's budget or task text.
            page.locator("#logout").click()
            expect(page.locator("#auth-screen")).to_be_visible()
            assert "浏览器验收：复现一个实验" not in page.content()
            page.locator("#register-tab").click()
            page.locator("#username").fill("phase3_other")
            page.locator("#password").fill(PASSWORD)
            page.locator("#auth-submit").click()
            expect(page.locator("#load-summary")).to_contain_text("信息待补全")
            other = workspace(page)
            assert other["tasks"] == []
            assert other["window"]["budget_minutes"] is None
            assert not errors, errors
            assert not external, external
            return {
                "login_defaults_to_budget_overview": "pass",
                "unknown_vs_zero_budget": "pass",
                "failed_save_retains_input_and_retries": "pass",
                "task_plan_confirmation_and_interval_load": "pass",
                "preview_readonly_apply_undo": "pass",
                "search_does_not_change_total_load": "pass",
                "deadline_and_history_routes": "pass",
                "refresh_persistence_and_390px_layout": "pass",
                "account_isolation": "pass",
                "page_errors": errors,
                "external_requests": external,
                "real_database_or_secret_contents_read": False,
            }
        except Exception:
            page.screenshot(path=str(ROOT / "evidence/phase3-browser-failure.png"), full_page=True)
            raise
        finally:
            browser.close()


def main():
    (ROOT / "evidence").mkdir(exist_ok=True)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 8029))
    with tempfile.TemporaryDirectory(prefix="liubai-phase3-browser-") as name:
        directory = Path(name)
        environment = {
            **os.environ,
            "TASKFLOW_DB": str(directory / "qa.sqlite3"),
            "TASKFLOW_STATE_DIR": str(directory / ".local"),
            "DEEPSEEK_API_KEY": "",
            "DEEPSEEK_MODEL": "",
        }
        python = str(ROOT / ".venv/bin/python")
        subprocess.run(
            [python, "manage.py", "migrate", "--noinput"],
            cwd=ROOT,
            env=environment,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        with (ROOT / "evidence/phase3-browser-server.log").open("w") as log:
            server = subprocess.Popen(
                [python, __file__, "--server", name],
                cwd=ROOT,
                env=environment,
                stdout=log,
                stderr=log,
            )
            try:
                wait_server(server)
                result = run_browser()
                (ROOT / "evidence/phase3-browser.json").write_text(
                    json.dumps(result, ensure_ascii=False, indent=2) + "\n"
                )
                print(json.dumps(result, ensure_ascii=False))
            finally:
                server.terminate()
                server.wait(timeout=10)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--server":
        serve(sys.argv[2])
    else:
        main()
