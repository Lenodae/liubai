"""Generate the phase-five design proposal with local PyMuPDF and Chinese font."""

from pathlib import Path
import hashlib
import json
import math
import platform
import re

import pymupdf as fitz


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "第五部分_首页减负与交互设计书_v1.0.pdf"
FONT_PATH = Path("/Library/Fonts/Arial Unicode.ttf")
FONT = fitz.Font(fontfile=str(FONT_PATH))
W, H = 842, 595
BG, INK, GREEN = "#F7F8F3", "#263E37", "#285E4F"
MUTED, LINE, PALE = "#5C6F66", "#D5DED5", "#EAF1E8"
GOLD = "#A37038"
doc = fitz.open()
page = None
drawn = []
titles = []


def rgb(value):
    return tuple(int(value[i : i + 2], 16) / 255 for i in (1, 3, 5))


def box(x, y, w, h, fill="#FFFFFF", stroke=LINE, radius=8):
    page.draw_rect(
        fitz.Rect(x, y, x + w, y + h),
        fill=rgb(fill),
        color=rgb(stroke),
        width=0.7,
        radius=radius / min(w, h),
    )


def text(x, y, value, size=11.5, ink=INK):
    value = str(value)
    width = FONT.text_length(value, fontsize=size)
    assert 24 <= x and x + width <= W - 24, (len(doc), value, x, width)
    assert 20 <= y <= H - 14, (len(doc), value, y)
    page.insert_text((x, y), value, fontsize=size, fontname="cn", color=rgb(ink))
    drawn.append({"page": len(doc), "x": x, "y": y, "width": width, "text": value})


def lines(value, width, size):
    result = []
    for para in value.split("\n"):
        line = ""
        for char in para:
            if FONT.text_length(line + char, fontsize=size) > width:
                if char in "，。；：！？、）》】”’":
                    result.append(line[:-1])
                    line = line[-1] + char
                elif char.isascii() and char.isalnum() and (tail := re.search(r"[A-Za-z0-9_./+-]+$", line)) and tail.start() > 0:
                    result.append(line[: tail.start()])
                    line = tail.group() + char
                else:
                    result.append(line)
                    line = char
            else:
                line += char
        result.append(line)
    return result


def paragraph(x, y, value, width, size=11.5, ink=INK, leading=19):
    for line in lines(value, width, size):
        text(x, y, line, size, ink)
        y += leading
    return y


def line(x1, y1, x2, y2, ink=LINE, width=1):
    page.draw_line((x1, y1), (x2, y2), color=rgb(ink), width=width)


def base(title, sub):
    global page
    page = doc.new_page(width=W, height=H)
    page.insert_font(fontname="cn", fontfile=str(FONT_PATH))
    page.draw_rect(page.rect, fill=rgb(BG), color=None)
    titles.append(title)
    text(36, 29, "留白  /  ROOM TO FOCUS", 10, GREEN)
    text(584, 29, "第五部分 · 交互设计提案 v1.0", 10, MUTED)
    text(36, 72, title, 25)
    text(36, 99, sub, 11, MUTED)
    line(36, 116, 806, 116)
    line(36, 557, 806, 557)
    text(36, 577, "设计提案 · 实施前版本 · 2026.10.15", 9, MUTED)
    text(727, 577, f"{len(doc):02d} / 07", 10, GREEN)


def button(x, y, w, label, primary=False, h=31, size=10.5):
    box(x, y, w, h, GREEN if primary else "#FFFFFF", GREEN if primary else LINE)
    tw = FONT.text_length(label, fontsize=size)
    text(x + (w - tw) / 2, y + h / 2 + size * 0.36, label, size, "#FFFFFF" if primary else GREEN)


def card(x, y, w, h, title, body, fill="#FFFFFF"):
    box(x, y, w, h, fill)
    text(x + 17, y + 29, title, 14, GREEN)
    paragraph(x + 17, y + 54, body, w - 34, 11.5, leading=19)


def banner(y, value):
    box(36, y, 770, 45, PALE, PALE)
    paragraph(50, y + 20, value, 740, 10.8, GREEN, 17)


def circle(cx, cy, r, size=12):
    page.draw_circle((cx, cy), r, color=rgb(LINE), width=13)
    # A restrained 33% plan-occupancy segment, rendered as connected vector lines.
    for i in range(40):
        a1 = -math.pi / 2 + i / 40 * math.pi * 2 / 3
        a2 = -math.pi / 2 + (i + 1) / 40 * math.pi * 2 / 3
        line(cx + r * math.cos(a1), cy + r * math.sin(a1), cx + r * math.cos(a2), cy + r * math.sin(a2), GREEN, 13)
    text(cx - 18, cy + 3, "33%", size + 3, GREEN)
    text(cx - 24, cy + 21, "时间安排", 9, MUTED)


base("少找一步，更容易继续", "保留预算优先，把有限的首页空间留给理解余量与行动。")
text(36, 157, "这一轮要解决的三个问题", 16, GREEN)
card(36, 179, 246, 150, "01  首页太长", "鼓励、预算摘要、圆盘和足迹层层堆叠；手机用户要滑很久才能找到正在做的事。")
card(298, 179, 246, 150, "02  数字不够好懂", "总预算、留白、计划占用和实际投入各有口径。算对数字，还需要让用户读对数字。")
card(560, 179, 246, 150, "03  继续成本偏高", "用户知道自己要继续做什么，却仍需搜索任务、进入详情，再找到步骤或耗时页。")
text(36, 371, "新的阅读顺序", 16, GREEN)
for x, label, sub in [(36, "看余量", "一份预算与圆盘"), (298, "接着做", "一个就近继续入口"), (560, "再展开", "足迹与任务细节按需看")]:
    box(x, 391, 246, 91, PALE, PALE)
    text(x + 18, 420, label, 18, GREEN)
    text(x + 18, 452, sub, 11.5, MUTED)
paragraph(36, 517, "产品边界：这一轮优化已有页面与操作路径；任务、签到、真实耗时与预算计算规则沿用现有版本。", 765, 11.5)

base("首页结构：预算之后，立刻能继续", "桌面线框示意；元素关系与内容层级为实施目标，最终尺寸以真实浏览器验收。")
box(36, 133, 523, 408, "#FFFFFF")
text(52, 158, "留白", 15, GREEN)
text(128, 157, "预算与任务总览     想法池     负载分析", 10.5, MUTED)
line(51, 171, 544, 171)
text(52, 190, "今日鼓励：走一小步，也是在向前。", 10.5)
button(423, 177, 118, "今日签到 / 休息", h=26, size=9.5)
box(51, 205, 493, 180, BG)
text(65, 225, "本周时间预算", 12, GREEN)
button(426, 212, 104, "预算怎么填", h=25, size=9)
circle(120, 291, 38)
text(182, 254, "进行中计划   6 小时", 10.5)
text(182, 276, "可再安排    12 小时", 10.5)
text(182, 298, "其中留白     2 小时", 10.5)
text(182, 326, "实际已记 1 小时 · 单独记录", 9.5, MUTED)
text(377, 254, "总预算      留白", 10)
box(377, 263, 69, 28)
box(455, 263, 69, 28)
text(386, 282, "20 时 0 分", 9)
text(462, 282, "2 时 0 分", 9)
button(377, 301, 147, "保存这个窗口", True, h=31)
text(66, 350, "安排约 33% · 时间还有余量；感受由你判断。", 10, MUTED)
text(66, 375, "进行中事项来源 · 3 项                         展开明细", 9.7, GREEN)
box(51, 395, 493, 46, PALE, PALE)
text(65, 415, "继续上次查看 · 学习 Python", 11.5, GREEN)
text(65, 433, "打开已有步骤，不自动开始计时。", 9.5, MUTED)
button(431, 403, 99, "继续步骤", True, h=29, size=10)
box(51, 451, 493, 32)
text(65, 473, "每日足迹  ·  最近 12 周摘要", 10.5)
text(376, 473, "查看全年    展开足迹", 10, GREEN)
text(52, 507, "正在投入的事", 12, GREEN)
button(420, 491, 122, "搜索 / 记录想法", h=27, size=9.5)
text(52, 532, "学习 Python    ·    阅读项目    ·    生活整理", 10, MUTED)
text(581, 157, "1 / 预算保持第一优先", 13, GREEN)
paragraph(581, 182, "圆盘右侧直接编辑。其下来源明细默认折叠，摘要显示事项数；缺时间时提示“有待补时间”。", 210, 11, leading=18)
text(581, 257, "2 / 继续入口靠近预算", 13, GREEN)
paragraph(581, 282, "用户看完余量，就能回到手头任务；搜索任务列表不改变继续对象。", 210, 11, leading=19)
text(581, 357, "3 / 足迹默认收起", 13, GREEN)
paragraph(581, 382, "保留摘要、签到与全年入口；展开才显示 84 格日历。错误与重试保持可见。", 210, 11, leading=19)
text(581, 467, "4 / 任务列表继续承接", 13, GREEN)
paragraph(581, 492, "想法、进行中事项与搜索保留。记录想法无需先填预算。", 210, 11, leading=19)

base("预算口径：同一段时间，只安排一次", "预算是“这段时间准备分给这里这些任务的总时间”；留白已经包含在总预算里。")
for x, n, label, desc in [(36, "20 小时", "总预算", "本周分给这些任务的时间"), (233, "2 小时", "其中留白", "预留缓冲，已经包含在 20 内"), (430, "6 小时", "进行中计划", "正在投入的任务预计占用"), (627, "12 小时", "可再安排", "扣除留白与已有计划后的余量")]:
    box(x, 136, 179, 105, PALE if x == 627 else "#FFFFFF")
    text(x + 13, 161, label, 11, MUTED)
    text(x + 13, 191, n, 22, GREEN)
    paragraph(x + 13, 216, desc, 153, 9.2, MUTED, 13)
box(36, 257, 770, 82, PALE, PALE)
text(54, 286, "可安排容量 20 − 2 = 18 小时     可再安排 18 − 6 = 12 小时", 15, GREEN)
text(54, 315, "时间负载 = 6 ÷ 18 ≈ 33%    ·    另记实际投入 1 小时，不自动再次扣减这份计划。", 11.5)
card(36, 356, 377, 125, "睡眠 / 工作已扣除", "若预算是扣除睡眠与固定工作后的空闲时间，就不要再把同一段睡眠或工作作为占用放入圆盘。")
card(429, 356, 377, 125, "睡眠 / 工作也想看见", "若希望圆盘展示它们，预算就应包含对应时间，再让任务占用。两种用法都可以，口径要一致。")
paragraph(36, 509, "整周与剩余时间分别保存；未知可以留空，0 表示明确没有。首次只给简短说明，不强制弹窗或自动填值。", 768, 11, leading=18)

base("继续入口与足迹：记住偏好，保留选择", "本机按账号记住最近查看与日历开合；只保存必要标识，不保存任务正文。")
text(36, 151, "继续对象怎样选", 16, GREEN)
box(36, 170, 770, 68, "#FFFFFF")
text(53, 195, "上次成功打开的任务仍进行中", 12, GREEN)
text(53, 220, "显示“继续上次查看”", 11)
text(335, 204, "→", 20, MUTED)
text(369, 195, "否则选当前进行中的一项", 12, GREEN)
text(369, 220, "固定排序选取，结果可预期", 11)
text(650, 204, "→", 20, MUTED)
text(682, 195, "没有进行中", 12, GREEN)
text(682, 220, "引导记录想法", 11)
card(36, 258, 377, 136, "只读继续，不偷偷改变任务", "点击进入已有步骤或耗时页面，不启动计时、不完成任务。暂停、完成、放弃和回收站任务都不会被继续入口选中。")
card(429, 258, 377, 136, "足迹默认紧凑，展开由自己决定", "摘要与“查看全年”始终可达；签到放在顶部。展开日历后保留日详情、历史真实记录和键盘操作。")
box(36, 412, 770, 111, PALE, PALE)
text(53, 439, "账号与失败场景", 13, GREEN)
paragraph(53, 464, "偏好按版本和账号分开；退出立即清空旧内容。任务状态变化后重新选择，迟到的旧账号响应不得覆盖新账号。", 735, 11.5, leading=19)
paragraph(53, 507, "存储损坏或不可写时回到默认值；折叠不能藏住读取错误、未确认提交与重试入口。", 735, 11.5, leading=19)

base("手机优先：清楚、够大、够近", "390 × 844 是主要验收场景之一；线框表达层级，不用截图缩放冒充页面变短。")
box(49, 131, 259, 414, "#FFFFFF", GREEN, 18)
text(66, 157, "留白  /  预算与任务总览", 12, GREEN)
line(65, 169, 292, 169)
text(66, 190, "今天，小步也算数。", 11)
button(66, 202, 105, "今日签到", True, h=28, size=10)
button(180, 202, 111, "今天休息", h=28, size=10)
box(65, 242, 227, 155, BG)
text(78, 264, "本周预算", 12, GREEN)
text(211, 263, "怎么填", 10, GREEN)
circle(115, 311, 30, 10)
text(161, 297, "计划 6 小时", 10.5)
text(161, 319, "可再排 12 小时", 10.5)
text(161, 341, "实际已记 1 小时", 9.5, MUTED)
button(78, 355, 200, "总预算 / 留白 · 小时 + 分钟", h=28, size=9.5)
box(65, 408, 227, 54, PALE, PALE)
text(77, 431, "继续上次查看", 11, GREEN)
text(77, 450, "学习 Python", 10)
button(205, 420, 73, "继续", True, h=30, size=10)
box(65, 473, 227, 28)
text(77, 492, "每日足迹    全年 / 展开", 10, GREEN)
text(66, 526, "正在投入的事    搜索 / 记录想法", 10.5)
text(339, 155, "文字与触点", 16, GREEN)
paragraph(339, 182, "主要正文约 14px，常用说明至少 12px。常用按钮与输入高度至少 40px；增加辅助文字对比，保留绿色与暖白气质。", 448, 12, leading=21)
text(339, 273, "布局与信息密度", 16, GREEN)
paragraph(339, 300, "窄屏自然换行，预算输入保持就近。页面不横向溢出；全年密集日历在弹窗内部滚动，日格保留键盘与日详情辅助。", 448, 12, leading=21)
text(339, 391, "键盘与状态反馈", 16, GREEN)
paragraph(339, 418, "按钮有可见焦点，折叠声明 aria-expanded 与 aria-controls。保留 Esc 与关闭后的焦点回到入口，忙碌、错误和重试状态能被理解。", 448, 12, leading=21)
paragraph(339, 513, "验收记录真实像素位置：预算高度、继续入口位置，以及它相对旧版任务区提前了多少。", 448, 11, MUTED, 18)

base("典型使用：先理解，再继续，随时调整", "四条真实路径串起这次改动；成功反馈建立在已有请求确认之上。")
rows = [
    ("第一次进入", "看预算旁的短说明 → 可先记录想法 → 准备投入时再设置预算", "不强制弹窗；不自动写入时间。"),
    ("回来接着做", "看余量 → 点“继续上次查看” → 进入现有步骤或耗时页", "打开页面只读取，不自动计时。"),
    ("想回看进展", "读足迹摘要 → 展开 12 周 / 查看全年 → 点某一天查看记录", "手动签到与真实投入分开呈现。"),
    ("安排需要调整", "就近修改总预算与留白 → 保存 → 圆盘与余量更新", "草稿不被折叠、说明或继续模块刷新覆盖。"),
]
y = 137
for index, (title, flow, note) in enumerate(rows, 1):
    box(36, y, 770, 72, "#FFFFFF" if index % 2 else PALE)
    text(52, y + 29, f"0{index}  {title}", 13, GREEN)
    text(213, y + 28, flow, 11.3)
    text(213, y + 54, note, 10.8, MUTED)
    y += 82
box(36, 467, 770, 76, PALE, PALE)
text(50, 489, "预算来源明细：展开后保留原任务链接，本轮刷新保持展开；负载分析页仍默认展开。", 10.8, GREEN)
paragraph(50, 513, "提交失败仍可原样重试：保留同一请求标识与内容，防止重复记录；旧账号的延迟响应不会串入新账号。", 740, 10.5, GREEN, 17)

base("独立落地与验收：先设计，再证明", "本文件是实施依据；具体通过项、实际截图与限制将在实施后的验收报告中记录。")
card(36, 136, 377, 126, "第五部分单独保存", "代码、规划书、运行环境与本地数据分别落在第五部分目录。服务使用 8004；账号会话 Cookie 与签名密钥独立。")
card(429, 136, 377, 126, "继承数据，保留旧版本", "从第四部分只读创建一致性快照，核对账号、任务、预算与签到记录。配置按原字节复制；导入后各版本不自动同步。")
text(36, 295, "五组必须通过的验收", 16, GREEN)
checks = [
    ("位置", "桌面 1440 × 1000 与手机 390 × 844；继续入口比旧任务区更靠上，页面无横溢。"),
    ("含义", "20 / 2 / 6 小时算例得到 18 小时容量与 12 小时余量；实际投入独立显示。"),
    ("交互", "展开、说明、继续、搜索与切换窗口可用；预算草稿、失败重试与原有签到保留。"),
    ("隔离", "换号、退出、旧响应、损坏偏好不串数据；导入拒绝覆盖，备份可恢复。"),
    ("回归", "沿用后端测试并跑关键浏览器流程；检查新逻辑性质与针对性故障，不虚报覆盖。"),
]
y = 321
for label, body in checks:
    text(36, y, label, 11.5, GREEN)
    paragraph(89, y, body, 715, 11.2, leading=17)
    y += 35
banner(502, "实施顺序：设计 PDF → 新交互失败验证 → 页面实现 → 浏览器与导入验收 → 启动新入口。")

assert len(doc) == 7
doc.set_metadata({"title": "留白 · 第五部分首页减负与交互设计书 v1.0", "author": "留白项目", "subject": "实施前设计提案；首页层级、预算口径与常用操作", "keywords": "留白, 首页, 预算, 交互, 每日足迹, 设计提案"})
doc.subset_fonts()
doc.save(OUT, garbage=4, deflate=True)
doc.close()

check = fitz.open(OUT)
extracted = "\n".join(p.get_text() for p in check)
expected = ["少找一步", "20 小时", "可再安排", "睡眠", "继续上次查看", "aria-expanded", "8004", "设计提案", "有待补时间", "负载分析页仍默认展开"]
compact_text = re.sub(r"\s+", "", extracted)
missing = [value for value in expected if re.sub(r"\s+", "", value) not in compact_text]
assert not missing, missing
bounds = []
for index, p in enumerate(check, 1):
    for block in p.get_text("dict")["blocks"]:
        if "lines" not in block:
            continue
        for row in block["lines"]:
            for span in row["spans"]:
                r = fitz.Rect(span["bbox"])
                if r.x0 < 20 or r.y0 < 12 or r.x1 > W - 20 or r.y1 > H - 8:
                    bounds.append({"page": index, "text": span["text"], "bbox": list(r)})
assert not bounds, bounds
preview = ROOT / "预览图"
preview.mkdir(exist_ok=True)
for index, p in enumerate(check, 1):
    p.get_pixmap(matrix=fitz.Matrix(1.6, 1.6), alpha=False).save(preview / f"设计书_{index:02d}.png")
sheet = fitz.open()
sheet_page = sheet.new_page(width=W * 2, height=H * 4)
for index in range(7):
    x, y = index % 2 * W, index // 2 * H
    sheet_page.show_pdf_page(fitz.Rect(x, y, x + W, y + H), check, index)
sheet_page.get_pixmap(matrix=fitz.Matrix(0.9, 0.9), alpha=False).save(preview / "设计书_总览.png")
report = {
    "pdf": OUT.name,
    "status": "design proposal, not an implementation completion claim",
    "pages": len(check),
    "page_size_pt": [W, H],
    "pymupdf": fitz.VersionBind,
    "python": platform.python_version(),
    "font": str(FONT_PATH),
    "sha256": hashlib.sha256(OUT.read_bytes()).hexdigest(),
    "characters_extracted": len(extracted),
    "required_text_found": expected,
    "out_of_bounds_text": bounds,
    "manual_visual_check": "pending",
    "titles": titles,
}
(ROOT / "第五部分_设计书PDF检查.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
(ROOT / "源文件" / "复现说明.txt").write_text("在项目根目录运行：\npython3 第五部分_首页减负与交互打磨/规划书/源文件/生成首页交互设计书.py\n\n依赖为系统现有 PyMuPDF 1.27.2.3 和 Arial Unicode.ttf，无新增运行依赖。\n产物包含七页 A4 横向设计提案、文本边界检查与逐页预览。\n")
print(json.dumps(report, ensure_ascii=False, indent=2))
