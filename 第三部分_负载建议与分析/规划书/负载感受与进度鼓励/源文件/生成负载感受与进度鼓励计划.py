"""Rebuild the standalone plan: python3 本文件.py (requires PyMuPDF).

Pure vector layout, embedded Chinese font; no account or network access.
LIUBAI_PLAN_FONT may point to another Chinese TrueType font.
"""
from pathlib import Path
import hashlib
import json
import math
import os

import pymupdf as fitz

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "负载感受与进度鼓励_实施计划_v1.0.pdf"
FONT_PATH = os.environ.get("LIUBAI_PLAN_FONT", "/System/Library/Fonts/Supplemental/Arial Unicode.ttf")
FONT = fitz.Font(fontfile=FONT_PATH)
W, H = 842, 595
INK, GREEN, MUTED = "#243E38", "#286753", "#64766D"
LINE, BG, WHITE = "#D7E2DA", "#F7F9F5", "#FFFFFF"
LIGHT, GOOD, CHALLENGE, HIGH, FULL, OVER = "#5C8976", "#286753", "#927126", "#A86A36", "#A55642", "#A24743"
doc = fitz.open()
page = None
titles = []


def c(v):
    return tuple(int(v[i:i+2], 16) / 255 for i in (1, 3, 5))


def text(x, y, value, size=11.5, ink=INK):
    value = str(value)
    length = FONT.text_length(value, fontsize=size)
    assert 24 <= x and x + length <= W - 24, (len(doc), value, x, length)
    assert 18 <= y <= H - 14, (len(doc), value, y)
    page.insert_text((x, y), value, fontsize=size, fontname="cn", color=c(ink))


def center(x, y, value, size=11.5, ink=INK):
    text(x-FONT.text_length(value, fontsize=size)/2, y, value, size, ink)


def lines(value, width, size):
    out = []
    for para in value.split("\n"):
        line = ""
        for ch in para:
            if FONT.text_length(line + ch, fontsize=size) > width:
                if ch in "，。；：、？！）】》”’" and line:
                    out.append(line[:-1])
                    line = line[-1] + ch
                else:
                    out.append(line)
                    line = ch
            else:
                line += ch
        out.append(line)
    return out


def para(x, y, value, width=758, size=11.5, ink=INK, leading=18):
    for line in lines(value, width, size):
        text(x, y, line, size, ink)
        y += leading
    return y


def rect(x, y, width, height, fill=WHITE, stroke=LINE):
    page.draw_rect(fitz.Rect(x, y, x+width, y+height), fill=c(fill), color=c(stroke), width=.7)


def base(title, subtitle):
    global page
    page = doc.new_page(width=W, height=H)
    page.insert_font(fontname="cn", fontfile=FONT_PATH)
    page.draw_rect(page.rect, fill=c(BG), color=None)
    titles.append(title)
    text(42, 31, "留白 / ROOM TO FOCUS", 10, GREEN)
    text(597, 31, "负载感受与进度鼓励 · v1.0", 10, MUTED)
    text(42, 73, title, 24)
    para(42, 100, subtitle, size=10.7, ink=MUTED, leading=16)
    page.draw_line((42, 117), (800, 117), color=c(LINE))


def box(x, y, width, height, heading, body, accent=GREEN, size=11):
    rect(x, y, width, height)
    page.draw_rect(fitz.Rect(x, y, x+3, y+height), color=None, fill=c(accent))
    text(x+15, y+26, heading, 13, accent)
    end = para(x+15, y+50, body, width-30, size, leading=18)
    assert end-18 <= y+height-10, (heading, end, y+height)


def note(y, value):
    wrapped = lines(value, 730, 10.8)
    height = 20+len(wrapped)*17
    rect(42, y, 758, height, "#EBF2EA")
    para(56, y+23, value, 730, 10.8, GREEN, 17)
    assert y+height <= 545


def arc(cx, cy, radius, start, end, ink, width=13):
    if end <= start:
        return
    steps = max(2, math.ceil((end-start)*180))
    points = []
    for i in range(steps+1):
        a = -math.pi/2 + math.pi*2*(start+(end-start)*i/steps)
        points.append((cx+radius*math.cos(a), cy+radius*math.sin(a)))
    page.draw_polyline(points, color=c(ink), width=width)


def ring(cx, cy, percent, label, demand_fraction=.63, color=GOOD, radius=59, remaining="2小时42分"):
    page.draw_circle((cx, cy), radius, color=c("#DEE8DE"), width=13)
    arc(cx, cy, radius, 0, min(demand_fraction, .9), color)
    arc(cx, cy, radius, .9, 1, "#A0A8AE")
    center(cx, cy-17, "可再安排", 9, MUTED)
    center(cx, cy+7, remaining, 15.5, color)
    center(cx, cy+29, label, 11, color)


def table(headers, rows, widths, y=140, size=11):
    x = 42
    for head, width in zip(headers, widths):
        rect(x, y, width, 32, "#E4EDE4")
        text(x+11, y+21, head, 11, GREEN)
        x += width
    y += 32
    for idx, row in enumerate(rows):
        cells = [lines(v, w-22, size) for v, w in zip(row, widths)]
        height = max(map(len, cells))*17+20
        x = 42
        for cell, width in zip(cells, widths):
            rect(x, y, width, height, WHITE if idx % 2 == 0 else "#F0F4EF")
            for j, line in enumerate(cell):
                text(x+11, y+22+j*17, line, size)
            x += width
        y += height
    return y


# 01 / PRODUCT INTENT
base("把安排看成生活节奏，把进步看成值得记下的小事", "实施计划 · 2026.10.14 / 先完成这份计划，再实施网页；本文件中的图均为设计示意。")
rect(42, 138, 758, 179)
ring(148, 226, "70%", "刚刚好")
text(255, 176, "这一周，留一点从容给自己。", 19, GREEN)
para(255, 207, "时间负载 70% · 刚刚好\n看见负载，也看见每一步已经完成的小进展。", 510, 12, leading=23)
text(255, 277, "总预算 10 小时 · 留白 1 小时 · 进行中 6 小时 18 分钟", 10.8, MUTED)
box(42, 339, 369, 144, "01 / 负载有感受", "在 100% 以内也给出清楚的节奏描述，帮助用户判断是否适合继续安排。文字与颜色并用，时间数据仍可直接查看。")
box(431, 339, 369, 144, "02 / 进展被看见", "完成一个小步骤后出现一句轻量鼓励，带上步骤名称与已完成数量；不打断下一步，也允许随时关闭。")
note(499, "产品意图：让留白更有人情味。负载等级是个人时间计划参考，不代表健康、能力或努力程度。")

# 02 / THRESHOLDS
base("同样在 100% 内，也能读出不同的节奏", "阈值按未四舍五入的实际比值判断；70% 是“刚刚好”的例子，区间边界如下。")
y = table(["净容量负载", "页面主文案", "配套提示 / 颜色"], [
    ("0% ≤ 负载 < 60%", "轻松有余量", "还有余地，可以按自己的节奏来。 / 柔绿"),
    ("60% ≤ 负载 < 80%", "刚刚好", "安排有了重心，也保留着空间。 / 深绿"),
    ("80% ≤ 负载 < 90%", "有点挑战", "事情比较充实，记得给切换留点时间。 / 橄榄金"),
    ("90% ≤ 负载 < 100%", "负载偏高", "已经接近排满，新增事情前可以缓一缓。 / 暖琥珀"),
    ("负载 = 100%", "安排已满", "当前可安排时间已用满，可以先做眼前这一件。 / 砖橙"),
    ("负载 > 100%", "该减一点", "计划超过了可安排时间，可以挪走一小部分。 / 柔砖红"),
], [175, 155, 428], size=10.8)
note(y+20, "颜色服务于理解，不制造催促。始终同时显示等级文字、投入时间与净容量；不把更高负载渲染成更优秀。")

# 03 / SINGLE SOURCE
base("先把时间口径说清楚，再让圆盘说人话", "等级与百分比使用净容量；环形分配保留现有总预算口径。两者必须明确标注。")
box(42, 139, 758, 101, "一个可核对的算例", "总预算 B = 10 小时；留白 F = 1 小时；净可安排容量 C = B − F = 9 小时。\n进行中预计投入 D = 6 小时 18 分钟；负载 D ÷ C = 70%，等级“刚刚好”；可再安排 2 小时 42 分钟。", size=11.2)
box(42, 258, 369, 123, "圆环：一整圈仍代表总预算 B", "任务占整圈 63%，留白占 10%，可再安排占 27%。圆心保留剩余时间，旁边显示“时间负载 70%”，注明按净容量计算。", size=10.8)
box(431, 258, 369, 123, "分级：预计投入 ÷ 净容量 C", "只统计进行中任务。想法、暂停、完成和放弃不占当前预算；实际耗时仍单独记录。整周和剩余窗口沿用各自确认的预算。", size=10.8)
table(["不完整或边界数据", "呈现规则"], [
    ("预算未确认 / 已过期 / 任务估时未知", "显示待确认或待补充，保留已知时间，不捏造完整比例。"),
    ("区间估时，例如 60%–85%", "显示上下界，按上界分级为“有点挑战”，注明“按上界”。"),
    ("净容量为 0 / 超过 100%", "0 容量单独说明有无投入；超载只画一圈，并显示缺口。"),
], [285, 473], y=399, size=10.3)

# 04 / MOCKUPS
base("四个界面片段：一眼理解，随手就能调整", "预算输入继续放在圆盘右侧，小时＋分钟保持不变；新信息进入现有流程。")
rect(42, 137, 369, 181)
text(58, 161, "A / 正常负载", 12, GREEN)
ring(120, 237, "70%", "刚刚好", radius=48)
text(191, 199, "时间负载 70% · 刚刚好", 11, GREEN)
text(191, 222, "净容量 9 小时", 11)
text(191, 245, "投入 6 小时 18 分钟", 10.5)
rect(191, 262, 195, 33, "#EDF3EB")
text(203, 284, "预算 [10 小时] [0 分钟]", 9.8, GREEN)
rect(431, 137, 369, 181)
text(447, 161, "B / 接近排满", 12, HIGH)
ring(509, 237, "95%", "负载偏高", demand_fraction=.855, color=HIGH, radius=48, remaining="27分钟")
text(580, 199, "时间负载 95% · 负载偏高", 10.4, HIGH)
text(580, 222, "投入 8 小时 33 分钟", 11)
para(580, 246, "只剩 27 分钟，\n新增事情前可以缓一缓。", 198, 10.6, HIGH, 19)
rect(42, 336, 369, 174)
text(58, 361, "C / 步骤保存成功后", 12, GREEN)
rect(59, 378, 334, 112, "#EEF4EA")
text(74, 402, "又完成一小步，挺好的。", 13, GREEN)
text(369, 402, "×", 15, MUTED)
text(74, 428, "已完成「整理训练数据」", 11)
text(74, 451, "步骤 2 / 5 · 按自己的节奏继续。", 10.5)
text(74, 475, "6 秒后收起；停留或聚焦时暂停。", 9.2, MUTED)
rect(431, 336, 369, 174)
text(447, 361, "D / 用户掌握鼓励的开关", 12, GREEN)
rect(448, 379, 334, 56, "#F1F5EF")
text(463, 413, "顶部工具区 · 完成鼓励", 11)
rect(708, 392, 55, 28, GREEN, GREEN)
text(719, 411, "已开", 10, WHITE)
para(449, 459, "默认打开，可随时关闭。\n偏好仅在本机按账号保存，不保存任务文案。", 332, 10.2, MUTED, 18)

# 05 / ENCOURAGEMENT
base("一句鼓励，必须出现在真正完成之后", "鼓励来自已成功保存的完成事件；不用 AI、不发网络请求生成文案。")
table(["用户行为", "反馈规则"], [
    ("完成一个步骤，服务器确认成功", "显示步骤名与已完成 x / y；数量只是步骤数量，不代表耗时进度。"),
    ("完成整个任务，服务器确认成功", "包含普通编辑器设为完成；显示收尾鼓励，不替用户安排下一件事。"),
    ("编辑完成内容 / 撤销完成 / 刷新页面", "不弹出新的完成鼓励。撤销后再次完成，视为一次新的完成事件。"),
    ("保存失败 / 同次请求幂等重试", "失败不弹；按当前账号 + event_id 去重，成功重试只弹一次。"),
], [285, 473], y=139, size=10.6)
box(42, 361, 369, 132, "语气：具体、轻松、允许停下", "“这一小步已经完成了。”\n“又少了一件挂心的事。”\n“做到这里也不错，歇一下也可以。”\n不排名、不催促、不把用户称为胜者或落后者。", size=10.7)
box(431, 361, 369, 132, "呈现：轻量，也能被读到", "浮层 6 秒自动收起，可手动关闭；鼠标悬停或键盘焦点位于浮层时暂停倒计时。polite 实时区域，不抢焦点；遵守减少动态效果偏好。", size=10.8)
note(508, "快速完成多项时，反馈按新成功事件更新且不叠屏；切换账号立即清除旧浮层、队列与账号相关的临时状态。")

# 06 / IMPLEMENTATION
base("在第三部分接入，沿用已经可信的数据", "首版以静态前端模块为主；不改变后端完成、耗时与预算业务规则，不新增数据库迁移。")
nodes = [
    (42, "已有分析快照", "预算 / 留白 / 区间\n确认状态 / 窗口"),
    (300, "负载感受映射", "纯函数分级\n文字 / 颜色 / 百分比"),
    (558, "现有预算圆盘", "同一份数据渲染\n右侧仍可直接改预算"),
]
for x, heading, body in nodes:
    box(x, 139, 242, 106, heading, body, size=10.8)
for x in (288, 546):
    center(x+4, 198, "→", 14, GREEN)
box(42, 263, 242, 116, "已有完成接口", "用户点击完成 / 编辑为完成\n请求成功 + 当前账号核验\n带 event_id 与步骤 / 任务信息", size=10.8)
box(300, 263, 242, 116, "完成鼓励模块", "按事件去重 + 检查开关\n选择本地短句\n控制暂停、关闭与自动收起", size=10.8)
box(558, 263, 242, 116, "非阻塞反馈", "原界面更新继续执行\n浮层显示步骤名与 x / y\n失败时保留原错误处理", size=10.8)
for x in (288, 546):
    center(x+4, 327, "→", 14, GREEN)
table(["交付步骤", "本次执行范围"], [
    ("1. 固化规则与展示", "增加分级纯函数，接圆盘文字、色彩和百分比；保留小时＋分钟。"),
    ("2. 接完成反馈与偏好", "只绑定完成写入成功路径；按账号保存开关；隔离事件与会话。"),
    ("3. 验证并交付", "边界算例 + 桌面与手机验证；更新第三部分说明；前两部分保持独立。"),
], [230, 528], y=399, size=10.4)

# 07 / ACCEPTANCE
base("验收要覆盖感受，也要覆盖不该打扰的时刻", "先检查功能与边界，再用实际界面审视语气；本计划完成后即可开始实现。")
table(["验证项", "通过条件"], [
    ("等级边界", "0 / 59.9 / 60 / 70 / 79.9 / 80 / 89.9 / 90 / 99.9 / 100 / 100.1% 各归属正确。"),
    ("真实数字与区间", "10 小时减 1 小时、投入 6 小时 18 分钟 = 70%；60–85% 按上界提示。"),
    ("无效与未知状态", "未知、未确认、过期不生成完整比例；零容量不出现 NaN、Infinity 或假 0%。"),
    ("完成事件", "步骤 / 整任务成功才弹；编辑、撤销、刷新、失败不弹；同次成功不重复。"),
    ("鼓励偏好", "默认开；关闭后不弹；本机刷新后保持；换账号不串偏好、不串任务文案。"),
    ("操作与可读性", "6 秒自动收起、可关、悬停 / 焦点暂停；键盘可用，读屏礼貌播报，不抢焦点。"),
    ("移动端与回归", "390px 无横向溢出；减少动态效果有效；保存预算、状态更新、耗时登记可用。"),
], [170, 588], y=139, size=10.3)
box(42, 464, 758, 80, "本轮边界与后续可演进的方向", "这次实现分级描述与本地鼓励，不引入积分榜、打卡压力、情绪诊断或 AI 文案。后续根据使用反馈调整阈值与短句，再决定是否开放个性化设置。", size=10.6)

for index, p in enumerate(doc):
    page = p
    page.draw_line((42, 557), (800, 557), color=c(LINE))
    text(42, 578, "v1.0 · 2026.10.14 · 第三部分独立规划 · 设计示意，实施前生成", 9, MUTED)
    text(741, 578, f"{index+1:02d} / {len(doc):02d}", 9, MUTED)
doc.set_toc([[1, title, index+1] for index, title in enumerate(titles)])
doc.set_metadata({"title": "留白 · 负载感受与进度鼓励实施计划 v1.0", "author": "留白项目规划", "subject": "负载分级、完成反馈、前端交互与验收"})
doc.subset_fonts()
doc.save(OUT, garbage=4, deflate=True)
doc.close()

image_dir = ROOT / "页面预览"
image_dir.mkdir(exist_ok=True)
with fitz.open(OUT) as check:
    assert len(check) == 7
    for p in check:
        assert "\ufffd" not in p.get_text() and len(p.get_text()) > 150
        for block in p.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    x0, y0, x1, y1 = span["bbox"]
                    assert 20 <= x0 < x1 <= W-20 and 5 <= y0 < y1 <= H-5, (p.number+1, span)
        p.get_pixmap(matrix=fitz.Matrix(1.4, 1.4), alpha=False).save(image_dir / f"第{p.number+1:02d}页.png")
    report = {"document": OUT.name, "pages": len(check), "bookmarks": len(check.get_toc()), "size_bytes": OUT.stat().st_size, "sha256": hashlib.sha256(OUT.read_bytes()).hexdigest(), "checks": ["中文文本提取", "页面文字边界", "非空页面", "七页书签", "所有页面已渲染"], "page_titles": titles, "visual_review": "待执行"}
(ROOT / "PDF生成检查.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
(ROOT / "阅读与复现说明.txt").write_text("先规划后实施：本计划在应用功能改动前完成。PDF 内所有界面为矢量设计示意，不是真实账号截图。\n\n复现：安装 PyMuPDF 后运行：\npython3 源文件/生成负载感受与进度鼓励计划.py\n\n默认使用 macOS Arial Unicode 中文字体；其他系统通过 LIUBAI_PLAN_FONT 指定中文 TTF。生成脚本不读取数据库、任务、账号或 API Key，不发送网络请求。\n\nPDF、生成源码、页面预览、检查报告均保存在本目录，归属于第三部分。\n", encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
