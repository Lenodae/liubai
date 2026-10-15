# 留白 · 第二部分：分析与执行

双击上一级「打开留白.command」，访问 http://127.0.0.1:8001/ 。从任务详情点击「分析与执行 ↗」。

本目录是第二部分的独立完整应用：tasks 保留基础账号/任务，execution 专门实现任务拆分与实际执行。第一部分原版位于 ../../第一部分_任务基础/代码，使用 8000 端口。两个目录拥有各自的 .venv、.local/tasks.sqlite3、会话和密钥；本次初始化复制了第一部分已有账号与任务的数据库快照，之后不自动同步。第一部分仍可独立使用。

## 使用顺序

1. 保存任务目标、完成标准、前提、约束和可用总时间。
2. 手工编辑步骤草稿；或者配置 DeepSeek 后查看发送内容，勾选同意生成。
3. 编辑草稿后保存，勾选需要的步骤，再点击采纳。前置步骤也需勾选。
4. 开始父任务和步骤，逐次记录投入。投入按整数分钟计，留空不是零。
5. 完成时核对标准，选填说明、成果链接及漏记分钟。不要再次填写已累计的总时间。
6. 已花时间汇总到父任务；任务本身只登记不属于子步骤的额外投入。修改/删除留历史，撤销完成保留耗时。

每周计划投入、预计总耗时、实际投入分别保存。所有步骤完成仅提示，不自动结束父任务；提前结束需明确确认。未记录时间显示「未记录」，有记录但未核对显示「待确认」。

「步骤与完成」支持搜索步骤名称或完成标准，并显示匹配数量；点击「清空」恢复完整列表。已完成步骤自动排到末尾，撤销完成后恢复原组内顺序。显示编号与依赖保持原样，搜索不会改变任务和耗时记录。

已完成项可直接点击「编辑完成记录」，或在右侧选择已完成任务/步骤；表单自动载入原有说明和成果链接，点击「保存修改」即可。原完成时间、完成状态和已记耗时保留，执行历史记录修改前后内容。耗时修改通过账本完成。旧完成任务没有登记时间时允许补充说明，不补造原完成时间。

## 配置 DeepSeek

登录后，点击首页顶部「DeepSeek 设置 ↗」，填写 API Key 与模型，点击「验证并保存」。分析与拆分窗口也有「设置 / 验证 API Key」入口。后台仅访问官方 GET /models；通过后保存于 .local/deepseek.json，权限 0600，并显示验证时间，输入框清空。留空密钥可验证已保存配置。密钥不会回显或保存进浏览器存储；关闭窗口、退出或账号切换会清空输入。

此配置沿用本机共享方式，仅最早创建的账号可修改/验证；其他账号只能查看状态。错误密钥不会覆盖旧配置；旧页面或并发验证会提示重新打开。验证证明当时认证及模型可访问，不代表余额足够或之后生成必定成功。验证不生成任务，也不自动重试。

原「配置 DeepSeek.command」入口仍可使用。已有服务每次读取配置，无需重启。DEEPSEEK_API_KEY / DEEPSEEK_MODEL 环境变量优先；存在环境变量时网页只验证现有配置且不写入文件，验证结果仅保留当前页面。不要把密钥发到聊天或提交进代码。

默认模型 deepseek-flash，可自行调整。固定官方 HTTPS 地址 https://api.deepseek.com/chat/completions，标准库调用，无新增 SDK 依赖。参考 [官方首次调用文档](https://api-docs.deepseek.com/zh-cn/) 与 [Chat Completions 文档](https://api-docs.deepseek.com/api/create-chat-completion/)，核对日期 2026-10-14。

只发送界面展示的当前任务快照，不发送其他任务、账号、密钥或实际耗时记录。每用户最多一个排队/运行任务，模型响应最大 256 KiB、输出上限 4096 token、连接读取超时 60 秒。模型输出需通过结构、范围和无环依赖验证。每次生成最多一个外部请求，失败没有隐式重试；取消可能无法取消服务商已经发生的计费，但晚到结果不会采纳。后台中断的任务标为 interrupted，需用户明确重新生成。

## 代码结构

- config / tasks：基础设置、账号和任务；旧状态修改中的完成操作也进入统一完成逻辑。
- execution/models.py：步骤、耗时、事件、回执、分析任务、草稿。
- execution/services.py：事务、归属、版本、幂等与业务规则。
- execution/validation.py / rules.py：数据校验和可解释时间分析。
- execution/provider.py / jobs.py：DeepSeek 边界、持久化队列、结果校验。
- execution/settings_service.py：连接验证、配置权限、文件锁和原子保存。
- templates/deepseek_settings.html / static/deepseek_settings.*：网页密钥设置入口。
- execution/management/commands/analysis_worker.py：本机单实例后台任务。
- templates/execution.html / static/execution.*：前端四个功能页签。
- tools / evidence：可复现验证命令与结果。

新增接口：GET /api/tasks/:id/workspace 返回该用户的任务执行空间；POST 同路径带 action、version、Idempotency-Key。action 包含 profile、draft、apply、time_add、time_edit、time_delete、complete、undo、step_status、verify_time、analyze、cancel_analysis。步骤/分析/草稿/账本均通过父任务归属验证；不存在独立可绕过归属的资源入口。

另支持 `action=completion_edit`，带 step_id（整个任务为 null）、event_id（当前完成记录 id，历史任务未记录为 null）、note、link。沿用归属、版本、幂等与事务保护。响应顶层 completion 与各步骤 completion 返回当前说明/链接、原完成事件 id、原完成时间和最后更新时间；完整历史采用追加事件保留。

GET /api/settings/deepseek 返回配置状态、模型、验证时间、管理权限、环境变量来源和版本，不返回密钥。POST 同路径带 api_key、model、revision；要求初始账号会话、CSRF 和有效版本。验证等待期间关闭窗口不撤销已经提交的请求，重新打开可查看保存状态。

CompletionEvent 与 ExecutionEvent 合并为 Event 表的不同 kind；WriteReceipt 对应 Receipt 表。完成与补记写入同一事务，重试返回原回执；TimeEntry 作废后不参与求和。所有业务写入推进父版本，账本变化另推进 ledger_revision，使之前的完整性确认失效。

## 验证与边界

运行 `.venv/bin/python -m pip install -r requirements-dev.txt` 安装固定版本工具，然后 `bash tools/verify.sh`。规范与证据在 ../规划书/。所有浏览器与迁移测试使用临时数据库，不写真实账号。

网页设置验收使用 `bash tools/verify_settings.sh`，包括完整后端回归、定向变异、桌面/手机设置流程以及原任务执行浏览器回归。浏览器设置验收只模拟外部 DeepSeek 响应，实际网页、后端和临时文件保存均真实运行。

完成记录编辑验收：`bash tools/verify_completion_edit.sh`，包含完整后端回归、版本与历史保护的定向变异、真实浏览器编辑/失败重试/原任务流程以及隔离检查。

本机运行版本，尚未部署到公网；SQLite 单进程后台 worker，不是分布式队列。全局负载、自动排期、实时计时器和相似任务历史校准留待后续。实际 DeepSeek 付费调用需本机密钥，测试不会把模拟结果冒充真实服务。
