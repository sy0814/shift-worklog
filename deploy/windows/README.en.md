# Work Log System · Windows Installation Guide (for beginners)

**Language / 语言 / Jezik:** [中文](README.md) · [Srpski](README.sr.md) · English

This guide shows you, step by step, how to install the Work Log System on a Windows PC so that every phone and computer in the plant can use it. **No programming knowledge is needed.** Each step tells you how to check that it worked. If a check fails, do not continue.

> Time needed: **1–2 hours** the first time (mostly waiting for downloads and installs).

> **About Chinese text on screen:** the installation script prints its messages in Chinese. Every question it asks is quoted and explained in [section 6.3](#63-answer-the-scripts-questions), so you do not need to read Chinese.

---

## Contents

1. [A few words explained](#1-a-few-words-explained)
2. [Checklist](#2-checklist)
3. [Step 1: Prepare the server PC](#3-step-1-prepare-the-server-pc)
4. [Step 2: Install the PostgreSQL database](#4-step-2-install-the-postgresql-database)
5. [Step 3: Download the program](#5-step-3-download-the-program)
6. [Step 4: Run the installation script](#6-step-4-run-the-installation-script)
7. [Step 5: First login and setup on the server PC](#7-step-5-first-login-and-setup-on-the-server-pc)
8. [Step 6: Set up the phones](#8-step-6-set-up-the-phones)
9. [Daily maintenance](#9-daily-maintenance)
10. [Backup and restore](#10-backup-and-restore)
11. [Troubleshooting](#11-troubleshooting)
12. [Appendix: where things are](#12-appendix-where-things-are)

---

## 1. A few words explained

| Word | What it means |
|---|---|
| **Server PC** | The Windows PC that runs the system. It must stay on; all phones and computers connect to it. |
| **IP address** | The server PC's "house number" on the plant network, for example `192.168.1.50`. Phones find the system by this address. |
| **Fixed IP** | Making sure that house number never changes. If it changes, phones can no longer find the system. |
| **Ports 80 / 443** | Two "doors" used by web pages: 80 for normal pages, 443 for encrypted pages (HTTPS). No other program may use them. |
| **HTTPS and certificate** | HTTPS is an encrypted web connection. Each phone must install this system's "certificate" once to trust it; otherwise the browser says "Not secure". |
| **PowerShell** | The command window built into Windows. We use it to run the installation script. |
| **Run as administrator** | Running a program with full Windows rights. Needed to install software and services. |
| **Service** | A program that runs in the background and starts automatically when the PC starts. |
| **PostgreSQL** | The database program where all records are stored. |
| **DeepSeek API key** | A secret key the system uses to call DeepSeek for Chinese/Serbian/English translation and AI analysis. The system works without it, but texts will not be translated automatically. |

---

## 2. Checklist

Check each item before you start:

- [ ] **A Windows 10 or Windows 11 PC**, 64-bit, at least 8 GB RAM, at least 50 GB free disk space. Wired network is better.
- [ ] This PC can **stay on all the time** (no shutdown, no sleep).
- [ ] You know the password of an **administrator account** on this PC.
- [ ] This PC **has internet access** (it can open https://www.google.com). Needed to download software during installation, and for translation later.
- [ ] Phones on the plant Wi-Fi can reach this PC (usually true on the same plant network; ask your network administrator if unsure).
- [ ] You can sign in to GitHub to download the system (the repository is private; the owner must give you access), **or** someone gives you the program on a USB stick.
- [ ] (Optional) A DeepSeek API key. You can also add it later in the web page.
- [ ] (Recommended) A USB stick or a second hard disk for backups.

---

## 3. Step 1: Prepare the server PC

### 3.1 Find the PC's IP address

1. Press **Win + R**, type `cmd` and press Enter. A black window opens.
2. Type `ipconfig` and press Enter.
3. Find the network adapter in use ("Ethernet" for cable, "Wi-Fi"/"WLAN" for wireless) and the line **IPv4 Address**, for example `192.168.1.50`.
4. **Write this address down.** You will need it many times.

### 3.2 Make the IP address fixed (important)

If the IP address changes, all phones lose the connection. Choose one way:

- **Way A (recommended): ask your network administrator to "reserve" this IP for this PC in the router** (also called DHCP reservation). Give them the PC name and the IP you found above.
- **Way B: set a static IP yourself.** Not recommended if you are not familiar with networks: a mistake can cut this PC off the network. If you must: Settings → Network & internet → Ethernet → IP assignment → Edit → Manual → turn on IPv4, then enter IP address, subnet prefix length (usually 24), gateway and DNS (ask your network administrator for these values).

### 3.3 Make sure ports 80 and 443 are free

Most PCs can skip this. Only PCs with website software (for example IIS) may use these ports. The script checks automatically and tells you which program is using them.

If it is IIS: Control Panel → Programs → Turn Windows features on or off → untick "Internet Information Services" → OK → restart the PC when asked.

### 3.4 About sleep mode

The script turns off "sleep when plugged in" automatically. If the PC is a laptop, keep it plugged in and **do not close the lid** (or set "When I close the lid" to "Do nothing" in the power settings).

---

## 4. Step 2: Install the PostgreSQL database

1. Open <https://www.enterprisedb.com/downloads/postgres-postgresql-downloads> in a browser.
2. In the **PostgreSQL 17** row, click the download button under **Windows x86-64**. The file is named like `postgresql-17.x-windows-x64.exe`.
3. Double-click the file. If Windows asks "Do you want to allow this app to make changes to your device?", click **Yes**.
4. In the installer, choose:

| Installer page | What to do |
|---|---|
| Setup (welcome) | Click **Next** |
| Installation Directory | Leave as is, click **Next** |
| Select Components | Leave as is, click **Next** (you may untick Stack Builder; it is not needed) |
| Data Directory | Leave as is, click **Next** |
| **Password** | **Choose a password for the `postgres` superuser and type it twice. Do not forget it!** The installation script needs it. Write it on paper and give it to the person in charge. |
| Port | Keep **5432**, click **Next** |
| Advanced Options | Keep "Default locale", click **Next** |
| Pre Installation Summary | Click **Next** |
| Ready to Install | Click **Next** and wait a few minutes |
| Completing | **Untick** "Launch Stack Builder at exit", click **Finish** |

**How to check:** press Win + R, type `services.msc`, press Enter. In the list you should find **postgresql-x64-17** with status "Running".

---

## 5. Step 3: Download the program

**From GitHub:**

1. Sign in to GitHub in a browser and open the system's repository page (ask the person in charge for the address).
2. Click the green **Code** button → **Download ZIP**.
3. In your Downloads folder, **right-click the ZIP → Extract All**, and extract to `D:\shift-worklog` (use `C:\shift-worklog` if there is no D: drive).

**From a USB stick:** copy the whole program folder to `D:\shift-worklog`.

**How to check:** open `D:\shift-worklog`. You should directly see the folders `backend`, `frontend` and `deploy`.

> Note: sometimes extracting adds one more folder level, for example `D:\shift-worklog\shift-worklog-master\backend`. That is fine; just use the real path in the commands below.

---

## 6. Step 4: Run the installation script

### 6.1 Open PowerShell as administrator

- **Windows 11:** right-click the **Start** button → **Terminal (Admin)**.
- **Windows 10:** right-click the **Start** button → **Windows PowerShell (Admin)**.

If Windows asks for permission, click **Yes**. The window title should contain "Administrator".

### 6.2 Type the commands

Type the following commands **one line at a time**, pressing Enter after each. You can copy and paste: right-clicking inside the PowerShell window pastes.

First line: allow this window to run scripts (only this window; it resets when you close it):

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
```

Second line: go to the program folder (change the path to where you extracted it):

```powershell
cd D:\shift-worklog\deploy\windows
```

Third line: start the installation:

```powershell
.\install.ps1
```

### 6.3 Answer the script's questions

The script shows nine steps, "==> 1/9 …" to "==> 9/9 …", and asks a few questions. **The questions appear in Chinese**; here is what each one means:

| Text on screen (Chinese) | Meaning | What to enter |
|---|---|---|
| 手机用哪个地址访问？直接回车 = 用上面检测到的 | Which address will phones use? Press Enter to use the detected one. | Look at the line above, after「检测到：」("detected:"). If it contains the IP from 3.1, **just press Enter**. Otherwise type the IP, e.g. `192.168.1.50`. |
| 请输入安装 PostgreSQL 时设置的 postgres 密码 | Enter the `postgres` password you set when installing PostgreSQL. | The password from step 2. **Only `*` appears while typing; this is normal.** |
| 设置系统管理员 admin 的登录密码（至少 8 位） | Set the login password for the web administrator `admin` (at least 8 characters). | Choose a password of **8 or more characters** and write it down. If it is too short, you will be asked again. |
| DeepSeek API Key（可以先直接回车……） | DeepSeek API key (you can press Enter now and add it later in the web page). | Paste the key if you have it, otherwise **just press Enter**. |
| 备份放哪里？…… | Where should backups be stored? | With a second disk, type e.g. `D:\WorkRecordBackup`. Otherwise just press Enter (backups go to `C:\WorkRecord\backups`). |

The first run downloads and installs Python, Node.js and other software automatically, which **can take 10–30 minutes**. It is normal if nothing new appears for a long time. Do not close the window.

### 6.4 How to check it worked

At the end you see green **「安装完成！」** ("Installation complete!") and something like:

```
安装完成！
  手机 / 电脑先打开   http://192.168.1.50/install   安装证书（只需一次）
  然后访问           https://192.168.1.50
  管理员账号         admin（密码是刚才设置的）
```

This means:
- **First open** `http://192.168.1.50/install` on phones and computers to install the certificate (only once).
- **Then use** `https://192.168.1.50`.
- **Admin account:** `admin`, with the password you just set.

**Take a screenshot of this part.**

### 6.5 If you see a red error

- The script stops and explains (in Chinese) which step failed and why; usually it also says how to fix it.
- After fixing it, **simply run `.\install.ps1` again.** Finished steps are skipped and passwords already entered are not asked again.
- If you are not sure what to do, **take a screenshot of the whole window** and send it to the technical contact.

---

## 7. Step 5: First login and setup on the server PC

### 7.1 Install the certificate on the server PC

1. On the server PC, open `http://YOUR-IP/install` in Edge or Chrome (e.g. `http://192.168.1.50/install`).
2. Click **① Download certificate** to download `workrecord-ca.crt`.
3. Double-click the file → **Install Certificate** → **Local Machine** → Next → **Place all certificates in the following store** → Browse → **Trusted Root Certification Authorities** → OK → Next → Finish.
4. **Close the browser completely and open it again.**

> Tip: on the server PC itself you can also open `http://127.0.0.1:8000`, which needs no certificate. It only works on that PC and is useful for troubleshooting.

### 7.2 Log in

Open `https://YOUR-IP`. The address bar should show a lock and no "Not secure" warning. Log in as **admin** with your password.

The menu language can be switched at the top right (中文 / Srpski / English).

### 7.3 Settings you must do first

After logging in, open the **Admin** menu at the top and do the following:

1. **Accounts:** team leader accounts already exist (`t1_leader1`–`t4_leader1`, `day_leader1`–`day_leader3`). **Their initial password is the same as the user name, which is not safe.**
   - Under "Admin → Accounts" click "Reset password" for each one, set a new password and tell each team leader.
   - Each leader account belongs to a person in the "Workers" roster (named like the account at first, e.g. "t1_leader1"): rename the person in the roster to the leader's real name; if the person already exists in the roster, use "Relink" on the Accounts page and then disable the extra roster entry.
   - Accounts for other people are opened in the roster with "Account": leaders and deputies get a username + password; members use the "Team account" (sign in: choose team → tap own photo → personal password). What each role may do is set under "Admin → Roles & permissions".
2. **Workers:** click "Bulk add", choose a team, paste one name per line, and save. Do this for each team.
3. **Schedule** (top menu): check in the "Shift calendar" that today's shifts match reality. If not, edit that team's cycle under "Teams" (cycle length, shift for each day, first day of the cycle; admin only). Enter public holidays under "Holidays / make-up workdays".
4. **Settings:**
   - If you did not enter the DeepSeek key during installation, enter it under "API key", click "**Test connection**", and when you see the green "Works" with sample translations, click "**Save**".
   - Under "Alert settings" you can change after how many hours an unfinished task is marked red.
5. **Glossary:** 51 mineral-processing and electrical terms are already included. Ask a Serbian colleague to check them: click "Export CSV", send it to them, then "Import CSV" when they are done.

---

## 8. Step 6: Set up the phones

Each phone needs this only once. You can print this section for the team leaders. The page `http://YOUR-IP/install` shows the same instructions on the phone in Chinese, Serbian and English.

### 8.1 Android

1. Connect the phone to the plant Wi-Fi.
2. Open `http://YOUR-IP/install` in **Chrome** and tap **① Download certificate**.
3. Open **Settings** and search for "**certificate**". Find "**Install certificate**" or "**CA certificate**". The location differs by brand; a common one is Settings → Security → More security settings → Encryption & credentials → Install a certificate → CA certificate.
4. If the phone warns you, tap "**Install anyway**", then choose the downloaded `workrecord-ca.crt`.
5. Back in Chrome, open `https://YOUR-IP` and log in with the team leader account.
6. Tap Chrome's **⋮** (top right) → **Add to Home screen** → Add. From now on, open the system from the home-screen icon.

### 8.2 iPhone / iPad

1. Connect to the plant Wi-Fi.
2. You **must use Safari** (not another browser or an app). Open `http://YOUR-IP/install`, tap **① Download certificate**, then tap "**Allow**".
3. Open **Settings**. "**Profile Downloaded**" appears near the top; tap it → **Install** (top right) → enter the passcode → **Install** again.
   - If you do not see it: Settings → General → **VPN & Device Management**.
4. **This step is the one people forget:** Settings → General → **About** → scroll to the bottom → **Certificate Trust Settings** → **turn on the switch** next to this system's certificate → Continue.
5. Open `https://YOUR-IP` in Safari and log in.
6. Tap Safari's **Share** button (square with an arrow) → **Add to Home Screen** → Add.

### 8.3 Good to know

- Pages you opened once while online **also open without signal**, showing the data from the last time you were online. A yellow "Offline" bar appears at the top.
- Tasks and photos created without signal are kept on the phone ("Pending sync" at the top right) and **uploaded automatically** when the connection returns.
- After a system update, the phone shows "New version available"; tap "Reload".

---

## 9. Daily maintenance

### 9.1 The system runs in the background

There are two services. They **start automatically when the PC starts** and restart themselves after an error. Normally you do nothing.

| Service name | Purpose |
|---|---|
| WorkRecord App | The system itself |
| WorkRecord HTTPS (Caddy) | The encrypted web entrance and the certificate page |

**Check them:** press Win + R, type `services.msc`, press Enter, find the two services. The status should be "Running". Right-click → "Restart" if needed.

### 9.2 If the system does not open (check in this order)

1. Is the server PC **on**, not asleep, and connected to the network?
2. On the server PC, open `http://127.0.0.1:8000`:
   - **It opens:** the system works, so the problem is the network, HTTPS or the phone certificate. See [Troubleshooting](#11-troubleshooting).
   - **It does not open:** restart "WorkRecord App" in `services.msc`, wait 1 minute and try again.
3. Still not working: open `C:\WorkRecord\logs` and send the file `WorkRecordApp.err.log` to the technical contact.

### 9.3 Update to a new version

1. Download the new version as in step 3 and extract it to a **new folder**, e.g. `D:\shift-worklog-new`.
2. Open PowerShell as administrator (see 6.1) and type, one line at a time:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
```

```powershell
cd D:\shift-worklog-new\deploy\windows
```

```powershell
.\update.ps1
```

3. The update script **makes a backup first**, then stops the system, updates the program, upgrades the database and starts everything again. When you see「更新完成」("Update complete"), you are done. The system is unavailable for a few minutes, **so update outside shift-change times**.
4. Data, photos, passwords and certificates are kept, and phones do not need a new certificate.

### 9.4 Change the server's IP address

Changing the address has two parts: first the PC must **really get the new IP**, then you tell the system the new address.

**① Give the PC the new IP:** ask your network administrator to change the reservation in the router, or set a static IP as in 3.2. Then run `ipconfig` in `cmd` and check that "IPv4 Address" shows the new IP.

**② Tell the system the new address** (choose one):

**Way A: the address script (recommended).** In an administrator PowerShell, type one line at a time, with your new IP on the last line:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
```

```powershell
cd C:\WorkRecord\app\deploy\windows
```

```powershell
.\set-address.ps1 192.168.1.60
```

> If `C:\WorkRecord\app\deploy\windows` has no `set-address.ps1` (installations before 2026-11-23 do not), download and extract the latest version first, and run the same commands in the `deploy\windows` folder of the **new download**.

To also allow access by PC name, separate with a comma and use quotes: `.\set-address.ps1 '192.168.1.60, worklog-server'`

When you see green「地址已修改。」("Address changed."), you are done.

**Way B: edit by hand in Notepad (no download needed).**

1. Open Notepad as administrator: search "Notepad" in the Start menu → right-click → Run as administrator.
2. In Notepad, File → Open, set the file type to "All files", and open `C:\WorkRecord\tools\WorkRecordCaddy.xml`.
3. Find this line, replace the old IP inside `value="..."` with the new one, and save:

```
<env name="SITE_HOSTS" value="192.168.1.50"/>
```

4. Press Win + R, type `services.msc`, press Enter, find "WorkRecord HTTPS (Caddy)", right-click → "Restart".

**③ Afterwards**

- Data and passwords are not affected. **Phones that already have the certificate do not need it again**; just open `https://NEW-IP`.
- Old home-screen icons point to the old address and no longer open: open the new address, "Add to Home screen" again, and delete the old icon.
- New phones install the certificate as usual from `http://NEW-IP/install`.

### 9.5 Watchdog (automatic alerts)

The install / update script creates a scheduled task **WorkRecordWatchdog** that checks every 5 minutes:

| What it checks | When there is a problem |
|---|---|
| Are both services running | Starts them automatically; tells you once even if the restart worked, alerts if it could not start them |
| Does the system respond | Service is running but the system does not answer: alert |
| Backup | Backup failed, or no successful backup for more than 26 hours: alert |
| Disk space | Less than 5 GB or 10% free on the disk with the program data or the backups: alert |

- **How it alerts**: a **popup on the server PC** (sent to everyone logged in), plus the Windows **event log** (Event Viewer → Windows Logs → Application, source `WorkRecord`) and `C:\WorkRecord\logs\watchdog.log`. Keep someone logged in on the server so the popup is seen.
- The same problem pops up **at most once every 60 minutes**; when it is fixed you get one more message saying it has recovered.
- Failed backups and low disk space are **also shown as a red notice on the home page** when an administrator logs in.
- During an update the script pauses the watchdog and turns it back on at the end. **If the update fails halfway, the watchdog stays paused**: fix the problem and run `update.ps1` again.
- Windows Home has no popup program (msg.exe): there you only get the event log and the log file.

The popup messages are in Chinese:

| Popup text (beginning) | Meaning |
|---|---|
| 服务 … 停了，已自动重新启动 | The service had stopped and was restarted automatically |
| 服务 … 停了，自动启动失败 | The service stopped and could not be restarted – start it in Services and check the log |
| … 在运行，但系统没有响应 | The service runs but the system does not respond – check the log, restart the service |
| 备份失败 | Backup failed – see `logs\backup.log` |
| 超过 26 小时没有成功的备份 | No successful backup for over 26 hours – check the task WorkRecordBackup |
| 磁盘 …: 快满了 | That disk is almost full |
| 已恢复 | The problem is gone |

---

## 10. Backup and restore

### 10.1 Automatic backup

Every night at **03:40** a backup is saved to the folder chosen during installation (default `C:\WorkRecord\backups`):

| Folder | Contents |
|---|---|
| `db` | The database, files like `workrecord-20261122-0340.dump`, **kept for 30 days** |
| `uploads` | Task photos |
| `caddy-pki` | The HTTPS certificate. If it is lost, every phone must reinstall the certificate. |
| `config` | The configuration file. It contains passwords, **so do not share it.** |

**Check once a week:** open `C:\WorkRecord\logs\backup.log`; the last lines should show today's「备份完成」("backup complete").

**Also copy the backup somewhere else** (USB stick, another PC, network drive). If the backup is on the same disk as the server, a disk failure destroys both.

**Set it up on the web page (recommended):** log in as administrator →「管理 → 系统设置 → 存储与备份」(Admin → System settings → Storage & backup):

- **Backup folder**: where backups go (e.g. `D:\WorkRecordBackup`); "Check" shows whether it is writable and how much space is free.
- **Second copy**: after each backup, another copy is made here automatically – a USB / external disk, a network share, or **a cloud client's sync folder** (OneDrive etc.; the client uploads it). The backup contains the database password, so keep the cloud folder private.
- The page shows the **last backup** (time, success, database size, free space) and has a "Back up now" button.
- **Archive original photos**: when enabled, originals older than N months are moved every day at 02:50 to the "archive folder" (another disk). View-size images and thumbnails stay, so everything works the same; "Original" is read from the archive disk, and if it is not connected the view-size image is shown.

### 10.2 Make a backup now

In an administrator PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File C:\WorkRecord\app\deploy\windows\backup.ps1
```

### 10.3 Restore data (if the database is damaged or after a big mistake)

> Restoring **replaces** the current data with the backup. Anything entered after that backup is lost. Ask the technical contact if unsure.

1. Stop the system (administrator PowerShell):

```powershell
Stop-Service WorkRecordCaddy, WorkRecordApp
```

2. Find the database password: open `C:\WorkRecord\app\backend\.env` in Notepad. In the line `DATABASE_URL=`, the password is the text between `workrecord:` and `@`.
3. Restore the database (replace the password and the file name with the real ones):

```powershell
$env:PGPASSWORD = 'DATABASE-PASSWORD'
```

```powershell
& 'C:\Program Files\PostgreSQL\17\bin\pg_restore.exe' --clean --if-exists -h 127.0.0.1 -U workrecord -d workrecord 'C:\WorkRecord\backups\db\workrecord-20261122-0340.dump'
```

4. Restore the photos:

```powershell
robocopy C:\WorkRecord\backups\uploads C:\WorkRecord\data\uploads /E
```

5. Start the system:

```powershell
Start-Service WorkRecordApp, WorkRecordCaddy
```

### 10.4 Moving to a new server PC

1. Install everything on the new PC (steps 1–4, including PostgreSQL).
2. Copy the whole backup folder from the old PC and restore the database and photos as in 10.3.
3. Put the certificate and configuration back, so **phones keep their certificate and nobody has to log in again**:
   - Copy the contents of `caddy-pki` into `C:\WorkRecord\data\caddy\caddy\pki` (overwrite).
   - Copy `config\backend.env` to `C:\WorkRecord\app\backend\.env` (overwrite).
4. Restart both services. If the new PC has a different IP, also follow 9.4.

---

## 11. Troubleshooting

| What you see | Cause and fix |
|---|---|
| The service will not start; `logs\WorkRecordApp.err.log` keeps showing error `10048` ("only one usage of each socket address") | Port 8000 is held by a leftover old process (older versions could leave one behind when the service was stopped). Run `update.ps1` once to fix it for good: stopping the service no longer leaves a process, and the watchdog and update script clean up leftovers automatically. Quick manual fix: in an administrator PowerShell run `Get-NetTCPConnection -LocalPort 8000 -State Listen` to get the process id, check it is python, run `Stop-Process -Id <id> -Force`, then start the service. |
| "…cannot be loaded because running scripts is disabled on this system" | You did not run `Set-ExecutionPolicy -Scope Process Bypass -Force` first, or ran it in another window. Run it in the same window first. |
| Message「请右键以管理员身份运行 PowerShell」 | "Run PowerShell as administrator." Reopen it as in 6.1. |
| Message「没有找到 PostgreSQL」 | "PostgreSQL not found." Install it (step 2), using the default location. |
| Database error mentioning the postgres password | Wrong password. Run `.\install.ps1` again and retype it. If you forgot it, reinstall PostgreSQL (only possible while there is no data yet). |
| Message「端口 80 / 443 已被程序……占用」 | "Port 80/443 is used by program …". Stop that program (see 3.3) and run the script again. |
| Downloading Python / Caddy fails | The PC has no internet access, or the company firewall blocks it. Ask your network administrator. |
| Phones cannot open `http://IP/install` | The phone is not on the same network, or a security program on the PC blocks ports 80/443; allow them in that program. |
| Phone says "Not secure" / "certificate not valid" | The certificate is not installed correctly. On Android, install it again. On iPhone, check that the switch in step 8.2.4 (Certificate Trust Settings) is on. |
| "Certificate does not match the address" | You used an address that was not entered during installation (e.g. the PC name). Use the address shown at the end of installation, or add it as in 9.4. |
| Tasks stay "Awaiting translation" | The server has no internet, or no DeepSeek key is set. Click "Test connection" in Settings. |
| Does not open after the PC restarts | Services need 1–2 minutes to start. Wait, then check as in 9.2. |
| Forgot the admin password | In `C:\WorkRecord\app\backend\.env`, the line `ADMIN_PASSWORD=` shows the password from the **first installation**. If it was changed later in the web page, ask the technical contact. |

---

## 12. Appendix: where things are

| Location | Contents |
|---|---|
| `C:\WorkRecord\app` | The program (replaced on update) |
| `C:\WorkRecord\app\backend\.env` | Configuration: database password, keys. **Do not delete or share.** |
| `C:\WorkRecord\data\uploads` | Task photos |
| `C:\WorkRecord\data\caddy` | HTTPS certificate |
| `C:\WorkRecord\logs` | Program and backup logs |
| `C:\WorkRecord\backups` | Default backup location |
| `C:\WorkRecord\tools` | Helper programs (Caddy, service manager) |

**Uninstall** (rarely needed). In an administrator PowerShell, run the command below. By default it removes only the services; data and database are kept.

```powershell
powershell -ExecutionPolicy Bypass -File C:\WorkRecord\app\deploy\windows\uninstall.ps1
```
