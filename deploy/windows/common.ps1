# 工作记录系统 · Windows 部署公共函数（被 install / update / backup / uninstall 引用）
# 兼容 Windows PowerShell 5.1。本文件必须保存为 UTF-8 带 BOM，否则中文会乱码。

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

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

$CaddyUrl = 'https://caddyserver.com/api/download?os=windows&arch=amd64'
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
function Invoke-Native {
    param([Parameter(Mandatory)][string]$File, [string[]]$Arguments = @(), [Parameter(Mandatory)][string]$What)
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
    foreach ($c in $cands) {
        $v = & $c -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>$null
        if ($LASTEXITCODE -eq 0 -and $v) {
            $parts = $v.Trim().Split('.')
            if ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 11) { return $c }
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
        $cur = & $VenvPy -m alembic current 2>$null
        Write-Ok "数据库版本：$("$cur".Trim())"
    } finally { Pop-Location }
}

# ---------------- 服务 ----------------
function Invoke-WinSW([string]$Name, [string]$Command) {
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
