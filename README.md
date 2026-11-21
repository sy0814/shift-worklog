# 工作记录系统

需求与设计见 [CLAUDE.md](CLAUDE.md)。

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

```bash
cp backend/.env.example backend/.env   # 填 SECRET_KEY、ADMIN_PASSWORD 等
docker compose up -d --build
```
