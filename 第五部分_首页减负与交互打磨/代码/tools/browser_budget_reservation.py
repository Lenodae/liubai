"""Budget reservation acceptance in a browser with disposable accounts and state.

Port 8030 is independent of the installed app. No AI worker or real account,
database, configuration file, or provider key is read.
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
BASE = "http://127.0.0.1:8030"
PASSWORD = "Moss!River84Corner"


def serve(directory):
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from django.core.management import call_command
    from django.test import override_settings

    with override_settings(BASE_DIR=Path(directory)):
        call_command("runserver", "127.0.0.1:8030", use_reloader=False, insecure=True)


def wait_server(server):
    for _ in range(100):
        assert server.poll() is None, "Temporary budget browser server exited"
        try:
            with urllib.request.urlopen(BASE, timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.1)
    raise AssertionError("Temporary budget browser server did not become ready")


def workspace(page, week=None, mode=None):
    return page.evaluate(
        """async ([week, mode]) => api('/api/load/workspace?' + new URLSearchParams({
        week: week || document.querySelector('#load-week').value,
        mode: mode || document.querySelector('#load-mode').value
    }))""",
        [week, mode],
    )


def current_task(data, task_id):
    return next(task for task in data["tasks"] if task["id"] == task_id)


def submit(page, selector, suffix="/api/load/settings"):
    with page.expect_response(
        lambda response: response.url.endswith(suffix) and response.request.method == "POST"
    ) as response:
        page.locator(selector).click()
    result = response.value
    assert result.status in (200, 201), f"{suffix}: {result.status}: {result.text()}"
    return result.json()


def fill_duration(page, field, total):
    hours, minutes = ("", "") if total in (None, "") else map(str, divmod(int(total), 60))
    page.locator(f"#{field}-hours").fill(hours)
    page.locator(f"#{field}-minutes").fill(minutes)


def budget(page, total, buffer):
    expect(page.locator("#load-budget-editor")).to_be_visible()
    fill_duration(page, "load-budget", total)
    fill_duration(page, "load-buffer", buffer)
    result = submit(page, '#load-capacity-form button[type="submit"]')
    expect(page.locator('#load-capacity-form button[type="submit"]')).to_be_enabled()
    return result


def create(page, title, hours, schedule="weekly", week=None, status="planned"):
    page.locator("#new-task").click()
    expect(page.locator("#task-dialog")).to_be_visible()
    page.locator("#task-title").fill(title)
    page.locator("#task-more-settings > summary").click()
    page.locator("#task-hours").fill(hours)
    page.locator("#task-budget-schedule").select_option(schedule)
    page.locator("#task-status").select_option(status)
    if week:
        page.locator("#task-budget-week").fill(week)
        page.locator("#task-title").click()  # Commit the date's change / Monday normalization.
    result = submit(page, "#save-task", "/api/tasks")
    expect(page.locator("#task-dialog")).not_to_be_visible()
    expect(page.locator("#budget-reservation-dialog")).to_be_visible()
    expect(page.locator("#budget-reservation-result .budget-chart")).to_be_visible()
    return result["task"]


def close_result(page):
    page.locator("#budget-reservation-done").click()
    expect(page.locator("#budget-reservation-dialog")).not_to_be_visible()
    expect(page.locator("#new-task")).to_be_enabled()


def set_scope(page, week, mode="week"):
    page.evaluate(
        "([week, mode]) => { location.hash = '#overview?' + new URLSearchParams({week, mode}); }",
        [week, mode],
    )
    expect(page.locator("#load-week")).to_have_value(week)
    expect(page.locator("#load-mode")).to_have_value(mode)
    expect(page.locator("#load-summary .budget-chart")).to_be_visible()


def check_layout(page, dialog=False):
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    if dialog:
        assert page.locator("#budget-reservation-dialog").evaluate(
            "element => element.scrollWidth <= element.clientWidth"
        )
    assert "NaN" not in page.locator("#load-summary").inner_text()
    assert "Infinity" not in page.locator("#load-summary").inner_text()


def register(page, username):
    page.locator("#register-tab").click()
    page.locator("#username").fill(username)
    page.locator("#password").fill(PASSWORD)
    page.locator("#auth-submit").click()
    expect(page.locator("#workspace")).to_be_visible()
    expect(page.locator("#load-summary .budget-chart")).to_be_visible()


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
            register(page, "budget_qa")
            expect(page.locator("#load-mode")).to_have_value("week")
            week = page.locator("#load-week").input_value()
            next_week = (dt.date.fromisoformat(week) + dt.timedelta(days=7)).isoformat()
            later_week = (dt.date.fromisoformat(week) + dt.timedelta(days=14)).isoformat()
            original = budget(page, 600, 120)
            assert original["analysis"]["capacity"] == 480

            # Ideas are recorded without consuming capacity; starting opts into the budget.
            weekly = create(page, "本周：整理实验笔记", "4")
            assert weekly["status"] == "planned"
            assert weekly["budget_schedule"] == "weekly"
            assert weekly["budget_week"] == week
            reserved = workspace(page)
            assert reserved["analysis"]["low"] == reserved["analysis"]["high"] == 0
            assert reserved["analysis"]["available_low"] == 480
            assert current_task(reserved, weekly["id"])["allocation_source"] == "none"
            expect(page.locator("#budget-reservation-result")).to_contain_text("8 小时")
            expect(page.locator("#budget-reservation-result .budget-chart")).to_have_attribute(
                "data-demand-low", "0"
            )
            expect(page.locator("#budget-reservation-task")).to_contain_text("4 小时")
            expect(page.locator("#budget-reservation-task")).to_contain_text("尚未开始，不占用预算")
            page.screenshot(path=str(ROOT / "evidence/budget-week-created.png"), full_page=True)
            close_result(page)
            page.evaluate("id => window.LoadWorkspace.openTask(id)", weekly["id"])
            expect(page.locator("#task-dialog")).to_be_visible()
            page.get_by_role("button", name="开始投入", exact=True).click()
            expect(page.locator("#task-dialog")).not_to_be_visible()
            expect(page.locator("#load-summary .budget-chart")).to_have_attribute(
                "data-demand-low", "240"
            )
            assert workspace(page)["analysis"]["low"] == 240
            expect(page.locator("#load-summary .budget-chart")).to_have_attribute(
                "data-budget-verdict", "fits"
            )

            # A recurring task reserves every week from its start week.
            recurring = create(
                page, "长期：每周练习机器学习", "3", "recurring", status="in_progress"
            )
            reserved = workspace(page)
            assert reserved["analysis"]["low"] == 420
            assert reserved["analysis"]["available_low"] == 60
            expect(page.locator("#budget-reservation-task")).to_contain_text("每周计入 3 小时")
            page.screenshot(
                path=str(ROOT / "evidence/budget-recurring-created.png"), full_page=True
            )
            close_result(page)
            future = workspace(page, next_week, "week")
            assert future["analysis"]["known_low"] == 180
            assert current_task(future, weekly["id"])["allocation_source"] == "none"
            assert current_task(future, recurring["id"])["reservation_minutes"] == 180
            assert future["window"]["budget_minutes"] is None
            set_scope(page, next_week)
            future = budget(page, 600, 120)
            assert future["analysis"]["available_low"] == 300
            set_scope(page, week)

            # Completing a recurring task frees current and future automatic commitment.
            page.evaluate("id => window.LoadWorkspace.openTask(id, 'steps')", recurring["id"])
            expect(page.locator("#execution-dialog")).to_be_visible()
            page.locator("#ex-complete-note").fill("本轮学习完成")
            with page.expect_response(
                lambda response: (
                    response.url.endswith("/workspace") and response.request.method == "POST"
                )
            ) as completed:
                page.locator("#ex-complete-submit").click()
            assert completed.value.status == 200, completed.value.text()
            expect(page.locator("#ex-notice")).to_have_text("已保存。")
            assert workspace(page)["analysis"]["low"] == 240
            assert workspace(page, next_week, "week")["analysis"]["low"] == 0
            page.get_by_role("button", name="撤销整个任务完成", exact=True).click()
            expect(page.locator("#ex-notice")).to_have_text("已保存。")
            expect(
                page.get_by_role("button", name="撤销整个任务完成", exact=True)
            ).not_to_be_visible()
            assert workspace(page)["analysis"]["low"] == 420
            assert workspace(page, next_week, "week")["analysis"]["low"] == 180

            # Actual ledger time does not subtract again from capacity or reservation.
            page.locator('[data-ex-tab="time"]').click()
            page.locator("#ex-time-minutes").fill("30")
            page.get_by_role("button", name="保存耗时记录", exact=True).click()
            expect(page.locator("#ex-summary")).to_contain_text("30 分钟")
            page.locator("#ex-close").click()
            actual = workspace(page)
            assert actual["actual"]["minutes"] == 30
            assert actual["analysis"]["capacity"] == 480
            assert actual["analysis"]["low"] == 420

            # An explicit window plan overrides only that window's automatic amount.
            page.locator('[data-route="load"]').click()
            expect(page).to_have_url(re.compile(r"#load\?"))
            row = page.locator(f'[data-load-task="{recurring["id"]}"]')
            expect(row).to_contain_text("进行中整周投入")
            expect(row).not_to_contain_text("旧的每周推进参考")
            row.get_by_role("button", name="确认 / 修改投入").click()
            for field, amount in {
                "progress-low": "120",
                "progress-high": "120",
                "maintenance-low": "0",
                "maintenance-high": "0",
            }.items():
                page.locator(f"#load-{field}").fill(amount)
            page.locator("#load-scope-confirmed").check()
            manual = submit(page, '#load-plan-form button[type="submit"]')
            expect(page.locator("#load-plan-dialog")).not_to_be_visible()
            assert manual["analysis"]["low"] == 360
            assert current_task(manual, recurring["id"])["allocation_source"] == "manual"
            assert workspace(page, next_week, "week")["analysis"]["low"] == 180

            # Remaining mode stays independent, including its budget and task confirmation.
            set_scope(page, week, "remaining")
            remaining = workspace(page)
            assert remaining["window"]["budget_minutes"] is None
            assert current_task(remaining, recurring["id"])["progress_low"] is None
            assert current_task(remaining, recurring["id"])["allocation_source"] == "none"
            assert remaining["analysis"]["verdict"] == "unknown"
            expect(page.locator("#load-summary")).to_contain_text("整周投入请切到")
            budget(page, 60, 0)
            set_scope(page, week)
            assert workspace(page)["window"]["budget_minutes"] == 600
            assert workspace(page)["analysis"]["low"] == 360
            page.reload()
            expect(page.locator("#load-mode")).to_have_value("week")
            expect(page.locator("#load-summary .budget-chart")).to_contain_text("2 小时")
            assert workspace(page)["analysis"]["low"] == 360
            page.screenshot(path=str(ROOT / "evidence/budget-overview-desktop.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            check_layout(page)
            page.screenshot(path=str(ROOT / "evidence/budget-overview-mobile.png"), full_page=True)

            # Blank time is unknown and an unconfigured week cannot display false free time.
            unknown = create(page, "未来：还没有估时", "", week=later_week, status="in_progress")
            assert unknown["weekly_minutes"] is None
            expect(page.locator("#budget-reservation-result .budget-chart")).to_have_attribute(
                "data-budget-verdict", "unknown"
            )
            expect(page.locator("#budget-reservation-result")).to_contain_text("待设置 / 确认")
            assert workspace(page, later_week, "week")["analysis"]["available_low"] is None
            check_layout(page, dialog=True)
            page.screenshot(path=str(ROOT / "evidence/budget-unknown-mobile.png"), full_page=True)
            close_result(page)

            # New scheduling fields are restored only for the account that wrote the draft.
            page.locator("#new-task").click()
            page.locator("#task-title").fill("本账号的长期安排草稿")
            page.locator("#task-more-settings > summary").click()
            page.locator("#task-budget-schedule").select_option("recurring")
            page.locator("#task-budget-week").fill(next_week)
            page.locator("#task-hours").fill("2")
            token = next(c["value"] for c in context.cookies() if c["name"] == "taskflow5_csrf")
            assert (
                context.request.post(
                    BASE + "/api/auth/logout", headers={"X-CSRFToken": token}
                ).status
                == 200
            )
            page.locator("#save-task").click()
            expect(page.locator("#auth-screen")).to_be_visible()
            page.locator("#username").fill("budget_qa")
            page.locator("#password").fill(PASSWORD)
            page.locator("#auth-submit").click()
            expect(page.locator("#draft-recovery")).to_be_visible()
            page.locator("#restore-draft").click()
            expect(page.locator("#task-title")).to_have_value("本账号的长期安排草稿")
            expect(page.locator("#task-budget-schedule")).to_have_value("recurring")
            expect(page.locator("#task-budget-week")).to_have_value(next_week)
            page.locator("#cancel-editor").click()
            page.locator("#logout").click()
            expect(page.locator("#auth-screen")).to_be_visible()
            register(page, "budget_other")
            assert "本账号的长期安排草稿" not in page.content()
            assert "本周：整理实验笔记" not in page.content()

            # Explicit zero differs from unknown; an overfull circle never repeats a lap.
            budget(page, 0, 0)
            zero = create(page, "明确零预算任务", "0", status="in_progress")
            assert current_task(workspace(page), zero["id"])["reservation_minutes"] == 0
            expect(page.locator("#budget-reservation-result .budget-chart")).to_have_attribute(
                "data-budget-verdict", "fits"
            )
            expect(page.locator("#budget-reservation-result")).to_contain_text("0 分钟")
            close_result(page)
            budget(page, 60, 0)
            excessive = create(page, "超预算任务", "2", status="in_progress")
            data = workspace(page)
            assert data["analysis"]["available_low"] == -60
            expect(page.locator("#budget-reservation-result .budget-chart")).to_have_attribute(
                "data-budget-verdict", "conflict"
            )
            expect(page.locator("#budget-reservation-result")).to_contain_text("缺 1 小时")
            assert page.locator("#budget-reservation-result .budget-ring-task").evaluate(
                "circle => { const [drawn, circumference] = circle.getAttribute('stroke-dasharray').split(' ').map(Number); return Number.isFinite(drawn) && drawn <= circumference; }"
            )
            check_layout(page, dialog=True)
            page.screenshot(path=str(ROOT / "evidence/budget-conflict-mobile.png"), full_page=True)
            close_result(page)
            assert current_task(data, excessive["id"])["status"] == "in_progress"

            # A dedicated synthetic account supplies readable examples for the user's PDF.
            page.locator("#logout").click()
            expect(page.locator("#auth-screen")).to_be_visible()
            page.set_viewport_size({"width": 1280, "height": 980})
            register(page, "pdf_demo")
            budget(page, 600, 60)
            create(page, "本周任务：整理学习笔记", "2", status="in_progress")
            close_result(page)
            create(page, "长期任务：每周练习机器学习", "3", "recurring", status="in_progress")
            sample = workspace(page)
            assert sample["analysis"]["low"] == sample["analysis"]["high"] == 300
            assert sample["analysis"]["capacity"] == 540
            assert sample["analysis"]["available_low"] == 240
            screenshots = ROOT / "evidence/active-reservation-demo"
            screenshots.mkdir(parents=True, exist_ok=True)
            page.locator("#budget-reservation-dialog").screenshot(
                path=str(screenshots / "添加长期任务后的预算反馈.png")
            )
            close_result(page)
            expect(page.locator("#load-summary .budget-chart")).to_contain_text("4 小时")
            page.locator("#load-root").screenshot(
                path=str(screenshots / "预算总览_自动预留300分钟.png")
            )
            assert not errors, errors
            assert not external, external
            return {
                "idea_does_not_reserve_until_started": "pass",
                "recurring_reserves_future_weeks": "pass",
                "complete_and_undo_release_restore_future_commitment": "pass",
                "manual_plan_overrides_one_window": "pass",
                "actual_and_remaining_are_independent": "pass",
                "create_budget_feedback_and_reload": "pass",
                "unknown_zero_conflict_graphs": "pass",
                "account_specific_schedule_drafts": "pass",
                "390px_layout": "pass",
                "page_errors": errors,
                "external_requests": external,
                "real_database_or_secret_contents_read": False,
            }
        except Exception:
            page.screenshot(path=str(ROOT / "evidence/budget-browser-failure.png"), full_page=True)
            raise
        finally:
            browser.close()


def main():
    (ROOT / "evidence").mkdir(exist_ok=True)
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", 8030))
    with tempfile.TemporaryDirectory(prefix="liubai-budget-browser-") as name:
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
        with (ROOT / "evidence/budget-browser-server.log").open("w") as log:
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
                (ROOT / "evidence/budget-browser.json").write_text(
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
