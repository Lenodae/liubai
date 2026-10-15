# 第四部分：每日足迹与签到

用户已同意位置与交互方案并要求执行。Tier 3：新增账号内持久写入、幂等/并发及独立版本导入。spec approval: not obtained (autonomous run)；用户批准的是产品方案，本执行规范供事后复核。

## 结构与环境

第四部分在独立文件夹，以第三部分完整源码作为基线。代码、规划书、数据库、虚拟环境、session/CSRF cookie分别独立；服务8003，前三部分保持8000/8001/8002。只在最终验证通过后把根入口切换第四部分。首次从第三部分SQLite一致性快照复制现有账号、任务、步骤、完成/耗时、预算、回收站等数据；目标非空拒绝覆盖，备份0600。复制本机DeepSeek配置和secret文件，保留权限，禁止输出秘密内容。清理复制的会话，复制的排队/运行AI标记interrupted，避免重复执行/计费；不改变第三部分。

沿用固定Django、SQLite、Playwright、Hypothesis、coverage、Ruff、mypy等现有依赖版本，为第四部分建立独立.venv；无新依赖，不提交/推送Git，不调用付费模型。记录源码基线、SPEC、验证脚本、EVIDENCE；不追加无关功能。

## 产品与数据语义

1. 今日鼓励右侧提供今日签到按钮（已签到后禁用重复提交），并可在当天详情切换今天休息或撤销标记。签到和休息是互斥的手动标记，可与真实任务进展共存；不自动制造签到。
2. 每日足迹位于预算摘要/圆盘之后、任务引导和清单之前，仅总览显示。默认最近12周（本周及前11周，周一到周日）；提供查看全年（独立弹层、按年查看）。未来日禁用。手机390px无页面横向溢出，全年允许弹层内部横向滚动，键盘可选日期，文字/图例表达状态不只靠颜色。
3. 日期以服务器Asia/Shanghai日历为准，响应返回timezone/today；当前周或预算窗口的切换不改变签到日期。按日唯一，刷新/重新登录保留，不同账号隔离。新写入只允许今天，不补签或写将来日；已成功原请求跨午夜重试仅确认原操作。浏览器跨午夜/恢复及时刷新，延迟前一天的新写入明确拒绝。
4. 手动签到/休息/撤销不改任务状态、版本、完成事件、预算/估时或账本，也不弹完成鼓励。同一天只有一个标记行；多次相同请求幂等，同key不同内容409，版本过期409，重复同标记且版本新鲜可返回当前状态不重复计数。
5. 实际投入按TimeEntry.date、minutes求和，仅计voided_at为NULL的条目，父任务和子步骤各条账本只计一次。任务移回收站后事实仍保留；编辑日期/分钟或作废后日历更新，不复制周预估/预算到日统计。
6. 自动进展包括有效完成事件及实际耗时。complete按原事件created_at在Asia/Shanghai归日；completion_edit不新增计数/不改归日；后续同对象undo撤销该完成计数，重做产生新完成日期。步骤完成数和任务完成数分开展示，签到/休息不影响有效完成计数。旧数据有记录即读取，没有事实不猜测。
7. 点日期显示手动标记、真实小时分钟、完成步骤/任务和关联任务；已删除任务链接回收站；未记录天明确未记录，过去日只读。近期/年度分别统计范围内签到天数、休息天数、有进展天数。非空不等于更高价值，不以工时多少排名或以未签到惩罚。
8. 服务器成功后再显示已签到；网络结果不确定保留原body/key重试，不生成新key重复写入。冲突提供刷新，不自动覆盖。账号退出/换号清除弹层、旧数据及待重试写入；旧响应不得进入新账号。步进、时间、完成、编辑、撤销、任务删除恢复后刷新只读日历；读取失败不能阻断已有预算/任务操作。

## API契约（前后端共同遵守）

GET /api/footprints/calendar?view=recent 或 view=year&year=2026，返回 {today,timezone,view,year,start,end,days,summary,today_mark}。days为区间内每个日历日：{date,mark: null|checkin|rest,version:0或正整数,minutes,completed_steps,completed_tasks,has_activity}。summary={checkin_days,rest_days,active_days}；today_mark={date,mark,version}独立于选择年份。year允许1900..当前年，recent忽略year或拒绝无关参数但前端不发送。未来days为零/无记录且禁止交互。
GET /api/footprints/day?date=YYYY-MM-DD 返回 {today,timezone,day:上述day对象,entries:[{id,task_id,task_title,step_title,minutes,note,deleted}],completions:[{event_id,task_id,task_title,step_title,kind:step|task,at,note,deleted}]}，未来日期400。
POST /api/footprints/mark，Idempotency-Key UUID，body={date:YYYY-MM-DD,kind:checkin|rest|clear,version:非负整数}，返回 {today,timezone,day:{date,mark,version}}；clear使用null语义，保留版本行。需登录、CSRF和X-Workspace-User沿用既有api装饰器；未知字段/非法输入400，过期版本/日期变更409，旧回执重放只读不再写。唯一(owner,date)，事务保证标记与幂等回执一起成功/失败。

## 验收与失败模型

先RED后GREEN：日唯一/三种动作往返；账号与CSRF；重复键与丢回执；冲突/双线程争写；回执失败事务回滚；午夜与本地UTC边界、闰年365/366与12周84格；合成父子账本30+45=75，不叠加估时；时间编辑/作废和完成编辑/撤销/重做；已删除记录保留；签到不改变业务行或预算指纹。性质测试覆盖日期范围连续性、重试/标记独立及分钟求和，变异分别按契约与独立性质验证。

真实浏览器验证放置/签到重载/休息/撤销/当天详情/全年/手机/键盘、任务耗时与完成联动、失败原key重试与换号隔离、午夜过期处理。继承基础执行/预算/鼓励/删除回归；全后端随机序测试、类型/格式、新增代码覆盖、手动有效变异、迁移往返/备份恢复/真实导入检查与前三版源码隔离。对抗审查独立检查数据归日、并发及异常前端。未覆盖层和缺口明确入EVIDENCE，不虚报100%。

实施补充：检查现有配置后确认DeepSeek配置文件不依赖Django SECRET_KEY。为保证四个版本的签名密钥独立，第四部分生成新的secret-key；仅将DeepSeek配置逐字复制且不输出内容。账号密码哈希、任务及业务数据不依赖旧签名密钥，复制会话仍清空。此处替代上文复制secret文件的环境细节。
