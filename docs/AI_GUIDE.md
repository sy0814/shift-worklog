# 工作记录系统 · 给 AI 的开发说明

> 读者：在这个仓库里改代码的 AI 助手（以及想快速了解代码结构的开发者）。
> 给使用者看的说明书在 [USER_MANUAL.md](USER_MANUAL.md)。
> 需求来历、每一轮修改的细节和踩过的坑在根目录 [CLAUDE.md](../CLAUDE.md)（按时间记的开发日志，内容最全）。本文是**按结构整理的速查**，两者冲突时以代码为准，并顺手修正文档。

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
  migrations/versions/    0001…0016（表结构以这里为准）
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
  stores/auth.js          当前用户、权限、班组列表
  views/                  页面
  components/             组件
deploy/windows/           install / update / backup / uninstall / set-address / common .ps1 + 三语部署指南
deploy/Caddyfile, deploy/install/install.html
```

## 3. 核心概念（领域模型）

### 3.1 班次与排班（`shifts.py`）
- 三个班次 `day` / `middle` / `night`，开始时间在 `shift_config`（默认 07 / 15 / 23）。**夜班归属开始那一天**（「班次日」）。
- 每个班组一个**循环** `Cycle(pattern, start, holiday_off)`：pattern 每天一项，可以是 `day/middle/night/off` 或**自定义时间段**如 `07:00-12:00,14:00-17:00`（`check_hours` 校验）。自定义时间段按与哪个班重叠最多算作哪个班（`entry_kind`）。
- `kind`：`cycle`（有循环）/ `manual`（不固定，平时休息）。`is_main`：主班组（1～4 班）单独显示；其他班组（常白班、临时组）**合并**到同一班次的第一个主班组（`group_of`）。
- 优先级：`active_from/to` 有效期 → **班组调班**（`team_shift_overrides`，可为时间段）→ 循环 → 若是非主班组且结果为休息，再看**成员带出来的班次**（`member_fn`，有成员被单独安排上班就算在班）。
- 区分两类函数：`shift_of`（班组算不算在班，含成员带出来的）和 `team_entry`（班组自己的排班，**成员默认出勤只能用它**，否则一个人上班会把全组都算成上班）。
- 常用：`shift_at(dt)`、`main_team_on(d,k)`、`teams_on`、`group_of`、`recording_slot`（录入的任务归哪个班）、`receiving_slot`（移交过去归哪个班）、`next_shift_of_team`（找不到会抛 ValueError，调用方要兜底）、`coverage_problems`。
- 测试里构造班组用 `rotating(id, offset)` / `day_team(id)`。基准：2026-11-21 应为 1 班白、2 班中、3 班夜、4 班休。

### 3.2 员工、账号、角色
- **账号以名册为准**：`workers` 是人；`users.worker_id` 一对一关联；`users.role` 只有 `admin` 和 `staff`。
- 员工属于哪个班组、跟班组排班还是个人循环，按**变更记录** `worker_schedules` 的生效日期算（`worker_history.Timelines`），所以换班组不影响历史出勤。
- **角色** `roles`：权限表 `{权限: none/self/team/all}` + 登录方式（`password` 个人账号 / `pin` 班组账号点头像）+「首页单独显示」。
- 新员工自动开账号、默认密码、第一次登录强制改密码（`must_change_password`，后端拦截）。

### 3.3 出勤（`attendance_service.effective`）
- **默认不存库**，按当天有效的排班推算；`attendance` 表只存例外（请假 / 病假 / 缺勤 / 休息 / 调班 / 顶班）。
- 返回 `DayAttendance(status, shift_kind, team_id, source, note, hours)`。在岗、可分配人员、工时、导出、AI 分析都从这里取。
- 加班 `overtime`：某班次后加班到几点（`overtime_service.expand`）。

### 3.4 任务
- 三语列 `content_zh/sr/en` + `source_lang`；遗留问题 `leftover_*`、废弃原因 `discard_reason_*` 各自翻译；`translation_status`、`manual_fields`（人工校对过的列，机器不覆盖）。
- 状态：`not_started ⇄ in_progress → done →(重新打开) in_progress`；`handed_over`、`discarded` 为终态。
- 归属班次 `shift_date / shift_kind`（按录入班组的 `recording_slot`）。
- **移交** = 原任务标 `handed_over` + 接收班组新建一条（`source_task_id` 指回），带内容、译文、图片（指向同一文件）、`project_id`、`inspection_id`、`equipment_id`；逻辑在 `routers/handover.py:perform_handover`（手动、自动共用）。
- 带队人 `lead_worker_id` **同时也在** `task_workers` 里。
- 离线：`client_id`（UUID）去重；`recorded_at` 决定班次；状态修改带 `expect` / `at`。
- 关联：`project_id`（子项目）、`inspection_id`（巡查生成）、`equipment_id`（设备）。

### 3.5 项目与定期巡查
- **项目** `projects`：多个子项目（子项目就是任务）；全部完成或废弃才闭合（只看每条移交链的最新一条）；可移交的子项目下班 30 分钟后自动移交给在班主班组。
- **定期巡查** `inspection_templates`：周期（每天 / 每 N 天 / 每周几 / 每月几号 / 每年某天 / 每 N 个班）+ 派给谁；每分钟检查，`(巡查项, 触发时间)` 唯一不重复派；有小项目时每次派发生成一个项目。

### 3.6 其他
- 设备台账 `equipment`（三语名称 / 区域 / 备注，自动翻译）。
- 存储与备份：备份目录写进 `data/*.txt` 给 `backup.ps1` 读；原图超过 N 个月归档到另一块盘（`attachments.archived_at`）。
- 术语表 `glossary` 拼进翻译提示词。
- AI 分析报告 `ai_reports`。

## 4. 必须遵守的规则（不变量）

1. **权限只走 `permissions.who(db, user)`**：`scope(perm)` / `has` / `team_ok` / `task_ok` / `visible_team_ids`。新功能要在 `PERMS` 里加权限名和可选范围，在 `LEADER_PERMS` / `MEMBER_PERMS` 给默认值，**迁移里给已有角色补默认值**，前端 `i18n.js` 的 `rp.perms` 里加三语名称（key 里的 `.` 换成 `_`）。前端用 `auth.can(perm)` / `auth.scope(perm)` / `auth.teamOk(perm, teamId)` 控制显示，但后端必须再校验。
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
11. **离线**：新的「手机上常用的写操作」要考虑走发件箱（`stores/outbox.js`，带 `client_id` 或 `expect` 防重复 / 防覆盖）。`GET /api/*` 自动有离线缓存。

## 5. 加一个功能的标准步骤

1. `models.py` 加表 / 列 → 写迁移 → `schemas.py` 加入出模型。
2. 业务逻辑放 `app/xxx_service.py`，路由放 `app/routers/xxx.py`，在 `main.py` 注册（`app.include_router`）。
3. 权限：`PERMS` + 默认值 + 迁移补默认值 + 前端权限名称。
4. 留痕：每个写操作 `audit.log` / `log_changes`；`i18n.js` 的 `ent` 里加对象名称（操作记录页显示用）。
5. 有用户输入的文字 → 三语列 + 翻译队列（参考 `translate_equipment` / `translate_project`，队列项是元组 `("kind", id)`，在 `_work()` 里分发，`retry_pending` 里补定时重试）。
6. 前端：`views/Xxx.vue`、`router.js` 加路由（`meta.admin` / `meta.perm`）、`Layout.vue` 加菜单、`i18n.js` 三语、`apiErrors.js` 错误提示。
7. 测试：`backend/tests/test_xxx.py`。
8. 跑测试、`npm run build`、用 Playwright 在浏览器里点一遍（检查有没有跳动、控制台有没有报错）。
9. 在 CLAUDE.md「进度与约定」里记一条（做了什么、关键文件 / 接口、迁移号、坑）。用户可见的变化同步到 [USER_MANUAL.md](USER_MANUAL.md)。

## 6. 运行与测试

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
- 翻译测试用 `tests/test_translation.py` 的 `fake` fixture（假 DeepSeek，给每种语言加前缀）。
- 时间相关的测试：monkeypatch 路由模块里的 `local_now`（例如 `app.routers.duty.local_now`）。
- 示例账号：`admin` / `.env` 的 `ADMIN_PASSWORD`；`t1_leader1`…`t4_leader1`、`day_leader1`…`day_leader3`，密码同用户名。
- 测试真实翻译：用占位 Key 启动（`DEEPSEEK_API_KEY=sk-placeholder`）时，开发环境的出站代理会替换成真 Key（只限这个开发环境）。

## 7. 主要接口一览（前缀 `/api`）

| 领域 | 接口 |
|---|---|
| 登录 | `POST /auth/login`（表单）、`GET /auth/teams`、`GET /auth/teams/{id}/people`、`POST /auth/pin`、`GET/PATCH /auth/me`、`POST /auth/change-password` |
| 任务 | `GET/POST /tasks`、`GET/PATCH /tasks/{id}`、`POST /tasks/{id}/status`、`POST /tasks/{id}/attachments`、`DELETE /attachments/{id}`、`GET /files/{id}/{thumb\|view\|original}?t=`、`GET /tasks/{id}/history`、`GET /assignable` |
| 交接班 | `GET /board`、`GET /handover/default`、`POST /handover`、`POST /tasks/{id}/discard`、`GET /overdue`、`GET /duty?which=current\|next` |
| 翻译 | `PUT /tasks/{id}/translation`、`POST /tasks/{id}/retranslate`、`POST /translate`、`GET /translation/status`、`POST /translation/retry-failed`、术语表 `/glossary*` |
| 排班 | `GET /shifts/now`、`GET /shifts/calendar`、`GET /shifts/coverage`、`GET/PUT /shifts/config`（班次时间）、`/teams`（增删改）、`/team-shifts`（调班、`/swap` 互换）、`/holidays/{day}` |
| 出勤 | `GET/PUT /attendance`、`PUT /attendance/batch`、`POST /attendance/swap`、`GET /attendance/template`、`POST /attendance/import`、`GET /workers/{id}/day`、`/overtime` |
| 员工 / 账号 | `/workers`（增改、Excel 导入导出、自定义列、头像、`/{id}/schedule`、`/{id}/account`、`/accounts/open-all`）、`/users`、`/roles` |
| 项目 / 巡查 | `/projects`（`/subs`、`/subs/{id}/assign`、`/people`）、`/inspections`（`/preview`、`/{id}/run-now`、`/{id}/runs`） |
| 设备 | `/equipment`、`/equipment/export/xlsx`、`/equipment/import/xlsx` |
| 导出 / 分析 | `GET /export/tasks`、`/analysis`（`/{id}`、`/{id}/retry`） |
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

## 9. 常见坑（都踩过）

- 中文 Windows 默认 GBK：`.env` 按 UTF-8 读、服务设 `PYTHONUTF8=1`、`alembic.ini` 纯 ASCII、PowerShell 读 txt 要 `-Encoding UTF8`。
- vue-i18n 消息里的反斜杠会被吃掉一个，路径示例尽量别放在 i18n 文案里。
- Element Plus 弹窗会给 body 减滚动条宽度，和 `scrollbar-gutter` 叠加会跳——已在 `style.css` 统一处理，新类型的浮层要检查。
- 父组件 scoped 样式会命中子组件根元素（头像被压扁事件）。
- exifr lite 的 `pick` 有 bug，要按段（ifd0 / exif）指定。
- `deepseek-flash` 默认开思考，翻译要带 `thinking: disabled`。
- SQLite 读出的 datetime 没有时区（存的是 UTC）。
- PG 测试库必须是空的，否则大量失败（不是代码问题）。
- 非主班组「休息」但成员被单独安排上班的情况，见 3.1 的 `member_fn`。
