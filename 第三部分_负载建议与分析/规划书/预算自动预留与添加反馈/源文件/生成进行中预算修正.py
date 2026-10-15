"""Generate the one-page active-task budget correction without reading account data."""

from __future__ import annotations

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
MUTED = "#66776E"
LINE = "#D8E2DB"
BG = "#F7F9F5"
WHITE = "#FFFFFF"
FREE = "#DCE8DD"
BUFFER = "#A2A8B1"


def color(value):
    return tuple(int(value[i : i + 2], 16) / 255 for i in (1, 3, 5))


def generate():
    doc = fitz.open()
    page = doc.new_page(width=W, height=H)
    page.insert_font(fontname="cn", fontfile=FONT_PATH)
    page.draw_rect(page.rect, fill=color(BG), color=None)

    def text(x, y, value, size=11.5, ink=INK):
        value = str(value)
        width = FONT.text_length(value, fontsize=size)
        assert 24 <= x and x + width <= W - 24, (value, x, width)
        assert 18 <= y <= H - 14, (value, y)
        page.insert_text((x, y), value, fontsize=size, fontname="cn", color=color(ink))

    def centered(cx, y, value, size=11.5, ink=INK):
        text(cx - FONT.text_length(value, fontsize=size) / 2, y, value, size, ink)

    def rect(x, y, width, height, fill=WHITE):
        page.draw_rect(
            fitz.Rect(x, y, x + width, y + height),
            color=color(LINE),
            fill=color(fill),
            width=0.7,
        )

    def arc(cx, cy, radius, start, end, ink, width=17):
        steps = max(2, math.ceil((end - start) * 180))
        points = []
        for index in range(steps + 1):
            angle = -math.pi / 2 + 2 * math.pi * (start + (end - start) * index / steps)
            points.append(
                (cx + radius * math.cos(angle), cy + radius * math.sin(angle))
            )
        page.draw_polyline(points, color=color(ink), width=width)

    text(42, 31, "留白 / ROOM TO FOCUS", 10, GREEN)
    text(601, 31, "规则修正 v1.1 · 2026-10-14", 10, MUTED)
    text(42, 72, "默认先记想法，执行时才占预算", 24)
    text(
        42,
        101,
        "本页替代上轮9页 v1.0 中“创建即预留、暂停保留”的规则。旧PDF保留为历史方案。",
        11,
        MUTED,
    )
    page.draw_line((42, 122), (800, 122), color=color(LINE))

    text(42, 147, "状态变化直接驱动时间占用", 13, GREEN)
    states = [
        ("想法", "planned", "0 分钟", FREE),
        ("开始执行", "in_progress", "180 分钟", "#EAF2E9"),
        ("暂停", "paused", "0 分钟", FREE),
        ("恢复执行", "in_progress", "180 分钟", "#EAF2E9"),
        ("完成", "completed", "0 分钟", FREE),
    ]
    for index, (label, status, amount, fill) in enumerate(states):
        x = 42 + 153 * index
        rect(x, 163, 130, 76, fill)
        centered(x + 65, 186, label, 12, GREEN)
        centered(x + 65, 205, status, 9.5, MUTED)
        centered(x + 65, 226, amount, 12)
        if index < 4:
            centered(x + 141.5, 205, "→", 16, GREEN)

    text(42, 269, "同一个算例：圆盘与分析共用时间数据", 13, GREEN)
    cx, cy, radius = 150, 360, 69
    arc(cx, cy, radius, 0, 0.3, GREEN)
    arc(cx, cy, radius, 0.3, 0.4, BUFFER)
    arc(cx, cy, radius, 0.4, 1, FREE)
    centered(cx, 344, "可再安排", 11, MUTED)
    centered(cx, 373, "360 分钟", 20, GREEN)
    centered(cx, 394, "6 小时", 11, MUTED)

    text(272, 300, "总预算 B = 600   −   留白 F = 60   →   净容量 C = 540 分钟", 12)
    text(272, 324, "进行中占用 180 分钟   →   可再安排 540 − 180 = 360 分钟", 12, GREEN)
    text(272, 348, "再添加一个计划240分钟的想法：仍可再安排360分钟。", 11.5)
    text(272, 371, "开始执行这个想法后：占用420分钟，可再安排120分钟。", 11.5)
    text(272, 394, "改计划时间或开始／暂停／恢复／完成后，圆盘同步更新。", 11.5)
    text(272, 417, "进行中任务的时间未知时显示待确认，不能按0计算。", 11.5, MUTED)
    for index, (label, fill) in enumerate(
        [("进行中180", GREEN), ("留白60", BUFFER), ("可再安排360", FREE)]
    ):
        x = 42 + 85 * index
        page.draw_rect(fitz.Rect(x, 440, x + 9, 449), color=None, fill=color(fill))
        text(x + 13, 448, label, 8.5, MUTED)

    rect(42, 465, 758, 76, "#EDF3EB")
    text(
        56,
        487,
        "范围：按适用周计入进行中任务；想法、暂停、完成、放弃不占当前预算。",
        10.5,
    )
    text(
        56,
        507,
        "时间口径：实际耗时另记；本周剩余窗口单独确认，不直接复制整周计划；历史快照保留。",
        10.5,
    )
    text(
        56,
        527,
        "本次先实现状态与时间的基础联动，完整的就绪／阻塞队列调度留待后续设计。",
        10.5,
        MUTED,
    )
    text(
        42, 575, "演示使用虚构数据，不读取真实账号、任务、数据库或 API Key。", 9, MUTED
    )
    text(770, 575, "1 / 1", 9, MUTED)

    doc.set_metadata(
        {
            "title": "留白 · 进行中任务预算规则修正 v1.1",
            "author": "留白项目",
            "subject": "想法不占用，仅进行中任务计入预算；圆盘与时间联动",
        }
    )
    doc.set_toc([[1, "默认想法与进行中预算规则 v1.1", 1]])
    doc.subset_fonts()
    output = ROOT / "进行中任务预算_规则修正_v1.1.pdf"
    doc.save(output, garbage=4, deflate=True)
    doc.close()

    checked = fitz.open(output)
    extracted = checked[0].get_text()
    required = [
        "默认先记想法",
        "planned",
        "in_progress",
        "360 分钟",
        "历史快照保留",
        "实际耗时另记",
    ]
    assert checked.page_count == 1
    assert all(item in extracted for item in required), extracted
    violations = []
    for block in checked[0].get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                bounds = fitz.Rect(span["bbox"])
                if not fitz.Rect(0, 0, W, H).contains(bounds):
                    violations.append({"text": span["text"], "bbox": list(bounds)})
    assert not violations, violations
    report = {
        "file": output.name,
        "pages": checked.page_count,
        "page_size_points": [W, H],
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "required_chinese_and_states": {item: item in extracted for item in required},
        "text_boundary_violations": violations,
        "contains_live_data": False,
        "generated_date": "2026-10-14",
    }
    checked.close()
    (ROOT / "进行中任务预算_规则修正_v1.1_检查.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Generated {output.name}: 1 page; Chinese and boundary checks passed.")


if __name__ == "__main__":
    generate()
