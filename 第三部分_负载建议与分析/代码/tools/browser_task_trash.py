"""Disposable-browser acceptance for easy, recoverable task deletion (port 8033)."""

import datetime as dt
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.request
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

expect.set_options(timeout=15000)
ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8033"
PASSWORD = "Moss!River84Corner"


def serve(directory):
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from django.core.management import call_command
    from django.test import override_settings

    with override_settings(BASE_DIR=Path(directory)):
        call_command("runserver", "127.0.0.1:8033", use_reloader=False, insecure=True)


def wait_server(server):
    for _ in range(100):
        assert server.poll() is None, "Temporary task deletion server exited"
        try:
            with urllib.request.urlopen(BASE, timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.1)
    raise AssertionError("Temporary task deletion server did not become ready")


def api(page, path, body=None, method="POST"):
    return page.evaluate(
        """([path, body, method]) => api(path, body === null ? {} : {
          method, body, headers: {'Idempotency-Key': crypto.randomUUID()}
        })""",
        [path, body, method],
    )


def register(page, name):
    page.locator("#register-tab").click()
    page.locator("#username").fill(name)
    page.locator("#password").fill(PASSWORD)
    page.locator("#auth-submit").click()
    expect(page.locator("#workspace")).to_be_visible()
    expect(page.locator("#load-summary .budget-chart")).to_be_visible()


def mutation(page, task_id, action, values=None):
    path = f"/api/tasks/{task_id}/workspace"
    current = api(page, path)
    return api(
        page,
        path,
        {
            "action": action,
            "version": current["task"]["version"],
            **(values or {}),
        },
    )


def lifecycle(page, task, action):
    return api(
        page,
        f"/api/tasks/{task['id']}/lifecycle",
        {
            "action": action,
            "version": task["version"],
        },
    )["task"]


def load_workspace(page):
    return page.evaluate("""() => api('/api/load/workspace?' + new URLSearchParams({
        week: document.querySelector('#load-week').value, mode:'week'
    }))""")


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
        errors, external, dialogs = [], [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("dialog", lambda dialog: (dialogs.append(dialog.message), dialog.dismiss()))

        def local_only(route):
            if route.request.url.startswith(BASE):
                route.continue_()
            else:
                external.append(route.request.url)
                route.abort()

        page.route("**/*", local_only)
        chart = page.locator("#load-summary .budget-chart")
        encouragement = page.locator("#encouragement-toast")
        checks = {}

        def passed(name):
            checks[name] = "pass"

        def row(task_id):
            return page.locator(f'.task-row[data-task-row="{task_id}"]')

        def delete_button(task_id):
            return page.locator(f'button[data-delete-task="{task_id}"]')

        def restore_button(task_id):
            return page.locator(f'button[data-restore-task="{task_id}"]')

        def click_mutation(locator, task_id, status=200, keyboard=False):
            with page.expect_response(
                lambda response: (
                    response.url.endswith(f"/api/tasks/{task_id}/lifecycle")
                    and response.request.method == "POST"
                )
            ) as response:
                if keyboard:
                    locator.focus()
                    locator.press("Enter")
                else:
                    locator.click()
            assert response.value.status == status, response.value.text()
            return response.value

        def trash_page():
            page.locator('[data-tab="trash"]').click()
            expect(page.locator("#workspace")).to_have_attribute("data-page", "tasks/trash")
            expect(page.locator("#task-list")).to_have_attribute("aria-busy", "false")

        def overview():
            page.locator('[data-route="overview"]').click()
            expect(page.locator("#workspace")).to_have_attribute("data-page", "overview")
            expect(chart).to_be_visible()

        try:
            page.goto(BASE)
            register(page, "task_trash_qa")
            for field, value in [
                ("load-budget-hours", "10"),
                ("load-budget-minutes", "0"),
                ("load-buffer-hours", "1"),
                ("load-buffer-minutes", "0"),
            ]:
                page.locator(f"#{field}").fill(value)
            with page.expect_response("**/api/load/settings") as saved:
                page.locator('#load-capacity-form button[type="submit"]').click()
            assert saved.value.status == 200
            task = api(
                page,
                "/api/tasks",
                {
                    "title": "不必为了删除先放弃的事情",
                    "status": "in_progress",
                    "weekly_minutes": 180,
                },
            )["task"]
            task_id = task["id"]
            workspace_path = f"/api/tasks/{task_id}/workspace"
            mutation(
                page,
                task_id,
                "time_add",
                {
                    "step_id": None,
                    "minutes": 45,
                    "date": dt.date.today().isoformat(),
                    "note": "删除后也应保留的真实投入",
                },
            )
            before = mutation(page, task_id, "verify_time", {"step_id": None, "verified": True})
            page.evaluate("async () => await loadTasks()")
            expect(page.locator(f'.task-card[data-task-id="{task_id}"]')).to_be_visible()
            # RED: user-visible action is missing in the original implementation.
            expect(delete_button(task_id)).to_be_visible()
            expect(page.locator('[data-tab="trash"]')).to_be_visible()
            expect(chart).to_have_attribute("data-demand-low", "180")
            expect(delete_button(task_id)).to_have_accessible_name(f"删除「{task['title']}」")
            assert not page.locator("button button").count(), "Action buttons must not be nested"
            page.screenshot(path=str(ROOT / "evidence/task-trash-desktop.png"), full_page=True)
            passed("visible_card_delete_and_trash_navigation")

            deleted = click_mutation(delete_button(task_id), task_id).json()["task"]
            assert deleted["deleted_at"] and deleted["status"] == "in_progress"
            expect(row(task_id)).to_have_count(0)
            expect(page.locator("#task-dialog")).not_to_be_visible()
            expect(page.locator("#execution-dialog")).not_to_be_visible()
            expect(chart).to_have_attribute("data-demand-low", "0")
            expect(page.locator("#task-trash-message")).to_contain_text(task["title"])
            expect(page.locator("#task-trash-undo")).to_be_visible()
            assert not dialogs, "Card deletion should take one click, with no confirmation dialog"
            assert load_workspace(page)["actual"]["minutes"] == 45
            passed("one_click_delete_does_not_open_details_and_releases_budget_180_to_zero")

            restored = click_mutation(page.locator("#task-trash-undo"), task_id).json()["task"]
            assert restored["deleted_at"] is None and restored["status"] == "in_progress"
            expect(row(task_id)).to_be_visible()
            expect(chart).to_have_attribute("data-demand-low", "180")
            after = api(page, workspace_path)
            assert after["entries"] == before["entries"]
            assert after["summary"] == before["summary"]
            assert [
                event
                for event in after["history"]
                if event["kind"] not in ("task_trash", "task_restore")
            ] == before["history"]
            assert [event["kind"] for event in after["history"][:2]] == [
                "task_restore",
                "task_trash",
            ]
            expect(encouragement).not_to_be_visible()
            passed("immediate_undo_restores_original_status_budget_and_verified_actual_ledger")

            # Hold the canonical read after the POST: a real navigation click during
            # this interval must execute when the operation settles, never disappear.
            canonical_reads = []

            def hold_canonical_read(route):
                canonical_reads.append(route)

            page.route("**/api/tasks?status=trash", hold_canonical_read)
            with page.expect_request(
                lambda request: (
                    request.url == BASE + "/api/tasks?status=trash" and request.method == "GET"
                )
            ):
                click_mutation(delete_button(task_id), task_id)
            page.locator('[data-tab="trash"]').click()
            assert len(canonical_reads) == 1
            canonical_reads[0].continue_()
            page.unroute("**/api/tasks?status=trash", hold_canonical_read)
            expect(page.locator("#workspace")).to_have_attribute("data-page", "tasks/trash")
            expect(page.locator("#task-list")).to_have_attribute("aria-busy", "false")
            expect(restore_button(task_id)).to_be_visible()
            page.reload()
            expect(page.locator("#workspace")).to_have_attribute("data-page", "tasks/trash")
            expect(restore_button(task_id)).to_be_visible()
            expect(row(task_id)).to_contain_text(task["title"])
            assert row(task_id).locator(".task-card").evaluate("e => e.tagName") == "ARTICLE"
            page.screenshot(path=str(ROOT / "evidence/task-trash-recycle-bin.png"), full_page=True)
            click_mutation(restore_button(task_id), task_id)
            expect(row(task_id)).to_have_count(0)
            after = api(page, workspace_path)
            assert after["entries"] == before["entries"]
            assert after["summary"] == before["summary"]
            overview()
            expect(chart).to_have_attribute("data-demand-low", "180")
            passed("recycle_bin_survives_reload_and_restores_full_records")

            # A server failure keeps the visible row and every byte of the retry packet.
            failure_packets = []
            lifecycle_path = f"/api/tasks/{task_id}/lifecycle"

            def fail_without_write(route):
                if route.request.method == "POST":
                    failure_packets.append(
                        {
                            "key": route.request.headers["idempotency-key"],
                            "body": route.request.post_data_json,
                        }
                    )
                    route.fulfill(
                        status=503,
                        content_type="application/json",
                        body=json.dumps(
                            {
                                "error": "测试保存失败，请重试。",
                            }
                        ),
                    )
                else:
                    route.continue_()

            page.route("**" + lifecycle_path, fail_without_write)
            click_mutation(delete_button(task_id), task_id, 503)
            expect(row(task_id)).to_be_visible()
            expect(page.locator("#task-trash-retry")).to_be_visible()
            expect(chart).to_have_attribute("data-demand-low", "180")
            assert api(page, f"/api/tasks/{task_id}")["task"]["deleted_at"] is None
            page.unroute("**" + lifecycle_path, fail_without_write)
            retry = click_mutation(page.locator("#task-trash-retry"), task_id)
            assert retry.request.headers["idempotency-key"] == failure_packets[0]["key"]
            assert retry.request.post_data_json == failure_packets[0]["body"]
            expect(row(task_id)).to_have_count(0)
            click_mutation(page.locator("#task-trash-undo"), task_id)
            expect(row(task_id)).to_be_visible()
            passed("failed_delete_preserves_row_budget_and_retries_identical_request_key_and_body")

            # The database commit is real. Only the successful response is discarded.
            lost = []
            version_before = api(page, f"/api/tasks/{task_id}")["task"]["version"]

            def lose_committed_response(route):
                if route.request.method == "POST":
                    response = route.fetch()
                    assert response.status == 200, response.text()
                    lost.append(
                        {
                            "key": route.request.headers["idempotency-key"],
                            "body": route.request.post_data_json,
                            "task": response.json()["task"],
                        }
                    )
                    route.abort()
                else:
                    route.continue_()

            page.route("**" + lifecycle_path, lose_committed_response)
            delete_button(task_id).click()
            expect(page.locator("#task-trash-retry")).to_be_visible()
            expect(row(task_id)).to_be_visible()
            assert len(lost) == 1
            expect(page.locator("#task-trash-undo")).not_to_be_visible()
            page.unroute("**" + lifecycle_path, lose_committed_response)
            retry = click_mutation(page.locator("#task-trash-retry"), task_id)
            assert retry.request.headers["idempotency-key"] == lost[0]["key"]
            assert retry.request.post_data_json == lost[0]["body"]
            assert retry.json()["task"] == lost[0]["task"]
            assert retry.json()["task"]["version"] == version_before + 1
            trashed = api(page, "/api/tasks?status=trash")["tasks"]
            assert [t["id"] for t in trashed].count(task_id) == 1
            expect(row(task_id)).to_have_count(0)
            click_mutation(page.locator("#task-trash-undo"), task_id)
            expect(row(task_id)).to_be_visible()
            passed("real_commit_lost_response_same_key_retry_only_one_version_increment")

            # Filtering cannot make an action target a different task with a similar title.
            keep = api(
                page,
                "/api/tasks",
                {
                    "title": "保留这个想法",
                    "status": "planned",
                    "weekly_minutes": 60,
                },
            )["task"]
            search_task = api(
                page,
                "/api/tasks",
                {
                    "title": "只删除搜到的想法 <img src=x onerror=window.trashXSS=1>",
                    "status": "planned",
                    "weekly_minutes": 120,
                },
            )["task"]
            page.locator('[data-tab="planned"]').click()
            page.locator("#search").fill("只删除搜到")
            expect(page.locator("#task-list .task-row")).to_have_count(1)
            expect(row(search_task["id"])).to_be_visible()
            assert page.evaluate("window.trashXSS") is None
            assert row(search_task["id"]).locator("img").count() == 0
            click_mutation(delete_button(search_task["id"]), search_task["id"])
            expect(row(search_task["id"])).to_have_count(0)
            assert api(page, f"/api/tasks/{keep['id']}")["task"]["deleted_at"] is None
            assert load_workspace(page)["analysis"]["low"] == 180
            passed("searched_delete_uses_correct_task_id_idea_does_not_change_budget_title_is_text")
            page.locator("#search").fill("")

            # The ordinary task details provide the same single-click delete action.
            overview()
            expect(row(task_id)).to_be_visible()
            row(task_id).locator(".task-card").click()
            expect(page.locator("#task-dialog")).to_be_visible()
            expect(page.locator("#delete-task")).to_be_visible()
            click_mutation(page.locator("#delete-task"), task_id)
            expect(page.locator("#task-dialog")).not_to_be_visible()
            expect(row(task_id)).to_have_count(0)
            expect(chart).to_have_attribute("data-demand-low", "0")
            click_mutation(page.locator("#task-trash-undo"), task_id)
            expect(row(task_id)).to_be_visible()
            assert not dialogs
            passed("details_delete_closes_details_after_success_and_can_be_undone")

            completed_task = api(
                page,
                "/api/tasks",
                {
                    "title": "已经做好的小成果",
                    "status": "in_progress",
                    "weekly_minutes": 20,
                },
            )["task"]
            completed = mutation(
                page,
                completed_task["id"],
                "complete",
                {
                    "step_id": None,
                    "note": "原本就已完成的成果说明",
                    "verified": True,
                    "extra_minutes": 12,
                    "date": dt.date.today().isoformat(),
                },
            )
            page.locator('[data-tab="history"]').click()
            expect(delete_button(completed_task["id"])).to_be_visible()
            click_mutation(delete_button(completed_task["id"]), completed_task["id"])
            expect(row(completed_task["id"])).to_have_count(0)
            trash_page()
            click_mutation(restore_button(completed_task["id"]), completed_task["id"])
            restored_completed = api(page, f"/api/tasks/{completed_task['id']}/workspace")
            assert restored_completed["completion"] == completed["completion"]
            assert restored_completed["entries"] == completed["entries"]
            assert restored_completed["task"]["status"] == "completed"
            expect(encouragement).not_to_be_visible()
            passed("completed_task_round_trip_preserves_completion_event_and_does_not_congratulate")

            # Out-of-date restore must not overwrite a concurrent restore/delete cycle.
            stale_task = next(
                t
                for t in api(page, "/api/tasks?status=trash")["tasks"]
                if t["id"] == search_task["id"]
            )
            fresh_task = lifecycle(page, stale_task, "restore")
            fresh_task = lifecycle(page, fresh_task, "trash")
            click_mutation(restore_button(stale_task["id"]), stale_task["id"], 409)
            expect(row(stale_task["id"])).to_be_visible()
            expect(page.locator("#task-trash-reload")).to_be_visible()
            still_deleted = next(
                t
                for t in api(page, "/api/tasks?status=trash")["tasks"]
                if t["id"] == stale_task["id"]
            )
            assert still_deleted["version"] == fresh_task["version"]
            assert still_deleted["deleted_at"] == fresh_task["deleted_at"]
            page.locator("#task-trash-reload").click()
            expect(page.locator("#task-trash-reload")).not_to_be_visible()
            click_mutation(restore_button(stale_task["id"]), stale_task["id"])
            expect(row(stale_task["id"])).to_have_count(0)
            passed("stale_restore_409_keeps_task_deleted_until_reload_and_explicit_retry")

            overview()
            page.set_viewport_size({"width": 390, "height": 844})
            expect(delete_button(task_id)).to_be_visible()
            delete_button(task_id).scroll_into_view_if_needed()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            rectangle = delete_button(task_id).bounding_box()
            assert rectangle and rectangle["x"] >= 0 and rectangle["x"] + rectangle["width"] <= 390
            assert rectangle["height"] >= 40, "Mobile deletion needs a usable touch target"
            assert not page.locator("button button").count()
            page.screenshot(path=str(ROOT / "evidence/task-trash-mobile.png"), full_page=True)
            click_mutation(delete_button(task_id), task_id, keyboard=True)
            expect(row(task_id)).to_have_count(0)
            expect(page.locator("#task-dialog")).not_to_be_visible()
            trash_page()
            expect(restore_button(task_id)).to_be_visible()
            restore_button(task_id).scroll_into_view_if_needed()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.screenshot(
                path=str(ROOT / "evidence/task-trash-recycle-mobile.png"), full_page=True
            )
            click_mutation(restore_button(task_id), task_id, keyboard=True)
            expect(row(task_id)).to_have_count(0)
            passed("mobile_390px_no_horizontal_overflow_no_nested_buttons_keyboard_delete_restore")

            # Undo state is private account state, including the removed task's title.
            overview()
            click_mutation(delete_button(task_id), task_id)
            expect(page.locator("#task-trash-undo")).to_be_visible()
            page.locator("#logout").click()
            expect(page.locator("#auth-screen")).to_be_visible()
            expect(page.locator("#task-trash-notice")).not_to_be_visible()
            assert not page.locator("#task-trash-message").text_content()
            register(page, "task_trash_other")
            expect(page.locator("#task-trash-notice")).not_to_be_visible()
            trash_page()
            expect(page.locator("#task-list .task-row")).to_have_count(0)
            assert api(page, "/api/tasks?status=trash")["tasks"] == []
            outsider = page.evaluate(
                """async taskId => {
              try { await api(`/api/tasks/${taskId}/lifecycle`, {method:'POST',
                headers:{'Idempotency-Key':crypto.randomUUID()},
                body:{action:'restore',version:1}}); return {status:200};
              } catch(error) { return {status:error.status}; }
            }""",
                task_id,
            )
            assert outsider["status"] == 404, outsider
            passed("logout_clears_private_undo_content_other_account_cannot_list_or_restore")
            assert not errors, errors
            assert not external, external
            assert not dialogs, dialogs
            expect(encouragement).not_to_be_visible()
            return {
                **checks,
                "page_errors": errors,
                "external_requests": external,
                "unexpected_confirmation_dialogs": dialogs,
                "real_database_or_secret_contents_read": False,
            }
        except Exception:
            page.screenshot(path=str(ROOT / "evidence/task-trash-failure.png"), full_page=True)
            raise
        finally:
            browser.close()


def run_edge_browser(case):
    """Two independent regression cases; never substitute for the original twelve."""
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

        def local_only(route):
            if route.request.url.startswith(BASE):
                route.continue_()
            else:
                external.append(route.request.url)
                route.abort()

        page.route("**/*", local_only)
        chart = page.locator("#load-summary .budget-chart")
        try:
            page.goto(BASE)
            register(page, f"trash_edge_{case}")
            for field, value in [
                ("load-budget-hours", "10"),
                ("load-budget-minutes", "0"),
                ("load-buffer-hours", "1"),
                ("load-buffer-minutes", "0"),
            ]:
                page.locator(f"#{field}").fill(value)
            with page.expect_response("**/api/load/settings") as saved:
                page.locator('#load-capacity-form button[type="submit"]').click()
            assert saved.value.status == 200
            task = api(
                page,
                "/api/tasks",
                {
                    "title": "并发检查中的三小时任务",
                    "status": "in_progress",
                    "weekly_minutes": 180,
                },
            )["task"]
            task_id = task["id"]
            path = f"/api/tasks/{task_id}/lifecycle"
            delete = page.locator(f'button[data-delete-task="{task_id}"]')
            row = page.locator(f'.task-row[data-task-row="{task_id}"]')
            page.evaluate("async () => await loadTasks()")
            expect(delete).to_be_visible()
            expect(chart).to_have_attribute("data-demand-low", "180")

            if case == "pending_budget":
                packets = []

                def fail_budget_save(route):
                    if route.request.method == "POST":
                        packets.append(
                            {
                                "key": route.request.headers["idempotency-key"],
                                "body": route.request.post_data_json,
                            }
                        )
                        route.fulfill(
                            status=503,
                            content_type="application/json",
                            body=json.dumps({"error": "模拟预算保存暂时不可用"}),
                        )
                    else:
                        route.continue_()

                page.route("**/api/load/settings", fail_budget_save)
                page.locator("#load-budget-hours").fill("11")
                with page.expect_response("**/api/load/settings") as failed:
                    page.locator('#load-capacity-form button[type="submit"]').click()
                assert failed.value.status == 503
                expect(page.locator("#load-retry")).to_be_visible()
                expect(page.locator("#load-retry")).to_be_enabled()
                expect(chart).to_have_attribute("data-demand-low", "180")
                page.unroute("**/api/load/settings", fail_budget_save)
                with page.expect_response("**" + path) as deleted:
                    delete.click()
                assert deleted.value.status == 200
                expect(row).to_have_count(0)
                authoritative = load_workspace(page)
                assert authoritative["analysis"]["low"] == 0
                assert authoritative["window"]["budget_minutes"] == 600
                # RED 1: a pending budget request must not freeze canonical task demand.
                expect(chart).to_have_attribute("data-demand-low", "0")
                expect(page.locator("#load-budget-hours")).to_have_value("11")
                expect(page.locator("#load-budget-minutes")).to_have_value("0")
                expect(page.locator("#load-retry")).to_be_visible()
                expect(page.locator("#load-retry")).to_be_enabled()
                page.screenshot(
                    path=str(ROOT / "evidence/task-trash-edge-pending-budget.png"), full_page=True
                )
                with page.expect_response("**/api/load/settings") as retried:
                    page.locator("#load-retry").click()
                assert retried.value.request.headers["idempotency-key"] == packets[0]["key"]
                assert retried.value.request.post_data_json == packets[0]["body"]
                # Task deletion legitimately invalidates the old budget fingerprint.
                assert retried.value.status == 409
                expect(page.locator("#load-budget-hours")).to_have_value("11")
                assert load_workspace(page)["window"]["budget_minutes"] == 600
                expect(chart).to_have_attribute("data-demand-low", "0")
                result = {
                    "pending_budget_does_not_freeze_task_delete_chart": "pass",
                    "pending_draft_and_original_retry_packet_preserved": "pass",
                    "stale_budget_retry_409_preserves_draft_and_saved_capacity": "pass",
                }
            else:
                lost = []

                def lose_committed_response(route):
                    if route.request.method == "POST":
                        response = route.fetch()
                        assert response.status == 200, response.text()
                        lost.append(
                            {
                                "key": route.request.headers["idempotency-key"],
                                "body": route.request.post_data_json,
                                "task": response.json()["task"],
                            }
                        )
                        route.abort()
                    else:
                        route.continue_()

                page.route("**" + path, lose_committed_response)
                delete.click()
                expect(page.locator("#task-trash-retry")).to_be_visible()
                assert len(lost) == 1 and lost[0]["task"]["version"] == 2
                page.unroute("**" + path, lose_committed_response)
                # An API request models a second tab, deliberately without refreshing this UI.
                elsewhere = lifecycle(page, lost[0]["task"], "restore")
                assert elsewhere["version"] == 3 and elsewhere["deleted_at"] is None
                with page.expect_response("**" + path) as replayed:
                    page.locator("#task-trash-retry").click()
                assert replayed.value.status == 200
                assert replayed.value.request.headers["idempotency-key"] == lost[0]["key"]
                assert replayed.value.request.post_data_json == lost[0]["body"]
                # The backend receipt is immutable evidence of the earlier operation.
                assert replayed.value.json()["task"] == lost[0]["task"]
                current = api(page, f"/api/tasks/{task_id}")["task"]
                assert current["version"] == 3 and current["deleted_at"] is None
                expect(row).to_be_visible()
                expect(page.locator("#task-trash-retry")).not_to_be_visible()
                # RED 2: a historical delete receipt cannot claim the task is still deleted.
                expect(page.locator("#task-trash-undo")).not_to_be_visible()
                expect(page.locator("#task-trash-notice")).not_to_have_attribute(
                    "data-state", "trashed"
                )
                expect(page.locator("#task-trash-message")).not_to_contain_text("已移入回收站")
                expect(chart).to_have_attribute("data-demand-low", "180")
                assert api(page, f"/api/tasks/{task_id}")["task"]["version"] == 3
                page.screenshot(
                    path=str(ROOT / "evidence/task-trash-edge-stale-receipt.png"), full_page=True
                )
                result = {
                    "old_delete_receipt_replay_does_not_claim_current_task_is_deleted": "pass",
                    "restored_task_stays_visible_no_stale_undo": "pass",
                    "same_key_receipt_preserved_without_second_delete_version_stays_three": "pass",
                }
            assert not errors, errors
            assert not external, external
            return {
                **result,
                "page_errors": errors,
                "external_requests": external,
                "real_database_or_secret_contents_read": False,
            }
        except Exception:
            page.screenshot(
                path=str(ROOT / f"evidence/task-trash-edge-{case}-failure.png"), full_page=True
            )
            raise
        finally:
            browser.close()


def run_edges():
    results, failed = {}, []
    for case in ("pending_budget", "stale_receipt"):
        try:
            results[case] = run_edge_browser(case)
        except Exception as error:
            results[case] = {"status": "fail", "error": str(error)}
            failed.append(case)
            print(f"EDGE {case}: FAIL\n{traceback.format_exc()}", flush=True)
        else:
            print(f"EDGE {case}: PASS", flush=True)
    (ROOT / "evidence/task-trash-edge-browser.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n"
    )
    assert not failed, f"Independent edge failures: {failed}"
    return results


def main(edge_only=False):
    (ROOT / "evidence").mkdir(exist_ok=True)
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", 8033))
    with tempfile.TemporaryDirectory(prefix="liubai-task-trash-") as name:
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
        name = "task-trash-edge" if edge_only else "task-trash"
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
                result = run_edges() if edge_only else run_browser()
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
        main(edge_only="--edge-only" in sys.argv)
