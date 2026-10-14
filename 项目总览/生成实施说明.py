"""Regenerate phase-specific implementation PDFs from local verification artifacts."""
import json
from pathlib import Path
import pymupdf as fitz

ROOT=Path(__file__).resolve().parent.parent
FONT='/System/Library/Fonts/Supplemental/Arial Unicode.ttf'
font=fitz.Font(fontfile=FONT)
INK=(.13,.24,.21);GREEN=(.14,.38,.29);MUTED=(.40,.48,.42)

def write_pdf(folder,name,pages):
    doc=fitz.open()
    for i,(title,sections) in enumerate(pages):
        p=doc.new_page(width=595.28,height=841.89);p.insert_font(fontname='cn',fontfile=FONT)
        p.draw_rect(p.rect,fill=(.98,.99,.97),color=None)
        p.insert_text((42,33),'留白 / ROOM TO FOCUS',fontname='cn',fontsize=10,color=GREEN)
        p.insert_text((42,77),title,fontname='cn',fontsize=23,color=INK)
        p.draw_line((42,100),(553,100),color=(.83,.88,.83))
        y=129
        for heading,body in sections:
            p.insert_text((42,y),heading,fontname='cn',fontsize=13,color=GREEN);y+=24
            for para in body.split('\n'):
                line=''
                for char in para:
                    if font.text_length(line+char,fontsize=10.5)>508:
                        p.insert_text((42,y),line,fontname='cn',fontsize=10.5,color=INK);y+=17;line=char
                    else:line+=char
                if line:p.insert_text((42,y),line,fontname='cn',fontsize=10.5,color=INK);y+=17
            y+=17
        assert y<778,(title,y)
        p.draw_line((42,790),(553,790),color=(.83,.88,.83))
        p.insert_text((42,813),f'v1.0 · 2026.10.14 · 本机实施说明   |   {i+1}/{len(pages)}',fontname='cn',fontsize=9,color=MUTED)
    out=ROOT/folder/'规划书'/name
    doc.set_metadata({'title':name[:-4],'author':'留白项目设计'})
    doc.subset_fonts();doc.save(out,garbage=4,deflate=True)
    for page in doc:
        assert '\ufffd' not in page.get_text()
    doc.close();print(out)

write_pdf('第一部分_任务基础','第一部分_实施规划与运行说明_v1.0.pdf',[
 ('第一部分：任务基础与独立原版',[
 ('范围与成果','第一部分负责账号注册、登录、退出、任务新建与编辑、清单筛选、状态切换和状态历史。支持待选择、进行中、暂停、完成、放弃五种状态；每周投入可以留空，留空不等于零。'),
 ('前后端组织','前端使用原生 HTML / CSS / JavaScript。后端为 Django 5.2.18，SQLite 保存本机数据；tasks 包包含任务与账号接口。按当前登录用户查询，拒绝跨账号访问；写入配合 CSRF、版本校验和创建请求去重。'),
 ('独立保存位置','第一部分_任务基础 / 代码：第一版完整代码与独立运行环境。\n第一部分_任务基础 / 规划书：原架构 PDF、原 SPEC / EVIDENCE，以及本实施说明。\n第一部分_任务基础 / 打开留白.command：双击启动原版。'),
 ('运行与数据','地址：http://127.0.0.1:8000/\n数据库：代码/.local/tasks.sqlite3。虚拟环境：代码/.venv。原有账号和任务保留，目录迁移前 24 项测试通过。业务源码逐文件哈希与迁移前一致。'),
 ('与第二部分的关系','第二部分以本版为基础建立独立完整应用，新增分析与执行模块。迁移时复制了一份用户与任务快照到第二部分；后续修改不同步，不共用数据库或会话。第一部分保留原有能力，第二部分功能在第二部分入口使用。'),
 ('规划文档的阅读顺序','先看本说明了解已经落地的版本，再查原《第一部分_前后端架构与交互逻辑_v0.1.pdf》；原图中的“暂定”属于历史设计描述，以实际代码与验收报告为准。'),
 ])])

second=ROOT/'第二部分_分析与执行/代码'
evidence=second/'evidence'
coverage=json.loads((evidence/'coverage.json').read_text()) if (evidence/'coverage.json').exists() else None
cov='详见规划书 EVIDENCE.md 和代码/evidence。'
if coverage:
    s=coverage['totals'];cov=f"后端语句执行：{s['covered_lines']}/{s['num_statements']}；分支执行：{s['covered_branches']}/{s['num_branches']}。覆盖范围为 tasks 与 execution，不含模板、浏览器 JavaScript、框架与迁移。"
write_pdf('第二部分_分析与执行','第二部分_实施说明与验收_v1.0.pdf',[
 ('第二部分：从计划走到执行',[
 ('本期完整流程','保存目标与完成标准 → 手工拆分或 DeepSeek 生成 → 编辑保存草稿 → 明确采纳 → 步骤执行 → 逐次记时 → 用户确认完成 → 保留执行历史。第一部分账号与任务入口继续保留在本版中。'),
 ('实际耗时与完成登记','一个 TimeEntry 对应一次实际投入，归属父任务本身或一个子步骤。父任务合计所有有效记录；子步骤时间不会额外再登记成父任务时间。无记录显示“未记录”，完整性需用户核对。\n已记 90 分钟，完成时漏记 30 分钟：只补 30，合计 120。撤销完成保留 120 分钟；修改或删除时间会使完整性待重新确认。'),
 ('任务拆分与规则分析','一份草稿 1–12 步，仅一层；校验完成标准、估时范围、前置依赖和循环。采纳只追加待选择步骤。整体任务不随子步骤自动完成；前置未完成不能开始后续步骤。\n规则分析比较剩余预计区间与用户确认的可用总分钟，不把每周投入当作总预算，也不猜测成功概率。'),
 ('前端入口','任务详情内点击“分析与执行 ↗”，进入“分析与拆分 / 步骤与完成 / 耗时账本 / 执行历史”四个页签。手机端改为单列。网络失败保留表单并用原请求键重试；账号切换清理前一个账号的页面内容。'),
 ('本期边界','已完成手工与规则流程，以及 DeepSeek 配置、调用适配、持久化队列、取消与中断恢复。整体负载、自动排期、实时计时器和历史校准仍属于后续部分。'),
 ]),
 ('独立运行与 DeepSeek 配置',[
 ('目录与默认入口','第二部分_分析与执行 / 代码：第二版完整应用，新功能集中在 execution，前端为 execution.html / execution.js / execution.css。\n第二部分_分析与执行 / 规划书：两份原方案 PDF、本期 SPEC / EVIDENCE 和本说明。\n工作区根目录“打开留白.command”默认打开第二部分，地址 http://127.0.0.1:8001/ 。'),
 ('密钥在本机填写','双击第二部分文件夹里的“配置 DeepSeek.command”，输入密钥，默认模型 deepseek-flash。配置保存于代码/.local/deepseek.json，权限 0600，不出现在页面或日志中；也支持环境变量。配置后在页面载入最新数据即可。'),
 ('每次调用的控制','页面可查看将发送的当前任务内容。勾选同意后才排队，已有步骤只作参考；不会发送其他任务、账号和实际耗时账本。模型输出严格校验后成为草稿，不能直接写入步骤、状态或时间。\n每用户一个活动分析，单次最多一个外部调用；输出上限 4096 token、响应 256 KiB、连接读取超时 60 秒。取消阻止晚到结果进入草稿；已发生的服务商计费未必能取消。'),
 ('断线与重启','Web 和 worker 随启动入口运行。分析队列保存在数据库中；重启时原运行中任务标为中断，需用户明确重新生成，避免自动重复计费。耗时和完成写入同一事务，失败回滚；重复请求返回同一回执。'),
 ('实现细化与架构对应','拟定资源接口统一收敛为 GET/POST /api/tasks/:id/workspace，action 区分操作；既有任务接口保留。CompletionEvent 与 ExecutionEvent 合并为 Event 表不同 kind；WriteReceipt 对应 Receipt。功能职责和隔离原则与 v0.2 保持一致。'),
 ]),
 ('验证证据与已知边界',[
 ('可复现验证','在“代码”目录运行 bash tools/verify.sh。包含原功能回归、新增行为测试、属性与并发测试、静态类型、格式、覆盖率、手动变异、真实浏览器、迁移演练、依赖审计和目录隔离检查。所有测试使用隔离数据库。'),
 ('后端覆盖记录',cov),
 ('实际浏览器验证','已验证：手工草稿采纳、步骤执行、90 + 30 = 120、撤销保留时间、修改账本与完整性核对、网络重试、刷新与服务重启持久性、390px 手机布局、同账号草稿恢复和不同账号内容隔离。'),
 ('DeepSeek 的验证范围','接口与 worker 使用外部边界模拟响应验证，不把模拟结果当作真实模型输出。浏览器验证了同意发送、入队和取消；真实付费调用仍需用户配置本机密钥后完成。未做真实模型语义质量评测，AI 建议始终需要人工审核。'),
 ('已知运行边界','本机 Django 开发服务器、SQLite 和单 worker；未部署为公网服务。HTTP 连接读取超时不等于端到端绝对截止时间。账本和幂等回执尚未做归档清理，个人长期大量记录时数据库会持续增长。'),
 ('人工审核与文档版本','用户已确认 v0.2 架构并授权实施；细化测试规范由执行者自主整理，未进行独立人工逐条审核。准确的测试数量、变异结果、源码哈希与失败修复过程，以同目录 EVIDENCE.md 和代码/evidence 原始日志为准。'),
 ])])
