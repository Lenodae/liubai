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
