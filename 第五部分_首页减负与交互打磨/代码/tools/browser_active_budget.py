"""Active-only budgeting and idea entry in a real browser with disposable state.

Port 8031 is independent of the installed app. No AI worker or real account,
database, configuration file, or provider key is read.
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

# Account creation performs the production password hash; allow for local CPU contention.
expect.set_options(timeout=15000)

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8031"
PASSWORD = "Moss!River84Corner"


def serve(directory):
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from django.core.management import call_command
    from django.test import override_settings

    with override_settings(BASE_DIR=Path(directory)):
        call_command("runserver", "127.0.0.1:8031", use_reloader=False, insecure=True)


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


def expect_duration(page, field, total):
    hours, minutes = ("", "") if total in (None, "") else map(str, divmod(int(total), 60))
    expect(page.locator(f"#{field}-hours")).to_have_value(hours)
    expect(page.locator(f"#{field}-minutes")).to_have_value(minutes)


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

        def overview():
            page.locator('[data-route="overview"]').click()
            expect(page.locator("#load-summary .budget-chart")).to_be_visible()

        def ring(demand, available):
            chart = page.locator("#load-summary .budget-chart")
            expect(chart).to_have_attribute("data-demand-low", str(demand))
            expect(chart).to_have_attribute("data-demand-high", str(demand))
            expect(chart).to_have_attribute("data-available-low", str(available))
            data = workspace(page)
            assert data["analysis"]["low"] == data["analysis"]["high"] == demand
            assert (
                data["analysis"]["available_low"] == data["analysis"]["available_high"] == available
            )
            if demand:
                drawn = chart.locator(".budget-ring-task").get_attribute("stroke-dasharray")
                arc, circumference = map(float, drawn.split())
                assert abs(arc / circumference - min(demand / 600, 0.9)) < 1e-9
            else:
                expect(chart.locator(".budget-ring-task")).to_have_count(0)

        def edit(task_id):
            page.evaluate("id => window.LoadWorkspace.openTask(id)", task_id)
            expect(page.locator("#task-dialog")).to_be_visible()

        def action(task_id, label):
            edit(task_id)
            with page.expect_response(
                lambda r: r.url.endswith(f"/api/tasks/{task_id}") and r.request.method == "PATCH"
            ) as response:
                page.get_by_role("button", name=label, exact=True).click()
            assert response.value.status == 200, response.value.text()
            expect(page.locator("#task-dialog")).not_to_be_visible()
            return response.value.json()["task"]

        def edit_hours(task_id, hours):
            edit(task_id)
            page.locator("#task-hours").fill(hours)
            with page.expect_response(
                lambda r: r.url.endswith(f"/api/tasks/{task_id}") and r.request.method == "PATCH"
            ) as response:
                page.locator("#save-task").click()
            assert response.value.status == 200, response.value.text()
            expect(page.locator("#task-dialog")).not_to_be_visible()

        try:
            page.goto(BASE)
            register(page, "active_budget_qa")
            expect(page.locator("#new-task")).to_contain_text("记录想法")
            expect(page.locator("#task-dialog")).not_to_be_visible()
            budget(page, 600, 60)
            # A name alone is sufficient; timing and scheduling stay optional and folded.
            page.locator("#new-task").click()
            expect(page.locator("#editor-heading")).to_have_text("记录一个想法")
            expect(page.locator("#task-status")).to_have_value("planned")
            assert not page.locator("#task-more-settings").evaluate("el => el.open")
            page.locator("#task-title").fill("先记录：想做一个小实验")
            idea = submit(page, "#save-task", "/api/tasks")["task"]
            expect(page.locator("#budget-reservation-result .budget-chart")).to_be_visible()
            expect(page.locator("#budget-reservation-task")).to_contain_text("尚未开始，不占用预算")
            assert idea["weekly_minutes"] is None
            assert workspace(page)["analysis"]["unknown_count"] == 0
            page.locator("#budget-reservation-ideas").click()
            expect(page.locator("#page-title")).to_contain_text("想法池")
            expect(page.locator(".task-card")).to_have_count(1)
            edit_hours(idea["id"], "3")
            assert workspace(page)["analysis"]["low"] == 0
            action(idea["id"], "开始投入")
            overview()
            ring(180, 360)
            page.screenshot(
                path=str(ROOT / "evidence/active-budget-180-desktop.png"), full_page=True
            )
            blank = create(page, "另一个还不确定的想法", "")
            expect(page.locator("#budget-reservation-task")).to_contain_text(
                "估计时间可等想清楚以后补充"
            )
            assert workspace(page)["analysis"]["low"] == 180
            assert workspace(page)["analysis"]["unknown_count"] == 0
            close_result(page)
            edit_hours(idea["id"], "4")
            ring(240, 300)
            action(idea["id"], "暂停一下")
            ring(0, 540)
            action(idea["id"], "恢复进行")
            ring(240, 300)
            # Actual records persist through completion, while future commitment is released.
            page.evaluate("id => window.LoadWorkspace.openTask(id, 'time')", idea["id"])
            expect(page.locator("#execution-dialog")).to_be_visible()
            page.locator("#ex-time-minutes").fill("30")
            page.get_by_role("button", name="保存耗时记录", exact=True).click()
            expect(page.locator("#ex-summary")).to_contain_text("30 分钟")
            page.locator('[data-ex-tab="steps"]').click()
            page.locator("#ex-complete-note").fill("完成这一轮实验")
            page.locator("#ex-extra").fill("20")
            page.get_by_role("button", name="确认完成", exact=True).click()
            expect(page.locator("#ex-notice")).to_have_text("已保存。")
            assert workspace(page)["actual"]["minutes"] == 50
            assert workspace(page)["analysis"]["low"] == 0
            page.get_by_role("button", name="撤销整个任务完成", exact=True).click()
            expect(page.locator("#ex-notice")).to_have_text("已保存。")
            assert workspace(page)["actual"]["minutes"] == 50
            page.locator("#ex-close").click()
            ring(240, 300)
            # Even an explicit inactive window plan including maintenance cannot consume capacity.
            page.locator('[data-route="load"]').click()
            page.locator(f'[data-load-task="{blank["id"]}"]').get_by_role(
                "button", name="确认 / 修改投入"
            ).click()
            for field, amount in {
                "progress-low": "600",
                "progress-high": "600",
                "maintenance-low": "120",
                "maintenance-high": "120",
            }.items():
                page.locator(f"#load-{field}").fill(amount)
            page.locator("#load-maintenance-active").check()
            page.locator("#load-scope-confirmed").check()
            inactive_manual = submit(page, '#load-plan-form button[type="submit"]')
            expect(page.locator("#load-plan-dialog")).not_to_be_visible()
            assert inactive_manual["analysis"]["low"] == 240
            assert current_task(inactive_manual, blank["id"])["budget_occupies"] is False
            overview()
            ring(240, 300)
            unknown = create(page, "进行中：还需要补估时", "", status="in_progress")
            expect(page.locator("#budget-reservation-result .budget-chart")).to_have_attribute(
                "data-budget-verdict", "unknown"
            )
            unknown_data = workspace(page)
            assert unknown_data["analysis"]["low"] is None
            assert unknown_data["analysis"]["unknown_count"] == 1
            assert unknown_data["analysis"]["available_low"] is None
            close_result(page)
            edit_hours(unknown["id"], "2")
            ring(360, 180)
            zero = create(page, "进行中：明确无需投入", "0", status="in_progress")
            assert current_task(workspace(page), zero["id"])["reservation_minutes"] == 0
            close_result(page)
            ring(360, 180)
            page.reload()
            ring(360, 180)
            page.set_viewport_size({"width": 390, "height": 844})
            check_layout(page)
            page.screenshot(path=str(ROOT / "evidence/active-budget-mobile.png"), full_page=True)
            narrow_idea = create(page, "手机上记录一个想法", "")
            assert current_task(workspace(page), narrow_idea["id"])["budget_occupies"] is False
            check_layout(page, dialog=True)
            page.screenshot(
                path=str(ROOT / "evidence/active-idea-feedback-mobile.png"), full_page=True
            )
            close_result(page)
            # Missing budgets do not turn into a falsely available allowance.
            next_week = (
                dt.date.fromisoformat(page.locator("#load-week").input_value())
                + dt.timedelta(days=7)
            ).isoformat()
            set_scope(page, next_week)
            expect(page.locator("#load-summary .budget-chart")).to_contain_text("待设置 / 确认")
            assert workspace(page)["analysis"]["available_low"] is None

            # Reproduce the user's two running tasks with disposable account data.
            page.locator("#logout").click()
            expect(page.locator("#auth-screen")).to_be_visible()
            page.set_viewport_size({"width": 1440, "height": 1050})
            register(page, "inline_budget_qa")
            rest = create(page, "休息", "70", "recurring", status="in_progress")
            close_result(page)
            python_task = create(page, "学习python", "8", status="in_progress")
            close_result(page)
            chart = page.locator("#load-summary .budget-chart")
            expect(chart).to_have_attribute("data-demand-low", "4680")
            expect(chart).to_have_attribute("data-budget-verdict", "unknown")
            expect(chart.locator(".budget-ring-task")).to_have_count(0)
            expect(chart.locator("#load-budget-hours")).to_be_visible()
            expect(chart.locator("#load-budget-minutes")).to_be_visible()
            expect(chart.locator("#load-buffer-hours")).to_be_visible()
            expect(chart.locator("#load-buffer-minutes")).to_be_visible()
            expect(chart.locator(f'[data-budget-task="{rest["id"]}"]')).to_contain_text("70 小时")
            expect(chart.locator(f'[data-budget-task="{python_task["id"]}"]')).to_contain_text(
                "8 小时"
            )
            ring_box = chart.locator(".budget-chart-ring").bounding_box()
            editor_box = chart.locator("#load-budget-editor").bounding_box()
            assert ring_box and editor_box
            assert editor_box["x"] > ring_box["x"] + ring_box["width"]
            assert editor_box["y"] < ring_box["y"] + ring_box["height"]
            page.screenshot(
                path=str(ROOT / "evidence/inline-budget-unconfirmed-desktop.png"), full_page=True
            )

            # One save updates the same card without hiding its editor.
            budget(page, 6000, 600)
            expect(chart).to_have_attribute("data-available-low", "720")
            expect(chart.locator("#load-budget-hours")).to_be_visible()
            page.reload()
            expect_duration(page, "load-budget", 6000)
            expect(chart).to_have_attribute("data-demand-low", "4680")
            assert chart.locator(".budget-ring-task").evaluate(
                "circle => { const [arc, circumference] = circle.getAttribute('stroke-dasharray').split(' ').map(Number); return Math.abs(arc / circumference - 4680 / 6000) < 1e-9; }"
            )

            # A refresh or a rejected save must retain the budget adjustment draft.
            fill_duration(page, "load-budget", 6200)
            with page.expect_response(lambda r: "/api/load/workspace?" in r.url):
                page.locator("#load-refresh").click()
            expect_duration(page, "load-budget", 6200)
            fill_duration(page, "load-budget", 6000)
            fill_duration(page, "load-buffer", 7000)
            with page.expect_response(
                lambda r: r.url.endswith("/api/load/settings") and r.request.method == "POST"
            ) as rejected:
                page.locator('#load-capacity-form button[type="submit"]').click()
            assert rejected.value.status == 400
            expect(page.locator("#load-problem")).to_be_visible()
            expect_duration(page, "load-budget", 6000)
            expect_duration(page, "load-buffer", 7000)
            expect(chart).to_have_attribute("data-available-low", "720")
            budget(page, 6000, 600)

            # Change a running task directly from the chart and verify the API total.
            page.locator("#overview-budget-sources > summary").click()
            chart.locator(f'[data-budget-task="{python_task["id"]}"] .budget-task-open').click()
            expect(page.locator("#task-dialog")).to_be_visible()
            page.locator("#task-hours").fill("10")
            with page.expect_response(
                lambda r: (
                    r.url.endswith(f"/api/tasks/{python_task['id']}")
                    and r.request.method == "PATCH"
                )
            ) as edited:
                page.locator("#save-task").click()
            assert edited.value.status == 200, edited.value.text()
            expect(page.locator("#task-dialog")).not_to_be_visible()
            expect(chart).to_have_attribute("data-demand-low", "4800")
            assert workspace(page)["analysis"]["available_low"] == 600
            expect(chart).to_have_attribute("data-available-low", "600")
            page.screenshot(
                path=str(ROOT / "evidence/inline-budget-confirmed-desktop.png"), full_page=True
            )
            action(python_task["id"], "暂停一下")
            expect(chart).to_have_attribute("data-demand-low", "4200")
            expect(chart.locator(f'[data-budget-task="{python_task["id"]}"]')).to_have_count(0)
            action(python_task["id"], "恢复进行")
            expect(chart).to_have_attribute("data-demand-low", "4800")
            page.set_viewport_size({"width": 390, "height": 844})
            check_layout(page)
            expect(chart.locator("#load-budget-hours")).to_be_visible()
            budget(page, 5400, 600)
            expect(chart).to_have_attribute("data-available-low", "0")
            # Preserve non-hour values through both controls, the API and a full reload.
            detailed = budget(page, 6015, 605)
            assert detailed["window"]["budget_minutes"] == 6015
            assert detailed["window"]["buffer_minutes"] == 605
            assert detailed["analysis"]["available_low"] == 610
            expect(chart).to_have_attribute("data-available-low", "610")
            expect(chart).to_contain_text("100 小时 15 分钟")
            expect(chart).to_contain_text("10 小时 5 分钟")
            expect(chart.locator(".budget-chart-center")).to_contain_text("10 小时 10 分钟")
            page.reload()
            expect_duration(page, "load-budget", 6015)
            expect_duration(page, "load-buffer", 605)
            expect(chart).to_have_attribute("data-available-low", "610")
            expect(chart.locator(".budget-chart-center")).to_contain_text("10 小时 10 分钟")
            check_layout(page)
            page.screenshot(path=str(ROOT / "evidence/inline-budget-mobile.png"), full_page=True)
            assert not errors, errors
            assert not external, external
            return {
                "default_name_only_idea_and_idea_pool": "pass",
                "planned_with_or_without_time_occupies_zero": "pass",
                "start_edit_pause_resume_bind_minutes_to_circle": "pass",
                "complete_and_undo_preserve_actuals": "pass",
                "inactive_manual_maintenance_excluded": "pass",
                "active_unknown_vs_zero": "pass",
                "refresh_and_390px_layout": "pass",
                "missing_budget_not_false_free_time": "pass",
                "user_example_4680_and_per_task_times": "pass",
                "inline_budget_right_of_circle_one_save_reload": "pass",
                "inline_draft_refresh_and_validation_error": "pass",
                "chart_task_edit_pause_resume": "pass",
                "inline_budget_390px": "pass",
                "hours_minutes_input_display_reload": "pass",
                "page_errors": errors,
                "external_requests": external,
                "real_database_or_secret_contents_read": False,
            }
        except Exception:
            page.screenshot(path=str(ROOT / "evidence/active-browser-failure.png"), full_page=True)
            raise
        finally:
            browser.close()


def main():
    (ROOT / "evidence").mkdir(exist_ok=True)
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", 8031))
    with tempfile.TemporaryDirectory(prefix="liubai-active-browser-") as name:
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
        with (ROOT / "evidence/active-browser-server.log").open("w") as log:
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
                (ROOT / "evidence/active-browser.json").write_text(
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
