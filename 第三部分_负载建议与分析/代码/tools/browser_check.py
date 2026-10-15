"""Real-browser acceptance against an isolated database; never writes user data."""

import json
import os
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

# Account creation performs the production password hash; allow for local CPU contention.
expect.set_options(timeout=15000)

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8027"
PASSWORD = "Moss!River84Corner"


def wait_server():
    for _ in range(80):
        try:
            with urllib.request.urlopen(BASE) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.15)
    raise RuntimeError("QA server did not start")


def register(page, name):
    page.goto(BASE)
    page.locator("#register-tab").click()
    page.locator("#username").fill(name)
    page.locator("#password").fill(PASSWORD)
    page.locator("#auth-submit").click()
    expect(page.locator("#workspace")).to_be_visible()
    expect(page.locator("#account-name")).to_have_text(name)
    expect(page.locator("#empty")).to_be_visible()


def login(page, name):
    page.locator("#login-tab").click()
    page.locator("#username").fill(name)
    page.locator("#password").fill(PASSWORD)
    page.locator("#auth-submit").click()
    expect(page.locator("#workspace")).to_be_visible()


def new_task(page, title, hours="", status="in_progress"):
    page.locator("#new-task").click()
    page.locator("#task-title").fill(title)
    page.locator("#task-more-settings > summary").click()
    page.locator("#task-hours").fill(hours)
    page.locator("#task-status").select_option(status)
    page.locator("#save-task").click()
    expect(page.locator("#task-dialog")).not_to_be_visible()
    expect(page.locator("#budget-reservation-dialog")).to_be_visible()
    expect(page.locator("#budget-reservation-result .budget-chart")).to_be_visible()
    if status == "planned":
        expect(page.locator("#budget-reservation-task")).to_contain_text("不占用预算")
        page.locator("#budget-reservation-ideas").click()
    else:
        page.locator("#budget-reservation-done").click()
    expect(page.locator(".task-name").filter(has_text=title)).to_be_visible()


def expire(context):
    token = next(c["value"] for c in context.cookies() if c["name"] == "taskflow3_csrf")
    response = context.request.post(f"{BASE}/api/auth/logout", headers={"X-CSRFToken": token})
    assert response.status == 200


def run_browser():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        a = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = a.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("dialog", lambda dialog: dialog.accept())
        page.goto(BASE)
        expect(page.locator("#auth-screen")).to_be_visible()
        page.screenshot(path=str(ROOT / "evidence/login.png"), full_page=True)
        register(page, "qa_alice")
        page.screenshot(path=str(ROOT / "evidence/empty.png"), full_page=True)
        new_task(page, "隔离验收：修改论文实验图", "8")
        row = page.locator(".task-card").filter(has_text="隔离验收：修改论文实验图")
        expect(row).to_contain_text("8 小时")
        tid = row.get_attribute("data-task-id")
        page.reload()
        expect(page.locator(".task-name")).to_have_text("隔离验收：修改论文实验图")
        row = page.locator(".task-card").filter(has_text="隔离验收：修改论文实验图")
        row.click()
        page.locator("#task-title").fill("不应保存的修改")
        page.locator("#cancel-editor").click()
        expect(page.locator(".task-name")).to_have_text("隔离验收：修改论文实验图")
        row.click()
        page.locator("#task-title").fill("隔离验收：修改论文实验图 · 第二版")
        page.route("**/api/tasks/*", lambda route: route.abort())
        page.locator("#save-task").click()
        expect(page.locator("#save-error")).to_contain_text("未保存")
        expect(page.locator("#task-title")).to_have_value("隔离验收：修改论文实验图 · 第二版")
        page.unroute("**/api/tasks/*")
        page.locator("#save-task").click()
        expect(page.locator("#task-dialog")).not_to_be_visible()
        page.locator(".task-card").click()
        page.get_by_role("button", name="暂停一下", exact=True).click()
        expect(page.locator("#task-dialog")).not_to_be_visible()
        page.locator('[data-tab="paused"]').click()
        expect(page.locator("#page-title")).to_contain_text("暂停一下")
        page.locator(".task-card").click()
        page.get_by_role("button", name="恢复进行", exact=True).click()
        expect(page.locator("#task-dialog")).not_to_be_visible()
        page.locator('[data-tab="in_progress"]').click()
        expect(page.locator("#page-title")).to_contain_text("当前清单")
        assert page.locator(".task-card").get_attribute("data-task-id") == tid
        page.locator(".task-card").click()
        page.get_by_role("button", name="标记完成", exact=True).click()
        expect(page.locator("#execution-dialog")).to_be_visible()
        page.locator("#ex-complete-note").fill("完成验收任务")
        page.get_by_role("button", name="确认完成", exact=True).click()
        expect(page.locator("#ex-notice")).to_have_text("已保存。")
        page.locator("#ex-close").click()
        page.locator('[data-tab="history"]').click()
        expect(page.locator("#page-title")).to_contain_text("历史记录")
        page.locator(".task-card").click()
        expect(page.locator("#event-list li")).to_have_count(3)
        page.get_by_role("button", name="恢复进行", exact=True).click()
        expect(page.locator("#task-dialog")).not_to_be_visible()
        page.locator('[data-tab="in_progress"]').click()
        new_task(page, "学习 Transformer 的注意力机制", "3.5")
        new_task(page, "整理这一周的生活记录", "")
        page.locator("#search").fill("注意力")
        expect(page.locator(".task-card")).to_have_count(1)
        page.locator("#search").fill("")
        expect(page.locator(".task-card")).to_have_count(3)
        page.screenshot(path=str(ROOT / "evidence/workspace.png"), full_page=True)
        page.locator(".task-card").filter(has_text="修改论文").click()
        page.screenshot(path=str(ROOT / "evidence/editor.png"), full_page=True)
        page.locator("#cancel-editor").click()
        page.locator("#logout").click()
        expect(page.locator("#auth-screen")).to_be_visible()
        login(page, "qa_alice")
        expect(page.locator(".task-card")).to_have_count(3)
        b = browser.new_context(viewport={"width": 1280, "height": 900})
        bob = b.new_page()
        register(bob, "qa_bob")
        assert b.request.get(f"{BASE}/api/tasks/{tid}").status == 404
        token = next(c["value"] for c in b.cookies() if c["name"] == "taskflow3_csrf")
        assert (
            b.request.patch(
                f"{BASE}/api/tasks/{tid}",
                data={"version": 1, "title": "stolen"},
                headers={"X-CSRFToken": token},
            ).status
            == 404
        )
        expect(bob.locator(".task-card")).to_have_count(0)
        page.locator(".task-card").filter(has_text="修改论文").click()
        page.locator("#task-title").fill("仅甲可恢复的未保存草稿")
        expire(a)
        page.locator("#save-task").click()
        expect(page.locator("#auth-screen")).to_be_visible()
        login(page, "qa_alice")
        expect(page.locator("#draft-recovery")).to_be_visible()
        page.locator("#restore-draft").click()
        expect(page.locator("#task-dialog")).to_be_visible()
        expect(page.locator("#task-title")).to_have_value("仅甲可恢复的未保存草稿")
        page.locator("#cancel-editor").click()
        page.locator(".task-card").filter(has_text="修改论文").click()
        page.locator("#task-title").fill("绝不能让乙看到的草稿")
        expire(a)
        page.locator("#save-task").click()
        expect(page.locator("#auth-screen")).to_be_visible()
        login(page, "qa_bob")
        expect(page.locator("#task-dialog")).not_to_be_visible()
        expect(page.locator("#empty")).to_be_visible()
        assert "绝不能让乙看到的草稿" not in page.content()
        assert "隔离验收：修改论文实验图" not in page.content()
        page.locator("#logout").click()
        expect(page.locator("#auth-screen")).to_be_visible()
        login(page, "qa_alice")
        new_task(page, '<img src=x onerror="window.hacked=1">', "0", "planned")
        assert page.evaluate("window.hacked") is None
        expect(page.locator(".task-card")).to_contain_text("0 分钟")
        page.locator('[data-tab="in_progress"]').click()
        expect(page.locator(".task-card")).to_have_count(3)
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(ROOT / "evidence/mobile.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.locator("#new-task").click()
        expect(page.locator("#task-dialog")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.locator("#cancel-editor").click()
        assert not errors, errors
        browser.close()
        return {
            "browser": "Chrome via Playwright",
            "checks": [
                "register/login/logout",
                "empty state",
                "create/edit/cancel",
                "network failure retains input",
                "pause/resume/history",
                "search",
                "reload/relogin persistence",
                "cross-account read/write rejected",
                "same-user draft recovery",
                "different-user draft isolation",
                "XSS text rendering",
                "zero vs unknown",
                "390px mobile no overflow",
            ],
            "page_errors": errors,
        }


def main():
    with tempfile.TemporaryDirectory(prefix="taskflow-qa-") as tmp:
        env = {
            **os.environ,
            "TASKFLOW_DB": str(Path(tmp) / "qa.sqlite3"),
            "TASKFLOW_STATE_DIR": str(Path(tmp) / "state"),
        }
        python = str(ROOT / ".venv/bin/python")
        subprocess.run(
            [python, "manage.py", "migrate", "--noinput"],
            cwd=ROOT,
            env=env,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        with (ROOT / "evidence/browser-server.log").open("w") as log:
            server = subprocess.Popen(
                [python, "manage.py", "runserver", "127.0.0.1:8027", "--noreload", "--insecure"],
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=log,
            )
            try:
                wait_server()
                result = run_browser()
                # Restart the actual server with the same database; verify session + records survived.
                server.terminate()
                server.wait(timeout=10)
                server = subprocess.Popen(
                    [
                        python,
                        "manage.py",
                        "runserver",
                        "127.0.0.1:8027",
                        "--noreload",
                        "--insecure",
                    ],
                    cwd=ROOT,
                    env=env,
                    stdout=log,
                    stderr=log,
                )
                wait_server()
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(channel="chrome", headless=True)
                    page = browser.new_page()
                    page.goto(BASE)
                    login(page, "qa_alice")
                    expect(page.locator(".task-card")).to_have_count(3)
                    browser.close()
                result["restart_persistence"] = "pass"
                (ROOT / "evidence/browser.json").write_text(
                    json.dumps(result, ensure_ascii=False, indent=2)
                )
                print(json.dumps(result, ensure_ascii=False, indent=2))
            finally:
                server.terminate()
                server.wait(timeout=10)


if __name__ == "__main__":
    main()
