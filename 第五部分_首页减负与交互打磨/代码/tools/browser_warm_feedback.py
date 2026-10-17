"""Warm load feedback and completion encouragement, using disposable local state.

The temporary server uses port 8032. No installed database, provider key, or
external service is used. Completion retries exercise the real idempotency API.
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
BASE = "http://127.0.0.1:8032"
PASSWORD = "Moss!River84Corner"


def serve(directory):
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from django.core.management import call_command
    from django.test import override_settings

    with override_settings(BASE_DIR=Path(directory)):
        call_command("runserver", "127.0.0.1:8032", use_reloader=False, insecure=True)


def wait_server(server):
    for _ in range(100):
        assert server.poll() is None, "Temporary feedback server exited"
        try:
            with urllib.request.urlopen(BASE, timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.1)
    raise AssertionError("Temporary feedback server did not become ready")


def api(page, path, body=None, method="POST"):
    return page.evaluate(
        """([path, body, method]) => api(path, body === null ? {} : {
          method, body, headers: {'Idempotency-Key': crypto.randomUUID()}
        })""",
        [path, body, method],
    )


def mutation(page, task_id, action, values=None):
    path = f"/api/tasks/{task_id}/workspace"
    current = api(page, path)
    return api(
        page, path, {"action": action, "version": current["task"]["version"], **(values or {})}
    )


def register(page, name):
    page.locator("#register-tab").click()
    page.locator("#username").fill(name)
    page.locator("#password").fill(PASSWORD)
    page.locator("#auth-submit").click()
    expect(page.locator("#workspace")).to_be_visible()
    expect(page.locator("#load-summary .budget-chart")).to_be_visible()


def check_feeling_boundaries(page):
    cases = [
        (0, "light"),
        (59, "light"),
        (59.99, "light"),
        (60, "balanced"),
        (70, "balanced"),
        (79.99, "balanced"),
        (80, "challenge"),
        (89.99, "challenge"),
        (90, "high"),
        (99.99, "high"),
        (100, "full"),
        (100.01, "overload"),
        (101, "overload"),
    ]
    for demand, level in cases:
        result = page.evaluate(
            "demand => LoadFeeling.describe({capacity:100,low:demand,high:demand,verdict:'fits'})",
            demand,
        )
        assert result["level"] == level, (demand, result)
    variants = page.evaluate(
        """() => {
          const base = {capacity:100,low:60,high:85,verdict:'conditional'};
          return {
            range:LoadFeeling.describe(base),
            unknown:LoadFeeling.describe({...base,unknown_count:1}),
            missing:LoadFeeling.describe({...base,capacity:null}),
            stale:LoadFeeling.describe(base,{stale:true}),
            unconfirmed:LoadFeeling.describe(base,{confirmed:false}),
            zero:LoadFeeling.describe({...base,capacity:0,low:0,high:0}),
            zeroDemand:LoadFeeling.describe({...base,capacity:0,low:1,high:1}),
            knownGap:LoadFeeling.describe({...base,unknown_count:1,deficit_low:15})
          };
        }"""
    )
    assert variants["range"]["level"] == "challenge"
    assert variants["range"]["percent"] == "85%"
    assert variants["range"]["rangeText"] == "60%–85%"
    for key in ["unknown", "missing", "stale", "unconfirmed", "knownGap"]:
        assert variants[key]["level"] == "unknown", (key, variants[key])
        assert variants[key]["percent"] is None
    assert variants["zero"]["level"] == "zero"
    assert variants["zeroDemand"]["level"] == "overload"
    assert variants["zero"]["percent"] is variants["zeroDemand"]["percent"] is None
    assert "Infinity" not in json.dumps(variants)
    assert "NaN" not in json.dumps(variants)


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
        toast = page.locator("#encouragement-toast")
        chart = page.locator("#load-summary .budget-chart")
        path = None

        def count():
            return int(toast.get_attribute("data-show-count") or 0)

        def complete(step_id=None):
            if step_id:
                page.locator(f'.ex-step[data-step-id="{step_id}"]').get_by_role(
                    "button", name="登记完成", exact=True
                ).click()
            else:
                page.locator("#ex-complete-target").select_option("")
            page.locator("#ex-complete-note").fill("已核对这个小成果")
            with page.expect_response(
                lambda r: r.url.endswith(path) and r.request.method == "POST"
            ) as response:
                page.locator("#ex-complete-submit").click()
            assert response.value.status == 200, response.value.text()
            expect(page.locator("#ex-complete-submit")).to_be_enabled()
            return response.value.json()

        def visible_toast(title, progress=None):
            expect(toast).to_be_visible()
            expect(page.locator("#encouragement-title")).not_to_be_empty()
            expect(page.locator("#encouragement-detail")).to_contain_text(title)
            if progress:
                expect(page.locator("#encouragement-progress")).to_contain_text(progress)
            assert not page.evaluate(
                "document.querySelector('#encouragement-toast').contains(document.activeElement)"
            ), "A completion toast must not steal keyboard focus"
            rectangle = toast.bounding_box()
            assert rectangle and 0 <= rectangle["y"] < page.viewport_size["height"] / 2

        try:
            page.goto(BASE)
            register(page, "warm_feedback_qa")
            expect(page.locator("#encouragement-toggle")).to_have_attribute("aria-pressed", "true")
            check_feeling_boundaries(page)
            # 10h total minus 1h buffer = 9h capacity; 6h18m demand is exactly 70%.
            page.locator("#load-budget-hours").fill("10")
            page.locator("#load-budget-minutes").fill("0")
            page.locator("#load-buffer-hours").fill("1")
            page.locator("#load-buffer-minutes").fill("0")
            with page.expect_response("**/api/load/settings") as saved:
                page.locator('#load-capacity-form button[type="submit"]').click()
            assert saved.value.status == 200
            task = api(
                page,
                "/api/tasks",
                {
                    "title": "把小实验慢慢做出来",
                    "status": "in_progress",
                    "weekly_minutes": 378,
                },
            )["task"]
            task_id = task["id"]
            path = f"/api/tasks/{task_id}/workspace"
            page.evaluate("async () => { await loadTasks(); LoadWorkspace.invalidate(); }")
            expect(chart).to_have_attribute("data-load-feeling", "balanced")
            expect(chart.locator(".budget-feeling-badge")).to_contain_text("70%")
            expect(chart.locator(".budget-feeling-badge")).to_contain_text("刚刚好")
            expect(chart.locator(".budget-chart-center")).to_contain_text("2 小时 42 分钟")
            expect(page.locator("#load-summary .load-verdict")).to_have_attribute(
                "data-load-feeling", "balanced"
            )
            task = api(
                page,
                f"/api/tasks/{task_id}",
                {
                    "version": task["version"],
                    "weekly_minutes": 486,
                },
                "PATCH",
            )["task"]
            page.evaluate("async () => await loadTasks()")
            page.locator("#load-refresh").click()
            expect(chart).to_have_attribute("data-load-feeling", "high")
            expect(chart.locator(".budget-feeling-badge")).to_contain_text("90%")
            page.screenshot(path=str(ROOT / "evidence/warm-load-desktop.png"), full_page=True)
            page.locator("#load-mode").select_option("remaining")
            expect(chart).to_have_attribute("data-load-feeling", "unknown")
            expect(chart.locator(".budget-feeling-badge")).not_to_contain_text("%")
            page.locator("#load-mode").select_option("week")
            expect(chart).to_have_attribute("data-load-feeling", "high")

            mutation(page, task_id, "profile", {"criterion": "能运行并说明这个小实验"})
            drafted = mutation(
                page,
                task_id,
                "draft",
                {
                    "nodes": [
                        {
                            "title": "看懂一个小例子",
                            "criterion": "能说明输入和输出",
                            "low": 30,
                            "high": 45,
                            "depends": [],
                        },
                        {
                            "title": "跑通一段小代码",
                            "criterion": "看到预期结果",
                            "low": 30,
                            "high": 60,
                            "depends": [],
                        },
                    ]
                },
            )
            draft = drafted["drafts"][0]
            applied = mutation(
                page,
                task_id,
                "apply",
                {
                    "draft_id": draft["id"],
                    "revision": draft["revision"],
                    "selected": [0, 1],
                },
            )
            first, second = applied["steps"]
            page.evaluate("id => Execution.open(id, 'steps')", task_id)
            expect(page.locator("#execution-dialog")).to_be_visible()
            expect(page.locator(".ex-step")).to_have_count(2)
            # Control only browser timers; production server time and saved dates stay real.
            page.clock.install(time=dt.datetime.now(dt.timezone.utc))
            lost = []

            def lose_success_response(route):
                if (
                    route.request.method == "POST"
                    and route.request.post_data_json["action"] == "complete"
                ):
                    response = route.fetch()
                    assert response.status == 200, response.text()
                    lost.append(
                        {"key": route.request.headers["idempotency-key"], "result": response.json()}
                    )
                    route.abort()
                else:
                    route.continue_()

            page.route("**" + path, lose_success_response)
            page.locator(f'.ex-step[data-step-id="{first["id"]}"]').get_by_role(
                "button", name="登记完成", exact=True
            ).click()
            page.locator("#ex-complete-submit").click()
            expect(page.locator("#ex-error")).to_contain_text("未保存")
            expect(toast).not_to_be_visible()
            assert len(lost) == 1
            page.unroute("**" + path, lose_success_response)
            with page.expect_response(
                lambda r: r.url.endswith(path) and r.request.method == "POST"
            ) as retried:
                page.locator("#ex-retry").click()
            assert retried.value.status == 200
            assert retried.value.request.headers["idempotency-key"] == lost[0]["key"]
            result = retried.value.json()
            assert len([e for e in result["history"] if e["kind"] == "complete"]) == 1
            visible_toast(first["title"], "1 / 2")
            first_event = toast.get_attribute("data-event-id")
            assert count() == 1
            page.evaluate(
                """({result, taskId, stepId}) => {
                  const payload = {owner:state.user.id,taskId,result,stepId,host:document.querySelector('#execution-dialog')};
                  Encouragement.completed(payload); Encouragement.completed(payload);
                }""",
                {"result": result, "taskId": task_id, "stepId": first["id"]},
            )
            assert count() == 1
            page.screenshot(path=str(ROOT / "evidence/encouragement-desktop.png"), full_page=True)
            # Hover and keyboard focus each keep the message available; leave resumes its six seconds.
            toast.hover()
            page.clock.fast_forward(7000)
            expect(toast).to_be_visible()
            page.locator("#encouragement-close").focus()
            page.mouse.move(0, 0)
            page.clock.fast_forward(7000)
            expect(toast).to_be_visible()
            page.locator("#ex-step-search").focus()
            page.clock.fast_forward(6100)
            expect(toast).not_to_be_visible()

            first_row = page.locator(f'.ex-step[data-step-id="{first["id"]}"]')
            first_row.get_by_role("button", name="编辑完成记录", exact=True).click()
            page.locator("#ex-complete-note").fill("补充一个已经完成的小结果")
            page.locator("#ex-complete-submit").click()
            expect(first_row).to_contain_text("补充一个已经完成的小结果")
            expect(toast).not_to_be_visible()
            assert count() == 1
            first_row.get_by_role("button", name="撤销完成", exact=True).click()
            expect(first_row.locator(".ex-status")).not_to_have_text("完成")
            expect(toast).not_to_be_visible()
            complete(first["id"])
            visible_toast(first["title"], "1 / 2")
            assert toast.get_attribute("data-event-id") != first_event
            assert count() == 2

            page.set_viewport_size({"width": 390, "height": 844})
            expired_during_request = []

            def expire_old_toast_before_response(route):
                if route.request.method == "POST":
                    response = route.fetch()
                    assert response.status == 200
                    page.mouse.move(0, 0)
                    page.clock.fast_forward(6100)
                    expect(toast).not_to_be_visible()
                    expired_during_request.append(True)
                    route.fulfill(response=response)
                else:
                    route.continue_()

            page.route("**" + path, expire_old_toast_before_response)
            complete(second["id"])
            page.unroute("**" + path, expire_old_toast_before_response)
            assert expired_during_request == [True]
            visible_toast(second["title"], "2 / 2")
            assert count() == 3
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            assert page.locator("#execution-dialog").evaluate("e => e.scrollWidth <= e.clientWidth")
            assert toast.evaluate("e => e.getBoundingClientRect().right <= window.innerWidth")
            page.screenshot(path=str(ROOT / "evidence/encouragement-mobile.png"), full_page=True)
            page.locator("#encouragement-close").click()
            page.locator("#ex-refresh").click()
            expect(page.locator("#ex-notice")).to_contain_text("已载入最新版本")
            expect(toast).not_to_be_visible()
            assert count() == 3
            complete()
            visible_toast(task["title"])
            assert count() == 4
            page.locator("#ex-close").click()
            expect(toast).not_to_be_visible()
            page.locator("#encouragement-toggle").click()
            expect(page.locator("#encouragement-toggle")).to_have_attribute("aria-pressed", "false")
            page.reload()
            expect(page.locator("#workspace")).to_be_visible()
            expect(page.locator("#encouragement-toggle")).to_have_attribute("aria-pressed", "false")
            expect(toast).not_to_be_visible()
            page.evaluate("id => Execution.open(id, 'steps')", task_id)
            page.get_by_role("button", name="撤销整个任务完成", exact=True).click()
            expect(page.locator("#ex-subtitle")).to_contain_text("进行中")
            complete()
            expect(toast).not_to_be_visible()
            assert count() == 0
            page.locator("#ex-close").click()
            page.locator("#encouragement-toggle").click()
            page.evaluate("id => Execution.open(id, 'steps')", task_id)
            page.get_by_role("button", name="撤销整个任务完成", exact=True).click()
            expect(page.locator("#ex-subtitle")).to_contain_text("进行中")
            complete()
            visible_toast(task["title"])
            # Dispatch the existing logout action while the modal contains a visible notification.
            page.evaluate("document.querySelector('#logout').click()")
            expect(page.locator("#auth-screen")).to_be_visible()
            expect(toast).not_to_be_visible()
            assert not page.locator("#encouragement-detail").inner_text()
            assert not page.locator("#encouragement-progress").inner_text()
            # Same browser storage, different account: one user's off switch cannot affect another.
            page.locator("#username").fill("warm_feedback_qa")
            page.locator("#password").fill(PASSWORD)
            page.locator("#auth-submit").click()
            expect(page.locator("#workspace")).to_be_visible()
            page.locator("#encouragement-toggle").click()
            expect(page.locator("#encouragement-toggle")).to_have_attribute("aria-pressed", "false")
            page.locator("#logout").click()
            expect(page.locator("#auth-screen")).to_be_visible()
            register(page, "warm_feedback_other")
            expect(page.locator("#encouragement-toggle")).to_have_attribute("aria-pressed", "true")
            expect(toast).not_to_be_visible()
            assert task["title"] not in page.content()
            assert not errors, errors
            assert not external, external
            return {
                "load_boundaries_unknown_stale_intervals_zero_capacity": "pass",
                "real_net_capacity_540_demand_378_is_70_percent": "pass",
                "real_90_percent_and_remaining_unknown": "pass",
                "saved_completion_lost_response_same_key_retry_once": "pass",
                "same_event_replay_no_duplicate": "pass",
                "old_toast_expiry_during_next_completion_preserves_new_feedback": "pass",
                "step_title_and_1_of_2_then_2_of_2": "pass",
                "six_second_timer_hover_focus_pause_no_focus_theft": "pass",
                "edit_undo_refresh_reload_no_new_notification": "pass",
                "undo_then_recomplete_is_a_new_event": "pass",
                "parent_completion_notification": "pass",
                "preference_persistence_disabled_completion_and_account_isolation": "pass",
                "logout_clears_notification_contents": "pass",
                "390px_modal_layout": "pass",
                "page_errors": errors,
                "external_requests": external,
                "real_database_or_secret_contents_read": False,
            }
        except Exception:
            page.screenshot(path=str(ROOT / "evidence/warm-feedback-failure.png"), full_page=True)
            raise
        finally:
            browser.close()


def run_editor_browser():
    """Exercise the ordinary task editor completion hook without repeating the full suite."""
    with sync_playwright() as playwright:
        options = {"headless": True}
        if Path("/Applications/Google Chrome.app").exists():
            options["channel"] = "chrome"
        browser = playwright.chromium.launch(**options)
        context = browser.new_context(viewport={"width": 1440, "height": 1050})
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
        toast = page.locator("#encouragement-toast")

        def open_editor(task_id):
            page.evaluate("id => LoadWorkspace.openTask(id)", task_id)
            expect(page.locator("#task-dialog")).to_be_visible()

        def save_editor(task_id):
            with page.expect_response(
                lambda r: r.url.endswith(f"/api/tasks/{task_id}") and r.request.method == "PATCH"
            ) as saved:
                page.locator("#save-task").click()
            assert saved.value.status == 200, saved.value.text()
            expect(page.locator("#task-dialog")).not_to_be_visible()
            expect(page.locator("#new-task")).to_be_enabled()
            return saved.value.json()["task"]

        try:
            page.goto(BASE)
            register(page, "warm_editor_qa")
            task = api(
                page,
                "/api/tasks",
                {
                    "title": "普通编辑器完成的小事",
                    "status": "in_progress",
                    "weekly_minutes": 30,
                },
            )["task"]
            task_id = task["id"]
            path = f"/api/tasks/{task_id}/workspace"
            open_editor(task_id)
            page.locator("#task-status").select_option("completed")
            saved = save_editor(task_id)
            assert saved["status"] == "completed"
            expect(toast).to_be_visible()
            expect(page.locator("#encouragement-detail")).to_contain_text(task["title"])
            expect(toast).to_have_attribute("data-show-count", "1")
            authoritative = api(page, path)
            expect(toast).to_have_attribute(
                "data-event-id", str(authoritative["completion"]["event_id"])
            )
            assert toast.evaluate("element => element.parentElement === document.body")
            page.screenshot(
                path=str(ROOT / "evidence/encouragement-task-editor.png"), full_page=True
            )
            open_editor(task_id)
            expect(toast).not_to_be_visible()
            page.locator("#task-description").fill("给已完成的事情补充说明")
            saved = save_editor(task_id)
            assert saved["status"] == "completed"
            expect(toast).not_to_be_visible()
            expect(toast).to_have_attribute("data-show-count", "1")
            # Editing the completion record is a separate save, and keeps the original event.
            page.evaluate("id => Execution.open(id, 'steps')", task_id)
            expect(page.locator("#ex-complete-heading")).to_have_text("编辑完成记录")
            page.locator("#ex-complete-note").fill("补记完成说明，仍是同一次完成")
            with page.expect_response(
                lambda r: r.url.endswith(path) and r.request.method == "POST"
            ) as edited:
                page.locator("#ex-complete-submit").click()
            assert edited.value.status == 200, edited.value.text()
            assert (
                edited.value.json()["completion"]["event_id"]
                == authoritative["completion"]["event_id"]
            )
            expect(page.locator("#ex-notice")).to_have_text("已保存。")
            expect(toast).not_to_be_visible()
            expect(toast).to_have_attribute("data-show-count", "1")
            page.locator("#ex-close").click()
            # A genuine reopen and new completion can produce another notification.
            open_editor(task_id)
            page.locator("#task-status").select_option("in_progress")
            save_editor(task_id)
            open_editor(task_id)
            page.locator("#task-status").select_option("completed")
            save_editor(task_id)
            expect(toast).to_be_visible()
            expect(toast).to_have_attribute("data-show-count", "2")
            page.locator("#logout").click()
            expect(page.locator("#auth-screen")).to_be_visible()
            expect(toast).not_to_be_visible()
            assert not page.locator("#encouragement-detail").inner_text()
            assert not page.locator("#encouragement-title").inner_text()
            assert not errors, errors
            assert not external, external
            return {
                "ordinary_editor_completed_status_uses_authoritative_event": "pass",
                "completed_task_description_edit_no_new_notification": "pass",
                "completion_record_edit_preserves_event_no_new_notification": "pass",
                "editor_reopen_recomplete_new_notification": "pass",
                "logout_clears_body_notification": "pass",
                "page_errors": errors,
                "external_requests": external,
                "real_database_or_secret_contents_read": False,
            }
        except Exception:
            page.screenshot(path=str(ROOT / "evidence/warm-editor-failure.png"), full_page=True)
            raise
        finally:
            browser.close()


def main(editor_only=False):
    (ROOT / "evidence").mkdir(exist_ok=True)
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", 8032))
    with tempfile.TemporaryDirectory(prefix="liubai-warm-feedback-") as name:
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
        name = "warm-feedback-editor" if editor_only else "warm-feedback"
        with (ROOT / f"evidence/{name}-server.log").open("w") as log:
            server = subprocess.Popen(
                [python, __file__, "--server", str(directory)],
                cwd=ROOT,
                env=environment,
                stdout=log,
                stderr=log,
            )
            try:
                wait_server(server)
                result = run_editor_browser() if editor_only else run_browser()
                (ROOT / f"evidence/{name}-browser.json").write_text(
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
        main(editor_only="--editor-only" in sys.argv)
