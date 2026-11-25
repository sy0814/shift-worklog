# 工作记录系统 · 看门狗：每 5 分钟检查一次（计划任务 WorkRecordWatchdog，以 SYSTEM 运行）
#  - 服务停了（WorkRecordApp / WorkRecordCaddy）：先尝试启动，再报警
#  - 系统没有响应（服务在跑但 http://127.0.0.1:8000/api/health 不通）
#  - 备份失败、超过 26 小时没有成功的备份
#  - 磁盘快满（剩余少于 5 GB 或 10%）：程序数据所在的盘、备份所在的盘
# 报警方式：服务器上弹窗（msg.exe，发给所有登录的人）+ Windows 事件日志（应用程序，来源 WorkRecord）+ logs\watchdog.log。
# 同一个问题 60 分钟内只弹一次；问题消失时再提示一次「已恢复」。
# 阈值和 backend/app/alerts.py 保持一致。兼容 Windows PowerShell 5.1，本文件必须 UTF-8 带 BOM。

. (Join-Path $PSScriptRoot 'common.ps1')
$ErrorActionPreference = 'Continue'

$DiskMinGB = 5
$DiskMinPct = 10
$BackupMaxAgeH = 26
$RepeatMinutes = 60
$StateFile = Join-Path $DataDir 'watchdog-state.json'
$LogFile = Join-Path $LogDir 'watchdog.log'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-WatchLog([string]$Msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $Msg"
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

# 上次报过哪些问题、什么时候报的：{ 问题: 'yyyy-MM-dd HH:mm:ss' }
function Read-State {
    $h = @{}
    if (Test-Path $StateFile) {
        try {
            $o = Get-Content -Path $StateFile -Raw -Encoding UTF8 | ConvertFrom-Json
            foreach ($p in $o.PSObject.Properties) { $h[$p.Name] = [string]$p.Value }
        } catch { }
    }
    return $h
}

function Send-Alert([string]$Text, [bool]$IsError) {
    Write-WatchLog $Text
    try {
        if (-not [Diagnostics.EventLog]::SourceExists('WorkRecord')) { New-EventLog -LogName Application -Source 'WorkRecord' }
        $type = 'Information'
        if ($IsError) { $type = 'Error' }
        Write-EventLog -LogName Application -Source 'WorkRecord' -EventId 1001 -EntryType $type -Message $Text
    } catch { Write-WatchLog "写事件日志失败：$($_.Exception.Message)" }
    $msg = Join-Path $env:SystemRoot 'System32\msg.exe'
    if (Test-Path $msg) {
        # 消息里不要有双引号（PowerShell 5.1 传给外部程序时会弄丢）
        $body = '工作记录系统：' + ($Text -replace '"', '')
        & $msg '*' '/TIME:3600' $body 2>&1 | Out-Null
    }
}

# ---------------- 检查 ----------------
$problems = [ordered]@{}   # 问题 → 说明

foreach ($name in @($SvcApp, $SvcCaddy)) {
    $svc = Get-Service -Name $name -ErrorAction SilentlyContinue
    if (-not $svc) { continue }   # 没装这个服务（例如还没运行 install.ps1）
    if ($svc.Status -ne 'Running') {
        if ($name -eq $SvcApp) { Stop-StaleApp }   # 残留进程占着 8000 端口时，不先结束它就启动不了
        try { Start-Service -Name $name -ErrorAction Stop; Start-Sleep -Seconds 10 } catch { }
        $svc = Get-Service -Name $name -ErrorAction SilentlyContinue
        if ($svc -and $svc.Status -eq 'Running') {
            Send-Alert "服务 $name 停了，已自动重新启动。请查看日志 $LogDir\$name.err.log" $true
        } else {
            $problems["svc:$name"] = "服务 $name 停了，自动启动失败。请在「服务」里手动启动，并查看日志 $LogDir\$name.err.log"
        }
    }
}

# 8000 端口被不是本服务启动的 Python 占着（以前的版本停服务后会留下这种进程，服务就一直启动失败、日志报 10048）：
# 停服务、结束它、再启动。本服务启动的进程，往上两层之内能找到 WorkRecordApp.exe（WinSW）。
function Test-FromService([int]$ProcId) {
    $cur = $ProcId
    for ($i = 0; $i -lt 3; $i++) {
        $pr = Get-CimInstance Win32_Process -Filter "ProcessId=$cur" -ErrorAction SilentlyContinue
        if (-not $pr) { return $false }
        if ($pr.Name -eq "$SvcApp.exe") { return $true }
        $cur = [int]$pr.ParentProcessId
    }
    return $false
}
foreach ($c in @(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)) {
    $pr = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
    if (-not $pr -or $pr.ProcessName -notlike 'python*') { continue }
    if (Test-FromService $pr.Id) { continue }
    try { Stop-Service -Name $SvcApp -Force -ErrorAction Stop } catch { }
    Stop-StaleApp
    try { Start-Service -Name $SvcApp -ErrorAction Stop; Start-Sleep -Seconds 10 } catch { }
    Send-Alert "8000 端口被残留的旧进程占着（$($pr.ProcessName) $($pr.Id)），已结束它并重新启动服务 $SvcApp" $true
    break
}

$app = Get-Service -Name $SvcApp -ErrorAction SilentlyContinue
if ($app -and $app.Status -eq 'Running') {
    $okHealth = $false
    for ($i = 0; $i -lt 3 -and -not $okHealth; $i++) {
        try {
            $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 10 -Uri 'http://127.0.0.1:8000/api/health'
            if ($r.StatusCode -eq 200) { $okHealth = $true }
        } catch { Start-Sleep -Seconds 5 }
    }
    if (-not $okHealth) { $problems['health'] = "服务 $SvcApp 在运行，但系统没有响应。请查看日志 $LogDir\$SvcApp.err.log，必要时重启这个服务" }
}

$statusFile = Join-Path $DataDir 'backup-status.json'
if (Test-Path $statusFile) {
    try {
        $st = Get-Content -Path $statusFile -Raw -Encoding UTF8 | ConvertFrom-Json
        if (-not $st.ok) {
            $problems['backup_failed'] = "备份失败（$($st.at)）：$($st.message)。请查看 $LogDir\backup.log"
        } else {
            $at = [datetime]::ParseExact([string]$st.at, 'yyyy-MM-dd HH:mm', [Globalization.CultureInfo]::InvariantCulture)
            if (((Get-Date) - $at).TotalHours -gt $BackupMaxAgeH) {
                $problems['backup_old'] = "超过 $BackupMaxAgeH 小时没有成功的备份（最后一次 $($st.at)）。请检查计划任务 $TaskBackup"
            }
        }
    } catch { $problems['backup_status'] = "读不了备份结果文件 $statusFile" }
}

$dirs = @($DataDir)
if (Test-Path $BackupCfg) {
    $bt = (Get-Content -Path $BackupCfg -Raw -Encoding UTF8).Trim()
    if ($bt) { $dirs += $bt }
}
$seen = @{}
foreach ($d in $dirs) {
    if ($d -notmatch '^([A-Za-z]):') { continue }   # 网络共享路径不检查
    $letter = $Matches[1].ToUpper()
    if ($seen.ContainsKey($letter)) { continue }
    $seen[$letter] = $true
    $drive = Get-PSDrive -Name $letter -ErrorAction SilentlyContinue
    if (-not $drive -or ($drive.Free + $drive.Used) -le 0) { continue }
    $freeGb = [math]::Round($drive.Free / 1GB, 1)
    $pct = [math]::Round($drive.Free * 100 / ($drive.Free + $drive.Used), 1)
    if ($freeGb -lt $DiskMinGB -or $pct -lt $DiskMinPct) {
        $problems["disk:$letter"] = "磁盘 ${letter}: 快满了，只剩 $freeGb GB（$pct%）。请清理或把备份 / 原图归档挪到别的盘"
    }
}

# ---------------- 报警 ----------------
$state = Read-State
$now = Get-Date
$newState = @{}
foreach ($k in $problems.Keys) {
    $last = $null
    if ($state.ContainsKey($k)) {
        try { $last = [datetime]::ParseExact($state[$k], 'yyyy-MM-dd HH:mm:ss', [Globalization.CultureInfo]::InvariantCulture) } catch { }
    }
    if (-not $last -or ($now - $last).TotalMinutes -ge $RepeatMinutes) {
        Send-Alert $problems[$k] $true
        $newState[$k] = $now.ToString('yyyy-MM-dd HH:mm:ss')
    } else {
        $newState[$k] = $state[$k]
    }
}
foreach ($k in $state.Keys) {
    if (-not $problems.Contains($k)) { Send-Alert "已恢复：$k" $false }
}
Write-Utf8NoBom $StateFile ($newState | ConvertTo-Json)
