"""Daily footprints acceptance: disposable SQLite, server clock, localhost:8035.

No installed account/database/key or paid provider is accessed. The test server's
clock is isolated in its child process; the host clock is never changed.
"""

import datetime as dt
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
BASE = "http://127.0.0.1:8035"
TODAY = "2026-10-15"
PASSWORD = "Moss!River84Corner"


def serve(directory):
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from unittest.mock import patch

    from django.conf import settings
    from django.core.management import call_command
    from django.test import override_settings

    def isolated_now():
        return dt.datetime.fromisoformat((Path(directory) / "clock.txt").read_text().strip())

    overrides = {"BASE_DIR": Path(directory)}
    if os.environ.get("FOOTPRINTS_BASELINE") == "1":
        baseline = ROOT.parents[1] / "第三部分_负载建议与分析/代码"
        overrides["TEMPLATES"] = [{**settings.TEMPLATES[0], "DIRS": [baseline / "templates"]}]
        overrides["STATICFILES_DIRS"] = [baseline / "static"]
        overrides["CSRF_COOKIE_NAME"] = "taskflow3_csrf"
        overrides["SESSION_COOKIE_NAME"] = "taskflow3_session"
    with override_settings(**overrides), patch("django.utils.timezone.now", isolated_now):
        call_command("runserver", "127.0.0.1:8035", use_reloader=False, insecure=True)


def wait_server(server):
    for _ in range(100):
        assert server.poll() is None, "Temporary footprints server exited"
        try:
            with urllib.request.urlopen(BASE, timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.1)
    raise AssertionError("Temporary footprints server did not become ready")


def register(page, name):
    page.locator("#register-tab").click()
    page.locator("#username").fill(name)
    page.locator("#password").fill(PASSWORD)
    page.locator("#auth-submit").click()
    expect(page.locator("#workspace")).to_be_visible()
    expect(page.locator("#load-summary .budget-chart")).to_be_visible()


def api(page, path, body=None):
    return page.evaluate(
        """([path, body]) => api(path, body === null ? {} : {
          method:'POST', body, headers:{'Idempotency-Key':crypto.randomUUID()}
        })""",
        [path, body],
    )


def mutation(page, task_id, action, values=None):
    path = f"/api/tasks/{task_id}/workspace"
    current = api(page, path)
    return api(
        page,
        path,
        {"action": action, "version": current["task"]["version"], **(values or {})},
    )


def run_browser(directory, red=False):
    checks, errors, external = {}, [], []
    with sync_playwright() as playwright:
        options = {"headless": True}
        if Path("/Applications/Google Chrome.app").exists():
            options["channel"] = "chrome"
        browser = playwright.chromium.launch(**options)
        context = browser.new_context(
            viewport={"width": 1440, "height": 1050}, timezone_id="Asia/Shanghai"
        )

        def local_only(route):
            if route.request.url.startswith(BASE):
                route.continue_()
            else:
                external.append(route.request.url)
                route.abort()

        context.route("**/*", local_only)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.clock.install(time=f"{TODAY}T12:00:00+08:00")
        checkin = page.locator("#footprints-checkin")
        try:
            page.goto(BASE)
            register(page, "footprints_qa")
            if red:
                assert checkin.count() == 0, "RED requires original missing check-in action"
                page.screenshot(path=str(ROOT / "evidence/footprints-red.png"), full_page=True)
                return {"expected_red": "original overview has no daily check-in action"}
            expect(checkin).to_be_visible()
            panel = page.locator("#footprints-panel")
            grid = page.locator("#footprints-grid")
            today_cell = grid.locator(f'button[data-date="{TODAY}"]')
            day_dialog = page.locator("#footprints-day-dialog")
            day_content = page.locator("#footprints-day-content")
            retry = page.locator("#footprints-retry")

            def close_day():
                page.locator("#footprints-day-close").click()
                expect(day_dialog).not_to_be_visible()

            def current_day():
                return api(page, f"/api/footprints/day?date={TODAY}")

            def mark(locator, expected=200):
                with page.expect_response(
                    lambda response: (
                        response.url.endswith("/api/footprints/mark")
                        and response.request.method == "POST"
                    )
                ) as response:
                    locator.click()
                assert response.value.status == expected, response.value.text()
                return response.value.json()

            def wait_day(minutes, steps=0, tasks=0):
                expect(today_cell).to_have_attribute("data-minutes", str(minutes))
                expect(today_cell).to_have_attribute("data-completed-steps", str(steps))
                expect(today_cell).to_have_attribute("data-completed-tasks", str(tasks))

            expect(panel).to_be_visible()
            expect(grid.locator("button[data-date]")).to_have_count(84)
            assert page.locator("#daily-encouragement #footprints-checkin").count() == 1
            assert page.evaluate("""() => {
                const chart=document.querySelector('#load-summary');
                const panel=document.querySelector('#footprints-panel');
                const tasks=document.querySelector('#load-overview');
                return Boolean(chart.compareDocumentPosition(panel)&4)
                    && Boolean(panel.compareDocumentPosition(tasks)&4);
            }""")
            expect(grid.locator('button[data-date="2026-10-16"]')).to_be_disabled()
            expect(checkin).to_be_enabled()
            before_budget = api(page, "/api/load/workspace?week=2026-10-12&mode=week")
            first = mark(checkin)
            assert first["day"]["mark"] == "checkin"
            expect(checkin).to_be_disabled()
            expect(checkin).to_contain_text("已签到")
            expect(today_cell).to_have_attribute("data-mark", "checkin")
            assert (
                api(page, "/api/load/workspace?week=2026-10-12&mode=week")["fingerprint"]
                == (before_budget["fingerprint"])
            )
            expect(page.locator("#encouragement-toast")).not_to_be_visible()
            page.reload()
            expect(checkin).to_be_disabled()
            expect(checkin).to_contain_text("已签到")
            assert current_day()["day"]["version"] == first["day"]["version"]
            checks["overview_position_84_days_future_disabled_checkin_persists_no_budget_write"] = (
                "pass"
            )

            page.locator("#footprints-today-detail").click()
            expect(day_dialog).to_be_visible()
            mark(page.locator("#footprints-day-rest"))
            expect(today_cell).to_have_attribute("data-mark", "rest")
            assert current_day()["day"]["mark"] == "rest"
            mark(page.locator("#footprints-day-clear"))
            assert current_day()["day"]["mark"] is None
            expect(checkin).to_be_enabled()
            close_day()
            checks["today_checkin_rest_clear_are_mutually_exclusive_and_do_not_complete_tasks"] = (
                "pass"
            )

            page.locator("#load-week").fill("2026-10-05")
            page.locator("#load-week").dispatch_event("change")
            expect(page.locator("#load-week")).to_have_value("2026-10-05")
            result = mark(checkin)
            assert result["day"]["date"] == TODAY
            page.locator("#load-week").fill("2026-10-12")
            page.locator("#load-week").dispatch_event("change")
            checks["budget_week_change_does_not_change_server_checkin_day"] = "pass"

            # Public execution API seeds an independent parent+child ledger. A real
            # completion/undo UI action must refresh footprints without a page reload.
            title = '<img src=x onerror="window.footprintsInjected=true"> 的学习足迹'
            task = api(
                page,
                "/api/tasks",
                {"title": title, "status": "in_progress", "weekly_minutes": 600},
            )["task"]
            task_id = task["id"]
            mutation(page, task_id, "profile", {"criterion": "留下可运行的小例子"})
            draft = mutation(
                page,
                task_id,
                "draft",
                {
                    "nodes": [
                        {
                            "title": "先写一段示例",
                            "criterion": "运行成功",
                            "low": 60,
                            "high": 90,
                            "depends": [],
                        }
                    ]
                },
            )["drafts"][0]
            step = mutation(
                page,
                task_id,
                "apply",
                {"draft_id": draft["id"], "revision": draft["revision"], "selected": [0]},
            )["steps"][0]
            for step_id, minutes, note in [
                (None, 30, "任务额外的准备"),
                (step["id"], 45, "子步骤真实投入"),
            ]:
                mutation(
                    page,
                    task_id,
                    "time_add",
                    {"step_id": step_id, "minutes": minutes, "date": TODAY, "note": note},
                )
            page.evaluate("async () => await loadTasks()")
            wait_day(75)
            today_cell.click()
            expect(day_content).to_contain_text("1 小时 15 分钟")
            expect(day_content).to_contain_text(title)
            assert not day_content.locator("img").count()
            assert not page.evaluate("Boolean(window.footprintsInjected)")
            close_day()
            page.locator(f'.task-card[data-task-id="{task_id}"]').click()
            page.get_by_role("button", name="分析与执行 ↗", exact=True).click()
            page.locator('[data-ex-tab="steps"]').click()
            step_row = page.locator(f'.ex-step[data-step-id="{step["id"]}"]')
            step_row.get_by_role("button", name="登记完成", exact=True).click()
            page.locator("#ex-complete-note").fill("今天终于让这个小例子运行了")
            page.get_by_role("button", name="确认完成", exact=True).click()
            wait_day(75, 1)
            if page.locator("#encouragement-close").is_visible():
                page.locator("#encouragement-close").click()
            page.on("dialog", lambda dialog: dialog.accept())
            step_row.get_by_role("button", name="撤销完成", exact=True).click()
            wait_day(75)
            page.locator('[data-ex-tab="time"]').click()
            parent_entry = page.locator(".ex-entry").filter(has_text="任务额外的准备")
            parent_entry.get_by_role("button", name="修改", exact=True).click()
            page.locator("#ex-time-minutes").fill("20")
            page.get_by_role("button", name="保存耗时记录", exact=True).click()
            wait_day(65)
            page.locator(".ex-entry").filter(has_text="子步骤真实投入").get_by_role(
                "button", name="删除", exact=True
            ).click()
            wait_day(20)
            page.locator("#ex-close").click()
            expect(page.locator("#execution-dialog")).not_to_be_visible()
            checks["parent_child_30_plus_45_only_once_real_completion_undo_edit_void_refresh"] = (
                "pass"
            )

            page.locator(f'button[data-delete-task="{task_id}"]').click()
            expect(page.locator(f'.task-row[data-task-row="{task_id}"]')).to_have_count(0)
            wait_day(20)
            today_cell.click()
            expect(day_content).to_contain_text("20 分钟")
            expect(day_content).to_contain_text(title)
            assert current_day()["entries"][0]["deleted"] is True
            day_content.get_by_role("button", name="前往回收站", exact=False).first.click()
            expect(page.locator("#workspace")).to_have_attribute("data-page", "tasks/trash")
            expect(panel).not_to_be_visible()
            expect(checkin).not_to_be_visible()
            page.locator('[data-route="overview"]').click()
            expect(panel).to_be_visible()
            checks["deleted_task_actual_fact_survives_link_routes_to_trash_overview_only"] = "pass"

            page.locator("#footprints-year-open").click()
            expect(page.locator("#footprints-year-dialog")).to_be_visible()
            expect(page.locator("#footprints-year-grid button[data-date]")).to_have_count(365)
            page.locator("#footprints-year-select").select_option("2024")
            expect(page.locator("#footprints-year-grid button[data-date]")).to_have_count(366)
            leap_day = page.locator('#footprints-year-grid button[data-date="2024-02-29"]')
            leap_day.focus()
            leap_day.press("Enter")
            expect(day_dialog).to_be_visible()
            expect(page.locator("#footprints-day-checkin")).not_to_be_visible()
            close_day()
            page.locator("#footprints-year-close").click()
            today_cell.focus()
            today_cell.press("ArrowLeft")
            assert page.evaluate("document.activeElement.dataset.date") != TODAY
            page.keyboard.press("Enter")
            expect(day_dialog).to_be_visible()
            close_day()
            checks["annual_365_leap_366_past_readonly_and_keyboard_selection"] = "pass"

            page.screenshot(path=str(ROOT / "evidence/footprints-desktop.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            expect(panel).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=str(ROOT / "evidence/footprints-mobile.png"), full_page=True)
            page.locator("#footprints-year-open").click()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=str(ROOT / "evidence/footprints-year-mobile.png"), full_page=True)
            page.locator("#footprints-year-close").click()
            page.set_viewport_size({"width": 1440, "height": 1050})
            checks["390px_page_does_not_overflow_recent_or_annual_calendar"] = "pass"

            # A pre-commit failure and a post-commit lost response must keep the exact
            # same request key/body. A retry may acknowledge, never double-write.
            page.locator("#footprints-today-detail").click()
            mark(page.locator("#footprints-day-clear"))
            close_day()
            packets = []

            def unavailable(route):
                packets.append((route.request.post_data, route.request.headers["idempotency-key"]))
                route.fulfill(status=503, json={"error": "临时不可用"})

            page.route("**/api/footprints/mark", unavailable)
            mark(checkin, 503)
            expect(retry).to_be_visible()
            assert current_day()["day"]["mark"] is None
            page.unroute("**/api/footprints/mark", unavailable)

            def capture_and_continue(route):
                packets.append((route.request.post_data, route.request.headers["idempotency-key"]))
                route.continue_()

            page.route("**/api/footprints/mark", capture_and_continue)
            mark(retry)
            expect(checkin).to_contain_text("已签到")
            expect(retry).not_to_be_visible()
            assert len(packets) == 2 and packets[0] == packets[1]
            page.unroute("**/api/footprints/mark", capture_and_continue)
            page.locator("#footprints-today-detail").click()
            mark(page.locator("#footprints-day-clear"))
            close_day()
            before_version = current_day()["day"]["version"]
            packets.clear()

            def committed_but_lost(route):
                packets.append((route.request.post_data, route.request.headers["idempotency-key"]))
                response = route.fetch()
                assert response.status == 200, response.text()
                route.abort("failed")

            page.route("**/api/footprints/mark", committed_but_lost)
            checkin.click()
            expect(retry).to_be_visible()
            assert current_day()["day"]["version"] == before_version + 1
            page.unroute("**/api/footprints/mark", committed_but_lost)
            page.route("**/api/footprints/mark", capture_and_continue)
            mark(retry)
            expect(retry).not_to_be_visible()
            assert len(packets) == 2 and packets[0] == packets[1]
            assert current_day()["day"]["version"] == before_version + 1
            page.unroute("**/api/footprints/mark", capture_and_continue)
            checks["failed_and_committed_lost_responses_retry_same_packet_once"] = "pass"

            # Another page writes first. This page must expose the version conflict,
            # retain current state, and allow a canonical reload without overwriting.
            page.locator("#footprints-today-detail").click()
            actual = current_day()["day"]
            api(
                page,
                "/api/footprints/mark",
                {"date": TODAY, "kind": "rest", "version": actual["version"]},
            )
            mark(page.locator("#footprints-day-clear"), 409)
            expect(page.locator("#footprints-day-reload")).to_be_visible()
            assert current_day()["day"]["mark"] == "rest"
            page.locator("#footprints-day-reload").click()
            expect(today_cell).to_have_attribute("data-mark", "rest")
            close_day()
            checks["stale_tab_write_conflict_does_not_overwrite_current_mark"] = "pass"

            # A server day, not the selected budget week or browser's old cached
            # date, determines the new mark after the tab wakes across midnight.
            (directory / "clock.txt").write_text("2026-10-16T00:00:01+08:00")
            page.clock.set_system_time("2026-10-16T00:00:01+08:00")
            page.evaluate("window.dispatchEvent(new Event('focus'))")
            expect(checkin).to_have_attribute("data-date", "2026-10-16")
            expect(checkin).to_be_enabled()
            next_mark = mark(checkin)
            assert next_mark["day"]["date"] == "2026-10-16"
            assert current_day()["day"]["mark"] == "rest"
            checks["server_midnight_focus_refresh_new_day_without_changing_yesterday"] = "pass"

            # Hold an already-produced old-account response, then switch accounts.
            # Releasing it must neither render the old grid nor open old details.
            held = []
            hold_started = []

            def hold_old_calendar(route):
                if hold_started:
                    route.continue_()
                    return
                hold_started.append(True)
                held.append((route, route.fetch()))

            page.route("**/api/footprints/calendar?view=recent", hold_old_calendar)
            with page.expect_request("**/api/footprints/calendar?view=recent"):
                page.evaluate("void Footprints.refresh()")
            deadline = time.monotonic() + 10
            while not held and time.monotonic() < deadline:
                page.wait_for_timeout(50)
            assert len(held) == 1
            page.locator("#logout").click()
            expect(page.locator("#auth-screen")).to_be_visible()
            expect(day_dialog).not_to_be_visible()
            expect(panel).not_to_be_visible()
            register(page, "footprints_other")
            expect(checkin).to_be_enabled()
            expect(grid.locator('button[data-date="2026-10-16"]')).to_have_attribute(
                "data-mark", ""
            )
            held[0][0].fulfill(response=held[0][1])
            page.unroute("**/api/footprints/calendar?view=recent", hold_old_calendar)
            expect(grid.locator('button[data-date="2026-10-16"]')).to_have_attribute(
                "data-mark", ""
            )
            assert api(page, "/api/footprints/calendar?view=recent")["summary"] == {
                "checkin_days": 0,
                "rest_days": 0,
                "active_days": 0,
            }
            assert not page.evaluate("document.body.textContent.includes('子步骤真实投入')")
            checks["logout_clears_private_ui_old_response_cannot_enter_new_account"] = "pass"

            def fail_calendar(route):
                route.abort("failed")

            page.route("**/api/footprints/calendar*", fail_calendar)
            page.reload()
            expect(page.locator("#footprints-reload")).to_be_visible()
            expect(page.locator("#load-summary .budget-chart")).to_be_visible()
            for field, value in [
                ("load-budget-hours", "10"),
                ("load-budget-minutes", "0"),
                ("load-buffer-hours", "1"),
                ("load-buffer-minutes", "0"),
            ]:
                page.locator(f"#{field}").fill(value)
            with page.expect_response("**/api/load/settings") as saved:
                page.locator('#load-capacity-form button[type="submit"]').click()
            assert saved.value.status == 200, saved.value.text()
            assert saved.value.json()["window"]["budget_minutes"] == 600
            page.unroute("**/api/footprints/calendar*", fail_calendar)
            page.locator("#footprints-reload").click()
            expect(checkin).to_be_enabled()
            page.route("**/api/footprints/mark", unavailable)
            mark(checkin, 503)
            expect(retry).to_be_visible()
            page.locator("#logout").click()
            expect(page.locator("#auth-screen")).to_be_visible()
            expect(retry).not_to_be_visible()
            page.unroute("**/api/footprints/mark", unavailable)
            register(page, "footprints_third")
            expect(checkin).to_be_enabled()
            expect(retry).not_to_be_visible()
            assert api(page, "/api/footprints/calendar?view=recent")["today_mark"]["version"] == 0
            checks["calendar_read_failure_preserves_budget_save_pending_write_clears_on_logout"] = (
                "pass"
            )
            assert not errors, errors
            assert not external, external
            return {
                "checks": checks,
                "page_errors": errors,
                "external_requests": external,
                "installed_database_or_secret_contents_read": False,
                "isolated_server_clock": True,
                "browser_timezone": "Asia/Shanghai",
            }
        except Exception:
            (ROOT / "evidence/footprints-browser-partial.json").write_text(
                json.dumps(
                    {"completed_checks": checks, "page_errors": errors},
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n"
            )
            page.screenshot(path=str(ROOT / "evidence/footprints-failure.png"), full_page=True)
            raise
        finally:
            browser.close()


def main():
    red = "--red" in sys.argv
    (ROOT / "evidence").mkdir(exist_ok=True)
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", 8035))
    with tempfile.TemporaryDirectory(prefix="liubai-footprints-") as name:
        directory = Path(name)
        (directory / "clock.txt").write_text(f"{TODAY}T12:00:00+08:00")
        environment = {
            **os.environ,
            "TASKFLOW_DB": str(directory / "qa.sqlite3"),
            "TASKFLOW_STATE_DIR": str(directory / ".local"),
            "DEEPSEEK_API_KEY": "",
            "DEEPSEEK_MODEL": "",
            "FOOTPRINTS_BASELINE": "1" if red else "0",
        }
        python = str(ROOT / ".venv/bin/python")
        subprocess.run(
            [python, "manage.py", "migrate", "--noinput"],
            cwd=ROOT,
            env=environment,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        with (ROOT / "evidence/footprints-server.log").open("w") as log:
            server = subprocess.Popen(
                [python, __file__, "--server", str(directory)],
                cwd=ROOT,
                env=environment,
                stdout=log,
                stderr=log,
            )
            try:
                wait_server(server)
                result = run_browser(directory, red)
                filename = "footprints-browser-red.json" if red else "footprints-browser.json"
                (ROOT / "evidence" / filename).write_text(
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
