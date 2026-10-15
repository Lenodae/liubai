"""Generate a standalone Chinese PDF teaching automatic budget reservation.

Uses installed PyMuPDF and a local Unicode font; does not access live account data.
Example:
  python3 生成预算自动预留讲解.py
  python3 生成预算自动预留讲解.py --final --screenshots ../截图/截图清单.json
Screenshot JSON is an array of {title, path, caption}; paths are relative to the JSON.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path

import pymupdf as fitz


ROOT = Path(__file__).resolve().parents[1]
FONT_PATH = os.environ.get(
    "LIUBAI_PLAN_FONT", "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
)
FONT = fitz.Font(fontfile=FONT_PATH)
W, H = 842, 595
INK = "#243E38"
GREEN = "#286753"
BLUE = "#416F91"
MUTED = "#65776E"
AMBER = "#A26B2F"
RED = "#A3493F"
LINE = "#D8E2DB"
BG = "#F7F9F5"
WHITE = "#FFFFFF"
TRACK = "#E5EBE5"


def color(value):
    return tuple(int(value[i : i + 2], 16) / 255 for i in (1, 3, 5))


class Book:
    def __init__(self, final=False):
        self.doc = fitz.open()
        self.page = None
        self.titles = []
        self.final = final

    def text(self, x, y, value, size=11.5, ink=INK):
        value = str(value)
        width = FONT.text_length(value, fontsize=size)
        assert x >= 24 and x + width <= W - 24, (
            len(self.doc), value, x, width
        )
        assert 18 <= y <= H - 14, (len(self.doc), value, y)
        self.page.insert_text(
            (x, y), value, fontsize=size, fontname="cn", color=color(ink)
        )

    def centered(self, cx, y, value, size=11.5, ink=INK):
        width = FONT.text_length(str(value), fontsize=size)
        self.text(cx - width / 2, y, value, size, ink)

    def wrap(self, value, width, size=11.5):
        lines = []
        for para in str(value).split("\n"):
            line = ""
            for char in para:
                if FONT.text_length(line + char, fontsize=size) > width:
                    lines.append(line)
                    line = char
                else:
                    line += char
            lines.append(line)
        return lines

    def paragraph(self, x, y, value, width=758, size=11.5, ink=INK, leading=18):
        for line in self.wrap(value, width, size):
            self.text(x, y, line, size, ink)
            y += leading
        return y

    def rect(self, x, y, w, h, fill=WHITE, stroke=LINE):
        self.page.draw_rect(
            fitz.Rect(x, y, x + w, y + h),
            fill=color(fill), color=color(stroke), width=0.7,
        )

    def base(self, title, subtitle):
        self.page = self.doc.new_page(width=W, height=H)
        self.page.insert_font(fontname="cn", fontfile=FONT_PATH)
        self.page.draw_rect(self.page.rect, fill=color(BG), color=None)
        self.titles.append(title)
        self.text(42, 31, "留白 / ROOM TO FOCUS", 10, GREEN)
        self.text(612, 31, "预算自动预留 · 操作讲解", 10, MUTED)
        self.text(42, 73, title, 24)
        self.paragraph(42, 101, subtitle, size=10.8, ink=MUTED, leading=16)
        self.page.draw_line((42, 118), (800, 118), color=color(LINE))

    def note(self, y, value, ink=GREEN):
        lines = self.wrap(value, 730, 11)
        height = len(lines) * 17 + 20
        self.rect(42, y, 758, height, "#EDF3EB")
        self.paragraph(56, y + 23, value, 730, 11, ink, 17)
        assert y + height <= 543, (self.titles[-1], y + height)

    def box(self, x, y, w, h, heading, body, accent=GREEN, size=11):
        self.rect(x, y, w, h)
        self.page.draw_rect(
            fitz.Rect(x, y, x + 3, y + h), color=color(accent), fill=color(accent)
        )
        self.text(x + 14, y + 26, heading, 13, accent)
        end = self.paragraph(x + 14, y + 49, body, w - 28, size, INK, 18)
        assert end - 18 <= y + h - 9, (heading, end, y + h)

    def arrow(self, x1, y1, x2, y2, ink=GREEN):
        self.page.draw_line((x1, y1), (x2, y2), color=color(ink), width=1.2)
        angle = math.atan2(y2 - y1, x2 - x1)
        points = [
            (x2 - 7 * math.cos(angle - 0.5), y2 - 7 * math.sin(angle - 0.5)),
            (x2, y2),
            (x2 - 7 * math.cos(angle + 0.5), y2 - 7 * math.sin(angle + 0.5)),
        ]
        self.page.draw_polyline(points, color=color(ink), width=1.2)

    def arc(self, cx, cy, radius, start, end, ink, width=14, dashed=False):
        if end <= start:
            return
        if dashed:
            position = start
            while position < end:
                self.arc(cx, cy, radius, position, min(position + 0.016, end), ink, width)
                position += 0.031
            return
        count = max(2, math.ceil((end - start) * 180))
        points = []
        for index in range(count + 1):
            angle = -math.pi / 2 + 2 * math.pi * (
                start + (end - start) * index / count
            )
            points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
        self.page.draw_polyline(points, color=color(ink), width=width)

    def dial(self, cx, cy, demand, capacity, label, status, *, ink=GREEN, radius=66, buffer=60):
        self.page.draw_circle((cx, cy), radius, color=color(TRACK), width=14)
        if capacity is not None and capacity + buffer > 0:
            total = capacity + buffer
            share = min(capacity / total, max(0, (demand or 0) / total))
            self.arc(cx, cy, radius, 0, share, ink)
            self.arc(cx, cy, radius, share, share + buffer / total, "#A2A8B1")
        self.centered(cx, cy - 21, "信息待确认" if demand is None else "可再安排", 9.5, MUTED)
        self.centered(cx, cy + 5, label, 17, ink)
        self.centered(cx, cy + 28, status, 10.5, ink)

    def table(self, headers, rows, widths, y=139, size=11):
        x = 42
        for heading, width in zip(headers, widths):
            self.rect(x, y, width, 32, "#E4EEE5")
            self.text(x + 11, y + 22, heading, 11.5, GREEN)
            x += width
        y += 32
        for index, row in enumerate(rows):
            cells = [self.wrap(cell, width - 22, size) for cell, width in zip(row, widths)]
            height = max(map(len, cells)) * 18 + 20
            x = 42
            for lines, width in zip(cells, widths):
                self.rect(x, y, width, height, WHITE if index % 2 == 0 else "#F0F4EF")
                for j, line in enumerate(lines):
                    self.text(x + 11, y + 24 + 18 * j, line, size)
                x += width
            y += height
        assert y <= 537, (self.titles[-1], y)
        return y

    def screenshot(self, info, y=137, max_height=354):
        path = Path(info["path"])
        pix = fitz.Pixmap(path)
        clip = info.get("clip", [0, 0, pix.width, pix.height])
        x0, y0, x1, y1 = clip
        assert 0 <= x0 < x1 <= pix.width and 0 <= y0 < y1 <= pix.height
        ratio = (x1 - x0) / (y1 - y0)
        frame_w = min(758, max_height * ratio)
        frame_h = frame_w / ratio
        x = (W - frame_w) / 2
        self.rect(x - 1, y - 1, frame_w + 2, frame_h + 2)
        # Clip only the PDF presentation; the original screenshot is preserved.
        with fitz.open(path) as image_doc:
            image_pdf_bytes = image_doc.convert_to_pdf()
        with fitz.open("pdf", image_pdf_bytes) as image_pdf:
            image_rect = image_pdf[0].rect
            crop_rect = fitz.Rect(
                x0 * image_rect.width / pix.width,
                y0 * image_rect.height / pix.height,
                x1 * image_rect.width / pix.width,
                y1 * image_rect.height / pix.height,
            )
            self.page.show_pdf_page(
                fitz.Rect(x, y, x + frame_w, y + frame_h), image_pdf, 0, clip=crop_rect
            )
        end = self.paragraph(42, y + frame_h + 23, info["caption"], size=10.6, ink=MUTED)
        assert end - 18 <= 537, (self.titles[-1], end)

    def finish(self, out):
        for index, page in enumerate(self.doc):
            self.page = page
            self.page.draw_line((42, 555), (800, 555), color=color(LINE))
            label = "v1.0 · 操作讲解 · 合成演示数据" if self.final else "校对稿 · 示例规则待最终实现确认"
            self.text(42, 579, label, 9, MUTED)
            self.text(739, 579, f"{index + 1:02d} / {len(self.doc):02d}", 9, MUTED)
        self.doc.set_toc([[1, title, index + 1] for index, title in enumerate(self.titles)])
        self.doc.set_metadata(
            {
                "title": "留白 · 预算自动预留与添加反馈讲解演示",
                "author": "留白项目",
                "subject": "周任务、长期承诺、预算圆盘、剩余窗口与耗时账本",
            }
        )
        self.doc.subset_fonts()
        self.doc.save(out, garbage=4, deflate=True)
        self.doc.close()


def validate(out, titles):
    with fitz.open(out) as doc:
        for page in doc:
            content = page.get_text()
            assert "\ufffd" not in content
            assert len(content) > 100, (page.number + 1, len(content))
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    for span in line["spans"]:
                        x0, y0, x1, y1 = span["bbox"]
                        assert 20 <= x0 < x1 <= W - 20 and 5 <= y0 < y1 <= H - 5, (
                            page.number + 1, span
                        )
        report = {
            "document": out.name,
            "pages": len(doc),
            "bookmarks": len(doc.get_toc()),
            "size_bytes": out.stat().st_size,
            "sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
            "checks": ["中文提取", "文本边界", "非空页面", "页码与书签"],
            "page_titles": titles,
        }
    report_path = out.with_suffix(".检查.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def build(args):
    screenshots = []
    if args.screenshots:
        manifest = Path(args.screenshots).resolve()
        screenshots = json.loads(manifest.read_text())
        for item in screenshots:
            item["path"] = str((manifest.parent / item["path"]).resolve())
            assert Path(item["path"]).is_file(), item["path"]
    if args.final:
        assert len(screenshots) >= 2, "最终版需要至少两张实际网页的合成数据截图"
    book = Book(args.final)

    # 01
    book.base(
        "创建任务，就把它放进预算里",
        "周任务按指定周预留；长期任务持续按周预留。圆盘表达时间承诺，不需要等到点击“开始执行”。",
    )
    book.box(42, 142, 237, 160, "周任务", "这周整理资料：120 分钟。\n创建时指定这一周，就预留 120 分钟。\n下周不会自动继续占用。")
    book.box(302, 142, 238, 160, "长期任务", "学习项目：每周 180 分钟。\n从所选周起，每周保留这份投入。\n直到任务完成或终止承诺。", BLUE)
    book.box(563, 142, 237, 160, "添加后立即看到反馈", "保存成功后，展示预算图和当前余额。\n回到首页，圆盘与任务贡献同步更新。\n若资料缺失，会明确提示待补。", AMBER)
    book.arrow(157, 316, 157, 342)
    book.arrow(421, 316, 421, 342)
    book.arrow(682, 316, 682, 342)
    book.rect(42, 352, 758, 99)
    book.text(61, 382, "同一份预算，统一看所有任务", 16, GREEN)
    book.paragraph(61, 409, "任务的周投入汇总进入负载分析；是否已经执行、花了多少时间，则由步骤与耗时账本记录。", 719)
    book.note(474, "已创建但尚未开始的任务，也是一份时间承诺。把它算进去，才能提前看见还能否安排新的事情。")

    # 02
    book.base("哪些任务会占用？看任务类型与承诺", "每周投入是任务整体的时间预留。列表筛选与搜索只改变展示范围，不改变总预算。")
    y = book.table(
        ["情形", "预算处理", "你会看到什么"],
        [
            ["周任务，指定本周", "在所选周预留填写的每周总投入。", "还未执行，也出现在负载贡献里。"],
            ["周任务，指定其他周", "占用指定周；不自动延续到下一周。", "切换到对应周后查看贡献。"],
            ["长期任务，待开始或正在处理", "从所选周起，持续按周保留总投入。", "当前与后续负载都有这份承诺。"],
            ["长期任务暂停", "暂停执行仍保留长期预算承诺。", "需要减轻本窗投入时，手工调整窗口计划。"],
            ["任务完成或放弃", "释放当前及未来的自动预留。", "已结束的历史周与快照保留；耗时不清除。"],
        ],
        [194, 306, 258], size=10.8,
    )
    book.note(y + 18, "手工确认过的整周计划仍保留当时的基线。完成后自动承诺会释放，但不能把所有历史与手工计划一并归零。")

    # 03
    book.base("一个例子：600 分钟，怎样留出余量？", "以下全部为合成示例。预算 B=600，缓冲 F=60，因此可分配容量 C=540 分钟。")
    book.rect(42, 140, 758, 85)
    book.text(60, 171, "预算 600", 18, GREEN)
    book.text(239, 171, "−", 21, MUTED)
    book.text(283, 171, "缓冲 60", 18, AMBER)
    book.text(451, 171, "=", 21, MUTED)
    book.text(502, 171, "可分配 540 分钟", 18, GREEN)
    book.text(60, 203, "页面预算填分钟：600 / 60；任务预留填小时：周任务 2h、长期任务 3h。", 11.2, MUTED)
    book.dial(185, 343, 300, 540, "240 分钟", "当前可覆盖", radius=75)
    book.text(331, 275, "新增周任务 120 分钟", 15, GREEN)
    book.text(331, 310, "+ 长期任务每周 180 分钟", 15, BLUE)
    book.text(331, 353, "= 当前预留 300 分钟", 17)
    book.text(331, 390, "540 − 300 = 240 分钟可再安排", 15, GREEN)
    book.rect(42, 459, 758, 68, "#EDF3EB")
    book.paragraph(58, 483, "长期任务完成后，当前及未来释放它的自动预留 180 分钟。若本周其他条件相同，则只剩周任务 120 分钟，可再安排 420 分钟。手工确认过的整周计划与实际耗时记录仍保留。", 724, 11, leading=18)

    # 04
    book.base("每周总投入，只算一次", "创建时的时间是整个任务的周投入；手工窗口计划优先使用推进与维护的合计，不与自动值叠加。")
    book.box(42, 142, 350, 132, "自动预留", "长期学习任务：每周总投入 180 分钟。\n未填写手工窗口计划时，用 180 分钟。\n步骤估时只是任务内部的拆分依据。")
    book.box(450, 142, 350, 132, "手工确认当前窗口", "本窗推进 120 分钟 + 维护 30 分钟。\n以合计 150 分钟替代自动的 180。\n当前窗口按 150 分钟计入。", BLUE)
    book.arrow(401, 208, 441, 208)
    book.rect(42, 296, 758, 75, "#EDF3EB")
    book.text(59, 325, "本窗需求 = 推进 120 + 维护 30 = 150 分钟", 16, GREEN)
    book.text(59, 351, "自动周投入 180 不再额外加上；步骤估时也不再重复叠加。", 11, MUTED)
    book.box(42, 394, 350, 112, "一个窗口的调整", "当前周调成 150 分钟，影响的是本窗安排。\n长期周投入仍作为未来窗口的默认承诺。")
    book.box(450, 394, 350, 112, "长期默认的调整", "希望以后每周都减少投入时，修改任务的每周总投入。\n已有手工窗口计划仍按它自己的确认值判断。", BLUE)

    # 05
    book.base("整周计划与本周剩余，各算各的", "整周回顾原来的承诺；本周剩余处理从现在到周日还能安排的时间。已花耗时单独留在账本中。")
    book.box(42, 142, 363, 181, "整周计划", "窗口：周一到周日。\n预算：这一整周打算投入的总量。\n任务：窗口的手工基线与当前自动承诺。\n用途：看整周是否承诺过多、保留回顾依据。")
    book.box(437, 142, 363, 181, "本周剩余", "窗口：当前确认时点到周日。\n预算：这段时间真正还能用的总量。\n任务：这段窗口还准备安排的推进与维护。\n用途：据现在的情况继续安排。", BLUE)
    book.arrow(227, 336, 227, 361)
    book.arrow(619, 336, 619, 361, BLUE)
    book.rect(42, 372, 758, 80)
    book.text(61, 402, "账本：例如已花 90 分钟", 16, GREEN)
    book.paragraph(61, 429, "这 90 分钟作为实际记录保留。剩余预算由你确认，不再把已经考虑过的耗时重复扣一次。", 719, 11.1)
    book.note(473, "以前填写的是“本周剩余”预算时，新切到“整周计划”仍需单独填写整周预算。圆盘显示待设置并不代表原预算丢失；切回本周剩余可查看原值。")

    # 06
    book.base("圆盘怎么读：余量、未知与超额", "圆环按总预算 B 分配：任务预留、留白缓冲、可再安排。负载是否超额，仍与可分配容量 C=B−F 比较。")
    examples = [
        (135, 270, 300, 540, "240 分钟", "当前可覆盖", GREEN, "预留 300 / 容量 540\n剩余 240，缓冲另留 60"),
        (326, 270, 600, 540, "缺 60 分钟", "预留超出容量", RED, "预留 600 / 容量 540\n超额另列，不多画一圈"),
        (517, 270, None, 540, "待确认", "还有未知投入", MUTED, "未填投入不能当作 0\n暂不能确定完整余量"),
        (708, 270, 0, 540, "540 分钟", "本窗无安排", GREEN, "明确填写 0 分钟\n表示本窗不预留投入"),
    ]
    for cx, cy, demand, capacity, label, status, ink, caption in examples:
        book.dial(cx, cy, demand, capacity, label, status, ink=ink, radius=57)
        for index, line in enumerate(caption.split("\n")):
            book.centered(cx, 360 + index * 20, line, 10.4, MUTED)
    book.box(42, 407, 363, 112, "分配图与负载比例是两种表达", "图中圆环按总预算 600 分钟分配。\n单独算负载比例：300 ÷ 540 ≈ 55.6%。\n圆环上任务占比为 300 ÷ 600 = 50%。", size=10.6)
    book.box(437, 407, 363, 112, "区间、未知或零容量", "区间按预留上界绘图，余量保留区间；\n未知不能当作 0，提示补充资料。\n容量为 0 时，直接报告无安排或超出分钟。", AMBER, size=10.6)

    # 07
    book.base("你的操作顺序：先有预算，再看承诺", "任务添加成功后看即时反馈；调整预算或任务投入后，回到同一窗口检查最新负载。")
    steps = [
        ("1", "确认窗口与预算", "先选计划口径。示例：整周预算填 600 分钟，缓冲填 60 分钟。"),
        ("2", "创建并指定时间安排", "周任务填 2 小时；长期任务填每周 3 小时，并选安排所在周。"),
        ("3", "阅读添加后的反馈", "查看本次任务、当前预留、可再安排的时间，以及未知或超额提示。"),
        ("4", "处理与当前窗口不同的安排", "需要细调时确认本窗推进、维护或剩余投入；手工值替代自动值。"),
        ("5", "执行与完成记录", "登记步骤、完成内容与耗时。完成后释放当前及未来的自动承诺。"),
    ]
    y = 143
    for number, heading, body in steps:
        book.page.draw_circle((58, y + 18), 15, fill=color(GREEN), color=color(GREEN))
        book.centered(58, y + 23, number, 11.5, WHITE)
        book.text(89, y + 14, heading, 13.3, GREEN)
        book.paragraph(89, y + 38, body, 691, 11, leading=17)
        y += 73
    book.note(504, "圆盘从同一份负载分析取数；修改任务后需要显示新结果，不能让旧百分比继续冒充当前值。")

    # 08 and 09: final screenshots use synthetic test accounts only.
    titles = [
        ("网页演示：总览里的预算与任务贡献", "实际网页截图 / 合成测试数据。圆盘、预算摘要和任务贡献一起帮助判断还能安排多少。"),
        ("网页演示：添加任务后的即时反馈", "实际网页截图 / 合成测试数据。任务保存后立即展示本次承诺进入预算的结果。"),
    ]
    for index, (title, subtitle) in enumerate(titles):
        if index < len(screenshots):
            item = screenshots[index]
            book.base(item.get("title", title), subtitle)
            book.screenshot(item)
        else:
            book.base(title, "截图页尚待本次实现验收后补入。以下仅为布局示意，不是已经运行的网页截图。")
            book.rect(42, 142, 758, 345)
            book.text(61, 174, "留白 / 总览" if index == 0 else "任务已添加 / 预算反馈", 16, GREEN)
            book.text(61, 202, "整周计划 · 预算 600 分钟 · 缓冲 60 分钟", 11, MUTED)
            book.dial(184, 316, 300, 540, "240 分钟", "当前可覆盖", radius=72)
            book.text(326, 266, "周任务：整理资料 · 120 分钟", 14, GREEN)
            book.text(326, 303, "长期任务：学习项目 · 180 分钟 / 周", 14, BLUE)
            book.text(326, 345, "合计预留 300 分钟，可分配 540 分钟", 12)
            book.text(326, 379, "保存后刷新同一份分析结果", 11, MUTED)
            book.page.draw_line((61, 414), (781, 414), color=color(LINE))
            book.text(61, 447, "此页会替换为真实浏览器中使用合成数据的演示截图。", 11, MUTED)
            book.note(504, "校对稿用于确认讲解内容。最终 PDF 会在后端、前端与浏览器演示完成后生成。")

    out = Path(args.output) if args.output else ROOT / (
        "预算自动预留与添加反馈_讲解演示_v1.0.pdf"
        if args.final else "预算自动预留与添加反馈_讲解演示_校对稿.pdf"
    )
    book.finish(out)
    report = validate(out, book.titles)
    print(json.dumps({key: value for key, value in report.items() if key != "page_titles"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screenshots", help="JSON screenshot manifest")
    parser.add_argument("--final", action="store_true", help="Generate the verified final PDF")
    parser.add_argument("--output", help="Override output path")
    build(parser.parse_args())
