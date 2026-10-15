"""Build the standalone load-dial design plan. Content and vector layout are self-contained."""
from pathlib import Path
import os
import math
import hashlib
import json

import pymupdf as fitz

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '负载圆盘_交互与视觉设计计划_v0.1.pdf'
FONT_PATH = os.environ.get('LIUBAI_PLAN_FONT', '/System/Library/Fonts/Supplemental/Arial Unicode.ttf')
FONT = fitz.Font(fontfile=FONT_PATH)
W, H = 842, 595
INK = '#243E38'
GREEN = '#286753'
MUTED = '#63766E'
BLUE = '#366884'
AMBER = '#965D24'
RED = '#A3493F'
LINE = '#D8E2DB'
BG = '#F7F9F5'
doc = fitz.open()
page = None
titles = []
drawn = []


def color(value):
    return tuple(int(value[i:i+2], 16) / 255 for i in (1, 3, 5))


def text(x, y, value, size=11.5, ink=INK):
    value = str(value)
    width = FONT.text_length(value, fontsize=size)
    assert x >= 24 and x + width <= W - 24, (len(doc), value, x, width)
    assert 20 <= y <= H - 14, (len(doc), value, y)
    page.insert_text((x, y), value, fontsize=size, fontname='cn', color=color(ink))
    drawn.append((len(doc), x, y, width, value))


def wrap(value, width, size=11.5):
    result = []
    for para in value.split('\n'):
        line = ''
        for char in para:
            if FONT.text_length(line + char, fontsize=size) > width:
                result.append(line)
                line = char
            else:
                line += char
        result.append(line)
    return result


def paragraph(x, y, value, width=758, size=11.5, ink=INK, leading=18):
    for line in wrap(value, width, size):
        text(x, y, line, size, ink)
        y += leading
    return y


def rect(x, y, w, h, fill='#FFFFFF', stroke=LINE):
    page.draw_rect(fitz.Rect(x, y, x+w, y+h), fill=color(fill), color=color(stroke), width=.7)


def base(title, subtitle):
    global page
    page = doc.new_page(width=W, height=H)
    page.insert_font(fontname='cn', fontfile=FONT_PATH)
    page.draw_rect(page.rect, fill=color(BG), color=None)
    titles.append(title)
    text(42, 31, '留白 / ROOM TO FOCUS', 10, GREEN)
    text(570, 31, '负载圆盘专项 · 视觉与交互设计', 10, MUTED)
    text(42, 73, title, 24)
    paragraph(42, 100, subtitle, size=10.8, ink=MUTED, leading=16)
    page.draw_line((42, 116), (800, 116), color=color(LINE))


def note(y, value, ink=GREEN):
    lines = wrap(value, 730, 11)
    h = len(lines)*17 + 20
    rect(42, y, 758, h, '#EDF3EB')
    paragraph(56, y+23, value, 730, 11, ink, 17)
    assert y+h <= 546, (titles[-1], y+h)
    return y+h


def sections(title, subtitle, items, takeaway=None):
    base(title, subtitle)
    y = 147
    for heading, body in items:
        text(42, y, heading, 13, GREEN)
        y = paragraph(42, y+23, body, leading=18) + 15
    if takeaway:
        note(y-3, takeaway)
    else:
        assert y <= 548, (title, y)


def table(title, subtitle, headers, rows, widths, tail=None, size=11):
    base(title, subtitle)
    y = 134
    x = 42
    for head, width in zip(headers, widths):
        rect(x, y, width, 30, '#E4EEE5')
        text(x+10, y+20, head, 11, GREEN)
        x += width
    y += 30
    for index, row in enumerate(rows):
        cells = [wrap(cell, width-20, size) for cell, width in zip(row, widths)]
        height = max(map(len, cells))*17+17
        x = 42
        for lines, width in zip(cells, widths):
            rect(x, y, width, height, '#FFFFFF' if index%2 == 0 else '#F0F4EF')
            for j, line in enumerate(lines):
                text(x+10, y+21+j*17, line, size)
            x += width
        y += height
    if tail:
        y = paragraph(42, y+25, tail, size=10.8, ink=MUTED, leading=17)
    assert y <= 546, (title, y)


def box(x, y, w, h, heading, body, accent=GREEN):
    rect(x, y, w, h)
    page.draw_rect(fitz.Rect(x, y, x+3, y+h), color=color(accent), fill=color(accent))
    text(x+14, y+24, heading, 13, accent)
    end = paragraph(x+14, y+46, body, w-28, 10.8, INK, 17)
    assert end-17 <= y+h-9, (heading, end, y+h)


def arrow(points, ink=GREEN):
    for a, b in zip(points, points[1:]):
        page.draw_line(a, b, color=color(ink), width=1.2)
    a, b = points[-2:]
    theta = math.atan2(b[1]-a[1], b[0]-a[0])
    page.draw_polyline([(b[0]-6*math.cos(theta-.5), b[1]-6*math.sin(theta-.5)), b,
                       (b[0]-6*math.cos(theta+.5), b[1]-6*math.sin(theta+.5))],
                      color=color(ink), width=1.2)


def centered(cx, y, value, size=11.5, ink=INK):
    width = FONT.text_length(value, fontsize=size)
    text(cx-width/2, y, value, size, ink)


def arc(cx, cy, radius, start, end, ink, width=13):
    if end <= start:
        return
    n = max(2, math.ceil((end-start)*160))
    points = []
    for i in range(n+1):
        angle = -math.pi/2 + 2*math.pi*(start+(end-start)*i/n)
        points.append((cx+radius*math.cos(angle), cy+radius*math.sin(angle)))
    page.draw_polyline(points, color=color(ink), width=width)


def dial(cx, cy, label, status, *, low=None, high=None, ink=GREEN, r=61, outline=False):
    page.draw_circle((cx, cy), r, color=color('#DDE5DE'), width=13)
    if outline:
        for i in range(36):
            arc(cx, cy, r, i/36, (i+.55)/36, ink, 5)
    elif low is not None:
        filled = min(max(low, 0), 1)
        arc(cx, cy, r, 0, filled, ink)
        if high is not None and high > low:
            top = min(high, 1)
            pos = filled
            while pos < top:
                arc(cx, cy, r, pos, min(pos+.013, top), ink)
                pos += .025
    centered(cx, cy-20, '当前负载', 9.5, MUTED)
    centered(cx, cy+7, label, 18 if len(label)<10 else 14.2, ink)
    centered(cx, cy+29, status, 10.5, ink)


# 01
base('负载圆盘：让当前承诺一眼可读', '专项设计计划 v0.1 / 2026.10.14 / 独立于实施排期；先确定视觉与交互，不修改正在使用的页面。')
text(42, 148, '推荐形态：环形圆盘 + 中心数字 + 文字状态', 16, GREEN)
paragraph(42, 173, '圆盘显示所选窗口内“需求占可分配时间的比例”；不是完成进度，也不是人的健康或能力评分。', size=11.5)
for cx, label, status, low, high, ink, caption in [
    (137, '75%', '当前可覆盖', .75, None, GREEN, '需求 6h / 可分配 8h'),
    (326, '87.5–125%', '区间有风险', .875, 1.25, AMBER, '需求 7–10h / 可分配 8h'),
    (515, '125%', '已超可分配量', 1.25, None, RED, '需求 10h / 可分配 8h'),
    (704, '待补资料', '整体尚不确定', None, None, MUTED, '还有 2 项投入未确认'),
]:
    dial(cx, 269, label, status, low=low, high=high, ink=ink, outline=low is None)
    centered(cx, 367, caption, 10.2, MUTED)
note(399, '绿色表示当前时间估计可覆盖；黄色表示估时上下界跨过预算；红色表示已知需求超出可分配量；灰色表示暂不能完整判断。')
paragraph(42, 474, '独立放在第三部分的“负载圆盘专项”文件夹。它替代总览中的部分摘要图形，与预算和任务集共同展示，不新增一个登录后必须经过的页面。', size=11.2, ink=MUTED)

# 02
base('视觉结构：一个圆盘只表达一个问题', '不使用速度表指针、多层彩虹和完成度动画。默认看“本周剩余”，窗口标签始终在圆盘上方。')
rect(42, 137, 310, 346)
centered(197, 163, '本周剩余 · 10/14 15:00 至周日', 10.5, MUTED)
dial(197, 272, '87.5–125%', '区间有风险', low=.875, high=1.25, ink=AMBER, r=76)
centered(197, 379, '需求 7–10h / 可分配 8h', 12)
centered(197, 405, '上界超出 2h', 12, AMBER)
centered(197, 433, '预算 9h − 预留缓冲 1h = 8h', 10.5, MUTED)
centered(197, 459, '15:00 已确认 · 查看负载详情 →', 10, GREEN)
box(382, 137, 418, 87, '颜色：只来自确定性状态', '采用留白现有的绿、琥珀、红、灰色系。\n不设通用“超过 80% 就危险”的阈值；判定看需求区间与容量。')
box(382, 243, 418, 111, '弧线：实段是下限，虚段是区间延伸', '从顶部顺时针绘制；浅灰底轨代表可分配量。\n需求区间的下限画实线，上限延伸部分画虚线。\n超出一圈的部分用文字报告，不再绕第二圈或截成 100%。')
box(382, 373, 418, 110, '中心与旁边：数字帮助解释颜色', '中心显示真实比例或待确认状态，旁边保留小时数。\n容量未知、为零或结论过期时不显示比率。\n文字与图形同步变化，图例可点击展开，不只悬停可见。')
note(503, '小数显示最多 1 位；颜色与边界始终按原始分钟判断。若四舍五入会把实际超载显示为 100%，显示“>100%”并列出超出分钟。')

# 03
table('颜色规则：先判断资料，再判断压力', '沿用负载模块：B 为该窗口预算，F 为缓冲，C = B − F；需求为 [L, U]，精确值等价于 L = U。',
      ['条件', '颜色与文字', '圆盘行为'], [
          ['资料完整，C>0，U<C', '绿：当前估计可覆盖。', '显示 [L/C, U/C]；精确值只显示一个百分比。'],
          ['资料完整，C>0，U=C', '绿：上界刚好用满；精确值显示可分配量已用满。', '保留真实区间；L=U=C 时为100%。注明可分配余量为0。'],
          ['资料完整，C>0，L≤C<U', '琥珀：区间有风险；上界缺多少。', '下限实段 + 上限虚段；超圈部分以数值说明。'],
          ['资料完整，C>0，L>C', '红：至少超出 L−C。', '环最多画满，比例可以是125%或更高，不能截断数值。'],
          ['资料不完整，且已知下限 K>C', '红色虚环：已知至少超出 K−C；另有未知项。', '不输出完整总比例；中心显示“至少超 X”。'],
          ['预算/需求有未知，其余情况', '灰：待填预算或待补资料。', '不按0填充，不显示“剩余X小时”，不套用绿灯。'],
      ], [220, 283, 255], '红色只说明超出可分配量。需求仍在 B 以内时标“需占用缓冲”；超过 B 另列总预算缺口。\nC=0 且需求下限>0：红色虚环报告冲突；需求也确认0：中性灰、无安排。两者都不计算比率。', size=10.5)

# 04
base('特殊状态：不能靠满圈或空圈让用户猜', '零容量、未知、过期和超载都必须有自己的文字。以下为示例，所有数据均非真实账号记录。')
cards = [
    (42, 137, '零容量', '无可分配', '超出 1h', RED, 'C=0，需求1h：不除以零、不显示∞。'),
    (432, 137, '已知超载 + 仍有未知', '至少超1h', '另有2项未知', RED, 'C=8h，K=9h：红色虚环，无总比例。'),
    (42, 330, '确认已失效', '待复核', '上次 15:00', MUTED, '跨日或执行有变化：灰环，旧值单列。'),
    (432, 330, '真实零需求', '0%', '本窗未安排', GREEN, 'C=8h、需求确认0：空轨和文字；不是未录入。'),
]
for x,y,title,label,status,ink,body in cards:
    rect(x,y,368,177)
    text(x+13,y+23,title,12,GREEN)
    dial(x+91,y+97,label,status,low=0 if label=='0%' else None,ink=ink,r=49,outline=label!='0%')
    paragraph(x+164,y+78,body,190,11,INK,18)
text(42, 539, 'C=0 且需求确认0：显示“本窗无安排”，仍无百分比。读取失败显示“暂不可用”；旧结果不能伪装成实时值。', 10.4, MUTED)

# 05
base('放到总览里：醒目，但不挡住任务集', '这是前端结构计划 v0.2 的组件补充。桌面横排、手机紧凑横排；点击进入已有“负载与建议”页。')
rect(42, 139, 758, 337)
text(59, 165, '留白 / 总览', 14,GREEN)
text(570, 165, '编辑预算    查看建议    ＋记录任务', 11,GREEN)
text(59, 190, '本周剩余 · 10/14 15:00 至周日',10.5,MUTED)
dial(147, 284, '87.5–125%', '区间有风险',low=.875,high=1.25,ink=AMBER,r=59)
text(247, 239, '当前需求 7–10 小时 / 可分配 8 小时',16)
text(247, 271, '预算 9h，缓冲 1h；上界可能缺 2h。',12,AMBER)
text(247, 302, '实段 = 下限；虚段 = 上限延伸。查看任务贡献 →',11,MUTED)
text(247, 331, '15:00 已确认 · 期限详情仍需另看',10.5,MUTED)
page.draw_line((59, 362), (783, 362),color=color(LINE))
text(59, 387, '当前任务集',14)
text(630, 387, '搜索任务…  查看全部',10.5,GREEN)
for y,title,amount in [(416,'论文：整理与修改','推进 3–4h + 维护 1h'),
                       (444,'机器学习：完成示例','推进 2–3h + 维护 0.5h'),
                       (472,'生活项目：处理待办','推进 0.5–1.5h + 维护 0h')]:
    text(64,y,title,11)
    text(427,y,amount,10.5,MUTED)
    text(717,y,'打开 →',10.5,GREEN)
note(491, '桌面144–176px；手机96–112px，区间比例放盘旁、盘内仅短状态。手机仍保留窗口与小时数，首屏可见任务，不另开仪表页。')

# 06
sections('交互与可读性：数字、颜色、文字一起工作', '圆盘是信息组件，真正的操作仍通过清楚标注的按钮完成；不把拖动圆盘变成修改预算的捷径。', [
    ('可操作的入口', '圆盘旁提供“查看负载详情”，进入同账号、同窗口的负载页；预算未知时主操作为“补充预算”，需求未知时定位缺失项。仍可继续浏览任务和记录想法。完整圆盘可链接到详情，但不嵌套多个难以点击的热点。'),
    ('辅助信息不依赖颜色和鼠标', '状态文字、真实需求/容量、上界或下界缺口始终可见；区间用虚段区别。图例用可点击展开，键盘可达并有焦点。读屏按一句话朗读窗口、需求区间、可分配量、结论和未知项；SVG 形状本身避免重复朗读。'),
    ('刷新过程必须诚实', '保存任务/预算后先标记分析待刷新；同窗口新快照返回后一起更新颜色、文字和数字。换账号清空；换窗口丢弃旧响应。过期时改为灰色待复核，旧结论只以“上次结果”展示。'),
    ('动效与视觉约束', '首版默认静态；后续可加短暂淡入，不做自动旋转、呼吸红光或庆祝满圈。尊重减少动态效果偏好。颜色采用深绿/琥珀/红/灰，正文保持深色；验证灰度、色觉差异、放大字体与深浅背景下的辨识。'),
], '绿灯也只代表当前时间口径覆盖；期限风险仍单独提示。负载百分比越高不代表任务完成越多，不能配“继续冲刺到满圈”的文案。')

# 07
sections('实现拆分：纯展示组件，沿用同一份分析', '本次仅设计。后续优先完成总览、预算与规则计算，再接圆盘；它不阻塞第三部分核心交付。', [
    ('输入契约', '复用 loadStore 的同一快照：window、mode、as_of、computed_at、freshness、budget、buffer、capacity、demand_low/high、known_lower、unknown_count、verdict。后端决定状态与原始数值，前端只格式化数字和绘制弧线。'),
    ('组件职责', 'LoadDial 负责环形图；LoadSummary 负责小时数、缺口、未知项和时间标签；LoadLegend 解释实段/虚段；按钮复用既有路由。使用 SVG 绘制，文字用正常 HTML，响应式缩放；不要引入整套图表库只画一个圆盘。'),
    ('分三步落地', 'D1：静态样例覆盖绿/琥珀/红/灰、零容量和过期。D2：连接现有分析快照，接详情跳转、键盘与读屏。D3：完成真实浏览器的账号切换、窗口切换、过期和手机验收，再替换原摘要中的图形区域。'),
    ('与前两份规划的关系', '负载公式继续使用第三部分 v0.1，首页路径继续使用前端 v0.2。本专项只定义展示、状态映射和交互；不新增负载评分、不更改数据模型，不触发 DeepSeek 调用或自动修改任务。'),
], '新组件失效时降级为同样的文字摘要；预算与任务仍可使用，不能把整张首页变成错误页面。')

# 08
table('验收清单：图形漂亮，也要不误导', '未来实施时逐项验证；本次 PDF 已检查这些算例与绘制对应，未宣称网页组件已经实现。',
      ['输入 / 操作', '必须呈现的结果'], [
          ['C=8h，需求6h', '绿环75%，文字“当前估计可覆盖”；不是完成75%。'],
          ['C=8h，需求[7,10]h', '琥珀87.5–125%，下限实段、上限虚段；旁列上界超2h。'],
          ['C=8h，需求10h；B=10h、F=2h', '红环125%但只画一圈；超可分配2h，注明需要占用2h缓冲。'],
          ['C=8h，需求8h / [6,8]h', '前者100%并注明可分配量已用满；后者75–100%、上界刚好用满。'],
          ['C=0，需求1h / 需求0', '都不显示比例；分别写超出1h / 本窗无安排。'],
          ['C=8h，K=6h或9h，另有未知', '前者灰色待补；后者红虚环“至少超1h”，均没有完整总百分比。'],
          ['C=480min，需求481min', '按原值判红；不会因取整显示“100%刚好”。显示>100%或100.2%，并列超1min。'],
          ['跨日、改账、换账号/窗口、灰度与390px', '过期不能保留当前绿灯；旧响应不回填；不靠颜色也能理解；首页仍见任务。'],
      ], [320,438], '文件独立保存在“第三部分_负载建议与分析/规划书/负载圆盘专项”。首版设计完成，开发排期留到总览核心功能可用之后。', size=10.5)


for i, p in enumerate(doc):
    page=p
    page.draw_line((42,557),(800,557),color=color(LINE))
    text(42,578,'v0.1 · 2026.10.14 · 负载圆盘专项 · 设计稿，尚未实现',9,MUTED)
    text(737,578,f'{i+1:02d} / {len(doc):02d}',9,MUTED)
doc.set_toc([[1,t,i+1] for i,t in enumerate(titles)])
doc.set_metadata({'title':'留白 · 负载圆盘交互与视觉设计计划 v0.1',
                  'author':'留白项目规划','subject':'负载圆盘、颜色、区间估时、可访问性与前端接入'})
doc.subset_fonts()
doc.save(OUT,garbage=4,deflate=True)
doc.close()
with fitz.open(OUT) as check:
    for p in check:
        assert '\ufffd' not in p.get_text()
        assert len(p.get_text())>150
        for block in p.get_text('dict')['blocks']:
            for line in block.get('lines',[]):
                for span in line['spans']:
                    x0,y0,x1,y1=span['bbox']
                    assert 20<=x0<x1<=W-20 and 5<=y0<y1<=H-5,(p.number+1,span)
    report={'document':OUT.name,'pages':len(check),'bookmarks':len(check.get_toc()),
            'size_bytes':OUT.stat().st_size,'sha256':hashlib.sha256(OUT.read_bytes()).hexdigest(),
            'checks':['中文提取','页面边界','非空页面','页码与书签'],'page_titles':titles}
(ROOT/'PDF生成检查.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k!='page_titles'},ensure_ascii=False,indent=2))


