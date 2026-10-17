"""Phase-5 overview acceptance against isolated state and local Chrome.

--baseline serves phase-4 assets over the same backend/seed, measuring the original
layout and the missing new interactions. Never accesses installed user state.
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

ROOT = Path(__file__).resolve().parents[1]
PORT = int(os.environ.get("OVERVIEW_QA_PORT", "0"))
BASE = f"http://127.0.0.1:{PORT}"
PASSWORD = "Moss!River84Corner"
TODAY = "2026-10-15"
expect.set_options(timeout=15000)


def serve(directory):
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from unittest.mock import patch

    from django.conf import settings
    from django.core.management import call_command
    from django.test import override_settings

    overrides = {"BASE_DIR": Path(directory)}
    if os.environ.get("OVERVIEW_BASELINE") == "1":
        baseline = ROOT.parents[1] / "第四部分_每日签到与足迹/代码"
        if not baseline.is_dir():
            baseline = next(ROOT.parents[1].glob("第四部分*/代码"))
        overrides.update(
            TEMPLATES=[{**settings.TEMPLATES[0], "DIRS": [baseline / "templates"]}],
            STATICFILES_DIRS=[baseline / "static"],
            CSRF_COOKIE_NAME="taskflow4_csrf",
            SESSION_COOKIE_NAME="taskflow4_session",
        )
    instant = dt.datetime.fromisoformat(f"{TODAY}T12:00:00+08:00")
    with override_settings(**overrides), patch("django.utils.timezone.now", lambda: instant):
        call_command("runserver", f"127.0.0.1:{PORT}", use_reloader=False, insecure=True)


def api(page, path, body=None, method="POST"):
    return page.evaluate(
        """([path, body, method]) => api(path, body === null ? {} : {
            method, body, headers:{'Idempotency-Key':crypto.randomUUID()}
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
    return page.evaluate("state.user.id")


def login(page, name):
    page.locator("#login-tab").click()
    page.locator("#username").fill(name)
    page.locator("#password").fill(PASSWORD)
    page.locator("#auth-submit").click()
    expect(page.locator("#workspace")).to_be_visible()
    expect(page.locator("#load-summary .budget-chart")).to_be_visible()


def workspace(page):
    return api(page, "/api/load/workspace?week=2026-10-12&mode=week")


def refresh(page):
    page.evaluate("async () => { await loadTasks(); LoadWorkspace.invalidate(); }")
    expect(page.locator("#load-refresh")).to_be_enabled()


def patch_task(page, task_id, **values):
    current = api(page, f"/api/tasks/{task_id}/workspace")["task"]
    result = api(page, f"/api/tasks/{task_id}", {"version": current["version"], **values}, "PATCH")[
        "task"
    ]
    refresh(page)
    return result


def duration(page, field, minutes):
    hours, remainder = divmod(minutes, 60)
    page.locator(f"#{field}-hours").fill(str(hours))
    page.locator(f"#{field}-minutes").fill(str(remainder))


def measure(page, name):
    result = {}
    for label, width, height in [("desktop", 1440, 1000), ("mobile", 390, 844)]:
        page.set_viewport_size({"width": width, "height": height})
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(100)
        result[label] = page.evaluate("""() => {
            const position = (id) => { const el=document.getElementById(id);
                if (!el) return null; const r=el.getBoundingClientRect();
                return {top:r.top+scrollY,height:r.height,bottom:r.bottom+scrollY}; };
            return {width:innerWidth,height:innerHeight,pageWidth:document.documentElement.scrollWidth,
                budget:position('load-summary'),focus:position('overview-focus'),
                footprints:position('footprints-panel'),taskIntro:position('load-overview'),
                tasks:position('task-section')};
        }""")
        page.screenshot(path=str(ROOT / f"evidence/overview-{name}-{label}.png"), full_page=True)
    page.set_viewport_size({"width": 1440, "height": 1000})
    return result


def run_browser(baseline):
    checks, errors, external, writes = {}, [], [], []
    with sync_playwright() as playwright:
        options = {"headless": True}
        if Path("/Applications/Google Chrome.app").exists():
            options["channel"] = "chrome"
        browser = playwright.chromium.launch(**options)
        context = browser.new_context(
            viewport={"width": 1440, "height": 1000}, timezone_id="Asia/Shanghai"
        )
        context.route(
            "**/*",
            lambda route: (
                route.continue_()
                if route.request.url.startswith(BASE)
                else (external.append(route.request.url), route.abort())
            ),
        )
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("dialog", lambda dialog: dialog.accept())
        page.on(
            "request",
            lambda request: (
                writes.append((request.method, request.url))
                if request.method in {"POST", "PATCH", "DELETE"}
                else None
            ),
        )
        page.clock.install(time=f"{TODAY}T12:00:00+08:00")
        try:
            page.goto(BASE)
            owner = register(page, "overview_qa")
            focus = page.locator("#overview-focus")
            if not baseline:
                expect(focus).to_have_attribute("data-state", "empty")
                expect(page.locator("#overview-budget-first-hint")).to_be_visible()
                expect(page.locator("#footprints-toggle")).to_have_attribute(
                    "aria-expanded", "false"
                )
                expect(page.locator("#footprints-expanded-content")).not_to_be_visible()
                page.locator("#overview-focus-new").click()
                expect(page.locator("#task-dialog")).to_be_visible()
                expect(page.locator("#task-status")).to_have_value("planned")
                page.locator("#cancel-editor").click()
                page.locator('[data-route="overview"]').click()
                page.locator("#overview-focus-ideas").click()
                expect(page.locator("#workspace")).to_have_attribute("data-page", "tasks/planned")
                page.locator('[data-route="overview"]').click()
                checks["empty_state_new_idea_and_ideas_navigation"] = "pass"
            duration(page, "load-budget", 1200)
            duration(page, "load-buffer", 120)
            with page.expect_response("**/api/load/settings") as saved:
                page.locator('#load-capacity-form button[type="submit"]').click()
            assert saved.value.status == 200
            first = api(
                page,
                "/api/tasks",
                {
                    "title": "先完成一个小实验",
                    "status": "in_progress",
                    "weekly_minutes": 360,
                    "priority": "high",
                },
            )["task"]
            second = api(
                page,
                "/api/tasks",
                {
                    "title": "另一件可继续的事",
                    "status": "in_progress",
                    "weekly_minutes": 0,
                    "priority": "normal",
                },
            )["task"]
            current = api(page, f"/api/tasks/{first['id']}/workspace")["task"]
            api(
                page,
                f"/api/tasks/{first['id']}/workspace",
                {
                    "action": "time_add",
                    "version": current["version"],
                    "step_id": None,
                    "minutes": 60,
                    "date": TODAY,
                    "note": "已经投入一小时",
                },
            )
            refresh(page)
            chart = page.locator("#load-summary .budget-chart")
            expect(chart).to_have_attribute("data-demand-low", "360")
            expect(chart).to_have_attribute("data-available-low", "720")
            state_before = workspace(page)
            assert state_before["analysis"]["capacity"] == 1080
            assert state_before["actual"]["minutes"] == 60
            geometry = measure(page, "before" if baseline else "after")
            if baseline:
                assert focus.count() == 0
                assert page.locator("#footprints-toggle").count() == 0
                assert page.locator("#overview-budget-help").count() == 0
                return {
                    "expected_red": "phase4 lacks quick continue, collapse, and budget help",
                    "geometry": geometry,
                }
            checks["budget_20h_buffer_2h_active_6h_actual_1h_separate"] = "pass"
            expect(focus).to_have_attribute("data-task-id", first["id"])
            expect(page.locator("#overview-actual")).to_have_attribute("data-minutes", "60")
            expect(page.locator("#overview-actual")).to_contain_text("1 小时")
            expect(page.locator("#load-summary .load-summary-analysis")).not_to_be_visible()
            expect(page.locator("#load-summary .load-metrics")).not_to_be_visible()
            expect(chart.locator(".budget-feeling-badge")).to_contain_text("33.3%")
            sources = page.locator("#overview-budget-sources")
            expect(sources).not_to_have_attribute("open", "")
            expect(sources.locator("summary")).to_contain_text("2 项")
            for value in geometry.values():
                assert value["pageWidth"] <= value["width"], value
                assert value["budget"]["bottom"] <= value["focus"]["top"]
                assert value["focus"]["bottom"] <= value["footprints"]["top"]
                assert value["footprints"]["bottom"] <= value["taskIntro"]["top"]
            previous = json.loads((ROOT / "evidence/overview-browser-baseline.json").read_text())
            for viewport in geometry:
                assert (
                    geometry[viewport]["focus"]["top"]
                    < previous["geometry"][viewport]["tasks"]["top"]
                )
                assert (
                    geometry[viewport]["tasks"]["top"]
                    < previous["geometry"][viewport]["tasks"]["top"]
                )
            checks["single_summary_order_measured_height_improvement_both_viewports"] = "pass"
            # Budget guide and collapse only read, even while there is an unsaved draft.
            duration(page, "load-budget", 1275)
            writes.clear()
            page.locator("#overview-budget-help").click()
            guide = page.locator("#overview-budget-guide")
            expect(guide).to_be_visible()
            for phrase in [
                "20 小时",
                "2 小时",
                "6 小时",
                "18 小时",
                "12 小时",
                "33%",
                "不会自动再扣减",
                "睡眠",
                "留空",
            ]:
                expect(guide).to_contain_text(phrase)
            page.keyboard.press("Escape")
            expect(guide).not_to_be_visible()
            expect(page.locator("#overview-budget-help")).to_be_focused()
            page.locator("#footprints-toggle").click()
            expect(page.locator("#footprints-grid button[data-date]")).to_have_count(84)
            expect(page.locator("#footprints-expanded-content")).to_be_visible()
            page.locator("#footprints-toggle").click()
            sources.locator("summary").click()
            refresh(page)
            expect(sources).to_have_attribute("open", "")
            expect(page.locator("#load-budget-hours")).to_have_value("21")
            expect(page.locator("#load-budget-minutes")).to_have_value("15")
            assert writes == [], writes
            assert workspace(page)["fingerprint"] == state_before["fingerprint"]
            checks["help_keyboard_and_collapse_refresh_preserve_draft_no_writes"] = "pass"
            # Preserve original idempotency body/key after a failed save and help navigation.
            captured = []

            def fail_save(route):
                captured.append(
                    (route.request.headers.get("idempotency-key"), route.request.post_data_json)
                )
                route.fulfill(
                    status=503,
                    content_type="application/json",
                    body='{"error":{"message":"temporary"}}',
                )

            page.route("**/api/load/settings", fail_save)
            page.locator('#load-capacity-form button[type="submit"]').click()
            expect(page.locator("#load-retry-wrap")).to_be_visible()
            page.locator("#overview-budget-help").click()
            page.locator("#overview-budget-guide-close").click()
            expect(page.locator("#load-budget-minutes")).to_have_value("15")
            page.unroute("**/api/load/settings", fail_save)
            with page.expect_response("**/api/load/settings") as retried:
                page.locator("#load-retry").click()
            assert retried.value.status == 200
            assert (
                retried.value.request.headers.get("idempotency-key"),
                retried.value.request.post_data_json,
            ) == captured[0]
            expect(page.locator("#load-retry-wrap")).not_to_be_visible()
            checks["budget_503_retry_same_body_key_draft_survives_help"] = "pass"
            writes.clear()
            page.locator("#overview-focus-steps").click()
            expect(page.locator("#execution-dialog")).to_be_visible()
            expect(page.locator('[data-ex-tab="steps"]')).to_have_attribute("aria-current", "page")
            page.locator("#ex-close").click()
            page.locator("#overview-focus-ledger").click()
            expect(page.locator('[data-ex-tab="time"]')).to_have_attribute("aria-current", "page")
            page.locator("#ex-close").click()
            assert writes == [], writes
            expect(page.locator("#overview-focus-heading")).to_have_text("继续上次查看")
            assert page.evaluate(
                "key => localStorage.getItem(key)", f"liubai.phase5.overview.last-task.{owner}"
            ) == json.dumps(first["id"])
            page.evaluate("id => Execution.open(id, 'steps')", second["id"])
            expect(page.locator("#execution-dialog")).to_be_visible()
            page.locator("#ex-close").click()
            expect(focus).to_have_attribute("data-task-id", second["id"])
            page.locator("#search").fill("肯定找不到的文字")
            expect(page.locator(".task-card")).to_have_count(0)
            expect(focus).to_have_attribute("data-task-id", second["id"])
            page.locator("#search").fill("")
            checks["navigation_only_uuid_memory_search_independent"] = "pass"
            patch_task(page, second["id"], status="paused")
            expect(focus).to_have_attribute("data-task-id", first["id"])
            patch_task(page, second["id"], status="in_progress")
            expect(focus).to_have_attribute("data-task-id", second["id"])
            page.locator(f'button[data-delete-task="{second["id"]}"]').click()
            expect(focus).to_have_attribute("data-task-id", first["id"])
            page.locator("#task-trash-undo").click()
            expect(focus).to_have_attribute("data-task-id", second["id"])
            patch_task(page, second["id"], status="completed")
            expect(focus).to_have_attribute("data-task-id", first["id"])
            checks["pause_complete_delete_restore_refresh_selection"] = "pass"
            # A route's forced expansion must not replace the overview preference.
            sources.locator("summary").click()
            expect(sources).not_to_have_attribute("open", "")
            page.locator('[data-route="load"]').click()
            expect(sources).to_have_attribute("open", "")
            expect(page.locator("#load-summary .load-summary-analysis")).to_be_visible()
            expect(page.locator("#load-summary .load-metrics")).to_be_visible()
            page.locator('[data-route="overview"]').click()
            expect(sources).not_to_have_attribute("open", "")
            unknown = api(
                page,
                "/api/tasks",
                {
                    "title": "还没估时的进行中任务",
                    "status": "in_progress",
                    "weekly_minutes": None,
                    "priority": "low",
                },
            )["task"]
            refresh(page)
            expect(sources.locator("summary")).to_contain_text("有待补时间")
            expect(sources).not_to_have_attribute("open", "")
            patch_task(page, unknown["id"], status="paused")
            expect(sources.locator(".overview-source-warning")).not_to_be_visible()
            checks["source_unknown_warning_and_analysis_expansion_preserves_overview_choice"] = (
                "pass"
            )
            # Collapsed calendar still exposes yearly view and failed read/write recovery.
            expect(page.locator("#footprints-toggle")).to_have_attribute("aria-expanded", "false")
            page.locator("#footprints-year-open").click()
            expect(page.locator("#footprints-year-dialog")).to_be_visible()
            page.locator("#footprints-year-close").click()
            page.route("**/api/footprints/calendar*", lambda route: route.abort())
            page.evaluate("void Footprints.refresh()")
            expect(page.locator("#footprints-reload")).to_be_visible()
            page.unroute("**/api/footprints/calendar*")
            page.locator("#footprints-reload").click()
            expect(page.locator("#footprints-checkin")).to_be_enabled()
            page.route(
                "**/api/footprints/mark",
                lambda route: route.fulfill(
                    status=503,
                    content_type="application/json",
                    body='{"error":{"message":"temporary"}}',
                ),
            )
            page.locator("#footprints-checkin").click()
            expect(page.locator("#footprints-retry")).to_be_visible()
            page.unroute("**/api/footprints/mark")
            page.locator("#footprints-retry").click()
            expect(page.locator("#footprints-checkin")).to_be_disabled()
            checks["collapsed_year_checkin_error_reload_write_retry_accessible"] = "pass"
            page.locator("#footprints-toggle").click()
            page.reload()
            expect(focus).to_have_attribute("data-task-id", first["id"])
            expect(page.locator("#footprints-toggle")).to_have_attribute("aria-expanded", "true")
            page.locator("#logout").click()
            expect(page.locator("#auth-screen")).to_be_visible()
            assert first["title"] not in page.locator("body").text_content()
            other = register(page, "overview_other")
            assert other != owner
            expect(focus).to_have_attribute("data-state", "empty")
            expect(page.locator("#footprints-toggle")).to_have_attribute("aria-expanded", "false")
            assert first["title"] not in page.locator("body").text_content()
            page.locator("#logout").click()
            login(page, "overview_qa")
            expect(focus).to_have_attribute("data-task-id", first["id"])
            expect(page.locator("#footprints-toggle")).to_have_attribute("aria-expanded", "true")
            checks["account_scoped_uuid_and_expansion_restored_no_private_leak"] = "pass"
            page.evaluate(
                "id => { localStorage.setItem('liubai.phase5.overview.last-task.'+id, '{broken'); localStorage.setItem('liubai.phase5.footprints.expanded.'+id,'garbage'); }",
                owner,
            )
            page.reload()
            expect(focus).to_have_attribute("data-task-id", first["id"])
            expect(page.locator("#footprints-toggle")).to_have_attribute("aria-expanded", "false")
            page.add_init_script(
                "Storage.prototype.getItem = Storage.prototype.setItem = () => {throw new DOMException('Blocked','SecurityError');};"
            )
            page.reload()
            expect(focus).to_have_attribute("data-task-id", first["id"])
            page.locator("#overview-focus-steps").click()
            expect(page.locator("#execution-dialog")).to_be_visible()
            page.locator("#ex-close").click()
            page.locator("#footprints-toggle").click()
            expect(page.locator("#footprints-toggle")).to_have_attribute("aria-expanded", "true")
            checks["malformed_and_blocked_storage_safe_in_memory_fallback"] = "pass"
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            sizes = page.evaluate(
                """() => Object.fromEntries(['new-task','overview-budget-help','overview-focus-steps','overview-focus-ledger','footprints-toggle','footprints-year-open','load-budget-hours','load-budget-minutes','load-buffer-hours','load-buffer-minutes','search'].map(id => [id,document.getElementById(id).getBoundingClientRect().height]))"""
            )
            assert all(size >= 40 for size in sizes.values()), sizes
            checks["390px_no_horizontal_overflow_common_controls_40px"] = sizes
            fonts = page.evaluate(
                """() => Object.fromEntries(['#load-window-help','#load-budget-editor-help','.budget-chart-head p','.budget-feeling-basis','.budget-chart-legend dt','#overview-actual span','#overview-focus-copy','#footprints-summary','.task-sub','.task-time'].map(selector => [selector,parseFloat(getComputedStyle(document.querySelector(selector)).fontSize)]))"""
            )
            assert all(size >= 12 for size in fonts.values()), fonts
            checks["390px_sampled_overview_explanatory_text_at_least_12px"] = fonts
            assert not errors, errors
            assert not external, external
            return {
                "checks": checks,
                "geometry": geometry,
                "page_errors": errors,
                "external_requests": external,
                "installed_state_read": False,
            }
        except Exception:
            page.screenshot(path=str(ROOT / "evidence/overview-failure.png"), full_page=True)
            (ROOT / "evidence/overview-browser-partial.json").write_text(
                json.dumps({"checks": checks, "errors": errors}, ensure_ascii=False, indent=2)
            )
            raise
        finally:
            browser.close()


def main():
    global PORT, BASE
    baseline = "--baseline" in sys.argv
    (ROOT / "evidence").mkdir(exist_ok=True)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        PORT = probe.getsockname()[1]
    BASE = f"http://127.0.0.1:{PORT}"
    with tempfile.TemporaryDirectory(prefix="liubai-overview-") as name:
        directory = Path(name)
        environment = {
            **os.environ,
            "TASKFLOW_DB": str(directory / "qa.sqlite3"),
            "TASKFLOW_STATE_DIR": str(directory / ".local"),
            "DEEPSEEK_API_KEY": "",
            "DEEPSEEK_MODEL": "",
            "OVERVIEW_BASELINE": "1" if baseline else "0",
            "OVERVIEW_QA_PORT": str(PORT),
        }
        python = str(ROOT / ".venv/bin/python")
        subprocess.run(
            [python, "manage.py", "migrate", "--noinput"],
            cwd=ROOT,
            env=environment,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        with (ROOT / "evidence/overview-server.log").open("w") as log:
            server = subprocess.Popen(
                [python, __file__, "--server", name],
                cwd=ROOT,
                env=environment,
                stdout=log,
                stderr=log,
            )
            try:
                for _ in range(100):
                    assert server.poll() is None, "Temporary overview server exited"
                    try:
                        with urllib.request.urlopen(BASE, timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(0.1)
                else:
                    raise AssertionError("Temporary overview server did not start")
                result = run_browser(baseline)
                suffix = "-baseline" if baseline else ""
                (ROOT / f"evidence/overview-browser{suffix}.json").write_text(
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
