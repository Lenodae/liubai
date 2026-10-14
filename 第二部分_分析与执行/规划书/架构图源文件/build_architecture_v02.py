"""Generate the reviewable phase-two architecture PDF. Requires PyMuPDF."""
from pathlib import Path
import math
import pymupdf as f

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / '第二部分_前后端与完成耗时架构_v0.2.pdf'
PREVIEW = Path('/tmp/taskflow_architecture_v02')
FONT = '/System/Library/Fonts/Supplemental/Arial Unicode.ttf'
font = f.Font(fontfile=FONT)
doc = f.open()
W, H = 1190, 842
P = None
texts = []

def c(v):
    return tuple(int(v[i:i+2], 16)/255 for i in (0,2,4))
INK=c('203B36'); MUTED=c('697B78'); GREEN=c('23735B'); BLUE=c('356DA9')
GRAY=c('7B838A'); LINE=c('D7E1DC'); BG=c('F8FAF6'); RED=c('A65343')

def txt(x,y,s,size=13,color=INK,center=False,maxw=None):
    width=font.text_length(s,fontsize=size)
    if maxw is not None and width > maxw:
        raise ValueError(('too wide',len(doc),s,width,maxw))
    if center: x-=width/2
    P.insert_text((x,y),s,fontname='cn',fontsize=size,color=color)
    texts.append((len(doc),x,y,width,s))

def rect(x,y,w,h,fill='FFFFFF',stroke=LINE):
    P.draw_rect(f.Rect(x,y,x+w,y+h),fill=c(fill),color=stroke,width=.8)

def box(x,y,w,h,title,lines=(),accent=GREEN):
    rect(x,y,w,h)
    P.draw_rect(f.Rect(x,y,x+4,y+h),fill=accent,color=accent)
    txt(x+18,y+28,title,16,accent,maxw=w-32)
    for i,s in enumerate(lines):
        txt(x+18,y+53+i*21,s,12.5,MUTED,maxw=w-32)
    if lines and 53+(len(lines)-1)*21 > h-10:
        raise ValueError(('too tall',title))

def arrow(points,color=GREEN,dash=False,label=None,pos=None):
    for a,b in zip(points,points[1:]):
        P.draw_line(a,b,color=color,width=1.35,dashes='[4 3]' if dash else None)
    a,b=points[-2:]; angle=math.atan2(b[1]-a[1],b[0]-a[0]); k=7
    P.draw_polyline([(b[0]-k*math.cos(angle-.45),b[1]-k*math.sin(angle-.45)),b,
                    (b[0]-k*math.cos(angle+.45),b[1]-k*math.sin(angle+.45))],color=color,width=1.35)
    if label:
        x,y=pos; width=font.text_length(label,fontsize=11)
        P.draw_rect(f.Rect(x-3,y-12,x+width+3,y+3),fill=BG,color=None)
        txt(x,y,label,11,color)

def base(n,title,sub):
    global P
    P=doc.new_page(width=W,height=H); P.insert_font(fontname='cn',fontfile=FONT)
    P.draw_rect(P.rect,fill=BG,color=None)
    txt(42,34,'留白 / 任务分析、执行与反馈',11,GREEN)
    txt(1000,34,f'架构修订  0{n} / 06',11,MUTED)
    txt(42,79,title,29)
    txt(42,108,sub,13,MUTED,maxw=1106)
    P.draw_line((42,129),(1148,129),color=LINE)
    P.draw_line((42,803),(1148,803),color=LINE)
    txt(42,824,'v0.2 · 2026.10.14 · 第二部分设计，尚未实现 · ' + ('绿色实线：请求  蓝色虚线：响应' if n == 5 else '蓝色：已有基础  绿色：本期新增  灰色：后续'),10,MUTED)
    txt(955,824,'实线：操作 / 关系；虚线：数据流',9,MUTED)

def note(y,s,color=GREEN):
    rect(42,y,1106,43,'EEF4EC')
    txt(57,y+27,s,13,color,maxw=1076)

# 1 — Whole system
base(1,'整体架构：从拆分计划走到完成反馈','沿用当前 Django + SQLite，新增步骤、完成登记与耗时账本；一个后端应用内分模块组织。')
box(42,155,340,103,'已有：账号与任务入口',[
    '登录 / 注册、任务清单与详情', '任务编辑、状态切换、状态历史'],BLUE)
box(425,155,340,103,'新增：分析与执行界面',[
    '完成标准 → 规则分析 → 步骤草稿', '确认采纳 → 执行 → 记时 → 完成'])
box(808,155,340,103,'后续：跨任务规划',[
    '个人周预算、整体负载与维护时间', '自动排期、计时器、历史估算校准'],GRAY)
box(42,309,1106,81,'统一 HTTP API 与当前用户上下文',[
    '沿用 Cookie 会话、CSRF、归属检查与版本冲突处理；新增写入沿用幂等请求键'],BLUE)
arrow([(212,258),(212,309)],BLUE); arrow([(595,258),(595,309)])
box(42,446,250,122,'任务与步骤',[
    '父任务 / 一层子步骤', '依赖关系与状态约束', '当前清单只展示父任务'])
box(327,446,250,122,'规则与拆分',[
    '目标、条件与估时区间', '手工草稿 / AI 草稿', '用户采纳才创建步骤'])
box(612,446,250,122,'执行与完成',[
    '逐次登记 / 完成时补记', '完成说明、成果链接', '完成撤销与操作历史'])
box(897,446,251,122,'统计与历史',[
    '按有效耗时记录汇总', '预计 / 实际分开展示', '记录完整性由用户确认'])
for x in [167,452,737,1022]: arrow([(x,390),(x,446)])
box(42,625,750,102,'同一个 SQLite 数据库 · 业务写入使用事务',[
    '现有 Task / TaskEvent + 新增 TaskStep、TimeEntry、CompletionEvent',
    'AnalysisRun / PlanDraft / WriteReceipt；不为每个模块拆独立数据库'],BLUE)
box(827,625,321,102,'2B：后台分析任务 + 模型适配器',[
    '持久化任务状态、前端轮询结果', '模型只生成草稿，不能写完成与耗时'])
for x in [167,452,737]: arrow([(x,568),(x,625)])
arrow([(1022,568),(1022,595),(760,595),(760,625)])
arrow([(577,507),(593,507),(593,609),(988,609),(988,625)],dash=True,label='分析子流程',pos=(852,600))
note(746,'新增主线：完成标准 → 步骤执行 → 实际耗时 → 用户确认完成 → 保留历史；AI 不替用户确认结果。')

# 2 — Frontend
base(2,'前端架构：完成按钮连接两份记录','完成状态回答“做完了吗”；耗时账本回答“实际投入多久”。两者可以一起提交，但含义各自独立。')
box(42,159,1106,81,'任务主页 → 父任务详情',[
    '保留原有筛选与入口；详情新增“分析与拆分 / 步骤 / 耗时记录 / 完成历史”'],BLUE)
for x in [212,595,978]: arrow([(x,240),(x,287)])
box(42,287,340,145,'分析与拆分面板',[
    '目标、完成标准、基础与约束', '预计总耗时区间、每周计划投入', '编辑草稿、选择步骤、确认采纳', '新分析不会替换已有执行记录'])
box(425,287,340,145,'步骤与完成面板',[
    '步骤状态、依赖、完成标准', '标记完成：说明 / 成果链接可选', '显示已记耗时，补记遗漏部分', '全部步骤完成后提示确认父任务'])
box(808,287,340,145,'实际耗时账本',[
    '选择任务本身或某个子步骤', '填写投入日期、时长、可选备注', '修改 / 删除自己的记录', '展示总量及“完整 / 待确认”'])
box(42,493,340,123,'分析草稿状态',[
    '输入 / 生成中 / 可编辑 / 已采纳', '过期结果提示重新分析', '生成失败仍可手工拆分'])
box(425,493,340,123,'完成确认弹层',[
    '已记 90 分钟 → 只补漏记时长', '暂不填写：保持“未记录 / 待确认”', '误点撤销：保留已有耗时账本'])
box(808,493,340,123,'数据与提交状态',[
    '已保存数据与表单草稿分离', '失败保留输入；成功刷新汇总', '切换账号时隔离数据与草稿'],BLUE)
for x in [212,595,978]: arrow([(x,432),(x,493)])
box(42,675,1106,78,'统一 API 客户端',[
    '携带会话、CSRF、对象版本和请求键；处理 401 / 404 / 409；服务器确认成功后再显示已保存'],BLUE)
for x in [212,595,978]: arrow([(x,616),(x,675)])
txt(44,782,'界面约定：有记录但尚未核对时显示“已记录 3 小时 · 待确认”，不能直接显示为最终总耗时。',13,GREEN)

# 3 — Backend
base(3,'后端架构：业务规则集中，统计只读汇总','以下接口为拟定设计；现有账号和任务接口保留。所有新增资源都沿所属父任务验证当前用户。')
box(42,153,1106,82,'API 校验层：登录、归属、输入、版本、重复请求',[
    '客户端传来的任务 / 步骤编号不是权限；步骤必须属于同一父任务；时长为正整数分钟'],BLUE)
xs=[42,326,610,894]
for x in xs: arrow([(x+127,235),(x+127,279)])
box(42,279,254,144,'分析与草稿服务',[
    'POST /tasks/:id/analyses', 'POST /drafts/:id/apply', '规则分析、草稿结构校验', '单次采纳事务与版本校验'])
box(326,279,254,144,'步骤与完成服务',[
    'PATCH /steps/:id', 'POST /tasks/:id/completions', 'POST /steps/:id/completions', '专用撤销操作记录原因'])
box(610,279,254,144,'耗时账本服务',[
    'GET/POST /tasks/:id/time-entries', 'PATCH/DELETE /time-entries/:id', '补记、改正、作废留痕', '检查归属与步骤关联'])
box(894,279,254,144,'统计查询服务',[
    'GET /tasks/:id/summary', '有效记录求和，无记录返回空', '预计 / 已记 / 完整性分别返回', '不把父子汇总再次相加'])
# Transaction box applies to writes; statistics reads are separate.
box(42,485,822,121,'写入事务边界',[
    '版本校验 → 写步骤 / 完成事件 / 耗时及修订 → 更新版本 → 写请求回执 → 提交',
    '一次“完成 + 补记”全部成功或全部回滚；相同请求重试返回原回执',
    '耗时变更使相应完成耗时结论待重新确认；新分析引用最新父任务版本'])
for x in [169,453,737]: arrow([(x,423),(x,485)])
box(894,485,254,121,'统计口径',[
    '按投入日期查看实际花费', '周计划投入独立存放', 'AI 无权写入实际耗时'])
arrow([(1021,423),(1021,485)])
box(42,666,1106,81,'SQLite 数据访问层',[
    '唯一请求键防重复；写入后推进父任务版本；修改记录校验记录版本；归属限定覆盖查询和修改'],BLUE)
arrow([(453,606),(453,666)])
arrow([(1021,666),(1021,606)],dash=True,label='读取有效账本',pos=(1029,641))
txt(44,780,'接口路径均带 /api 前缀；第二部分统一任务完成入口，原状态修改接口不能绕过完成登记规则。',12.5,GREEN)

# 4 — data architecture
base(4,'数据架构：账本是耗时事实，完成是独立事件','父任务的实际总耗时从记录计算；不同时保存一份可手改的父任务总数，避免统计漂移。')
box(42,155,340,145,'Task · 父任务（现有表扩展）',[
    'owner / status / version（已有）', 'weekly_minutes：每周计划投入（已有）', '新增完成标准、条件、目标日期', '实际耗时通过账本聚合返回'],BLUE)
box(425,155,340,145,'TaskStep · 子步骤',[
    'task_id / 顺序 / 状态 / version', '完成标准、预计总耗时上下限', 'StepDependency 保存同任务前置关系', '只允许一层，不另设每周投入'])
box(808,155,340,145,'TimeEntry · 实际投入记录',[
    'task_id + step_id（可空）', '投入日期 / duration_minutes / 备注', '创建及修改时间 / version / 作废时间', '一笔只归属任务本身或一个步骤'])
arrow([(382,226),(425,226)],label='1:N',pos=(390,214))
arrow([(765,226),(808,226)],label='关联',pos=(772,214))
box(42,371,340,145,'CompletionEvent · 完成登记',[
    'task_id + step_id（可空）', '完成 / 撤销 / 核对、时间、前后状态', '操作者、完成说明 / 成果链接（可选）', '完整性确认及当时账本版本'])
box(425,371,340,145,'ExecutionEvent · 操作历史',[
    '步骤状态变化、耗时增改作废', '对象编号、前后值、时间、操作者', '历史保留；不参与实际耗时求和', '父任务状态仍记入原 TaskEvent'])
box(808,371,340,145,'WriteReceipt · 幂等回执',[
    'owner / 操作类型 / request_key', '请求指纹、结果对象与响应快照', '同键同内容返回原结果', '同键不同内容返回冲突'])
arrow([(212,300),(212,371)])
arrow([(595,300),(595,371)])
# TimeEntry is the source of read-only statistics, not WriteReceipt.
box(42,585,530,118,'AnalysisRun → PlanDraft',[
    '输入快照 / 父任务版本 / 分析状态 / 模型与规则版本', '草稿可编辑；保存草稿修订与原始输出', 'WriteReceipt 统一承接原方案 PlanApplyReceipt 的采纳回执'])
box(612,585,536,118,'只读统计结果 · 不再建立第二份实际时间账本',[
    'task_actual = 任务本身有效记录 + 所有子步骤有效记录', 'step_actual = 该步骤的有效记录；作废 / 修订历史不计入', '无记录为 null；已记录合计与是否完整分别返回'])
arrow([(1148,226),(1163,226),(1163,644),(1148,644)],dash=True)
txt(805,568,'统计读取 TimeEntry 的有效记录',11,GREEN)
note(735,'约束：step_id 若非空，必须属于同一个 task_id；从父任务验证 owner；完成、暂停或撤销都不删除已花时间。')

# 5 — Sequence
base(5,'前后端交互：一次“完成 + 补记”怎么保存','示例：这个步骤已记 90 分钟，用户发现漏记 30 分钟；提交后显示 120 分钟，不另填一笔 120 分钟。')
centers=[114,350,590,828,1076]
labels=['用户','前端页面','完成 / 耗时 API','业务服务','数据库']
for x,s in zip(centers,labels):
    rect(x-69,156,138,47)
    txt(x,185,s,14,GREEN,center=True,maxw=126)
    P.draw_line((x,203),(x,654),color=LINE,dashes='[4 4]')
def msg(a,b,y,s,response=False):
    xa,xb=centers[a],centers[b]
    arrow([(xa,y),(xb,y)],color=BLUE if response else GREEN,dash=response)
    txt((xa+xb)/2,y-8,s,11.5,BLUE if response else INK,center=True,maxw=abs(xa-xb)-12)
msg(0,1,248,'点击“完成”并补记 30 分钟')
txt(470,304,'一次请求：目标 ID / 版本 / 请求键',11.5,INK,center=True)
msg(1,2,326,'说明、补记、完整性确认')
msg(2,3,370,'验证身份、归属、参数')
msg(3,4,414,'校验版本与幂等回执')
msg(3,4,458,'原子写入完成、补记、历史')
msg(4,3,502,'提交成功；回执持久保存',True)
msg(3,2,546,'返回状态与最新有效合计',True)
msg(2,1,590,'已完成；累计 120 分钟',True)
msg(1,0,634,'刷新步骤与父任务汇总',True)
box(42,680,340,106,'网络超时 / 重复点击',[
    '重试复用同一个请求键与原始内容', '后端返回原回执，不重复累计 30 分钟'])
box(425,680,340,106,'版本冲突 / 数据库失败',[
    '冲突保留输入，刷新后由用户重新确认', '事务失败回滚，不能留下半条完成记录'])
box(808,680,340,106,'独立记时 / 完成撤销',[
    '平时记时不改变任务完成状态', '撤销完成保留耗时，重新打开后可继续记'])

# 6 — rules and stages
base(6,'计算与状态规则：把“预计、实际、周期”分清','完成跨越了两天，不等于投入了 48 小时；耗时累计真实投入，周计划衡量每周愿意投入多少。')
box(42,155,340,124,'每周计划投入',[
    '父任务：4 小时 / 周', '用于后续整体负载与周预算', '不与步骤总耗时相加'])
box(425,155,340,124,'预计总耗时',[
    '步骤预计区间之和：5～9 小时', '只表示预估，未知项单独提示', '不能直接当作已花时间'])
box(808,155,340,124,'已记录实际耗时',[
    '概念 40 + 手算 50 + 代码 90 分钟', '父任务累计：180 分钟 = 3 小时', '此时父任务不再补记一笔 3 小时'])
box(42,315,535,166,'账本归属与后补规则',[
    '有子步骤：优先记到步骤；整体整理等工作可记父任务本身。',
    '父任务本身另花 20 分钟，则累计 180 + 20 = 200 分钟。',
    '已记 90 分钟，实际为 120：补记 30 或修正原记录。',
    '若先记在父任务后拆步骤：可迁移归属，不能复制时长。',
    '历史补记允许用于暂停 / 已结束任务，不自动恢复任务状态。'])
box(613,315,535,166,'状态与完成记录',[
    '必要步骤全部完成 → 提示用户确认父任务；不自动结束。',
    '父任务提前结束 → 明示未完成步骤，不批量假装完成。',
    '父任务暂停 → 子步骤显示随任务暂停，保留原始状态。',
    '撤销完成 → 恢复到完成前的非结束状态，并追加事件。',
    '父任务仍已结束时，先恢复父任务，再恢复步骤执行。'])
box(42,517,535,123,'完整性与撤销',[
    '没有耗时记录：显示“未记录”，不按 0 分钟处理。',
    '有记录但未核对：显示“已记录合计 · 待确认”。',
    '用户确认完整后才显示最终实际耗时；后续改账需重新确认。'])
box(613,517,535,123,'拆分改动与分析',[
    '本期重新拆分只支持明确追加，不自动替换已执行步骤。',
    '完成数占比不等于时间完成度，剩余耗时需重新估计。',
    'AI 可给预估与建议；实际投入与完成仍由用户登记确认。'])
rect(42,676,1106,109,'EEF4EC')
txt(58,702,'第二部分实施顺序',16,GREEN)
txt(58,728,'2A-1 手工步骤与完成标准  →  2A-2 耗时账本、完成登记与汇总  →  2A-3 规则分析与采纳',13)
txt(58,751,'2B 接入 AI 草稿与后台分析任务；计时器、全局负载与自动排期后续实现。',12.5,MUTED)
txt(58,772,'依据：原始需求分析、第二部分方案 v0.1、当前 Task / TaskEvent 代码及本次完成与耗时讨论。',11,MUTED)

# Ensure the exported vector text is legible and inside the page.
for page_no,x,y,width,s in texts:
    assert x >= 35 and x+width <= W-30 and y < H-10, (page_no,s)
    missing=[ch for ch in s if not ch.isspace() and font.has_glyph(ord(ch)) == 0]
    assert not missing,(s,missing)
doc.set_metadata({'title':'留白：第二部分前后端与完成耗时架构 v0.2',
                  'author':'留白项目设计','subject':'新增完成登记、实际耗时账本、父子汇总、版本与事务规则；设计待实现'})
doc.subset_fonts()
doc.save(OUT,garbage=4,deflate=True)
doc.close()
PREVIEW.mkdir(exist_ok=True)
with f.open(OUT) as check:
    assert len(check)==6
    for i,p in enumerate(check):
        p.get_pixmap(matrix=f.Matrix(1.1,1.1)).save(PREVIEW/f'page-{i+1}.png')
        assert '\ufffd' not in p.get_text()
print(OUT)
print(f'6 pages; {OUT.stat().st_size} bytes; all glyphs and text bounds checked')
