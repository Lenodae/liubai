"""Daily encouragement acceptance on disposable SQLite and localhost:8034.

The browser clock checks calendar behavior without changing the computer clock.
No installed database, account, provider key, or external service is used.
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

expect.set_options(timeout=15000)
ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8034"
CORPUS = "/static/data/daily_encouragement.json"
PASSWORD = "Moss!River84Corner"


def serve(directory):
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from django.core.management import call_command
    from django.test import override_settings

    with override_settings(BASE_DIR=Path(directory)):
        call_command("runserver", "127.0.0.1:8034", use_reloader=False, insecure=True)


def wait_server(server):
    for _ in range(100):
        assert server.poll() is None, "Temporary daily encouragement server exited"
        try:
            with urllib.request.urlopen(BASE, timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.1)
    raise AssertionError("Temporary daily encouragement server did not become ready")


def register(page):
    page.locator("#register-tab").click()
    page.locator("#username").fill("daily_encouragement_qa")
    page.locator("#password").fill(PASSWORD)
    page.locator("#auth-submit").click()
    expect(page.locator("#workspace")).to_be_visible()
    expect(page.locator("#load-summary .budget-chart")).to_be_visible()


def run_browser():
    corpus = json.loads((ROOT / "static/data/daily_encouragement.json").read_text())
    quotes = corpus["quotes"]
    assert corpus["version"] == 1
    assert len(quotes) == 300
    assert len({quote["id"] for quote in quotes}) == 300
    assert len({quote["text"].strip() for quote in quotes}) == 300
    assert all(quote["text"].strip() and quote["source"].strip() for quote in quotes)
    checks = {"local_corpus_300_unique_quotes_with_sources": "pass"}
    errors, external, business_writes = [], [], []

    def local_only(route):
        if route.request.url.startswith(BASE):
            route.continue_()
        else:
            external.append(route.request.url)
            route.abort()

    with sync_playwright() as playwright:
        options = {"headless": True}
        if Path("/Applications/Google Chrome.app").exists():
            options["channel"] = "chrome"
        browser = playwright.chromium.launch(**options)
        context = browser.new_context(
            viewport={"width": 1440, "height": 1050}, timezone_id="Asia/Shanghai"
        )
        context.route("**/*", local_only)
        context.on("page", lambda page: page.on("pageerror", lambda e: errors.append(str(e))))
        page = context.new_page()
        page.set_default_timeout(15000)
        page.clock.install(time="2026-10-15T12:00:00+08:00")
        page.clock.pause_at("2026-10-15T12:00:00+08:00")
        card = page.locator("#daily-encouragement")
        text = page.locator("#daily-encouragement-text")
        date = page.locator("#daily-encouragement-date")

        def current_quote():
            return page.evaluate("() => DailyEncouragement.quoteForDate(new Date())")

        def calendar_quote(iso):
            return page.evaluate("iso => DailyEncouragement.quoteForDate(new Date(iso))", iso)

        try:
            page.goto(BASE)
            expect(card).not_to_be_visible()
            register(page)
            expect(card).to_be_visible()
            page.wait_for_function(
                "texts => texts.includes(document.querySelector('#daily-encouragement-text').textContent)",
                arg=[quote["text"] for quote in quotes],
            )
            expect(text).to_have_text(current_quote()["text"])
            expect(date).to_have_attribute("datetime", "2026-10-15")
            page.on(
                "request",
                lambda request: (
                    business_writes.append(request.url)
                    if "/api/" in request.url and request.method not in ("GET", "HEAD", "OPTIONS")
                    else None
                ),
            )
            first = text.inner_text()
            page.reload()
            expect(card).to_be_visible()
            expect(text).to_have_text(first)
            checks["login_overview_same_local_day_stable_after_reload"] = "pass"

            # Calendar days, not elapsed 24-hour intervals or UTC dates, select a quote.
            days = page.evaluate(
                """() => Array.from({length:301}, (_, i) => {
                    const day = new Date(2026, 9, 15 + i, 12);
                    return DailyEncouragement.quoteForDate(day);
                })"""
            )
            assert len({quote["id"] for quote in days[:300]}) == 300
            assert len({quote["text"] for quote in days[:300]}) == 300
            assert days[0] == days[300]
            for before, after in [
                ("2026-10-31T23:59:59+08:00", "2026-11-01T00:00:00+08:00"),
                ("2026-12-31T23:59:59+08:00", "2027-01-01T00:00:00+08:00"),
                ("2028-02-28T23:59:59+08:00", "2028-02-29T00:00:00+08:00"),
                ("2028-02-29T23:59:59+08:00", "2028-03-01T00:00:00+08:00"),
            ]:
                assert calendar_quote(before)["id"] != calendar_quote(after)["id"]
            assert calendar_quote("2026-10-15T00:00:00+08:00") == calendar_quote(
                "2026-10-15T23:59:59+08:00"
            )
            assert calendar_quote("2026-10-15T00:00:00+08:00") != calendar_quote(
                "2026-10-14T23:59:59+08:00"
            )
            checks["300_calendar_days_unique_then_repeat_month_year_leap_day_local_midnight"] = (
                "pass"
            )

            page.clock.pause_at("2026-10-15T23:59:59+08:00")
            expect(text).to_have_text(first)
            page.clock.run_for(2000)
            expect(date).to_have_attribute("datetime", "2026-10-16")
            expect(text).to_have_text(current_quote()["text"])
            assert text.inner_text() != first
            checks["open_page_updates_automatically_at_local_midnight"] = "pass"

            # A suspended tab may miss its timer; focus/visibility must catch up.
            page.clock.set_system_time("2026-10-17T08:00:00+08:00")
            page.evaluate("window.dispatchEvent(new Event('focus'))")
            expect(date).to_have_attribute("datetime", "2026-10-17")
            expect(text).to_have_text(current_quote()["text"])
            page.clock.set_system_time("2026-10-18T09:00:00+08:00")
            page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
            expect(date).to_have_attribute("datetime", "2026-10-18")
            expect(text).to_have_text(current_quote()["text"])
            checks["resumed_tab_focus_and_visibility_recover_missed_days"] = "pass"

            for selector, route in [
                ('[data-tab="planned"]', "tasks/planned"),
                ('[data-route="load"]', "load"),
                ('[data-tab="trash"]', "tasks/trash"),
            ]:
                page.locator(selector).click()
                expect(page.locator("#workspace")).to_have_attribute("data-page", route)
                expect(card).not_to_be_visible()
                page.locator('[data-route="overview"]').click()
                expect(page.locator("#workspace")).to_have_attribute("data-page", "overview")
                expect(card).to_be_visible()
                expect(text).to_have_text(current_quote()["text"])
            assert business_writes == [], business_writes
            checks["overview_only_navigation_and_reading_do_not_write_tasks_or_budget"] = "pass"
            # Keep the review screenshots on the actual client date after clock scenarios.
            page.clock.set_system_time("2026-10-15T12:00:00+08:00")
            page.reload()
            expect(date).to_have_attribute("datetime", "2026-10-15")
            expect(text).to_have_text(quotes[0]["text"])
            expect(page.locator("#daily-encouragement-source")).to_have_text("— 墨韩")
            page.screenshot(
                path=str(ROOT / "evidence/daily-encouragement-desktop.png"), full_page=True
            )

            page.set_viewport_size({"width": 390, "height": 844})
            expect(card).to_be_visible()
            bounds = card.bounding_box()
            assert bounds and bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= 391
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            assert text.evaluate("node => node.scrollWidth <= node.clientWidth")
            page.screenshot(
                path=str(ROOT / "evidence/daily-encouragement-mobile.png"), full_page=True
            )
            checks["390px_card_and_text_do_not_overflow"] = "pass"

            # Failure is isolated to the quote card. Real budget and idea writes still work.
            page.route(f"**{CORPUS}*", lambda route: route.abort("failed"))
            page.reload()
            expect(card).to_be_visible()
            expect(text).not_to_be_empty()
            expect(page.locator("#daily-encouragement-source")).to_contain_text("留白")
            expect(page.locator("#daily-encouragement-retry")).to_be_visible()
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
            page.locator("#new-task").click()
            page.locator("#task-title").fill("每日鼓励暂未载入也能记下想法")
            with page.expect_response(
                lambda response: (
                    response.url.endswith("/api/tasks") and response.request.method == "POST"
                )
            ) as created:
                page.locator("#save-task").click()
            assert created.value.status == 201, created.value.text()
            assert created.value.json()["task"]["status"] == "planned"
            expect(page.locator("#task-dialog")).not_to_be_visible()
            # Recording an idea intentionally opens the existing budget result dialog.
            expect(page.locator("#budget-reservation-dialog")).to_be_visible()
            page.locator("#budget-reservation-close").click()
            expect(page.locator("#budget-reservation-dialog")).not_to_be_visible()
            checks["corpus_failure_fallback_preserves_budget_save_and_idea_create"] = "pass"
            page.unroute(f"**{CORPUS}*")
            page.locator("#daily-encouragement-retry").click()
            page.wait_for_function(
                "texts => texts.includes(document.querySelector('#daily-encouragement-text').textContent)",
                arg=[quote["text"] for quote in quotes],
            )
            expect(page.locator("#daily-encouragement-retry")).not_to_be_visible()
            expect(text).to_have_text(current_quote()["text"])
            checks["failed_local_fetch_can_be_retried_without_reload"] = "pass"

            page.locator("#logout").click()
            expect(page.locator("#auth-screen")).to_be_visible()
            expect(card).not_to_be_visible()
            checks["logout_hides_daily_card"] = "pass"
            assert not errors, errors
            assert not external, external
            return {
                "checks": checks,
                "page_errors": errors,
                "external_requests": external,
                "real_database_or_secret_contents_read": False,
                "browser_timezone": "Asia/Shanghai",
            }
        except Exception:
            page.screenshot(
                path=str(ROOT / "evidence/daily-encouragement-failure.png"), full_page=True
            )
            raise
        finally:
            browser.close()


def main():
    (ROOT / "evidence").mkdir(exist_ok=True)
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", 8034))
    with tempfile.TemporaryDirectory(prefix="liubai-daily-encouragement-") as name:
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
        with (ROOT / "evidence/daily-encouragement-server.log").open("w") as log:
            server = subprocess.Popen(
                [python, __file__, "--server", str(directory)],
                cwd=ROOT,
                env=environment,
                stdout=log,
                stderr=log,
            )
            try:
                wait_server(server)
                result = run_browser()
                (ROOT / "evidence/daily-encouragement-browser.json").write_text(
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
