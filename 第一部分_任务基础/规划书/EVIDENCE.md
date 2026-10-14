# 第一部分验收记录 · 留白

日期：2026-10-13。范围：本机账号、任务清单、任务隔离、编辑与状态历史。Tier 3。

- 用户已批准 PDF 方案并要求运行；细化的测试规格未取得逐条人工复核：**spec approval: not obtained (autonomous run)**。测试与实现均由同一代理编写，结果只说明已列场景满足约束，不构成独立安全审计。
- 源码标识（无 Git，排除运行数据、生成证据及本报告）：`67167cfcc4b0c598c3514ac060502ce9a8f7ad5fe1653d79edc391a341a10da4`。
- 复算源码：`.venv/bin/python tools/source_state.py`。
- 完整复验入口：`./tools/verify.sh`；工具版本：`requirements-dev.txt`，运行依赖：`requirements.txt`。
- 当前运行环境：macOS、Python 3.14.4、Node.js 24.18.0、Django 5.2.18、Google Chrome + Playwright。服务仅监听 127.0.0.1。

## 最终同一轮检查

| 检查 | 结果与证据 |
|---|---|
| 数据库模型与系统检查 | `manage.py check` 无问题；`makemigrations --check --dry-run` 无漂移 |
| Python 静态检查与格式 | Ruff 全部通过；20 个 Python 文件格式通过 |
| Python 类型 | mypy：7 个源码文件，无错误 |
| JavaScript / Shell | `node --check static/app.js`、`bash -n start.sh tools/verify.sh` 通过 |
| 首轮完整测试 | 24 个测试通过，48.944 秒，随机顺序种子 20261013；见 `evidence/tests.log` |
| 变异还原后的完整测试 | 24 个测试通过，49.579 秒，另一随机顺序种子 73；见 `evidence/restored-tests.log` |
| 后端业务覆盖率 | 255/255 行，64/64 分支，100%；仅 `tasks/models.py`、`services.py`、`views.py` 及包入口，不包含框架、配置、迁移、浏览器代码 |
| 手工变异 | 7/7 被针对性的验收测试拦截；每次按原始字节恢复；见 `tools/mutations.py` 和 `evidence/mutations.json` |
| 性质测试 | 一组跨账号隔离与 Unicode/时间往返性质，每次最多 20 个生成样例；通过 |
| 性质测试独立拦截范围 | 单独运行性质测试只拦截 2/7 个变异（归属条件、未知时间变为 0）；版本冲突、去重、历史、空更新、密码长度由各自的场景测试验证，不能声称性质测试覆盖这些规则 |
| 并发与回滚 | 两个真实线程同版本更新只允许一次成功，另一次 409；历史写入异常时状态与版本一起回滚 |
| 浏览器与实际运行 | 注册、登录、退出、空清单、创建/编辑/取消、状态/历史、搜索、重新登录、跨账号读取/修改、网络失败草稿、过期重登草稿、账号切换隔离、XSS 文字、0 与未知均通过；JS 页面异常为 0 |
| 手机布局 | Chrome 390px 宽度，清单和任务面板无横向溢出；见 `evidence/mobile.png` |
| 服务器重启 | 独立 QA 服务重启，原账号可登录且 3 条当前任务仍存在 |
| 迁移演练 | 临时数据库完成初始化 → 回退 tasks 迁移 → 重新迁入，无错误；不触碰用户数据库 |
| 供应链 | pip-audit 审计 46 个包，无已知漏洞记录；许可证清单 `evidence/licenses.json` 共 46 个包；运行依赖使用 BSD 系许可证 |
| 凭据与权限 | 私钥/API 密钥模式扫描无命中；`.local` 0700、随机密钥文件 0600；无预置用户密码或外部业务凭据。测试密码是公开测试夹具 |

上述命令全部保存在 `tools/verify.sh` 及其调用脚本中，完整输出在 `evidence/verification.log`。

## 规格对应测试

| SPEC 场景 | 实际测试 / 检查 | 状态 |
|---|---|---|
| 注册、登录、退出与弱密码 | `ApiCase.test_register_login_logout`、`test_registration_validation` | pass |
| 匿名访问拒绝 | `ApiCase.test_anonymous_denied` | pass |
| 两个账号读写与历史隔离 | `ApiCase.test_isolation`、浏览器独立上下文 | pass |
| 伪造归属字段与查询参数 | `ApiCase.test_forged_owner` | pass |
| 保存、重登、未知和 0 | `ApiCase.test_create_persist_and_zero`、`PersistenceCase.test_connection_reopen`、服务重启 | pass |
| 输入验证 | `ApiCase.test_validation`、`AdversarialCase.test_hostile_unicode_and_shapes`、`test_body_limit_and_empty_patch`、`test_deep_json_rejected_without_server_error` | pass |
| 状态与历史保留 | `ApiCase.test_status_history`、浏览器暂停/恢复/完成 | pass |
| 旧版本与并发修改 | `ApiCase.test_optimistic_conflict`、`ConcurrencyCase.test_concurrent_version_updates` | pass |
| 创建去重与账号内键范围 | `ApiCase.test_idempotency`、`test_idempotency_key_required` | pass |
| 原子回滚 | `ApiCase.test_atomic_rollback` | pass |
| CSRF 与会话 Cookie | `ApiCase.test_csrf` | pass |
| 登录限流与缓存失效 | `ApiCase.test_brute_force`、`AdversarialCase.test_login_cache_eviction_and_reset` | pass |
| 生成式隔离与数据往返 | `PropertyCase.test_property_isolation` | pass |
| UI 操作、手机布局 | `tools/browser_check.py` | pass |
| 网络失败输入保留 / XSS | `tools/browser_check.py` 的真实浏览器请求中断与恶意标题场景 | pass |
| 过期后同账号恢复、换账号不泄漏草稿 | `tools/browser_check.py` | pass |
| 不提供删除、不丢弃历史 | `ApiCase.test_query_and_methods`、`test_status_history` | pass |
| 多标签页会话身份错配 | `AdversarialCase.test_cross_tab_identity_mismatch`：请求拒绝；前端携带页面账号并在可见时核验 | pass（浏览器可见性事件未单独自动化） |
| 不改原有 PDF/PNG、不联网处理任务、不污染使用数据库 | 独立目录与临时 QA 数据库；能力检查：应用无第三方网络请求；原始设计文件保留 | pass |

## 过程中发现并解决的问题

1. 初始 16 个 API 测试在 501 占位接口上失败；2 个性质/并发测试也先失败。日志保留在 `evidence/red*.log`。浏览器测试在界面初次实现后建立，因此本轮并非每个 UI 行为都先执行 RED。
2. Ruff 修复导入/格式问题；mypy 提醒登录用户主键的可空类型，改为明确表达认证后的类型前提，没有关闭类型检查。
3. 浏览器发现保存完成但清单刷新未结束时，新建点击可能被忽略。提交期间禁用新建按钮，等待请求完成后恢复；原测试保持。
4. 隔离断言的示例标题与静态 placeholder 重名造成误报：在 SPEC 追加说明后，将测试数据加独特前缀，仍检查完整 DOM，未放宽隔离标准。
5. 恶意孤立 Unicode 代理码点可能导致数据库编码异常，已在输入边界拒绝；增加共享会话与界面账号的一致性检查。
6. 一次开发中并行启动测试共用了固定测试数据库，导致 readonly 错误；改为每进程独立测试文件。最终两轮完整套件按序执行且全部通过；不把那次受干扰的覆盖率当作最终证据。
7. 首次依赖审计报告虚拟环境旧 pip 26.0.1 存在漏洞记录；仅升级项目 pip 至 26.2.1，固定版本并重新跑完整检查。旧报告保存在 `evidence/audit-before-fix.json`。

## 限制与未验证项

- 未进行外部渗透测试、多机分布式压力测试、生产部署或多浏览器兼容性矩阵。并发检查为本机 SQLite 两线程，没有生产吞吐量承诺。
- JavaScript 为原生 JS，仅做语法检查和真实浏览器验收；没有 TypeScript 静态检查、JS 行覆盖率或自动化无障碍审计。视觉检查为桌面和手机截图人工检查。
- 后端 100% 覆盖率不包含 Django 内部、settings、数据库迁移或前端，不能解释为所有系统行为都已被证明。
- 密码找回、邮箱验证、分布式限流、长期草稿、负载分析、AI、学习调度、永久删除均未纳入第一版。身份限流为本地单进程缓存。
- 浏览器关闭/刷新会丢失未保存草稿；页面有未保存提醒。后续部署必须另行配置 HTTPS、生产服务器与共享限流存储。
- 没有初始化 Git 或创建提交，使用源码树哈希；密钥和用户数据库不在哈希范围内。
