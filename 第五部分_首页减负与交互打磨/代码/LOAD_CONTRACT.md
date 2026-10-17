# 第三部分前后端契约（实现协作）

所有日期 ISO，分钟整数或 null；window 参数为 week（周一日期）、mode（week / remaining）。GET 不创建记录。用户由会话决定，不接收 owner。

## GET /api/load/workspace?week=YYYY-MM-DD&mode=remaining

返回 `{window, tasks, analysis, actual, fingerprint, valid_until, history}`。

window: `{week, mode, as_of, budget_minutes, buffer_minutes, version, confirmed, stale}`；未配置 version=0，金额 null。
tasks 每项：`{id,title,status,priority,version,weekly_minutes,deadline,progress_low,progress_high,maintenance_low,maintenance_high,maintenance_active,scope_confirmed,plan_confirmed,remaining_low,remaining_high,remaining_confirmed,actual_minutes}`。
progress 为该窗口未来推进（完成/暂停/放弃由规则归0），maintenance 独立，不把旧 weekly_minutes 自动确认；remaining 为整个有限目标至截止的剩余工作，另填/可空，不参与周负载求和。
analysis: `{verdict,low,high,known_low,unknown_count,unknowns,capacity,budget,buffer,deficit_low,deficit_high,total_budget_deficit,ratio_low,ratio_high,recommendations}`。
verdict: unknown / conflict / conditional / fits。unknowns 为 `{task_id,title,fields}`；recommendations 为 `{kind,title,reason,task_id}`，不提供自动修改。
actual: `{minutes,entry_count,verified}`，按当前所选周全部有效账本，不从未来预算扣除。
history: 最近20条 `{id,kind,created_at,summary,can_undo}`；历史详情由 GET history 获取。

## POST /api/load/settings

统一带 `{week,mode,fingerprint,action,...}` 和 Idempotency-Key。返回最新 workspace。
`action=capacity`：`budget_minutes,buffer_minutes`（整数或null）。确认发生时点由服务端写；remaining确认到次日本地零点有效。
`action=plan`：`task_id,progress_low,progress_high,maintenance_low,maintenance_high,maintenance_active,scope_confirmed,remaining_low,remaining_high`。scope_confirmed 必须为布尔，明确推进/维护已经分开；可用 null 保存未知。保存同时确认当前任务版本/时点；未来目标 remaining 与窗口 progress 两个含义。
`action=save_snapshot`：无需其他字段，保存当前完整输入/结果供回顾。

## POST /api/load/preview

`{week,mode,fingerprint,changes:[...]}`，不写业务数据。change 为
`{task_id,progress_low,progress_high,maintenance_low,maintenance_high,status?}`；status 可选，仅 paused / in_progress；无status表示只改本窗口。允许changes带`{budget_minutes,buffer_minutes}`（无task_id）。
返回 `{before,after,changes,fingerprint,valid_until}`，before/after 为 analysis。

## POST /api/load/apply

相同payload + Idempotency-Key，事务采纳，返回workspace。
每个change都写明确原值与新值审计；更改status是持续全局状态变动。纯窗口调整不改周模板。允许未知但不能把未知当可行性保证。

## POST /api/load/undo

`{week,mode,fingerprint,event_id}` + Idempotency-Key。撤回只在完整来源与时间仍有效时，恢复 before 值并追加事件；失败409。

## GET /api/load/history?week=...

返回 `{week,actual:{minutes,entry_count,verified},tasks:[{id,title,status,minutes,entry_count}],events:[{id,kind,created_at,summary,before,after}],snapshots:[{id,created_at,window,analysis}]}`。按实际发生日期汇总，过去计划不重写。

## GET /api/load/deadlines?week=...&mode=...

返回 `{window,fingerprint,capacity,buffer,slices,work,checks}`。slices 是本窗口不重叠的分段：`[{end:'YYYY-MM-DD',budget_minutes,buffer_minutes,other_minutes}]`，隐式start从当前as_of日期或周一，末段必须到周日；other_minutes明确为本次待检查目标以外的推进+维护占用。分段budget/buffer合计必须分别等于window值，other不超过各段净容量。
work 为当前任务目标剩余量与deadline；checks按截止日累计比较共享净容量，未知/窗口外/逾期分别标注。
POST /api/load/deadlines 带 `{week,mode,fingerprint,slices}` + Idempotency-Key，保存分段；返回deadlines。没有分段时只能对周日检查，周中截止未知；支持切换不同周，跨周检查读取同账号已确认窗口合计，缺周或分段必须列未知，不能按天平均。

## 错误与刷新

400输入，401登录，404归属，409指纹/时间冲突。error字符串。指纹包括完整任务集合、任务版本、计划、预算、账本版本与规则。保存事实成功后分析失败不可重复提交；晚到响应按账号epoch和窗口generation丢弃。

## 预算自动预留扩展 · 2026-10-14

任务创建/编辑新增 `budget_schedule`（weekly/recurring）与 `budget_week`（YYYY-MM-DD周一）；创建默认weekly/当周。`weekly_minutes` 表示整个任务在所选周或每周的总预留分钟。创建即预留，planned/in_progress/paused均适用；weekly只所选周，recurring从起始周持续至completed/abandoned。Task写入与BudgetPolicy同时提交，重试、版本和所属账号校验沿用原接口。

Workspace任务增加 `allocation_source`（auto/manual/none）、`reservation_minutes`（未知null）、`budget_schedule`、`budget_week`；内部 `reservation_active` 区分政策不适用与未知，`budget_committed`用于明确的未执行手工承诺。auto是整个任务承诺，不再另加维护或子步骤；有该窗口TaskPlan时manual优先替代auto。政策自动值只用于整周，remaining不复制整周值。单独明确持续维护保留原确认逻辑。

analysis增加 `available_low`/`available_high`：净容量减去需求上/下界，资料不完整为null，负数表达缺口。界面图的可再安排扇区最少画0，并单列缺口；不画第二圈。预算分配环以总预算为整圈，区分缓冲、预留、可再安排，负载覆盖判定继续用净容量。

主导航默认week，明确remaining hash继续保留；新建成功弹出对应周的预算分配结果。历史revision与快照保留原记录；缺当时资料不当0。原SPEC中“旧weekly仅参考”的禁止规则按本轮用户授权更新，详见SPEC追加章节。
