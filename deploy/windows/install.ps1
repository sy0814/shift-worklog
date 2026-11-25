<#
工作记录系统 · Windows 10/11 安装脚本（原生安装，不用 Docker）

用法：右键「以管理员身份运行」PowerShell，然后：
    Set-ExecutionPolicy -Scope Process Bypass -Force
    cd <解压出来的目录>\deploy\windows
    .\install.ps1

可以重复运行：已经装好的步骤会跳过；已有的 backend\.env（密钥、数据库密码）不会被覆盖。
#>
param(
    [string]$SiteHosts,      # 手机访问用的地址：内网 IP 和/或电脑名，逗号分隔。不填会自动检测后让你确认
    [string]$BackupTarget    # 备份目录，建议另一块硬盘或共享盘。不填默认 C:\WorkRecord\backups
)

. (Join-Path $PSScriptRoot 'common.ps1')
Assert-Admin
$Source = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path

Write-Host '工作记录系统 · Windows 安装' -ForegroundColor White
Write-Host "程序来源：$Source"
Write-Host "安装位置：$Root"

# ---------------- 1. 前置软件 ----------------
Write-Step '1/9 检查前置软件（Python、Node.js、PostgreSQL）'
$winget = Get-Command winget.exe -ErrorAction SilentlyContinue

$python = Find-Python
if (-not $python) {
    if (-not $winget) { throw '没有找到 Python 3.11+，也没有 winget。请先手动安装 Python 3.13（https://www.python.org/downloads/windows/ ，安装时勾选 Add to PATH），再运行本脚本。' }
    Write-Ok '用 winget 安装 Python 3.13'
    Invoke-Native 'winget' @('install', '-e', '--id', 'Python.Python.3.13', '--scope', 'machine', '--silent', '--accept-package-agreements', '--accept-source-agreements') '安装 Python'
    Update-PathFromRegistry
    $python = Find-Python
    if (-not $python) { throw 'Python 装好了但没找到，请关掉 PowerShell 重新以管理员身份打开，再运行一次本脚本。' }
}
Write-Ok "Python：$python"

$npm = Find-Npm
if (-not $npm) {
    if (-not $winget) { throw '没有找到 Node.js，也没有 winget。请先手动安装 Node.js LTS（https://nodejs.org/ ），再运行本脚本。' }
    Write-Ok '用 winget 安装 Node.js LTS（只用来构建网页）'
    Invoke-Native 'winget' @('install', '-e', '--id', 'OpenJS.NodeJS.LTS', '--silent', '--accept-package-agreements', '--accept-source-agreements') '安装 Node.js'
    Update-PathFromRegistry
    $npm = Find-Npm
    if (-not $npm) { throw 'Node.js 装好了但没找到，请重新打开 PowerShell 再运行一次。' }
}
Write-Ok "npm：$npm"

$pgBin = Find-PgBin
$pgSvc = Get-PgServiceName
if (-not $pgBin -or -not $pgSvc) {
    throw @'
没有找到 PostgreSQL。请先安装：
  1. 打开 https://www.enterprisedb.com/downloads/postgres-postgresql-downloads ，下载 Windows x86-64 的 PostgreSQL 17
  2. 安装时记住你设置的 postgres 超级用户密码；端口保持 5432；Stack Builder 不用装
  3. 装完后重新运行本脚本
'@
}
if ((Get-Service $pgSvc).Status -ne 'Running') { Start-Service $pgSvc }
Write-Ok "PostgreSQL：$pgBin（服务 $pgSvc）"

# 80 / 443 端口不能被别的程序占用（常见：IIS）
foreach ($port in 80, 443) {
    $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($c) {
        $owner = (Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue).ProcessName
        if ($owner -ne 'caddy' -and $owner -ne $SvcCaddy) {
            throw "端口 $port 已被程序「$owner」（PID $($c.OwningProcess)）占用。HTTPS 需要 80 和 443 端口，请先停掉它（如果是 IIS：在「Windows 功能」里关闭 Internet Information Services）。"
        }
    }
}

# ---------------- 2. 访问地址 ----------------
Write-Step '2/9 确定手机访问用的地址'
$existingCaddy = Join-Path $DataDir 'site-hosts.txt'
if (-not $SiteHosts -and (Test-Path $existingCaddy)) { $SiteHosts = (Get-Content $existingCaddy -Raw).Trim() }
if (-not $SiteHosts) {
    $ips = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254\.)' -and $_.PrefixOrigin -in @('Dhcp', 'Manual') } |
        Select-Object -ExpandProperty IPAddress
    $guess = (@($ips) + @($env:COMPUTERNAME.ToLower())) -join ', '
    Write-Host "    检测到：$guess"
    Write-Note '建议给这台电脑设置固定 IP（在路由器里绑定，或在网卡里设静态 IP），否则 IP 变了手机就连不上。'
    $answer = Read-Host '    手机用哪个地址访问？直接回车 = 用上面检测到的'
    $SiteHosts = if ($answer.Trim()) { $answer.Trim() } else { $guess }
}
New-Item -ItemType Directory -Force -Path $DataDir, $LogDir, $ToolsDir | Out-Null
Write-Utf8NoBom $existingCaddy $SiteHosts
Write-Ok "访问地址：$SiteHosts"

# ---------------- 3. 复制程序 ----------------
Write-Step '3/9 复制程序文件'
$hadServices = [bool](Get-Service -Name $SvcApp -ErrorAction SilentlyContinue)
if ($hadServices) { Stop-AppServices }
if ($Source.TrimEnd('\') -ne $AppDir.TrimEnd('\')) { Copy-Source $Source }
Write-Ok "程序在 $AppDir"

# ---------------- 4. 数据库与配置 ----------------
Write-Step '4/9 数据库与配置文件'
$envCfg = Read-EnvFile $EnvFile
if ($envCfg.ContainsKey('DATABASE_URL')) {
    Write-Ok '已有配置文件 backend\.env，保留不动'
} else {
    $sec = Read-Host '    请输入安装 PostgreSQL 时设置的 postgres 密码' -AsSecureString
    $env:PGPASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
    $psql = Join-Path $pgBin 'psql.exe'
    function Invoke-Pg([string]$Sql) {
        $ErrorActionPreference = 'Continue'
        $out = & $psql -h 127.0.0.1 -U postgres -d postgres -v ON_ERROR_STOP=1 -tAc $Sql
        if ($LASTEXITCODE -ne 0) { throw "数据库操作失败：$Sql（postgres 密码对吗？）" }
        return "$out".Trim()
    }
    $dbPass = New-RandomString 32
    if (Invoke-Pg "SELECT 1 FROM pg_roles WHERE rolname='workrecord'") {
        Invoke-Pg "ALTER ROLE workrecord WITH LOGIN PASSWORD '$dbPass'" | Out-Null
    } else {
        Invoke-Pg "CREATE ROLE workrecord WITH LOGIN PASSWORD '$dbPass'" | Out-Null
    }
    if (-not (Invoke-Pg "SELECT 1 FROM pg_database WHERE datname='workrecord'")) {
        Invoke-Pg "CREATE DATABASE workrecord OWNER workrecord ENCODING 'UTF8' TEMPLATE template0" | Out-Null
    }
    Remove-Item Env:\PGPASSWORD
    Write-Ok '数据库 workrecord 已就绪（专用账号 workrecord，密码随机生成并写进配置文件）'

    do {
        $a1 = Read-Host '    设置系统管理员 admin 的登录密码（至少 8 位）' -AsSecureString
        $adminPass = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($a1))
    } while ($adminPass.Length -lt 8)
    $dsKey = Read-Host '    DeepSeek API Key（可以先直接回车，之后在网页「系统设置」里填）'

    $envText = @"
# 工作记录系统配置（install.ps1 生成）。SECRET_KEY 定好后不要改。
DATABASE_URL=postgresql+psycopg://workrecord:$dbPass@127.0.0.1:5432/workrecord
SECRET_KEY=$(New-RandomString 48)
APP_TIMEZONE=Europe/Belgrade
ACCESS_TOKEN_HOURS=12
ADMIN_USERNAME=admin
ADMIN_PASSWORD=$adminPass
DEEPSEEK_API_KEY=$($dsKey.Trim())
UPLOAD_DIR=$($DataDir.Replace('\', '/'))/uploads
"@
    Write-Utf8NoBom $EnvFile $envText
    # 配置文件里有密码：只给管理员和 SYSTEM 读
    # 用 SID（*S-1-5-32-544 = Administrators 组，*S-1-5-18 = SYSTEM），不受 Windows 语言影响
    & icacls $EnvFile /inheritance:r /grant:r '*S-1-5-32-544:F' '*S-1-5-18:F' | Out-Null
    Write-Ok "配置文件：$EnvFile"
}
New-Item -ItemType Directory -Force -Path (Join-Path $DataDir 'uploads') | Out-Null

# ---------------- 5. 安装依赖并构建 ----------------
Write-Step '5/9 安装依赖、构建网页、初始化数据库'
Build-App $python $npm
Invoke-Migrate

# ---------------- 6. 下载 Caddy 和服务程序 ----------------
Write-Step '6/9 下载 Caddy（HTTPS）和 WinSW（Windows 服务）'
$caddyExe = Join-Path $ToolsDir 'caddy.exe'
if (-not (Test-Path $caddyExe)) { Install-Caddy $caddyExe }
foreach ($n in @($SvcApp, $SvcCaddy)) {
    $w = Join-Path $ToolsDir "$n.exe"
    if (-not (Test-Path $w)) {
        Write-Ok "下载 WinSW → $n.exe"
        Invoke-WebRequest -UseBasicParsing -Uri $WinSWUrl -OutFile $w
    }
}
Write-Ok (& $caddyExe version)

# ---------------- 7. 注册 Windows 服务 ----------------
Write-Step '7/9 注册 Windows 服务（开机自动启动、崩溃自动重启）'
$fwd = { param($p) $p.Replace('\', '/') }
$appXml = @"
<service>
  <id>$SvcApp</id>
  <name>WorkRecord App</name>
  <description>工作记录系统（交接班 / 工作安排）后台程序</description>
  <executable>$VenvPy</executable>
  <arguments>-m uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips 127.0.0.1</arguments>
  <workingdirectory>$Backend</workingdirectory>
  <startmode>Automatic</startmode>
  <depend>$pgSvc</depend>
  <onfailure action="restart" delay="10 sec"/>
  <onfailure action="restart" delay="30 sec"/>
  <resetfailure>1 hour</resetfailure>
  <stoptimeout>15 sec</stoptimeout>
  <env name="PYTHONIOENCODING" value="utf-8"/>
  <env name="PYTHONUTF8" value="1"/>
  <logpath>$LogDir</logpath>
  <log mode="roll-by-size"><sizeThreshold>10240</sizeThreshold><keepFiles>8</keepFiles></log>
</service>
"@
$caddyData = Join-Path $DataDir 'caddy'
$caddyXml = @"
<service>
  <id>$SvcCaddy</id>
  <name>WorkRecord HTTPS (Caddy)</name>
  <description>工作记录系统 HTTPS 入口（80/443 端口）</description>
  <executable>$caddyExe</executable>
  <arguments>run --config "$(& $fwd (Join-Path $AppDir 'deploy\Caddyfile'))" --adapter caddyfile</arguments>
  <workingdirectory>$ToolsDir</workingdirectory>
  <startmode>Automatic</startmode>
  <depend>$SvcApp</depend>
  <onfailure action="restart" delay="10 sec"/>
  <resetfailure>1 hour</resetfailure>
  <env name="SITE_HOSTS" value="$SiteHosts"/>
  <env name="APP_UPSTREAM" value="127.0.0.1:8000"/>
  <env name="XDG_DATA_HOME" value="$(& $fwd $caddyData)"/>
  <env name="XDG_CONFIG_HOME" value="$(& $fwd (Join-Path $DataDir 'caddy-config'))"/>
  <env name="CA_DIR" value="$(& $fwd (Join-Path $caddyData 'caddy\pki\authorities\local'))"/>
  <env name="INSTALL_DIR" value="$(& $fwd (Join-Path $AppDir 'deploy\install'))"/>
  <logpath>$LogDir</logpath>
  <log mode="roll-by-size"><sizeThreshold>10240</sizeThreshold><keepFiles>4</keepFiles></log>
</service>
"@
foreach ($pair in @(@($SvcApp, $appXml), @($SvcCaddy, $caddyXml))) {
    $name = $pair[0]
    if (Get-Service -Name $name -ErrorAction SilentlyContinue) {
        Stop-AppServices
        Invoke-WinSW $name 'uninstall'
        Start-Sleep -Seconds 2
    }
    Write-Utf8NoBom (Join-Path $ToolsDir "$name.xml") $pair[1]
    Invoke-Native (Join-Path $ToolsDir "$name.exe") @('install') "注册服务 $name"
}
Start-AppServices
Wait-Health

# ---------------- 8. 防火墙、休眠 ----------------
Write-Step '8/9 防火墙与电源设置'
Get-NetFirewallRule -DisplayName 'WorkRecord HTTP/HTTPS' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName 'WorkRecord HTTP/HTTPS' -Direction Inbound -Protocol TCP -LocalPort 80, 443 -Action Allow -Profile Any | Out-Null
Write-Ok '已放行 80、443 端口（入站）'
& powercfg /change standby-timeout-ac 0 | Out-Null
& powercfg /change hibernate-timeout-ac 0 | Out-Null
$global:LASTEXITCODE = 0
Write-Ok '已关闭接通电源时的自动睡眠和休眠（服务器不能睡）'

# ---------------- 9. 每日备份 ----------------
Write-Step '9/9 每日自动备份'
if (-not $BackupTarget -and (Test-Path $BackupCfg)) { $BackupTarget = (Get-Content $BackupCfg -Raw).Trim() }
if (-not $BackupTarget) {
    $ans = Read-Host "    备份放哪里？建议另一块硬盘或共享盘，例如 D:\WorkRecordBackup。直接回车 = $Root\backups"
    $BackupTarget = if ($ans.Trim()) { $ans.Trim() } else { Join-Path $Root 'backups' }
}
Write-Utf8NoBom $BackupCfg $BackupTarget
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $AppDir 'deploy\windows\backup.ps1')`""
$trigger = New-ScheduledTaskTrigger -Daily -At '03:40'
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName $TaskBackup -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Write-Ok "每天 03:40 备份到 $BackupTarget（数据库、图片、证书、配置），数据库备份保留 30 天"
Register-Watchdog
Write-Ok '看门狗：每 5 分钟检查一次，服务停了会自动重启并弹窗提醒；备份失败、磁盘快满也会弹窗（记录在 Windows 事件日志和 logs\watchdog.log）'

# ---------------- 完成 ----------------
$first = ($SiteHosts -split ',')[0].Trim()
Write-Host ''
Write-Host '安装完成！' -ForegroundColor Green
Write-Host "  手机 / 电脑先打开   http://$first/install   安装证书（只需一次）"
Write-Host "  然后访问           https://$first"
Write-Host '  管理员账号         admin（密码是刚才设置的）'
Write-Host "  日志               $LogDir"
Write-Host "  图片和证书         $DataDir"
Write-Host ''
Write-Note '请马上登录，把各班长账号的初始密码改掉（初始密码 = 用户名）。'
