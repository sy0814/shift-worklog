# 工作记录系统 · Windows 部署公共函数（被 install / update / backup / uninstall 引用）
# 兼容 Windows PowerShell 5.1。本文件必须保存为 UTF-8 带 BOM，否则中文会乱码。

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
# 让本窗口里运行的所有 Python 程序都按 UTF-8 读写文件（中文 Windows 默认是 GBK，会读坏配置文件）
$env:PYTHONUTF8 = '1'

# ---------------- 路径 ----------------
$Root      = 'C:\WorkRecord'
if ($env:WORKRECORD_ROOT) { $Root = $env:WORKRECORD_ROOT }
$AppDir    = Join-Path $Root 'app'          # 程序（每次更新覆盖）
$DataDir   = Join-Path $Root 'data'         # 图片、HTTPS 证书（不会被更新覆盖）
$ToolsDir  = Join-Path $Root 'tools'        # caddy.exe、WinSW 服务包装程序
$LogDir    = Join-Path $Root 'logs'
$BackupCfg = Join-Path $DataDir 'backup-target.txt'
$Backend   = Join-Path $AppDir 'backend'
$Frontend  = Join-Path $AppDir 'frontend'
$VenvPy    = Join-Path $Backend '.venv\Scripts\python.exe'
$EnvFile   = Join-Path $Backend '.env'
$SvcApp    = 'WorkRecordApp'
$SvcCaddy  = 'WorkRecordCaddy'
$TaskBackup = 'WorkRecordBackup'
$TaskWatchdog = 'WorkRecordWatchdog'   # 看门狗：每 5 分钟检查服务、备份、磁盘（watchdog.ps1）

# Caddy：从官方 GitHub Releases 下载（caddyserver.com 的下载接口现在要登录，会返回 401）
$CaddyLatestApi = 'https://api.github.com/repos/caddyserver/caddy/releases/latest'
$CaddyFallbackVersion = '2.10.2'
$WinSWUrl = 'https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW-x64.exe'

# ---------------- 输出 ----------------
function Write-Step([string]$Msg) { Write-Host ''; Write-Host "==> $Msg" -ForegroundColor Cyan }
function Write-Ok([string]$Msg)   { Write-Host "    $Msg" -ForegroundColor Green }
function Write-Note([string]$Msg) { Write-Host "    $Msg" -ForegroundColor Yellow }

function Assert-Admin {
    $p = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw '请右键「以管理员身份运行」PowerShell 后再执行本脚本。'
    }
}

# 运行外部程序，失败就停下并说明是哪一步
# 注意 Windows PowerShell 5.1 的两个坑：
#  - 外部程序写到错误输出的内容，在 $ErrorActionPreference='Stop' 下可能被当成致命错误 → 这里局部改成 Continue，只看退出码
#  - 传给外部程序的参数里如果有双引号，会被悄悄去掉 → 参数里不要带双引号
function Invoke-Native {
    param([Parameter(Mandatory)][string]$File, [string[]]$Arguments = @(), [Parameter(Mandatory)][string]$What)
    $ErrorActionPreference = 'Continue'
    & $File @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$What 失败（退出码 $LASTEXITCODE）。请看上面的输出。" }
}

function Update-PathFromRegistry {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
}

function New-RandomString([int]$Length = 40) {
    $chars = 'abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789'.ToCharArray()
    $bytes = New-Object byte[] $Length
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes)
    -join ($bytes | ForEach-Object { $chars[$_ % $chars.Length] })
}

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    [IO.File]::WriteAllText($Path, $Text, (New-Object Text.UTF8Encoding $false))
}

# 读 backend\.env（KEY=VALUE）
function Read-EnvFile([string]$Path) {
    $h = @{}
    if (Test-Path $Path) {
        foreach ($line in [IO.File]::ReadAllLines($Path)) {
            if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') { $h[$Matches[1]] = $Matches[2].Trim() }
        }
    }
    return $h
}

# ---------------- 依赖查找 ----------------
function Find-Python {
    # 注意：Windows 自带的 python.exe「应用执行别名」会打开应用商店，要排除 WindowsApps
    $cands = @()
    $cands += Get-ChildItem 'C:\Program Files\Python31*\python.exe' -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | ForEach-Object { $_.FullName }
    $cands += Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python31*\python.exe" -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | ForEach-Object { $_.FullName }
    $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notmatch 'WindowsApps') { $cands += $cmd.Source }
    $ErrorActionPreference = 'Continue'  # 只在本函数内生效
    foreach ($c in $cands) {
        # 用 --version 判断版本（不能用 -c "代码"：PowerShell 5.1 会吞掉参数里的双引号）
        $v = (& $c --version 2>&1 | Out-String)
        if ($v -match 'Python (\d+)\.(\d+)') {
            if ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -ge 11) { return $c }
        }
    }
    return $null
}

function Find-Npm {
    $p = 'C:\Program Files\nodejs\npm.cmd'
    if (Test-Path $p) { return $p }
    $cmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

function Find-PgBin {
    $psql = Get-ChildItem 'C:\Program Files\PostgreSQL\*\bin\psql.exe' -ErrorAction SilentlyContinue |
        Sort-Object { [int]($_.Directory.Parent.Name -replace '\D', '') } -Descending | Select-Object -First 1
    if ($psql) { return $psql.DirectoryName }
    return $null
}

function Get-PgServiceName {
    $s = Get-Service -Name 'postgresql*' -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -First 1
    if ($s) { return $s.Name }
    return $null
}

# 下载 caddy.exe 到 tools 目录：先问 GitHub 最新版本，失败就用固定版本
function Install-Caddy([string]$Target) {
    $ver = $CaddyFallbackVersion
    try {
        $rel = Invoke-RestMethod -UseBasicParsing -Uri $CaddyLatestApi -Headers @{ 'User-Agent' = 'workrecord-installer' } -TimeoutSec 20
        if ($rel.tag_name) { $ver = $rel.tag_name.TrimStart('v') }
    } catch { Write-Note "查询 Caddy 最新版本失败，使用 $ver" }
    $url = "https://github.com/caddyserver/caddy/releases/download/v$ver/caddy_${ver}_windows_amd64.zip"
    $zip = Join-Path $env:TEMP "caddy_$ver.zip"
    $dir = Join-Path $env:TEMP "caddy_$ver"
    try {
        Write-Ok "下载 $url"
        Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $zip
        if (Test-Path $dir) { Remove-Item $dir -Recurse -Force }
        Expand-Archive -Path $zip -DestinationPath $dir -Force
        Copy-Item (Join-Path $dir 'caddy.exe') $Target -Force
    } catch {
        throw @"
下载 Caddy 失败：$($_.Exception.Message)
请手动下载后放到指定位置，再重新运行本脚本（脚本发现文件已存在就会跳过下载）：
  1. 浏览器打开 https://github.com/caddyserver/caddy/releases/latest
  2. 在 Assets 里下载 caddy_<版本号>_windows_amd64.zip（不要选 arm64）
  3. 解压，把里面的 caddy.exe 复制到 $Target
"@
    } finally {
        Remove-Item $zip, $dir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

# ---------------- 程序文件 ----------------
# 把源码复制到 C:\WorkRecord\app。/MIR 会删掉目标里多余的旧文件，但被排除的不会动：
# 虚拟环境 .venv、配置 .env、前端构建结果 static、node_modules、数据 data。
function Copy-Source([string]$Source) {
    if (-not (Test-Path (Join-Path $Source 'backend\app\main.py'))) { throw "源码目录不对：$Source（里面应该有 backend、frontend、deploy）" }
    New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
    & robocopy $Source $AppDir /MIR /XD .git node_modules .venv data static __pycache__ .pytest_cache /XF .env /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "复制程序文件失败（robocopy 退出码 $LASTEXITCODE）" }
    $global:LASTEXITCODE = 0
}

# 建 Python 虚拟环境、装依赖、构建前端
function Build-App([string]$Python, [string]$Npm) {
    if (-not (Test-Path $VenvPy)) {
        Write-Ok '创建 Python 虚拟环境'
        Invoke-Native $Python @('-m', 'venv', (Join-Path $Backend '.venv')) '创建虚拟环境'
    }
    Write-Ok '安装 Python 依赖（第一次要几分钟）'
    Invoke-Native $VenvPy @('-m', 'pip', 'install', '--upgrade', 'pip', '-q') '升级 pip'
    Invoke-Native $VenvPy @('-m', 'pip', 'install', '-r', (Join-Path $Backend 'requirements.txt'), '-q') '安装 Python 依赖'
    Write-Ok '构建网页（第一次要几分钟）'
    Push-Location $Frontend
    try {
        Invoke-Native $Npm @('ci', '--no-audit', '--no-fund', '--loglevel=error') '安装前端依赖（npm ci）'
        Invoke-Native $Npm @('run', 'build') '构建前端（npm run build）'
    } finally { Pop-Location }
    if (-not (Test-Path (Join-Path $Backend 'static\index.html'))) { throw '前端构建后没有找到 backend\static\index.html' }
}

# 数据库结构升级到最新版本（Alembic 迁移，数据保留）。单独执行，出错能直接在窗口里看到
function Invoke-Migrate {
    Write-Ok '升级数据库结构（已有数据保留）'
    Push-Location $Backend
    try {
        Invoke-Native $VenvPy @('-m', 'alembic', 'upgrade', 'head') '数据库升级'
        Write-Ok '数据库已是最新版本'
    } finally { Pop-Location }
}

# ---------------- 服务 ----------------
function Invoke-WinSW([string]$Name, [string]$Command) {
    $ErrorActionPreference = 'Continue'
    $exe = Join-Path $ToolsDir "$Name.exe"
    if (-not (Test-Path $exe)) { return }
    & $exe $Command | Out-Host
    $global:LASTEXITCODE = 0
}

function Stop-AppServices {
    foreach ($n in @($SvcCaddy, $SvcApp)) {
        $s = Get-Service -Name $n -ErrorAction SilentlyContinue
        if ($s -and $s.Status -ne 'Stopped') { Write-Ok "停止服务 $n"; Stop-Service -Name $n -Force }
    }
}

function Start-AppServices {
    foreach ($n in @($SvcApp, $SvcCaddy)) {
        $s = Get-Service -Name $n -ErrorAction SilentlyContinue
        if ($s) { Write-Ok "启动服务 $n"; Start-Service -Name $n }
    }
}

# 看门狗计划任务：每 5 分钟运行 watchdog.ps1（服务停了先尝试启动再报警；备份失败、磁盘快满也报警）
function Register-Watchdog {
    $wdScript = Join-Path $AppDir 'deploy\windows\watchdog.ps1'
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$wdScript`""
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Minutes 5)
    $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 4)
    Register-ScheduledTask -TaskName $TaskWatchdog -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
}

# 更新、卸载时先暂停看门狗，免得它把刚停下的服务又启动起来
function Disable-Watchdog {
    Disable-ScheduledTask -TaskName $TaskWatchdog -ErrorAction SilentlyContinue | Out-Null
}

function Wait-Health {
    Write-Ok '等待系统启动……'
    for ($i = 0; $i -lt 60; $i++) {
        try {
            $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 -Uri 'http://127.0.0.1:8000/api/health'
            if ($r.StatusCode -eq 200) { Write-Ok '系统已启动'; return }
        } catch { Start-Sleep -Seconds 2 }
    }
    throw "系统 60 秒内没有启动成功。请查看日志：$LogDir\$SvcApp.err.log"
}
