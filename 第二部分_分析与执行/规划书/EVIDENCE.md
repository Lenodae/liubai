# 第二部分验收证据 · 2026-10-14

Tier 3：账号归属、并发、幂等、防止数据丢失与外部模型调用。
Spec approval: not obtained (autonomous run)。用户确认了 v0.2 架构并授权实施；细化 SPEC 未经过独立人工逐条审核。所有实现、规范和测试由同一执行者完成，不能替代独立审查，也不能证明没有遗漏需求。

源码 SHA-256：`b838b6f97ca235d912149b688206a4494a2ebbd2a1a017778b33fb61da011655`。由 `代码/tools/source_state.py` 计算；不包括运行数据、虚拟环境、缓存、证据输出和 EVIDENCE.md。第一部分原业务源码逐文件哈希保持一致，见项目总览/目录迁移记录.json。

## 复现入口

在第二部分的代码目录运行 `bash tools/verify.sh`。依赖版本固定在 requirements-dev.txt；本次未增加依赖，两版各自复制并修复了虚拟环境入口路径。未创建 Git 仓库或提交，以树哈希、迁移清单和变异字节恢复验证来源。

## 最终完整运行

| 层 | 最终结果 / 原始证据 |
| --- | --- |
| 全测试 | 51/51 通过，随机顺序 20261014；evidence/tests.log |
| 恢复后随机回归 | 51/51 通过，随机顺序 73；evidence/restored-tests.log |
| 类型 | mypy 检查 19 个后端源文件，0 错误；tests 与 tools 不纳入此类型检查 |
| 代码规范 | Ruff check / format 通过；43 个 Python 文件；两份 JS 通过 node --check |
| 后端覆盖 | 823/823 语句，229/230 分支；evidence/coverage.json |
| 新模块覆盖 | execution 557/557 语句执行，所有新增后端语句被测试执行；既有任务服务改动语句也执行 |
| 手动变异 | 7/7 被完整新增测试集杀死，每个变异独立运行并逐字节还原；evidence/execution-mutations.json |
| 属性层单独变异 | 4/7 杀死：版本、重复写、作废统计、区间上界；归属、零分钟和取消由场景测试覆盖，属性层独立仍有盲区 |
| 属性测试 | 时间区间属性 100 个示例；账本合计及幂等属性 15 个示例；保留原账号隔离属性 20 个示例 |
| 并发 | 同版本两次独立写入恰一成功；同键并发写只生成一条记录；原任务并发版本测试继续通过 |
| 真浏览器 | Chrome + Playwright，桌面和 390px；12 类流程，0 页面异常；服务重启后合计 135 分钟和 2 个步骤保留 |
| 迁移演练 | 隔离数据库 forward → rollback tasks（含依赖 execution）→ forward → check 通过 |
| 供应链 | 46 个包清单和许可证；pip-audit 无已知漏洞；无新增依赖 |
| 密钥模式扫描 | 源码 0 命中；运行时 .local 按设计不扫描、不输出密钥 |
| 目录隔离 | 第一部分源码未变；独立环境、SQLite、密钥和规划目录；第一部分没有 execution 数据表 |

完整输出：代码/evidence/final-run.log；启动入口额外冷启动与登录数据库访问检查：项目总览/启动验收.json。8000/8001 均正常运行，分别使用 csrftoken 与 taskflow2_csrf。第二部分会话名 taskflow2_session，第一部分保持 sessionid。

## SPEC 到验证映射

| 行为 | 证据 |
| --- | --- |
| 步骤采纳、依赖、追加不改父状态/周投入 | test_steps、test_dependency_schema_and_selection、test_draft_revision_and_stale_apply |
| 预计区间与可用总量、未知语义 | test_rules、test_interval_boundaries、test_step_limit_and_time_unknown |
| 逐次账本、父子汇总、迁移归属、修改作废 | test_ledger、test_sum_and_idempotency、test_entry_conflicts_and_cross_resource |
| 完成补记、撤销、用户核对、提前结束 | test_completion、test_completed_without_time_and_legacy_patch、test_reestimate_restore_and_verify |
| 账号隔离、跨任务、伪造字段 | test_isolation、test_hostile、test_entry_conflicts_and_cross_resource、浏览器切换账号后 DOM 无残留 |
| 幂等、旧版本、事务回滚 | test_idempotency、test_conflict_and_rollback、test_concurrent_duplicate、test_concurrent_versions |
| 父暂停继承、前置未完成不开始 | test_lifecycle、test_reestimate_restore_and_verify |
| 分析队列、取消、中断、单 worker | test_jobs、test_worker_results_and_restart、test_worker_cancel_and_fail、两个 worker command 测试 |
| 模型边界、结构与异常、密钥不泄露 | test_provider、test_configuration_and_bad_responses；模拟的仅是外部网络边界 |
| UI 草稿、网络重试、刷新重启、手机布局 | tools/browser_phase2.py，截图在 evidence/phase2-*.png |
| 不自动完成父任务、不自动采纳 AI | test_completion、test_completed_without_time_and_legacy_patch、worker 与浏览器队列测试 |
| 原第一部分能力保留 | 原 24 个测试在第二部分回归；CSRF / session 固定名称适配独立 Cookie，断言未放宽；第一部分迁移前原样 24/24 |

## 发现与修复

- 初始 10 个核心新增测试针对 501 占位端点均失败；完成实现后通过。边界、属性、provider 和 worker 测试是在实现后扩展，不能声称全部经历了先红后绿；变异验证用于补强关键断言。
- Cookie 改名后旧测试的 csrftoken / sessionid 固定常量失败；仅更新第二部分测试的名称，保留 CSRF 与 HttpOnly 断言。
- 后端类型与 Ruff 初轮发现格式、导入和测试路径范围问题，修正后完整检查通过。
- 浏览器初步检查通过后，额外加入“换账号后 HTML 内不残留旧步骤名称”断言，观察失败。根因是关闭面板没有清空 select 选项；清理后同一断言通过，记录见 browser-security-red.log 与 browser-security-green.log。
- 后台启动最初只使用 nohup，工具终端结束后第二部分服务未持续保留；入口改为独立进程会话，再分别冷启动成功。原第一部分进程在目录移动后仍存活，已核实其归属后停止并从新目录启动，避免旧路径设置继续使用。
- 两版初始化数据通过 SQLite backup 复制，第二部分删除快照内旧登录会话并生成独立密钥；原版账号与任务未删除。测试没有写入正式账号任务。

## 已知边界 / 未验证项

- **真实 DeepSeek 付费调用未验证**：未配置用户密钥；本次外部模型调用为 0。已验证请求协议、解析、失败、取消和后台持久流程。真实模型语义质量、供应商可用性和账户配额仍需配置后验证；不把模拟结果当真实输出。
- 覆盖率不包括前端 JS、Django 框架、模板、迁移与配置；前端采用真实浏览器验收与语法检查，没有 TS 类型检查。后端未执行分支为 services.change_status 对父任务同状态操作的无变更分支；当前完成/撤销入口只调用不同状态。
- HTTP 连接读取超时 60 秒并非整个响应绝对截止时间；本机单 worker，未验证多机/分布式行为。服务停止后的原 running 分析需明确重新生成，不自动重复计费。
- 模型输出可通过 JSON 校验仍存在内容错误，需要用户复核。没有做真实模型学习/工作/生活三类语义样本评测。
- 本机开发服务器，未做公网部署、分布式登录限流、压力吞吐或多平台验证；本期未声明性能预算。
- 耗时条目、历史和幂等响应尚未归档，长期大量记录会增长数据库；全局负载、自动排期、计时器和历史估时校准仍属后续。
- 草稿编辑只有初始内容与当前修订号，未提供每一版差异浏览界面；完成事件和操作事件合并在 Event 表，接口收敛到 workspace action，见 SPEC 实施细化 1。


## 2026-10-14 DeepSeek TLS 修复验收

spec approval: not obtained (autonomous run)。Tier 2；对应规划书 SPEC 的 TLS 补充项。本机默认 CA 文件缺失且默认 TLS 校验失败；使用 certifi 的只读模型列表请求成功。仅改变第二部分 HTTPS 信任来源和错误分类，不关闭证书/主机名验证，不更改任务数据或自动重试失败生成。

复现入口：`bash tools/verify_tls.sh --live`；不带 `--live` 可跳过需要本机密钥的只读网络检查。最终源码哈希（tools/source_state.py）：`13cd4c33f7386cf950ad2c4b4aab8d859f9afae9f9d832f6f35e974bf177ac05`。当前为本机未提交修复，尚未同步 GitHub。

- RED：三个新增测试均失败（含子场景共 8 个失败）；既有两个 provider 测试通过。日志 evidence/tls-red.log。
- GREEN：完整 54 项测试通过，随机顺序 seed 20261014，包含原有属性测试。定向 5 项恢复测试 seed 73 通过。
- 证书与主机名验证、缺失系统 CA：test_tls_without_system_ca；安全错误分类、单次请求与密钥脱敏：test_distinct_safe_connection_errors；格式错误不混称超时：test_response_format_error_is_distinct。
- Ruff 检查通过，46 个 Python 文件格式通过，mypy 19 个源文件通过。provider 64/64 语句执行，16 个分支中 1 个部分分支未覆盖（既有配置文件读取异常路径 23→30）；新增修复行已执行。日志 evidence/tls-coverage.txt。
- 三个定向变异全部由断言杀死：移除显式 CA、取消 TLS 校验、隐藏证书错误；每次恢复字节一致。可重跑 tools/tls_mutations.py，未在运行中的 worker 内加载变异代码。
- 46 个已安装包依赖审计无已知漏洞；许可证清单已生成；代码密钥模式扫描 0 命中。certifi==2026.7.22 原开发环境已有，本次加入运行依赖以使新安装也有可信根证书。迁移往返验证通过。无新增网络目的地，不记录密钥或服务原始错误。
- 实际 GET https://api.deepseek.com/models 返回 HTTP 200，已配置模型存在；没有调用付费生成接口，不能据此宣称真实生成质量或输出格式已验证。tools/check_deepseek_connection.py 可复跑，只输出状态和模型是否存在。
- 第二部分服务在确认没有 queued/running 分析后重启，页面 HTTP 200；原两条失败历史保留。第一部分源码未变、两部分虚拟环境/数据库/密钥隔离检查通过。
- 本次未重跑浏览器交互、并发压测及旧七项业务变异：无前端、事务或业务计算改动；完整后端回归保留。无新解析或算术规则，未增属性测试；已有属性测试随全套运行。独立错误分支未引入重试或额外生成请求。


## 2026-10-14 网页 DeepSeek 设置验收

spec approval: not obtained (autonomous run)。Tier 3，需求与失败模型见规划书 SPEC 的网页设置补充。本次在第二部分增加首页醒目入口、拆分窗口入口，以及会话保护的 GET/POST /api/settings/deepseek；沿用本机共享配置，仅初始账号可管理。已有本机密钥未改写；网页验证成功后才保存替换，失败和并发冲突有明确提示。

最终复跑入口：`bash tools/verify_settings.sh`。最后一次完整运行全部通过；源码树哈希 `f7d4998fd48aac4d59880b5bdd2ef8b354d92b406db58f7649543c979cda974f`。当前本机工作区包含上次 TLS 修复和本次设置功能，尚未提交/推送 GitHub。

验收映射：
- 身份、账号一致性、CSRF、只读账号与不回显密钥：test_auth_owner_csrf_and_no_key_disclosure。
- 官方 GET /models、单次请求、证书与主机名校验、0600 文件、验证时间和空输入验证旧密钥：test_validate_save_and_verify_existing。
- 网络/证书/超时/401/429/服务故障不覆盖原文件、不登出应用、不暴露原错误：test_failed_validation_preserves_previous_config。
- 输入边界、未知字段、模型缺失与畸形/过大响应：test_invalid_input_and_missing_key、test_bad_models_and_response。
- 文件锁、旧版本与验证期间外部修改拒绝：test_stale_and_concurrent_requests。
- 写入替换故障保留原文件并清理临时文件：test_storage_failure_is_atomic；读取权限错误：test_unreadable_configuration_has_safe_message。
- 环境变量不被网页覆盖：test_environment_override_is_readonly。
- 深层 JSON 敌意响应安全失败：test_hostile_deep_json_preserves_configuration。
- 模型列表顺序、重复和无关模型不改变可用性：SettingsProperties，30 个生成样例，每例正序/逆序校验。
- 实际浏览器完整验证保存/刷新、错误密钥、空输入再验证、桌面/390px、关闭/退出后清理输入、迟到响应不重绘、其他账号只读、保持任务未保存表单：tools/browser_settings.py。运行网页、后端与临时配置文件，只有外部 DeepSeek 边界模拟。

最终证据：65/65 后端测试通过，seed 20261014；11/11 定向测试另以 seed 73 通过。Ruff 检查及 51 个 Python 文件格式通过，mypy 20 个源文件通过，三个前端 JS 语法检查通过，无模型迁移。settings_service.py + views.py 共 123/123 语句、24/24 分支覆盖。六个定向变异全部被测试杀死并逐次按字节恢复；模型可用性变异另由属性测试单独杀死，不宣称属性测试覆盖了全部六类故障。日志 evidence/settings-*.log。

设置浏览器与原第二部分浏览器回归均通过，无页面 JS 错误；原任务 90+30=120、账本修改 135、撤销保留时间、账号草稿隔离、重启持久化继续通过。迁移往返成功、密钥模式扫描 0 命中、46 个包许可证清单生成。本次未改变依赖，未重复依赖漏洞审计（上次 TLS 修复已审计）；第一部分源码和两部分虚拟环境/数据库/密钥隔离检查通过。

真实运行：第二部分服务已重启，首页包含设置按钮与弹窗，匿名设置 API 返回 401；没有排队/运行中的分析被打断或重试。`tools/check_deepseek_connection.py` 对现有配置只读检查 HTTP 200，模型存在；未生成任务、未改写现有密钥，不据此宣称付费生成质量已验证。

过程与限制：初次八项接口测试在接口不存在时失败（404 及随后的非 JSON 响应错误），实现后通过。补充的读取故障/深层 JSON 防御及属性行为已有，随后以独立变异验证断言有效。浏览器检查第一次因导航中断待验证响应而超时，第二次等待未消费响应的 finished() 挂起；修正测试为关闭/退出后等待响应头、断言状态与隐藏结果，关闭测试服务自动重载，再完整重跑通过。未删减产品行为断言。

余额、服务商生成行为不属于模型列表验证承诺；20 秒为网络操作超时，不是绝对整次操作截止。文件锁保护网页并发写入，无法禁止用户直接改文件，外部修改在验证结束时再核对版本；未模拟断电与任意时刻的外部文件强制改写。关闭窗口不撤销已经提交的后端验证，重新打开可查看保存状态。未重跑旧七项业务变异/并发压测（本次无账本事务逻辑变化），已有并发与属性测试随完整后端套件保留。


## 2026-10-14 步骤搜索与完成置底

仅修改第二部分步骤列表的前端呈现：按名称/完成标准搜索、清空、无匹配提示、匹配数量；非完成步骤在前，完成步骤在后，组内保持原顺序。原始步骤数组、编号、依赖、下拉选项和后端记录未重排。完成/撤销即时更新，搜索不会标记业务表单为未保存，任务重新打开清空搜索，账号退出清理输入。

验证：`node --check static/execution.js`、`manage.py check`、浏览器脚本 Ruff 检查和格式检查均通过；`.venv/bin/python tools/browser_phase2.py` 实际运行通过。浏览器覆盖名称/完成标准搜索、无匹配/清空、搜索中完成后保留筛选、完成置底与稳定编号、撤销恢复原位置、390px 搜索布局；既有完成/耗时/重启持久化/账号隔离流程继续通过，页面 JS 错误 0，外部生成请求 0。详情在 evidence/step-search-browser.log，截图 evidence/phase2-steps.png 和 phase2-mobile.png。为适应排序，原浏览器流程改用步骤 UUID 定位同一对象，保留原状态/耗时断言。

本次为局部展示改动，未新增测试框架，未重跑未改动的后端完整套件/变异/依赖审计；不将前一轮 65 项结果当成本轮重新运行。第二部分已在确认无运行中的分析后重启，实际首页 HTML 包含搜索框；第一部分未改动。本机修改尚未提交/推送 GitHub。


## 2026-10-14 已完成记录直接编辑验收

spec approval: not obtained (autonomous run)。沿用 old-coder 数据变更验收流程；需求与失败模型见规划书 SPEC 的对应补充。新增 completion_edit，只修改已完成任务/步骤的说明和成果链接；追加审计事件，原完成事件保持，完成状态/时间、耗时、核对状态保持。响应提供当前完成记录，旧任务缺少完成事件时可以补记说明但不伪造完成时间。第一部分保持独立。

复跑入口：`bash tools/verify_completion_edit.sh`。最终完整运行通过，源码树哈希 `465cf33b875feee0d0ddf1ef1716591057ea715938b15084973327da1557ef19`。本机变更尚未提交/推送 GitHub。

- RED：5 项新后端测试全部失败（新操作尚不存在，日志 completion-edit-red.log），实现后通过。后续只调整测试的 helper 导入结构以避免 Django 把导入的原测试类重复收集，断言保持。
- 映射：test_edit_parent_keeps_state_time_and_original_event 校验父任务状态/原事件/时间/账本/版本/有效记录；test_edit_step_even_when_parent_completed_and_preserve_undo 校验父已完成时编辑子步骤、撤销与再次完成轮次；test_only_current_completed_target_and_valid_content 校验未完成拒绝、无效链接/文字/未知字段/错误编号及清空内容；test_idempotency_stale_version_isolation_and_rollback 校验重复提交、旧版本、越权与回执故障的原子回滚；test_legacy_completed_task_can_add_note_without_inventing_time 校验旧完成记录兼容。
- 最终 70/70 后端测试通过，随机 seed 20261014，包含原并发、属性、账户隔离测试。另以 seed 73 运行 5/5 定向测试通过。Ruff 与 53 个 Python 文件格式通过，mypy 20 个源文件通过，JS 语法通过，Django check/无迁移通过。
- 总后端 970/970 语句执行，268 个分支有 1 个既有部分分支未覆盖（services.py:37 同状态父任务分支）；本次新增完成编辑/序列化代码行均执行。详见 completion-edit-coverage.txt。
- 3/3 定向变异被断言杀死：去掉已完成状态检查、去掉当前完成事件检查、旧记录覆盖最新记录；每次按字节恢复。脚本 tools/completion_edit_mutations.py。未把这些杀死归因于属性测试。
- 真实浏览器通过：原完成说明自动预填、已完成项进入编辑模式、首次完成的补记字段隐藏、说明/链接修改后仍完成置底、原完成时间和 120 分钟保持、原说明→新说明的审计、刷新后当前内容保留、网络中断输入保留并按原回执重试。原搜索/完成撤销/账本修改 135/重启持久化/390px/账户草稿隔离流程继续通过，页面 JS 错误 0，外部生成请求 0。截图 completion-edit-desktop.png；结果 completion-edit-browser.log。
- 迁移往返成功、源代码密钥模式扫描 0 命中、46 个包许可证清单生成、两部分隔离检查通过。本次无新依赖，无新增网络/进程/文件访问能力，未重复漏洞审计。没有新的解析/算术算法，沿用原字段校验与已有属性测试；未新增属性测试。未重复原七项业务变异，新的三个变异针对本次保护条件。
- 第二部分已确认无活动分析后重启，HTTP 页面包含编辑模式表单；本机已有任务数据和密钥未被验收脚本改写。另有只读复核未发现具体问题。

边界：编辑范围为完成说明/成果链接，时间修改仍走耗时账本，步骤名称/完成标准不在本次范围；新事件表示更正，旧完成事件作为历史保留。关闭窗口不撤销已提交请求，遇到版本冲突需重新核对当前记录。本轮首次功能实现与最终验收均通过，没有放宽或删除行为断言。
