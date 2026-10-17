"""Inline-step browser acceptance using disposable state and no external services.

--red <asset-snapshot> records the expected failure using pre-feature static/templates.
All fixture data is created through production APIs; installed user state is untouched.
"""

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

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "InlineSteps!Local918"
expect.set_options(timeout=15000)


def api(page, path, body=None, method="POST"):
    return page.evaluate(
        """([path,body,method]) => api(path, body === null ? {} : {
          method,body,headers:{'Idempotency-Key':crypto.randomUUID()}})""",
        [path, body, method],
    )


def register(page, name):
    page.locator("#register-tab").click()
    page.locator("#username").fill(name)
    page.locator("#password").fill(PASSWORD)
    page.locator("#auth-submit").click()
    expect(page.locator("#workspace")).to_be_visible()
    expect(page.locator("#overview-focus")).not_to_have_attribute("data-state", "loading")


def read_task(page, task):
    return api(page, f"/api/tasks/{task['id']}/workspace")


def mutate(page, task, action, **values):
    current = read_task(page, task)
    return api(
        page,
        f"/api/tasks/{task['id']}/workspace",
        {"action": action, "version": current["task"]["version"], **values},
    )


def node(title, depends=None):
    return {
        "title": title,
        "criterion": f"核对 {title}",
        "low": 10,
        "high": 20,
        "depends": depends or [],
    }


def create_task(page, title, nodes, priority="normal"):
    task = api(
        page,
        "/api/tasks",
        {"title": title, "status": "in_progress", "priority": priority, "weekly_minutes": 120},
    )["task"]
    mutate(page, task, "profile", criterion="所有小步骤完成后核对整体结果")
    draft = mutate(page, task, "draft", nodes=nodes)["drafts"][0]
    result = mutate(
        page,
        task,
        "apply",
        draft_id=draft["id"],
        revision=draft["revision"],
        selected=list(range(len(nodes))),
    )
    return task, result["steps"]


def refresh(page):
    page.evaluate("async () => { await loadTasks(); }")
    expect(page.locator("#load-refresh")).to_be_enabled()
    page.wait_for_load_state("networkidle")


def row(page, task):
    return page.locator(f'.task-row[data-task-row="{task["id"]}"]')


def current(page, task):
    return row(page, task).locator(".inline-step-current")


def checkbox(page, task, step):
    return row(page, task).locator(f'input[data-complete-step="{step["id"]}"]')


def assert_no_dialog(page):
    expect(page.locator("#execution-dialog")).not_to_be_visible()
    expect(page.locator("#task-dialog")).not_to_be_visible()


def assert_ledger_and_parent(page, task, amount=None, entries=0):
    result = read_task(page, task)
    assert result["task"]["status"] == "in_progress", result["task"]
    assert result["summary"]["actual_minutes"] == amount, result["summary"]
    assert len(result["entries"]) == entries, result["entries"]
    return result


def malformed_case(page, raw):
    task, steps = create_task(
        page, "截断回执核对", [node("被服务端完成的一步"), node("下一步", [0])]
    )
    refresh(page)
    packets, committed = [], []
    pattern = f"**/api/tasks/{task['id']}/workspace"

    def truncate(route):
        if route.request.method != "POST":
            route.continue_()
            return
        packets.append((route.request.headers.get("idempotency-key"), route.request.post_data_json))
        if len(packets) == 1:
            result = route.fetch()
            assert result.status == 200, result.text()
            committed.append(result.json())
            route.fulfill(status=200, content_type="application/json", body=raw)
        else:
            route.continue_()

    page.route(pattern, truncate)
    checkbox(page, task, steps[0]).click()
    expect(page.locator("#inline-step-feedback")).to_have_attribute("aria-busy", "false")
    assert committed and committed[0]["steps"][0]["status"] == "completed"
    expect(page.locator("#inline-step-retry")).to_be_visible()
    expect(page.locator("#inline-step-retry")).to_be_enabled()
    expect(current(page, task)).to_contain_text(steps[0]["title"])
    page.locator("#inline-step-retry").click()
    expect(current(page, task)).to_contain_text(steps[1]["title"])
    assert len(packets) == 2 and packets[0] == packets[1], packets
    page.unroute(pattern, truncate)
    result = assert_ledger_and_parent(page, task)
    assert len([event for event in result["history"] if event["kind"] == "complete"]) == 1


def malformed_success(page):
    for raw in ("{", "{}", "null"):
        malformed_case(page, raw)


def focus_recovery(page):
    task, steps = create_task(
        page, "键盘连续处理", [node("按空格完成这一步"), node("之后继续这一小步", [0])]
    )
    refresh(page)
    control = checkbox(page, task, steps[0])
    control.focus()
    expect(control).to_be_focused()
    control.press("Space")
    expect(current(page, task)).to_contain_text(steps[1]["title"])
    expect(page.locator("#inline-step-feedback")).to_have_attribute("aria-busy", "false")
    expect(page.locator("#load-refresh")).to_be_enabled()
    page.wait_for_load_state("networkidle")
    assert page.evaluate(
        """next => {
          const active=document.activeElement;
          return active?.id === 'inline-step-feedback' || active?.dataset.completeStep === next;
        }""",
        steps[1]["id"],
    ), page.evaluate("document.activeElement?.outerHTML.slice(0, 300)")
    assert_ledger_and_parent(page, task)


def run_browser(base, red=False):
    checks, errors, external = [], [], []
    with sync_playwright() as playwright:
        options = {"headless": True}
        if Path("/Applications/Google Chrome.app").exists():
            options["channel"] = "chrome"
        browser = playwright.chromium.launch(**options)
        context = browser.new_context(
            viewport={"width": 1440, "height": 1000}, timezone_id="Asia/Shanghai"
        )

        def local_only(route):
            if route.request.url.startswith(base):
                route.continue_()
            else:
                external.append(route.request.url)
                route.abort()

        context.route("**/*", local_only)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("dialog", lambda dialog: dialog.accept())
        try:
            page.goto(base)
            register(page, "inline_alpha")
            probe = next(
                (argument for argument in sys.argv if argument.startswith("--probe-")), None
            )
            if probe:
                {
                    "--probe-malformed": malformed_success,
                    "--probe-object": lambda page: malformed_case(page, "{}"),
                    "--probe-null": lambda page: malformed_case(page, "null"),
                    "--probe-focus": focus_recovery,
                }[probe](page)
                assert not errors, errors
                assert not external, external
                return {
                    "checks": [probe],
                    "page_errors": errors,
                    "external_requests": external,
                    "installed_state_read": False,
                }
            malicious = '<img src=x onerror="window.inlineInjected=1">'
            task, steps = create_task(
                page,
                "优先任务 A：把想法推进一小步",
                [
                    node("准备材料"),
                    node("核对输入", [0]),
                    node("执行步骤三", [1]),
                    node(malicious, [2]),
                ],
                "high",
            )
            mutate(page, task, "complete", step_id=steps[0]["id"])
            mutate(page, task, "complete", step_id=steps[1]["id"])
            mutate(page, task, "step_status", step_id=steps[2]["id"], status="in_progress")
            refresh(page)
            focus = page.locator("#overview-focus")
            expect(focus).to_have_attribute("data-task-id", task["id"])
            expect(focus.locator(".inline-step-preview")).to_be_visible(
                timeout=2000 if red else 15000
            )
            expect(focus.locator(".inline-step-current")).to_contain_text("执行步骤三")
            expect(focus.locator(".inline-step-current")).to_contain_text("3")
            expect(focus.locator(".inline-step-next")).to_contain_text(malicious)
            expect(current(page, task)).to_contain_text("执行步骤三")
            expect(row(page, task).locator(".inline-step-next")).to_contain_text(malicious)
            assert row(page, task).locator(".task-card .inline-step-preview").count() == 0
            assert page.locator(".inline-step-preview img").count() == 0
            assert page.evaluate("window.inlineInjected === undefined")
            assert_no_dialog(page)
            assert_ledger_and_parent(page, task)
            checks.append("overview_and_card_show_step_3_next_4_as_safe_text_without_details")
            if red:
                raise AssertionError("Baseline unexpectedly contains inline previews")

            # The server commits but its response is lost. The second click must
            # not send another packet; a deliberate retry reuses body and key.
            packets, committed = [], []
            pattern = f"**/api/tasks/{task['id']}/workspace"

            def lose_first_response(route):
                if route.request.method != "POST":
                    route.continue_()
                    return
                packets.append(
                    (route.request.headers.get("idempotency-key"), route.request.post_data_json)
                )
                if len(packets) == 1:
                    response = route.fetch()
                    assert response.status == 200, response.text()
                    committed.append(response.json())
                    route.abort()
                else:
                    route.continue_()

            page.route(pattern, lose_first_response)
            selector = f'#overview-focus input[data-complete-step="{steps[2]["id"]}"]'
            page.evaluate(
                "selector => { const button=document.querySelector(selector); button.click(); button.click(); }",
                selector,
            )
            expect(page.locator("#inline-step-retry")).to_be_visible()
            expect(page.locator("#inline-step-retry")).to_be_enabled()
            assert len(packets) == 1, packets
            assert committed[0]["steps"][2]["status"] == "completed"
            expect(focus.locator(".inline-step-current")).to_contain_text("执行步骤三")
            expect(page.locator("#encouragement-toast")).not_to_be_visible()
            assert_no_dialog(page)
            page.locator("#inline-step-retry").click()
            expect(focus.locator(".inline-step-current")).to_contain_text(malicious)
            expect(current(page, task)).to_contain_text(malicious)
            expect(page.locator("#inline-step-undo")).to_be_visible()
            expect(page.locator("#inline-step-retry")).not_to_be_visible()
            assert len(packets) == 2 and packets[0] == packets[1], packets
            page.unroute(pattern, lose_first_response)
            result = assert_ledger_and_parent(page, task)
            events = [
                e
                for e in result["history"]
                if e["kind"] == "complete" and e["step_id"] == steps[2]["id"]
            ]
            assert len(events) == 1, events
            expect(page.locator("#encouragement-toast")).to_be_visible()
            expect(page.locator("#encouragement-toast")).to_have_attribute("data-show-count", "1")
            checks.append(
                "double_click_single_write_lost_response_retry_same_packet_one_event_one_encouragement"
            )

            page.locator("#inline-step-undo").click()
            expect(focus.locator(".inline-step-current")).to_contain_text("执行步骤三")
            expect(current(page, task)).to_contain_text("执行步骤三")
            result = assert_ledger_and_parent(page, task)
            assert result["steps"][2]["status"] == "in_progress"
            checks.append("undo_restores_step_3_and_original_status_without_changing_ledger")

            checkbox(page, task, steps[2]).click()
            expect(current(page, task)).to_contain_text(malicious)
            checkbox(page, task, steps[3]).click()
            expect(row(page, task).locator("input[data-complete-step]")).to_have_count(0)
            result = assert_ledger_and_parent(page, task)
            assert all(step["status"] == "completed" for step in result["steps"])
            assert_no_dialog(page)
            checks.append(
                "card_completion_advances_final_child_does_not_complete_parent_or_invent_time"
            )
            page.locator("#inline-step-undo").click()
            expect(current(page, task)).to_contain_text(malicious)
            page.reload()
            expect(current(page, task)).to_contain_text(malicious)
            assert_ledger_and_parent(page, task)
            checks.append("completion_and_undo_persist_on_reload")

            # Simulate another tab modifying the task version after rendering.
            mutate(
                page,
                task,
                "time_add",
                step_id=steps[2]["id"],
                minutes=25,
                date="2026-10-17",
                note="真实投入",
            )
            stale_posts = []

            def capture_conflict(route):
                if route.request.method == "POST":
                    stale_posts.append(route.request.post_data_json)
                route.continue_()

            page.route(pattern, capture_conflict)
            with page.expect_response(
                lambda response: (
                    response.url.endswith(f"/api/tasks/{task['id']}/workspace")
                    and response.request.method == "POST"
                )
            ) as response:
                checkbox(page, task, steps[3]).click()
            assert response.value.status == 409, response.value.text()
            expect(page.locator("#inline-step-feedback")).to_contain_text("未")
            expect(checkbox(page, task, steps[3])).to_be_enabled()
            page.wait_for_load_state("networkidle")
            assert len(stale_posts) == 1, stale_posts
            result = assert_ledger_and_parent(page, task, 25, 1)
            assert result["steps"][3]["status"] != "completed"
            page.unroute(pattern, capture_conflict)
            checkbox(page, task, steps[3]).click()
            expect(row(page, task).locator("input[data-complete-step]")).to_have_count(0)
            assert_ledger_and_parent(page, task, 25, 1)
            checks.append(
                "version_conflict_explicit_no_auto_resubmit_refresh_allows_deliberate_retry"
            )

            blocked, blocked_steps = create_task(
                page, "有依赖的任务 B", [node("先恢复这个前置"), node("后置不应能勾选", [0])]
            )
            mutate(page, blocked, "step_status", step_id=blocked_steps[0]["id"], status="paused")
            refresh(page)
            expect(row(page, blocked).locator(".inline-step-preview")).to_be_visible()
            expect(row(page, blocked).locator("input[data-complete-step]")).to_have_count(0)
            mutate(page, blocked, "step_status", step_id=blocked_steps[0]["id"], status="abandoned")
            refresh(page)
            expect(row(page, blocked).locator("input[data-complete-step]")).to_have_count(0)
            mutate(
                page, blocked, "step_status", step_id=blocked_steps[0]["id"], status="in_progress"
            )
            refresh(page)
            expect(checkbox(page, blocked, blocked_steps[0])).to_be_enabled()
            expect(row(page, blocked).locator(".inline-step-next")).to_contain_text(
                "后置不应能勾选"
            )
            checkbox(page, blocked, blocked_steps[0]).click()
            expect(current(page, blocked)).to_contain_text("后置不应能勾选")
            checks.append(
                "paused_or_abandoned_prerequisites_block_until_real_completion_unlocks_next"
            )

            selected_task = focus.get_attribute("data-task-id")
            page.locator("#search").fill("没有匹配项")
            expect(page.locator(".task-card")).to_have_count(0)
            expect(focus).to_have_attribute("data-task-id", selected_task)
            page.locator("#search").fill("")
            expect(row(page, blocked)).to_be_visible()
            checks.append("search_does_not_change_focus_or_completion_state")
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            expect(checkbox(page, blocked, blocked_steps[1])).to_be_visible()
            assert checkbox(page, blocked, blocked_steps[1]).evaluate(
                "el => Boolean(el.labels?.length) || Boolean(el.getAttribute('aria-label'))"
            )
            page.screenshot(path=str(ROOT / "evidence/inline-steps-mobile.png"), full_page=True)
            page.set_viewport_size({"width": 1440, "height": 1000})
            page.screenshot(path=str(ROOT / "evidence/inline-steps-desktop.png"), full_page=True)
            checks.append("390px_no_horizontal_overflow_named_checkbox_both_viewport_screenshots")

            # Delay a committed completion response across an account switch.
            held = []
            hold_pattern = f"**/api/tasks/{blocked['id']}/workspace"

            def hold_response(route):
                if route.request.method == "POST":
                    held.append((route, route.fetch()))
                else:
                    route.continue_()

            page.route(hold_pattern, hold_response)
            checkbox(page, blocked, blocked_steps[1]).click()
            for _ in range(50):
                if held:
                    break
                page.wait_for_timeout(100)
            assert held, "Expected the prior account's completion response"
            page.locator("#logout").click()
            expect(page.locator("#auth-screen")).to_be_visible()
            register(page, "inline_beta")
            route, old_response = held.pop()
            assert old_response.status == 200, old_response.text()
            route.fulfill(response=old_response)
            page.wait_for_timeout(300)
            expect(focus).to_have_attribute("data-state", "empty")
            expect(page.locator("#inline-step-feedback")).not_to_be_visible()
            expect(page.locator("#encouragement-toast")).not_to_be_visible()
            for value in (task["title"], blocked["title"], blocked_steps[1]["title"]):
                assert value not in page.locator("body").text_content()
            checks.append("delayed_success_after_account_switch_does_not_leak_names_or_feedback")
            malformed_success(page)
            checks.append(
                "committed_http200_truncated_json_retains_same_packet_retry_exactly_one_completion"
            )
            focus_recovery(page)
            checks.append("keyboard_space_completion_restores_focus_after_both_views_refresh")
            assert not errors, errors
            assert not external, external
            return {
                "checks": checks,
                "page_errors": errors,
                "external_requests": external,
                "installed_state_read": False,
            }
        except Exception as error:
            page.screenshot(path=str(ROOT / "evidence/inline-steps-failure.png"), full_page=True)
            report = {
                "stage": "RED" if red else "FAILED",
                "checks": checks,
                "error": str(error),
                "page_errors": errors,
                "external_requests": external,
                "installed_state_read": False,
            }
            probe = next((argument for argument in sys.argv if argument.startswith("--probe-")), "")
            suffix = probe.removeprefix("-") + ("-red" if red else "-partial")
            (ROOT / f"evidence/inline-steps-browser{suffix}.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n"
            )
            raise
        finally:
            browser.close()


def serve(port, snapshot):
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from django.conf import settings
    from django.core.management import call_command
    from django.test import override_settings

    with override_settings(
        BASE_DIR=Path(os.environ["TASKFLOW_STATE_DIR"]),
        TEMPLATES=[{**settings.TEMPLATES[0], "DIRS": [Path(snapshot) / "templates"]}],
        STATICFILES_DIRS=[Path(snapshot) / "static"],
    ):
        call_command("runserver", f"127.0.0.1:{port}", use_reloader=False, insecure=True)


def main():
    (ROOT / "evidence").mkdir(exist_ok=True)
    red = "--red" in sys.argv
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="liubai-inline-steps-") as directory:
        env = {
            **os.environ,
            "TASKFLOW_STATE_DIR": directory,
            "TASKFLOW_DB": f"{directory}/qa.sqlite3",
            "DEEPSEEK_API_KEY": "",
            "DEEPSEEK_MODEL": "",
        }
        subprocess.run(
            [sys.executable, "manage.py", "migrate", "--noinput"],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
        )
        command = [sys.executable, __file__, "--server", str(port), str(ROOT)]
        if red:
            command = [
                sys.executable,
                __file__,
                "--server",
                str(port),
                sys.argv[sys.argv.index("--red") + 1],
            ]
        with (ROOT / "evidence/inline-steps-server.log").open("w") as log:
            server = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=log)
            try:
                for _ in range(100):
                    assert server.poll() is None, "Temporary server exited"
                    try:
                        with urllib.request.urlopen(base, timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(0.1)
                else:
                    raise AssertionError("Temporary server did not start")
                result = run_browser(base, red=red)
                (ROOT / "evidence/inline-steps-browser.json").write_text(
                    json.dumps(result, ensure_ascii=False, indent=2) + "\n"
                )
                print(json.dumps(result, ensure_ascii=False))
            finally:
                server.terminate()
                server.wait(timeout=10)


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--server":
        serve(int(sys.argv[2]), sys.argv[3])
    else:
        main()
