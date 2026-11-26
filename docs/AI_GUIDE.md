# 工作记录系统 · 给 AI 的开发说明

> 读者：在这个仓库里改代码的 AI 助手（以及想快速了解代码结构的开发者）。
> 给使用者看的说明书在 [USER_MANUAL.md](USER_MANUAL.md)。
> 现在的业务规则在根目录 [CLAUDE.md](../CLAUDE.md)（按领域整理）；需求原文、每一轮修改的经过和当时的决定在 [CHANGELOG.md](CHANGELOG.md)；排班的具体例子在 [SCHEDULE_SCENARIOS.md](SCHEDULE_SCENARIOS.md)（同时是测试）。本文是**按代码结构整理的速查**，冲突时以代码为准，并顺手修正文档。

---

## 1. 系统是什么

选矿厂车间内网用的**交接班 / 工作安排系统**，中文 / 塞尔维亚语（拉丁字母）/ 英语三语。

- 倒班班组按循环排班自动推算谁在班；任务按班次归属，下班可移交给下一班
- 任何语言录入，DeepSeek 自动翻译成另外两种，三种都存库
- 手机 PWA，Wi-Fi 死角能离线录入 / 开始 / 完成任务
- 所有修改留痕（只能追加）
- 正式部署在 **Windows 10/11 + PostgreSQL + Caddy**（WinSW 注册服务），单进程

## 2. 技术栈与目录

| 部分 | 技术 |
|---|---|
| 后端 | Python 3.11+、FastAPI、SQLAlchemy 2（`Mapped`）、Alembic、APScheduler、openpyxl、Pillow（+ HEIC） |
| 数据库 | 正式 PostgreSQL；开发 / 测试 SQLite（也能用 PG 跑全部测试） |
| 前端 | Vue 3 `<script setup>`、Vite、Element Plus、Pinia、vue-i18n、vite-plugin-pwa（injectManifest）、idb、exifr、dayjs |
| 翻译 / AI | DeepSeek（OpenAI 兼容），可在页面上换成其他兼容接口 |
| 部署 | `deploy/windows/*.ps1`（PowerShell 5.1）、Caddy 内部 CA 签 HTTPS |

```
backend/
  app/
    main.py               FastAPI 入口：注册路由、启动时迁移 + 种子数据 + 后台线程 + 调度器、静态文件
    config.py             .env 配置（get_settings()），时区 APP_TIMEZONE
    db.py                 引擎、Session、约束命名规则 NAMING（不要改）
    models.py             全部表
    schemas.py            Pydantic 模型（UTCDateTime、Trilingual、TaskOut……）
    migrate.py            启动时 alembic upgrade head；旧库认领
    seed.py               首次启动：班组、管理员、示例班长、术语表
    security.py           密码哈希、JWT、get_current_user（含「必须先改密码」拦截）、图片签名
    permissions.py        ★ 角色权限：PERMS、Who、who(db, user)
    departments.py        ★ 车间：当前车间（get_dept 依赖，X-Department 头）、员工车间跟班组同步（before_flush）
    audit.py              ★ 留痕：log() / log_changes()
    shifts.py             ★ 排班引擎（纯函数）：Cycle、TeamInfo、Schedule
    schedule_service.py   从库里构造 Schedule（含「成员带出来的班次」）、local_now()
    worker_history.py     员工班组 / 个人排班变更记录（Timelines）、账号同步
    attendance_service.py 出勤：默认按排班推算 + 例外记录（effective()）
    overtime_service.py   加班展开
    translator.py         ★ 只负责调翻译接口、校验 JSON（换模型只改这里）
    translation_service.py 翻译队列（2 个线程）、写回、定时重试、名称翻译；调度器也在这里启动
    llm_config.py / secretbox.py  AI 接口设置（库里加密存 Key）
    analysis.py           AI 工作量分析：程序算统计，模型只写报告
    inspection_schedule.py 定期巡查周期计算（纯函数）
    inspection_service.py  巡查到点派发
    project_service.py    项目进度、子项目创建、下班后自动移交
    storage_service.py    备份目录、备份状态、原图归档
    images.py             图片处理（EXIF 时间、转正、浏览图 / 缩略图、头像）
    app_settings.py       app_settings 表里的配置（警示阈值、默认密码……）
    routers/              每个页面 / 资源一个文件，前缀 /api
  migrations/versions/    0001…0017（表结构以这里为准）
  tests/                  pytest，conftest 用临时 SQLite
  static/                 前端构建产物（npm run build 输出，git 忽略）
frontend/src/
  main.js router.js App.vue style.css
  api.js                  axios：令牌、错误提示、403「必须改密码」跳转、download()
  apiErrors.js            ★ 服务器英文错误 → 三语提示
  i18n.js                 ★ 界面三语文案（zh / sr / en 三块，结构一致）
  offline.js + stores/outbox.js  ★ 离线发件箱（IndexedDB）
  sw.js                   Service Worker（预缓存 + API 网络优先）
  photo.js                手机端压缩、读 EXIF
  cycle.js                排班写法显示（「7-12 14-17」、休息时间）
  branding.js             系统名称
  stores/auth.js          当前用户、权限、班组列表（allTeams = 全厂，teams = 当前车间）、车间（dept / departments）
  dept.js                 本机记住的当前车间（api.js 每个请求带 X-Department）
  views/                  页面
  components/             组件
deploy/windows/           install / update / backup / uninstall / set-address / common .ps1 + 三语部署指南
deploy/Caddyfile, deploy/install/install.html
```

## 3. 核心概念（领域模型）

### 3.1 班次与排班（`shifts.py`）
- 三个班次 `day` / `middle` / `night`，开始时间在 `shift_config`（默认 07 / 15 / 23）。**夜班归属下班那一天**（「班次日」D = D-1 23:00 ～ D 23:00，顺序 夜 → 白 → 中，`shifts.ORDER`；2026-11-27 起，迁移 0022）。班次起止一律用 `Schedule.shift_window` / `shift_start`，不要自己拼日期；「现在是哪个班次日」用 `shift_at(now)`，23:00 以后它是第二天，不是 `now.date()`。
- 每个班组一个**循环** `Cycle(pattern, start, holiday_off)`：pattern 每天一项，可以是 `day/middle/night/off` 或**自定义时间段**如 `07:00-12:00,14:00-17:00`（`check_hours` 校验）。自定义时间段按与哪个班重叠最多算作哪个班（`entry_kind`）。
- `kind`：`cycle`（有循环）/ `manual`（不固定，平时休息）。`is_main`：主班组（1～4 班）单独显示；其他班组（常白班、临时组）**合并**到同一班次的第一个主班组（`group_of`）。
- 优先级：`active_from/to` 有效期 → **班组调班**（`team_shift_overrides`，可为时间段）→ 循环 → 若是非主班组且结果为休息，再看**成员带出来的班次**（`member_fn`，有成员被单独安排上班就算在班）——**这一天有班组调班时不看**（明确写下的优先于推算的；trace 记 `member_ignored`）。用户面前的说法是四类：班组长期（循环）/ 班组某天（调班）/ 个人长期（`worker_schedules`，名册「长期排班」）/ 个人某天（出勤例外），见 `components/ScheduleGuide.vue`。
- 区分两类函数：`shift_of`（班组算不算在班，含成员带出来的）和 `team_entry`（班组自己的排班，**成员默认出勤只能用它**，否则一个人上班会把全组都算成上班）。
- **推理过程（「为什么？」）**：`Cycle.planned`、`cycle_entry`、`team_entry`、`shift_of`、`worker_entry`、`entry_kind_traced` 和 `attendance_service.default_for` / `resolve` 都带可选参数 `trace: list`，按判定顺序追加 `{"code": ..., ...}`（`shifts.note()`）。不传时行为完全不变。`app/explain.py` 调同一批函数拿到 trace，再补「谁、什么时候设的」；code 的含义写在 `explain.py` 开头，前端 `components/WhyPanel.vue` 按 code 翻成三语句子。**改排班 / 出勤规则时：在改动的地方加 `note(trace, ...)`，在 `explain.py` 开头和 `WhyPanel.vue` 的 `text()`、`i18n.js` 的 `why` 里补上新 code**；`tests/test_explain.py` 有随机排班下「带 trace 和不带结果一致」的测试。
- 常用：`shift_at(dt)`、`main_team_on(d,k)`、`teams_on`、`group_of`、`recording_slot`（录入的任务归哪个班）、`receiving_slot`（移交过去归哪个班）、`next_shift_of_team`（找不到会抛 ValueError，调用方要兜底）、`coverage_problems`。
- 测试里构造班组用 `rotating(id, offset)` / `day_team(id)`。基准：2026-11-21 应为 1 班白、2 班中、3 班夜、4 班休。

### 3.1a 车间（`departments`，`departments.py`）
- 班组之上的一层：`teams.department_id` 必填；`workers.department_id`（有班组时 = 班组的车间，`before_flush` 自动同步；车间管理员这种没班组的人单独设）；`equipment.department_id`（空 = 全厂共用）；`inspection_templates.department_id`（「派给在班班组」在哪个车间找）；`ai_reports.department_id`。
- **排班按车间分开**：`TeamInfo.dept`；`teams_on(d, k, dept)`、`main_team_on(d, k, dept)`、`coverage_problems(..., dept)` 的 `dept` 不给（`shifts.ALL`）= 不分车间（只给旧测试和单车间用）；`group_of`、`handover_target`、`default_handover_target` 自动用 team 自己的车间。**新代码里凡是「某班次哪个班组在班」都要带车间。**
- **当前车间**：路由加参数 `dept: int | None = Depends(get_dept)`。只有能切换的人（系统管理员、角色的 `task.view` 为 `all`）认请求头 `X-Department`，其他人永远是自己的车间（`departments.current`）。列表类接口（首页、交接班、警示、在岗、日历、排班检查、调班列表、任务列表、项目、巡查、设备、出勤、加班、导出、AI 分析、名册导入导出）按当前车间筛。
- `GET /api/teams` 返回**所有车间**的班组（带 `department_id`），前端 `auth.teams` 再按当前车间筛；跨车间移交时用 `auth.allTeams`。
- 跨车间：移交可以交给任何车间的班组（`perform_handover` 不限车间）；借调 = 出勤里顶别的车间的班组。
- 只有一个车间时前端不显示车间（`auth.multiDept`），行为和加车间以前完全一样。

### 3.2 员工、账号、角色
- **账号以名册为准**：`workers` 是人；`users.worker_id` 一对一关联；`users.role` 只有 `admin` 和 `staff`。
- 员工属于哪个班组、跟班组排班还是个人循环，按**变更记录** `worker_schedules` 的生效日期算（`worker_history.Timelines`），所以换班组不影响历史出勤。
- **角色** `roles`：权限表 `{权限: none/self/team/dept/all}`（dept = 本车间，all = 全厂）+ 登录方式（`password` 管理账号 / `pin` 个人账号点头像）+「首页单独显示」。
- 新员工自动开账号、默认密码、第一次登录强制改密码（`must_change_password`，后端拦截）。
- 内置角色：班长、副班长、成员、**车间管理员**（`dept_admin`，`DEPT_ADMIN_PERMS` = 每项都是 dept）。按车间的权限 `worker.manage`（名册）、`team.manage`（班组管理）、`analysis`（AI 分析）用 `who.dept_ok(perm, dept_id)` 判断。范围不是 all 的人不能给别人设含 all 的角色、不能改含 all 角色的人（防止越权）。

### 3.3 出勤（`attendance_service.effective`）
- **默认不存库**，按当天有效的排班推算；`attendance` 表只存例外（请假 / 病假 / 缺勤 / 休息 / 调班 / 顶班）。
- 某人某天的判定只在 `attendance_service.resolve(sched, entry, 例外记录, d, trace=None)` 一处：先 `default_for`（排班），再叠例外。`effective` 逐天调它；不要在别处另写一份。
- 返回 `DayAttendance(status, shift_kind, team_id, source, note, hours)`。在岗、可分配人员、工时、导出、AI 分析都从这里取。
- 加班 `overtime`：某班次后加班到几点（`overtime_service.expand`）。
- 首页人员状态 `routers/duty.py`：**管理人员**（角色 `task.create` 为 dept / all、本车间）从班组里拿出来放 `DutyOut.managers`，`counts.managers` 单独数，其他 counts 不含他们；在不在班照常按 `attendance_service.resolve`（他们靠个人循环）；没有班组也没有个人循环的列在 `managers_unscheduled`

### 3.4 任务
- 三语列 `content_zh/sr/en` + `source_lang`；遗留问题 `leftover_*`、废弃原因 `discard_reason_*` 各自翻译；`translation_status`、`manual_fields`（人工校对过的列，机器不覆盖）。
- 状态：`not_started ⇄ in_progress → done →(重新打开) in_progress`；`handed_over`、`discarded` 为终态。
- 归属班次 `shift_date / shift_kind`（按录入班组的 `recording_slot`）。
- **移交** = 原任务标 `handed_over` + 接收班组新建一条（`source_task_id` 指回），带内容、译文、图片（指向同一文件）、`project_id`、`inspection_id`、`equipment_id`；逻辑在 `routers/handover.py:perform_handover`（手动、自动共用）。
- 带队人 `lead_worker_id` **同时也在** `task_workers` 里。
- **可移交** `tasks.transferable`（迁移 0018）：能不能移交看 `tasks.can_transfer(task)` = 任务自己可移交且（子项目时）项目也可移交；`TaskOut.transferable` 返回的就是它。巡查项的 `transferable` 在没有小项目时写到生成的任务上。
- 离线：`client_id`（UUID）去重；`recorded_at` 决定班次；状态修改带 `expect` / `at`。
- 关联：`project_id`（子项目）、`inspection_id`（巡查生成）、`equipment_id`（设备）。
- **任务类型** `tasks.kind`（迁移 0020）：fault / maintenance / inspection / other；巡查生成的为 inspection（`inspection_service`、`project_service`），移交时带过去；任务表单里选，导出有「类型」列。
- **设备统计**（`app/equipment_stats.py`、`routers/equipment_stats.py`，前缀 `/api/equipment-stats`，前端 `EquipmentStats.vue` 在设备台账页「统计」）：按**移交链**计数（第一条 `source_task_id` 为空且班次日期在时间段里），类型 / 状态 / 完成时间看链上最新一条；处理用时用最新一条的 完成 − 开始（移交会复制开始时间，不能链上相加）；反复 = 30 天内故障 ≥3 次（滑动窗口）。能看：管理员、`task.view` 为 dept / all、或有 `equipment.manage`
- **班次日志** `task_logs`（迁移 0019，`routers/task_logs.py`）：一条任务多条自由记录，三语列 + `source_lang`，翻译队列项 `("log", id)`（`translation_service.translate_log`，定时重试也包括）；班次按写的时间 `recorded_at` 算（离线最多往前 3 天）；`GET /tasks/{id}/logs` 列整条移交链（`chain_ids`）；写需要 `task_perms` 的 `log`（= 能开始 / 完成或修改，已完成的要 `task.edit_done`）；删 = 写的人或能修改任务的人，软删除；留痕在任务上（action `log` / `log_delete`）。前端 `TaskLogs.vue`，离线走发件箱（type `log`，`client_id` 去重）。导出多一张「班次日志」表。i18n 用 `tlog`（`log` 已被操作记录页占用）

### 3.5 项目与定期巡查
- **项目** `projects`：多个子项目（子项目就是任务）；全部完成或废弃才闭合（只看每条移交链的最新一条）；可移交的子项目下班 30 分钟后自动移交给在班主班组。
- **定期巡查** `inspection_templates`：周期（每天 / 每 N 天 / 每周几 / 每月几号 / 每年某天 / 每 N 个班）+ 派给谁；每分钟检查，`(巡查项, 触发时间)` 唯一不重复派；有小项目时每次派发生成一个项目。

### 3.6 其他
- 设备台账 `equipment`（三语名称 / 区域 / 备注，自动翻译）。
- 存储与备份：备份目录写进 `data/*.txt` 给 `backup.ps1` 读；原图超过 N 个月归档到另一块盘（`attachments.archived_at`）。
- 术语表 `glossary` 拼进翻译提示词。
- AI 分析报告 `ai_reports`。

## 4. 必须遵守的规则（不变量）

1. **权限只走 `permissions.who(db, user)`**：`scope(perm)` / `has` / `team_ok` / `task_ok` / `dept_ok` / `teams_in` / `visible_team_ids`。范围有 dept（本车间）时不要再写 `scope == "all"` 这种判断，用 `team_ok` / `dept_ok`；「像管理员一样不受限」用 `scope in ("dept", "all")`。新功能要在 `PERMS` 里加权限名和可选范围，在 `LEADER_PERMS` / `MEMBER_PERMS` 给默认值，**迁移里给已有角色补默认值**，前端 `i18n.js` 的 `rp.perms` 里加三语名称（key 里的 `.` 换成 `_`）。前端用 `auth.can(perm)` / `auth.scope(perm)` / `auth.teamOk(perm, teamId)` / `auth.deptOk(perm)` / `auth.wide(perm)` 控制显示，但后端必须再校验。
2. **所有修改写留痕**：`audit.log()` / `audit.log_changes()`。`audit_log` 由数据库触发器禁止 UPDATE / DELETE。系统自动的操作 `user_id=None`。留痕里不记密码、API Key。
3. **改了 `models.py` 必须写迁移**（`backend/migrations/versions/00NN_*.py`，revision 用四位数字串 `"0017"`，down_revision 指上一个）。新增非空列给 `server_default`；布尔用 `sa.true()/sa.false()`；SQLite 改表用 `op.batch_alter_table`。`tests/test_migrations.py` 会比对模型和迁移。
4. **三语**：
   - 用户输入的业务文字（任务、项目名、设备……）存三列 + `source_lang`，走翻译队列补齐；只填一种语言是正常的。
   - 名称类（班组、角色、系统名称）保存时 `translation_service.fill_names` 当场补。
   - 塞语一律拉丁字母。
   - 界面文案在 `i18n.js`，**zh / sr / en 三块都要加**。
   - 用户可能看到的服务器错误，在 `apiErrors.js` 加正则 → 三语提示。
5. **时间**：库里存 UTC（`DateTime(timezone=True)`），SQLite 读出来没有时区要按 UTC 补；排班计算用工厂本地 naive 时间（`local_now()`、`shift_window`）；给前端的本地时间要带时区。
6. **排班引擎保持纯函数**，数据库读取放 `schedule_service.py`。成员默认出勤用 `team_entry` / `worker_entry`，不要用 `shift_of`。
7. **翻译只经过 `translator.py`**；业务代码调 `translation_service.enqueue*`，不要在请求里同步调接口（名称类和 `/api/translate` 除外）。单进程部署（进程内锁）。
8. **API Key / 密钥不进代码和仓库**：.env 的 `DEEPSEEK_API_KEY`，或页面设置里加密存库（`secretbox`，用 SECRET_KEY 派生）。
9. **Windows 脚本**：`.ps1` 必须 **UTF-8 带 BOM + CRLF**，只用 PowerShell 5.1 语法；传给外部程序的参数里不要带双引号；调外部程序时局部 `$ErrorActionPreference='Continue'` 只看 `$LASTEXITCODE`（用 `Invoke-Native`）；icacls 用 SID；`alembic.ini` 必须纯 ASCII。改了脚本提示、步骤或网页菜单名，**同步改三份部署指南**。
10. **页面不能跳**：用户很在意点击后布局跳动。
    - 弹窗 / 抽屉 / 确认框的 body 宽度补偿已在 `style.css` 处理，加了 `scrollbar-gutter: stable`。
    - 会出现 / 消失的提示文字要**预留位置**（min-height），不要用 v-if 让下面的按钮移动。
    - 组件根元素 class 名要独特，避免被父组件 scoped 样式命中。
11. **表格和工具栏的写法**（2026-11-25 统一）：
    - 表格「操作」列一律用 `components/RowActions.vue`（items = [{label, type, onClick}]，删除放最后），列宽用 `rowActions.useActionsWidth(() => [所有可能的按钮文字])` 算（按当前语言量文字宽度，塞语最长也不换行；手机上只算直接显示的那几个）。标题都是「操作」、`fixed="right"`。
    - 普通列宽度用 `rowActions.colWidth(表头, 可能的内容)`（表头、内容取宽的，按当前语言量），标签一排用 `tagsWidth`；操作按钮多、页面放不下时给 `RowActions` 传 `max`，后面的收进「⋯」（账号管理页的做法）。
    - 手机上 `.toolbar` 的直接子元素由 `style.css` 统一排：输入框 / 下拉框整行，按钮两个一排等宽。新页面的工具栏按钮直接放在 `.toolbar` 下面就行。
    - 列表里一部分行有勾选框时，其他行也要留同样宽的位置（首页交接班的 `.pick`）。
    - 手机上表格单元格里的班次用 `<ShiftTag short>`。
    - 检查脚本思路：Playwright 逐页打开，找单元格里按钮 `top` 不同（换行）、`scrollWidth > clientWidth`（溢出）、同一列表卡片 `left` 不同；中文和塞语、电脑和手机各跑一遍。
12. **离线**：新的「手机上常用的写操作」要考虑走发件箱（`stores/outbox.js`，带 `client_id` 或 `expect` 防重复 / 防覆盖）。`GET /api/*` 自动有离线缓存。

## 5. 加一个功能的标准步骤

1. `models.py` 加表 / 列 → 写迁移 → `schemas.py` 加入出模型。
2. 业务逻辑放 `app/xxx_service.py`，路由放 `app/routers/xxx.py`，在 `main.py` 注册（`app.include_router`）。
3. 权限：`PERMS` + 默认值 + 迁移补默认值 + 前端权限名称。
4. 留痕：每个写操作 `audit.log` / `log_changes`；`i18n.js` 的 `ent` 里加对象名称（操作记录页显示用）。
5. 有用户输入的文字 → 三语列 + 翻译队列（参考 `translate_equipment` / `translate_project`，队列项是元组 `("kind", id)`，在 `_work()` 里分发，`retry_pending` 里补定时重试）。
6. 前端：`views/Xxx.vue`、`router.js` 加路由（`meta.admin` / `meta.perm`）、`Layout.vue` 加菜单、`i18n.js` 三语、`apiErrors.js` 错误提示。
7. 测试：`backend/tests/test_xxx.py`。
8. 跑测试、`npm run build`、用 Playwright 在浏览器里点一遍（检查有没有跳动、控制台有没有报错）。
9. 在 [CHANGELOG.md](CHANGELOG.md) 末尾记一条（做了什么、关键文件 / 接口、迁移号、坑）；规则变了改 CLAUDE.md 对应段落（只写现在的规则）。用户可见的变化同步到 [USER_MANUAL.md](USER_MANUAL.md)。改了排班 / 出勤判定，在 [SCHEDULE_SCENARIOS.md](SCHEDULE_SCENARIOS.md) 加场景。

## 6. 运行与测试

**CI**（`.github/workflows/ci.yml`）：每个 PR 和推到 master 时跑——后端测试（SQLite、PostgreSQL 16 各一遍）、前端构建、Windows 脚本格式（`scripts/check_ps1.py`：.ps1 要 UTF-8 BOM + CRLF，alembic.ini 纯 ASCII）。PowerShell 语法本身 CI 检查不了（没有 Windows 机器），改了脚本仍要请用户在服务器上跑一次。

```bash
# 后端
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env
.venv/bin/uvicorn app.main:app --reload --port 8000
.venv/bin/python -m pytest -q                      # SQLite，全部测试

# 在 PostgreSQL 上跑全部测试（库要是空的，先 DROP/CREATE）
TEST_DATABASE_URL=postgresql+psycopg://user:pw@127.0.0.1:5432/wrtest \
TEST_PG_URL=postgresql+psycopg://user:pw@127.0.0.1:5432/wrmig \
.venv/bin/python -m pytest -q

# 新迁移
.venv/bin/python -m alembic revision --autogenerate -m "说明"   # 生成后人工检查

# 前端
cd frontend
npm install
npm run dev      # http://localhost:5173，/api 代理到 8000
npm run build    # 输出到 backend/static
```

- 测试环境变量在 `tests/conftest.py`：临时 SQLite、`ADMIN_PASSWORD=admin123`、不启动调度器、默认不翻译。
- **排班场景测试** `tests/test_scenarios.py`：读 `docs/SCHEDULE_SCENARIOS.md` 的设置和表格，不用数据库，直接调 `Schedule` / `attendance_service.resolve` / `schedule_service.vote_member_shifts`。失败信息写明哪一行、表里写的、系统算出的和「为什么？」的依据。
- 翻译测试用 `tests/test_translation.py` 的 `fake` fixture（假 DeepSeek，给每种语言加前缀）。
- 时间相关的测试：monkeypatch 路由模块里的 `local_now`（例如 `app.routers.duty.local_now`）。
- 示例账号：`admin` / `.env` 的 `ADMIN_PASSWORD`；`t1_leader1`…`t4_leader1`、`day_leader1`…`day_leader3`，密码同用户名。
- 测试真实翻译：用占位 Key 启动（`DEEPSEEK_API_KEY=sk-placeholder`）时，开发环境的出站代理会替换成真 Key（只限这个开发环境）。

## 7. 主要接口一览（前缀 `/api`）

| 领域 | 接口 |
|---|---|
| 车间 | `GET /departments`（导航页，不需要登录，含此刻在班班组）、`POST/PUT/DELETE /departments/{id}`（系统管理员） |
| 登录 | `POST /auth/login`（表单）、`GET /auth/teams?department_id=`、`GET /auth/teams/{id}/people`、`POST /auth/pin`、`GET/PATCH /auth/me`、`POST /auth/change-password` |
| 任务 | `GET/POST /tasks`、`GET/PATCH /tasks/{id}`、`POST /tasks/{id}/status`、`POST /tasks/{id}/attachments`、`DELETE /attachments/{id}`、`GET /files/{id}/{thumb\|view\|original}?t=`、`GET /tasks/{id}/history`、`GET /assignable` |
| 交接班 | `GET /board`、`GET /handover/default`、`POST /handover`、`POST /tasks/{id}/discard`、`GET /overdue`、`GET /duty?which=current\|next` |
| 翻译 | `PUT /tasks/{id}/translation`、`POST /tasks/{id}/retranslate`、`POST /translate`、`GET /translation/status`、`POST /translation/retry-failed`、术语表 `/glossary*` |
| 排班 | `GET /shifts/now`、`GET /shifts/calendar`、`GET /shifts/coverage`、`GET/PUT /shifts/config`（班次时间）、`/teams`（增删改）、`/team-shifts`（调班、`/swap` 互换、`/unaffected` 不受调班影响的人）、`/holidays/{day}` |
| 为什么？ | `GET /explain/worker/{id}?day=`、`GET /explain/team/{id}?day=`：`{day, result, steps[]}`（权限 `schedule.why`，迁移 0021 给已有角色按以前的规则补默认值；按目标的班组判断范围，没有班组的人按车间；成员默认 403）。前端每一步的「去修改」链接（`WhyPanel.vue` 的 `link()`）靠页面 query 打开弹窗：`/attendance?worker=&day=`、`/attendance?team=&month=`、`/schedule?tab=teams&team=`、`/schedule?tab=calendar&shift=班组&day=`、`/schedule?tab=holidays`、`/workers?schedule=员工`；打开后 `router.replace` 去掉 query |
| 删除员工 / 账号 | `DELETE /workers/{id}`（连同账号、排班记录）、`DELETE /users/{id}`（只限管理员账号）：`app/usage.py` 按所有指向 workers.id / users.id 的外键 + 巡查 JSON 里的人数引用，用过（或登录过）→ 409 `worker in use: 表名,…`，前端 `apiErrors.js` 的 `REFS` 翻成「出勤记录、任务」这种说法 |
| 出勤 | `GET/PUT /attendance`、`PUT /attendance/batch`、`POST /attendance/swap`、`GET /attendance/template`、`POST /attendance/import`（multipart `file` + `month=YYYY-MM`；有「Sap No.」列的是工厂月表，走 `_import_sheet`，否则按模板；`ImportOut` 多 `month / people / days / cleared`）、`GET /workers/{id}/day`、`/overtime` |
| 员工 / 账号 | `/workers`（增改、Excel 导入导出、自定义列、头像、`/{id}/schedule`、`/{id}/account`、`/accounts/open-all`）、`/users`、`/roles` |
| 项目 / 巡查 | `/projects`（`/subs`、`/subs/{id}/assign`、`/people`）、`/inspections`（`/preview`、`/{id}/run-now`、`/{id}/runs`） |
| 设备 | `/equipment`、`/equipment/export/xlsx`、`/equipment/import/xlsx` |
| 导出 / 分析 | `GET /export/tasks`、`/analysis`（`/{id}`、`/{id}/retry`） |
| 班次日志 | `GET/POST /tasks/{id}/logs`、`DELETE /task-logs/{id}` |
| 设备统计 | `GET /equipment-stats?start&end`、`GET /equipment-stats/{id}/timeline`、`GET /equipment-stats/xlsx` |
| 报警 | `GET /alerts`（管理员：备份失败 / 太久没备份 / 磁盘快满，`app/alerts.py`）；服务停了由 `deploy/windows/watchdog.ps1` 检查 |
| 设置 | `GET/PUT /settings`（警示阈值）、`/branding`、`/settings/llm`（AI 接口，含 `/test`、`/models`）、`/users/default-password`、`/storage`（`/check`、`/backup-now`、`/archive-now`）、`/audit` |

准确的参数以 `backend/app/routers/*.py` 为准（FastAPI 自动文档：开发时 `http://localhost:8000/docs`）。

## 8. 后台任务（APScheduler，`translation_service.start_scheduler`）

| 任务 | 频率 |
|---|---|
| 翻译重试（任务、项目、设备） | 每 2 分钟 |
| 定期巡查派发 | 每分钟 |
| 项目子项目下班后自动移交 | 每分钟 |
| 员工班组变更到日子生效（`_sync_workers`） | 每分钟 |
| 原图归档 | 每天 02:50 |
| 数据库备份 | Windows 计划任务每天 03:40（`backup.ps1`，不在程序里） |
| 看门狗 | Windows 计划任务每 5 分钟（`watchdog.ps1`，`WorkRecordWatchdog`）：PostgreSQL 和两个服务停了先启动再报警（启动不了时 `Get-DbCause` / `Get-AppCause` / `Get-CaddyCause` 查可能原因写进报警，新的常见原因加到这三个函数里；报警文字一律 `T '中' '塞' '英'`，语言来自 `data\watchdog-lang.txt`，网页「存储与备份」里设，`storage_service.alert_lang`）、`/api/health` 不通、备份失败 / 超过 26 小时、磁盘少于 5 GB 或 10%；服务器弹窗（msg.exe）+ 事件日志 + `logs\watchdog.log`，同一问题 60 分钟一次。阈值和 `app/alerts.py` 一致。update.ps1 先 `Disable-Watchdog`、最后 `Register-Watchdog` |

## 9. 常见坑（都踩过）

- **夏令时（Europe/Belgrade）**：班次时间都是本地 naive datetime，**两个本地时间相减是钟面差**，3-29 那夜少 1 小时、10-25 那夜多 1 小时（Python 里两个带同一个 ZoneInfo 的时间相减也是钟面差）。算时长一律用 UTC 时间相减或 `schedule_service.local_hours`。以前导出工时和加班时长就这样算错过（2026-11-26 修好，`tests/test_dst.py`）

- **Windows 上 venv 的 `Scripts\python.exe` 是转接程序**，会再启动一个基础 Python。WinSW 停服务时只结束了转接程序，真正的进程留下来占着 8000 端口，服务就一直报 10048 启动不了（2026-11-25 用户实际遇到）。现在服务直接用基础 Python 运行 `backend/run_server.py`（它把 `.venv` 的包加进来再启动 uvicorn），配置由 `common.ps1` 的 `Get-AppServiceXml` 生成，install / update 都用它；另外 `Stop-AppServices`、`Start-AppServices`、看门狗会结束占着 8000 端口的残留 Python（`Stop-StaleApp`；看门狗用 `Test-FromService` 看进程往上几层是不是 `WorkRecordApp.exe`）

- 中文 Windows 默认 GBK：`.env` 按 UTF-8 读、服务设 `PYTHONUTF8=1`、`alembic.ini` 纯 ASCII、PowerShell 读 txt 要 `-Encoding UTF8`。
- vue-i18n 消息里的反斜杠会被吃掉一个，路径示例尽量别放在 i18n 文案里。
- Element Plus 弹窗会给 body 减滚动条宽度，和 `scrollbar-gutter` 叠加会跳——已在 `style.css` 统一处理，新类型的浮层要检查。
- 父组件 scoped 样式会命中子组件根元素（头像被压扁事件）。
- exifr lite 的 `pick` 有 bug，要按段（ifd0 / exif）指定。
- `deepseek-flash` 默认开思考，翻译要带 `thinking: disabled`。
- SQLite 读出的 datetime 没有时区（存的是 UTC）。
- PG 测试库必须是空的，否则大量失败（不是代码问题）。
- 非主班组「休息」但成员被单独安排上班的情况，见 3.1 的 `member_fn`。
- 多个车间的班组名可能相同（各车间都有「1班」）：按名字找班组时（Excel 导入）只在当前车间里找。
- Service Worker 的离线缓存按网址存，不看 `X-Department` 头：能切换车间的人离线时看到的是最后一次联网时那个网址的数据。
- `tests/test_inspections.py::test_due_creates_task_and_advances` 在工厂时间 08:00～08:05 之间跑会失败（测试把巡查定在每天 08:00，「5 分钟前到期」跨过了下一次），换个时间再跑就好，不是代码问题。
