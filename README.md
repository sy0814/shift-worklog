# 工作记录系统

- **使用说明书**（给使用者）：[docs/USER_MANUAL.md](docs/USER_MANUAL.md)
- **开发说明**（给 AI 和开发者）：[docs/AI_GUIDE.md](docs/AI_GUIDE.md)
- **现在的业务规则**（按领域）：[CLAUDE.md](CLAUDE.md)
- **排班场景表**（某种情况系统怎么排，同时是测试）：[docs/SCHEDULE_SCENARIOS.md](docs/SCHEDULE_SCENARIOS.md)
- 需求原文和每一轮修改的记录：[docs/CHANGELOG.md](docs/CHANGELOG.md)

## 开发

后端（Python 3.11+）：

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env        # 按需修改
.venv/bin/uvicorn app.main:app --reload --port 8000
.venv/bin/python -m pytest -q
```

前端（Node 20+）：

```bash
cd frontend
npm install
npm run dev     # http://localhost:5173，/api 代理到 8000
npm run build   # 输出到 backend/static，由后端直接提供
```

首次启动自动创建：

| 账号 | 初始密码 | 角色 |
|---|---|---|
| `admin` | `.env` 里的 `ADMIN_PASSWORD` | 管理员 |
| `t1_leader1` … `t4_leader1` | 与用户名相同 | 1～4 班班长 |
| `day_leader1` … `day_leader3` | 与用户名相同 | 常白班班长 |

**上线前所有初始密码都要改掉**，`SECRET_KEY` 也要换成随机长字符串。

## 部署

**Windows 10/11（正式部署方式）**：原生安装 + PostgreSQL。面向初学者的分步指南（三语）：
[中文](deploy/windows/README.md) · [Srpski](deploy/windows/README.sr.md) · [English](deploy/windows/README.en.md)

### Linux / Docker（备选）

需要一台装了 Docker 的内网电脑或小主机，手机和电脑要能访问它的内网 IP。

```bash
cp .env.example .env                    # 填 SITE_HOSTS（服务器内网 IP / 主机名）、POSTGRES_PASSWORD
cp backend/.env.example backend/.env    # 填 SECRET_KEY（随机长字符串）、ADMIN_PASSWORD、DEEPSEEK_API_KEY
docker compose up -d --build
```

启动后有三个服务：`db`（PostgreSQL）、`app`（系统本身，不直接对外）、`caddy`（HTTPS 入口，占用 80 / 443 端口）。

### 手机第一次使用

1. 手机连上厂区 Wi-Fi，打开 `http://服务器地址/install`，按页面说明下载并安装证书（安卓 / iPhone / Windows 都有步骤，中塞英三语）。iPhone 安装后还要在「关于本机 → 证书信任设置」里打开开关。
2. 用 `https://服务器地址` 打开系统，登录。
3. 安卓 Chrome：菜单 → 添加到主屏幕；iPhone Safari：分享 → 添加到主屏幕。之后像 APP 一样从桌面打开，断网也能打开并显示最后一次联网时的数据。

### 需要备份的数据

| Docker 卷 | 内容 |
|---|---|
| `pgdata` | 数据库（任务、留痕、出勤、账号……） |
| `uploads` | 任务图片 |
| `caddy_data` | HTTPS 根证书和私钥。丢了会生成新的，所有手机都要重装证书 |

### 注意

- `backend/.env` 里的 `SECRET_KEY` 定好后不要改：改了所有人要重新登录，后台保存的 AI 接口 Key 也要重新填。
- 系统只支持单进程运行（不要给 uvicorn 加 `--workers`），翻译任务的防重复靠进程内锁。
- 发布新版本：`git pull && docker compose up -d --build`。手机打开时会提示「有新版本」，点刷新即可。
