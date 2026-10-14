"""Real browser checks against a disposable database, with no external API calls."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

from browser_check import BASE, PASSWORD, wait_server
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def run():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1100})
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("dialog", lambda dialog: dialog.accept())
        page.goto(BASE)
        page.locator("#register-tab").click()
        page.locator("#username").fill("phase2_qa")
        page.locator("#password").fill(PASSWORD)
        page.locator("#auth-submit").click()
        expect(page.locator("#workspace")).to_be_visible()
        page.locator("#new-task").click()
        page.locator("#task-title").fill("做出一个最小注意力示例")
        page.locator("#task-status").select_option("in_progress")
        page.locator("#task-hours").fill("4")
        page.locator("#save-task").click()
        expect(page.locator(".task-card")).to_have_count(1)
        page.locator(".task-card").click()
        page.get_by_role("button", name="分析与执行 ↗").click()
        expect(page.locator("#execution-dialog")).to_be_visible()
        page.locator("#ex-criterion").fill("代码运行，并与手算结果一致")
        page.locator("#ex-foundation").fill("Python 与矩阵基础")
        page.locator("#ex-available").fill("480")
        page.get_by_role("button", name="保存目标与条件", exact=True).click()
        expect(page.locator("#ex-notice")).to_have_text("已保存。")
        page.locator("#ex-ai-consent").check()
        page.locator("#ex-generate").click()
        expect(page.locator("#ex-runs")).to_contain_text("等待生成")
        page.get_by_role("button", name="取消生成", exact=True).click()
        expect(page.locator("#ex-runs")).to_contain_text("已取消")
        expect(page.locator(".ex-step")).to_have_count(0)
        page.locator("#ex-node-0-title").fill("手算一个小例子")
        page.locator("#ex-node-0-criterion").fill("写出每一步结果")
        page.locator("#ex-node-0-low").fill("60")
        page.locator("#ex-node-0-high").fill("120")
        page.locator("#ex-add-node").click()
        page.locator("#ex-node-1-title").fill("写出可运行代码")
        page.locator("#ex-node-1-criterion").fill("结果与手算一致")
        page.locator("#ex-node-1-low").fill("240")
        page.locator("#ex-node-1-high").fill("420")
        page.locator("#ex-node-1-depends").fill("1")
        page.get_by_role("button", name="保存草稿", exact=True).click()
        expect(page.locator("#ex-draft-label")).to_contain_text("第 1 版")
        page.locator("#execution-dialog").evaluate("el => el.scrollTop = 0")
        page.screenshot(path=str(ROOT / "evidence/phase2-plan.png"), full_page=True)
        page.locator("#ex-apply").click()
        expect(page.locator(".ex-step")).to_have_count(2)
        expect(page.locator("#ex-analysis")).to_contain_text("覆盖估时下限")
        first = page.locator(".ex-step").first
        first.get_by_role("button", name="开始", exact=True).click()
        expect(first.locator(".ex-status")).to_have_text("进行中")
        first.get_by_role("button", name="记一次时间", exact=True).click()
        page.locator("#ex-time-minutes").fill("90")
        page.locator("#ex-time-note").fill("第一次学习")
        # The request fails before reaching the server. Retrying must retain input and use the same packet.
        page.route(
            "**/workspace",
            lambda route: route.abort() if route.request.method == "POST" else route.continue_(),
        )
        page.get_by_role("button", name="保存耗时记录", exact=True).click()
        expect(page.locator("#ex-error")).to_contain_text("未保存")
        expect(page.locator("#ex-time-minutes")).to_have_value("90")
        page.unroute("**/workspace")
        page.locator("#ex-retry").click()
        expect(page.locator(".ex-entry")).to_have_count(1)
        expect(page.locator("#ex-summary")).to_contain_text("90 分钟")
        page.locator('[data-ex-tab="steps"]').click()
        first.get_by_role("button", name="登记完成", exact=True).click()
        page.locator("#ex-extra").fill("30")
        page.locator("#ex-complete-note").fill("核对完成")
        page.locator("#ex-complete-verified").check()
        page.get_by_role("button", name="确认完成", exact=True).click()
        expect(first.locator(".ex-status")).to_have_text("完成")
        expect(page.locator("#ex-summary")).to_contain_text("120 分钟")
        page.locator("#execution-dialog").evaluate("el => el.scrollTop = 0")
        page.screenshot(path=str(ROOT / "evidence/phase2-steps.png"), full_page=True)
        first.get_by_role("button", name="撤销完成", exact=True).click()
        expect(first.locator(".ex-status")).to_have_text("进行中")
        expect(page.locator("#ex-summary")).to_contain_text("120 分钟")
        page.locator('[data-ex-tab="time"]').click()
        page.locator(".ex-entry").first.get_by_role("button", name="修改", exact=True).click()
        page.locator("#ex-time-minutes").fill("45")
        page.get_by_role("button", name="保存耗时记录", exact=True).click()
        expect(page.locator("#ex-summary")).to_contain_text("135 分钟")
        page.locator("#ex-verify").click()
        expect(page.locator("#ex-summary")).to_contain_text("你已确认记录完整")
        page.locator("#execution-dialog").evaluate("el => el.scrollTop = 0")
        page.screenshot(path=str(ROOT / "evidence/phase2-ledger.png"), full_page=True)
        page.locator("#ex-close").click()
        page.reload()
        page.locator(".task-card").click()
        page.get_by_role("button", name="分析与执行 ↗").click()
        expect(page.locator("#ex-summary")).to_contain_text("135 分钟")
        page.set_viewport_size({"width": 390, "height": 844})
        page.locator('[data-ex-tab="steps"]').click()
        page.locator("#execution-dialog").evaluate("el => el.scrollTop = 0")
        page.screenshot(path=str(ROOT / "evidence/phase2-mobile.png"), full_page=True)
        assert page.evaluate(
            'document.querySelector("#execution-dialog").scrollWidth <= window.innerWidth'
        )
        # Session expiry retains only the original user's draft; a different login clears it.
        page.locator('[data-ex-tab="plan"]').click()
        page.locator("#ex-criterion").fill("本账号未保存内容")
        token = next(c["value"] for c in context.cookies() if c["name"] == "taskflow2_csrf")
        assert (
            context.request.post(BASE + "/api/auth/logout", headers={"X-CSRFToken": token}).status
            == 200
        )
        page.get_by_role("button", name="保存目标与条件", exact=True).click()
        expect(page.locator("#auth-screen")).to_be_visible()
        page.locator("#username").fill("phase2_qa")
        page.locator("#password").fill(PASSWORD)
        page.locator("#auth-submit").click()
        expect(page.locator("#execution-dialog")).to_be_visible()
        expect(page.locator("#ex-criterion")).to_have_value("本账号未保存内容")
        page.locator("#ex-retry").click()
        expect(page.locator("#ex-notice")).to_have_text("已保存。")
        page.locator("#ex-criterion").fill("不能给其他账号看到的内容")
        token = next(c["value"] for c in context.cookies() if c["name"] == "taskflow2_csrf")
        context.request.post(BASE + "/api/auth/logout", headers={"X-CSRFToken": token})
        page.get_by_role("button", name="保存目标与条件", exact=True).click()
        expect(page.locator("#auth-screen")).to_be_visible()
        page.locator("#register-tab").click()
        page.locator("#username").fill("phase2_other")
        page.locator("#password").fill(PASSWORD)
        page.locator("#auth-submit").click()
        expect(page.locator("#workspace")).to_be_visible()
        expect(page.locator("#execution-dialog")).not_to_be_visible()
        assert "不能给其他账号看到的内容" not in page.content()
        assert "手算一个小例子" not in page.content()
        assert "写出可运行代码" not in page.content()
        assert not errors, errors
        browser.close()
        return {
            "page_errors": errors,
            "checks": [
                "manual draft and apply",
                "dependency execution",
                "90+30=120",
                "undo preserves time",
                "edit ledger 135",
                "completeness verification",
                "network retry retains input",
                "reload persistence",
                "390px layout",
                "same-account draft recovery",
                "different-account isolation",
            ],
            "external_api_calls": 0,
        }


def main():
    with tempfile.TemporaryDirectory(prefix="phase2-browser-") as directory:
        env = {
            **os.environ,
            "TASKFLOW_DB": str(Path(directory) / "qa.sqlite3"),
            "DEEPSEEK_API_KEY": "qa-placeholder-not-a-real-secret",
        }
        python = str(ROOT / ".venv/bin/python")
        subprocess.run(
            [python, "manage.py", "migrate", "--noinput"],
            cwd=ROOT,
            env=env,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        with (ROOT / "evidence/phase2-browser-server.log").open("w") as log:
            server = subprocess.Popen(
                [python, "manage.py", "runserver", "127.0.0.1:8017", "--noreload", "--insecure"],
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=log,
            )
            try:
                wait_server()
                result = run()
                server.terminate()
                server.wait(timeout=10)
                server = subprocess.Popen(
                    [
                        python,
                        "manage.py",
                        "runserver",
                        "127.0.0.1:8017",
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
                    page.locator("#username").fill("phase2_qa")
                    page.locator("#password").fill(PASSWORD)
                    page.locator("#auth-submit").click()
                    expect(page.locator(".task-card")).to_have_count(1)
                    page.locator(".task-card").click()
                    page.get_by_role("button", name="分析与执行 ↗").click()
                    expect(page.locator("#ex-summary")).to_contain_text("135 分钟")
                    expect(page.locator(".ex-step")).to_have_count(2)
                    browser.close()
                result["restart_persistence"] = "pass"
                result["checks"].append(
                    "AI queue consent and cancellation without calling external API"
                )
                (ROOT / "evidence/phase2-browser.json").write_text(
                    json.dumps(result, ensure_ascii=False, indent=2)
                )
                print(json.dumps(result, ensure_ascii=False, indent=2))
            finally:
                server.terminate()
                server.wait(timeout=10)


if __name__ == "__main__":
    main()
