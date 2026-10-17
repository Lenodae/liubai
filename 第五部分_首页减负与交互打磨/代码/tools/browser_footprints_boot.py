"""Reproduce delayed-module authenticated boot in a disposable localhost workspace."""

import argparse
import asyncio
import json
import os
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.async_api import TimeoutError as BrowserTimeout
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8042"


async def browser_run():
    external = []
    early = []
    errors = []
    async with async_playwright() as playwright:
        options = {"headless": True}
        if Path("/Applications/Google Chrome.app").exists():
            options["channel"] = "chrome"
        browser = await playwright.chromium.launch(**options)
        context = await browser.new_context(timezone_id="Asia/Shanghai")

        async def local_only(route):
            if route.request.url.startswith(BASE):
                await route.continue_()
            else:
                external.append(route.request.url)
                await route.abort()

        await context.route("**/*", local_only)
        page = await context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        await page.goto(BASE)
        await page.locator("#register-tab").click()
        await page.locator("#username").fill("delayed_module_fixture")
        await page.locator("#password").fill("Moss!River84Corner")
        await page.locator("#auth-submit").click()
        await page.wait_for_function(
            'state.user && document.querySelectorAll("#footprints-grid button").length === 84'
        )

        async def delay_module(route):
            await asyncio.sleep(3)
            early.append(
                await page.evaluate(
                    "({loggedIn:typeof state !== 'undefined' && !!state.user,"
                    "footprintsRegistered:!!window.Footprints,"
                    "readyState:document.readyState})"
                )
            )
            await route.continue_()

        await page.route("**/static/footprints.js", delay_module)
        await page.reload()
        try:
            await page.wait_for_function(
                'document.querySelectorAll("#footprints-grid button").length === 84',
                timeout=5000,
            )
        except BrowserTimeout:
            pass
        actual = await page.evaluate(
            "({loggedIn:!!state.user,footprintsRegistered:!!window.Footprints,"
            'calendarDays:document.querySelectorAll("#footprints-grid button").length,'
            'checkinDisabled:document.getElementById("footprints-checkin").disabled,'
            'summary:document.getElementById("footprints-summary").textContent})'
        )
        await browser.close()
    return {
        "test_state": "synthetic isolated database; no installed state or keys read",
        "delayed_static_resource_ms": 3000,
        "before_script_release": early,
        "after_boot": actual,
        "external_requests": external,
        "browser_errors": errors,
        "pass": actual["calendarDays"] == 84
        and not actual["checkinDisabled"]
        and not errors
        and not external,
    }


def main():
    global BASE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--red", action="store_true")
    args = parser.parse_args()
    with socket.socket() as port:
        port.bind(("127.0.0.1", 0))
        address = f"127.0.0.1:{port.getsockname()[1]}"
    BASE = f"http://{address}"
    with tempfile.TemporaryDirectory(prefix="liubai-boot-review-") as temporary:
        state = Path(temporary)
        environment = {
            **os.environ,
            "TASKFLOW_STATE_DIR": str(state),
            "TASKFLOW_DB": str(state / "tasks.sqlite3"),
            "DEEPSEEK_API_KEY": "",
        }
        command = [str(ROOT / ".venv/bin/python"), "manage.py"]
        subprocess.run(
            [*command, "migrate", "--noinput"],
            env=environment,
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            check=True,
        )
        with (state / "server.log").open("w") as log:
            server = subprocess.Popen(
                [*command, "runserver", address, "--noreload", "--insecure"],
                env=environment,
                cwd=ROOT,
                stdout=log,
                stderr=log,
            )
            try:
                for _ in range(100):
                    assert server.poll() is None, "Temporary boot server exited"
                    try:
                        with urllib.request.urlopen(BASE, timeout=1):
                            break
                    except OSError:
                        time.sleep(0.1)
                else:
                    raise AssertionError("Temporary boot server did not become ready")
                report = asyncio.run(browser_run())
            finally:
                server.terminate()
                server.wait(timeout=10)
    evidence = ROOT / "evidence"
    evidence.mkdir(exist_ok=True)
    suffix = "-red" if args.red else ""
    (evidence / f"footprints-boot{suffix}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(report, ensure_ascii=False))
    assert report["pass"], "Authenticated boot skipped the late-loaded footprints module"


if __name__ == "__main__":
    main()
