# Windows 10 / 11 部署说明

原生安装，不用 Docker。装好后有两个 Windows 服务，开机自动启动、崩溃自动重启：

| 服务 | 作用 |
|---|---|
| `WorkRecordApp` | 系统本身（只在本机 127.0.0.1:8000 监听，不直接对外） |
| `WorkRecordCaddy` | HTTPS 入口，占用 80 / 443 端口，自带证书机构 |

数据库用 PostgreSQL（Windows 服务 `postgresql-x64-17`）。

---

## 一、准备

1. **一台常开的 Windows 10/11 电脑**，接有线网更稳。手机要能通过厂区 Wi-Fi 访问到它。
2. **固定 IP**：在路由器里给这台电脑绑定 IP，或在网卡里设静态 IP。IP 变了手机就连不上。
3. **能上外网**：翻译要访问 `api.deepseek.com`。安装时也要下载 Python 依赖、Caddy 等。
4. **80、443 端口空闲**：如果开过 IIS，在「控制面板 → 程序 → 启用或关闭 Windows 功能」里关掉 Internet Information Services。
5. **安装 PostgreSQL 17**：
   - 打开 https://www.enterprisedb.com/downloads/postgres-postgresql-downloads ，下载 Windows x86-64 版
   - 一路默认，**记住设置的 postgres 密码**，端口保持 5432
   - 最后的 Stack Builder 不用装

Python 和 Node.js 不用自己装，安装脚本会用 winget 自动装。Node.js 只用来构建网页。如果电脑上没有 winget（很老的 Windows 10），先手动装 Python 3.13 和 Node.js LTS。

## 二、安装

1. 从 GitHub 下载代码：仓库页面 → Code → Download ZIP，解压到任意位置，例如 `D:\shift-worklog`。
2. 开始菜单搜「PowerShell」→ 右键 **以管理员身份运行**。
3. 执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
cd D:\shift-worklog\deploy\windows
.\install.ps1
```

4. 脚本会依次问你：
   - **手机访问用的地址**：会自动检测本机 IP，直接回车即可；
   - **postgres 密码**：安装 PostgreSQL 时设置的那个；
   - **admin 管理员密码**：至少 8 位；
   - **DeepSeek API Key**：可以先回车跳过，之后在网页「系统设置」里填；
   - **备份目录**：建议放另一块硬盘，例如 `D:\WorkRecordBackup`。
5. 看到「安装完成」就好了。第一次大约 5~15 分钟，主要是下载依赖。

安装位置：程序在 `C:\WorkRecord\app`，图片和证书在 `C:\WorkRecord\data`，日志在 `C:\WorkRecord\logs`。

脚本可以重复运行：已经完成的步骤会跳过，已有的配置（`backend\.env`）不会被覆盖。

## 三、手机第一次使用

1. 手机连厂区 Wi-Fi，浏览器打开 `http://服务器IP/install`。
2. 按页面上的步骤安装证书（有安卓、iPhone、Windows 的步骤，中塞英三语）。
   - **iPhone 必须多做一步**：设置 → 通用 → 关于本机 → 证书信任设置 → 打开开关。
3. 打开 `https://服务器IP`，用班长账号登录。
4. 添加到主屏幕：安卓 Chrome 在「菜单 → 添加到主屏幕」，iPhone Safari 在「分享 → 添加到主屏幕」。

**第一件事**：用 admin 登录，在「管理 → 账号管理」里把各班长账号的初始密码改掉（初始密码和用户名相同）。

## 四、日常管理

**查看服务状态 / 重启**（管理员 PowerShell）：

```powershell
Get-Service WorkRecord*
```

```powershell
Restart-Service WorkRecordApp
```

也可以在「服务」管理器（`services.msc`）里找 WorkRecord App、WorkRecord HTTPS (Caddy)。

**日志**：`C:\WorkRecord\logs\WorkRecordApp.err.log`（程序）、`WorkRecordCaddy.err.log`（HTTPS）、`backup.log`（备份）。

**更新到新版本**：下载新代码解压，然后以管理员身份运行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
cd <新代码目录>\deploy\windows
.\update.ps1
```

update.ps1 会先自动备份，然后更新、重启。手机打开时会提示「有新版本」，点刷新即可。

**服务器 IP 变了**：用新地址重新运行安装脚本。数据不受影响，手机证书也不用重装。

```powershell
.\install.ps1 -SiteHosts 192.168.1.60
```

## 五、备份与恢复

**每天 03:40 自动备份**到安装时设置的目录，内容如下：
- `db\workrecord-日期.dump`：数据库，保留 30 天
- `uploads\`：任务图片，增量备份
- `caddy-pki\`：HTTPS 根证书。丢了要让所有手机重装证书
- `config\backend.env`：配置文件，里面有数据库密码和密钥，备份目录要放在只有管理员能访问的地方

**手动备份一次**：

```powershell
C:\WorkRecord\app\deploy\windows\backup.ps1
```

**从备份恢复数据库**（管理员 PowerShell）：
1. 停服务：

```powershell
Stop-Service WorkRecordCaddy, WorkRecordApp
```

2. 恢复数据库。数据库密码在 `C:\WorkRecord\app\backend\.env` 的 `DATABASE_URL` 里，是 `workrecord:` 和 `@` 之间那一段：

```powershell
$env:PGPASSWORD = '数据库密码'
& 'C:\Program Files\PostgreSQL\17\bin\pg_restore.exe' --clean --if-exists -h 127.0.0.1 -U workrecord -d workrecord 'D:\WorkRecordBackup\db\workrecord-20261122-0340.dump'
```

3. 恢复图片：

```powershell
robocopy D:\WorkRecordBackup\uploads C:\WorkRecord\data\uploads /E
```

4. 启动服务：

```powershell
Start-Service WorkRecordApp, WorkRecordCaddy
```

**换一台电脑**：在新电脑上照常运行 install.ps1，然后按上面的方法恢复数据库和图片。再把旧备份里的 `caddy-pki` 复制到 `C:\WorkRecord\data\caddy\caddy\pki`，`config\backend.env` 复制到 `C:\WorkRecord\app\backend\.env`，然后重启服务。这样手机不用重装证书，所有人也不用重新登录。

## 六、常见问题

| 现象 | 原因和处理 |
|---|---|
| 安装时提示端口 80/443 被占用 | 通常是 IIS 或别的网站程序，关掉后重新运行 install.ps1 |
| 手机打不开 `http://IP/install` | 手机和电脑不在同一网段；或 Windows 防火墙被其他安全软件接管，要在那款软件里放行 80、443 |
| 手机提示「不安全 / 证书无效」 | 证书没装，或 iPhone 没在「证书信任设置」里打开开关 |
| 浏览器提示证书和地址不匹配 | 用了安装时没写进去的地址访问（比如电脑名），用 `-SiteHosts` 把它加进去重新运行 install.ps1 |
| 翻译一直「待翻译」 | 电脑上不了外网，或没填 DeepSeek Key。在「系统设置 → 测试连接」里检查 |
| 电脑重启后打不开 | 等 1~2 分钟让服务启动；仍不行就看 `C:\WorkRecord\logs` 里的日志 |

## 七、卸载

```powershell
C:\WorkRecord\app\deploy\windows\uninstall.ps1
```

默认只删服务、防火墙规则和备份任务，数据和数据库都保留。加 `-RemoveProgram` 会连程序文件一起删。
