# 工作记录系统 · 看门狗：每 5 分钟检查一次（计划任务 WorkRecordWatchdog，以 SYSTEM 运行）
#  - 服务停了（PostgreSQL 数据库 / WorkRecordApp / WorkRecordCaddy）：先尝试启动，再报警；启动不了时在报警里写出
#    查到的可能原因（程序文件不见了、端口被占、配置文件缺失、依赖的服务没起来、日志里最后的错误……），见「找原因」
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
        if ($body.Length -gt 450) { $body = $body.Substring(0, 450) + "…（完整内容见 $LogFile）" }
        & $msg '*' '/TIME:3600' $body 2>&1 | Out-Null
    }
}

# ---------------- 找原因 ----------------
# 服务起不来时，把能自动查到的可能原因写进报警，省得一个个去翻日志。每条原因尽量写清楚「怎么办」。

function Limit-Text([string]$Text, [int]$Max) {
    $t = ($Text -replace '\s+', ' ').Trim()
    if ($t.Length -gt $Max) { $t = $t.Substring(0, $Max) + '…' }
    return $t
}

# 服务注册表里的启动命令（ImagePath）
function Get-ServiceImage([string]$Name) {
    try {
        return [string](Get-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Services\$Name" -ErrorAction Stop).ImagePath
    } catch { return '' }
}

# 启动命令里的 exe 路径
function Get-ServiceExe([string]$Name) {
    $img = Get-ServiceImage $Name
    if ($img -match '^\s*"([^"]+)"') { return $Matches[1] }
    if ($img -match '^\s*(\S+\.exe)') { return $Matches[1] }
    return $null
}

# Windows 服务管理器最近 15 分钟记下的这个服务的错误（例如「系统找不到指定的文件」「拒绝访问」）
function Get-ScmError([string]$Name) {
    $svc = Get-Service -Name $Name -ErrorAction SilentlyContinue
    if (-not $svc) { return $null }
    $disp = $svc.DisplayName
    $evs = @(Get-WinEvent -FilterHashtable @{ LogName = 'System'; ProviderName = 'Service Control Manager'; Id = 7000, 7009, 7023, 7024, 7031, 7034; StartTime = (Get-Date).AddMinutes(-15) } -MaxEvents 50 -ErrorAction SilentlyContinue)
    foreach ($e in $evs) {
        if ($e.Message -like "*$disp*") { return 'Windows 记录的错误：' + (Limit-Text $e.Message 160) }
    }
    return $null
}

# 日志文件最近 $Minutes 分钟内写过的话，取最后一条像错误的行
function Get-LastErrorLine([string]$File, [int]$Minutes, [string]$Pattern) {
    if (-not (Test-Path $File)) { return $null }
    $f = Get-Item $File
    if (((Get-Date) - $f.LastWriteTime).TotalMinutes -gt $Minutes) { return $null }
    $lines = @(Get-Content -Path $File -Tail 80 -ErrorAction SilentlyContinue)
    for ($i = $lines.Count - 1; $i -ge 0; $i--) {
        if ($lines[$i] -match $Pattern) { return Limit-Text $lines[$i] 180 }
    }
    return $null
}

# 在这个端口上监听的程序（没有就是空字符串）
function Get-PortOwner([int]$Port) {
    $names = @()
    foreach ($c in @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)) {
        $pr = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
        if ($pr) { $names += "$($pr.ProcessName)（$($pr.Id)）" }
    }
    return (@($names | Select-Object -Unique) -join '、')
}

# 路径所在的盘剩不到 1 GB
function Get-DiskFullHint([string]$Path) {
    if ($Path -notmatch '^([A-Za-z]):') { return $null }
    $drive = Get-PSDrive -Name $Matches[1] -ErrorAction SilentlyContinue
    if ($drive -and ($drive.Free + $drive.Used) -gt 0 -and $drive.Free -lt 1GB) {
        return "磁盘 $($drive.Name): 满了（只剩 $([math]::Round($drive.Free / 1MB)) MB），程序写不了文件，先清理磁盘"
    }
    return $null
}

# 程序服务依赖的 PostgreSQL 服务名（安装时写进了依赖关系）；没有就按名字找。
# 读注册表而不是 Get-Service 的 ServicesDependedOn：PostgreSQL 服务被卸载后后者会出错，注册表里的名字还在
function Get-DbServiceName {
    try {
        $deps = @((Get-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Services\$SvcApp" -ErrorAction Stop).DependOnService)
        foreach ($d in $deps) { if ([string]$d -like 'postgresql*') { return [string]$d } }
    } catch { }
    return Get-PgServiceName
}

function Get-DbCause([string]$Name) {
    $c = @()
    $exe = Get-ServiceExe $Name
    $img = Get-ServiceImage $Name
    $data = $null
    if ($img -match '-D\s+"([^"]+)"') { $data = $Matches[1] } elseif ($img -match '-D\s+(\S+)') { $data = $Matches[1] }
    if ($data -and -not (Test-Path (Join-Path $data 'PG_VERSION'))) {
        $c += "数据目录 $data 不见了或不完整。不要重装覆盖，先联系技术负责人，用备份恢复（部署指南「10.3 恢复数据」）"
    }
    if ($exe -and -not (Test-Path $exe)) {
        $c += "PostgreSQL 程序文件不见了（$exe），可能被卸载、删除或被杀毒软件隔离。数据目录不要动，重装同一个大版本的 PostgreSQL，安装目录和数据目录都选原来的"
    } elseif ($exe) {
        $bin = Split-Path $exe -Parent
        $miss = @(@('postgres.exe', 'libpq.dll') | Where-Object { -not (Test-Path (Join-Path $bin $_)) })
        if ($miss.Count -gt 0) {
            $c += "PostgreSQL 程序目录不完整（缺 $($miss -join '、')），重装同一个大版本的 PostgreSQL，安装目录和数据目录都选原来的"
        }
    }
    $own = Get-PortOwner 5432
    if ($own -and $own -notmatch 'postgres') { $c += "5432 端口被 $own 占用（另一个数据库？），先关掉它" }
    if ($data) {
        $h = Get-DiskFullHint $data
        if ($h) { $c += $h }
        $log = Get-ChildItem -Path (Join-Path $data 'log') -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime | Select-Object -Last 1
        if ($log) {
            # PostgreSQL 的日志是系统默认编码（中文 Windows = GBK），Get-Content 不指定编码正好按它读
            $l = Get-LastErrorLine $log.FullName 30 'FATAL|PANIC|致命错误|严重错误'
            if ($l) { $c += "数据库日志：$l" }
        }
    }
    $e = Get-ScmError $Name
    if ($e) { $c += $e }
    return $c
}

function Get-AppCause {
    $c = @()
    $db = Get-DbServiceName
    if ($db) {
        $s = Get-Service -Name $db -ErrorAction SilentlyContinue
        if (-not $s) { $c += "依赖的数据库服务 $db 不存在了（PostgreSQL 被卸载了？）" }
        elseif ($s.Status -ne 'Running') { $c += "依赖的数据库服务 $db 没在运行（见数据库那条报警）" }
    }
    $xml = Join-Path $ToolsDir "$SvcApp.xml"
    if (Test-Path $xml) {
        $x = Get-Content -Path $xml -Raw -Encoding UTF8
        if ($x -match '<executable>\s*([^<]+?)\s*</executable>') {
            $py = $Matches[1]
            if (-not (Test-Path $py)) { $c += "找不到 Python（$py），可能被卸载或升级了。装回 Python 后运行 update.ps1" }
        }
    } else { $c += "服务配置 $xml 不见了，运行 update.ps1" }
    if (-not (Test-Path $RunServer)) { $c += '程序文件不完整（缺 run_server.py），运行 update.ps1 -Online 重新下载' }
    if (-not (Test-Path (Join-Path $Backend '.venv\pyvenv.cfg'))) { $c += 'Python 虚拟环境 .venv 不见了，运行 update.ps1' }
    if (-not (Test-Path $EnvFile)) { $c += "配置文件 $EnvFile 不见了，从备份目录的 config 里复制回来" }
    $own = Get-PortOwner 8000
    if ($own -and $own -notmatch 'python') { $c += "8000 端口被 $own 占用，不是本系统的程序，先关掉它" }
    $h = Get-DiskFullHint $Backend
    if ($h) { $c += $h }
    $l = Get-LastErrorLine (Join-Path $LogDir "$SvcApp.err.log") 30 '(Error|Exception)\b|Traceback|ERROR|10048'
    if ($l) { $c += "程序日志最后的错误：$l" }
    $e = Get-ScmError $SvcApp
    if ($e) { $c += $e }
    return $c
}

function Get-CaddyCause {
    $c = @()
    $app = Get-Service -Name $SvcApp -ErrorAction SilentlyContinue
    if ($app -and $app.Status -ne 'Running') { $c += "依赖的程序服务 $SvcApp 没在运行（见上一条）" }
    if (-not (Test-Path (Join-Path $ToolsDir 'caddy.exe'))) { $c += "$ToolsDir\caddy.exe 不见了（被杀毒软件隔离了？），运行 update.ps1" }
    if (-not (Test-Path (Join-Path $AppDir 'deploy\Caddyfile'))) { $c += 'deploy\Caddyfile 不见了，运行 update.ps1 -Online' }
    foreach ($port in @(80, 443)) {
        $own = Get-PortOwner $port
        if ($own -and $own -notmatch 'caddy') { $c += "$port 端口被 $own 占用（常见：IIS、别的网页服务器），先关掉它" }
    }
    $l = Get-LastErrorLine (Join-Path $LogDir "$SvcCaddy.err.log") 30 '"level":"(error|fatal)"|Error:'
    if ($l) {
        if ($l -match '"msg":"([^"]*)"') {
            $m = $Matches[1]
            if ($l -match '"error":"([^"]*)"') { $m = $m + '：' + $Matches[1] }
            $l = $m
        }
        $c += "Caddy 日志最后的错误：$(Limit-Text $l 180)"
    }
    $e = Get-ScmError $SvcCaddy
    if ($e) { $c += $e }
    return $c
}

# 启动服务；启动不了时返回 Windows 当场给的错误（最里面那层，例如「服务已被禁用」），成功返回空。
# 注意：服务被禁用时 Windows 直接拒绝，不会写事件日志，所以 Get-ScmError 查不到，只能靠这里
function Start-Svc([string]$Name) {
    try {
        Start-Service -Name $Name -ErrorAction Stop
        Start-Sleep -Seconds 10
        return $null
    } catch {
        $ex = $_.Exception
        $msg = $ex.Message
        while ($ex.InnerException) { $ex = $ex.InnerException; $msg = $ex.Message }
        return Limit-Text $msg 160
    }
}

# 服务被设成「禁用」
function Get-DisabledHint([string]$Name) {
    $svc = Get-Service -Name $Name -ErrorAction SilentlyContinue
    if ($svc -and [string]$svc.StartType -eq 'Disabled') {
        return "服务 $Name 被设成了「禁用」：在「服务」里双击它，启动类型改回「自动」，再点「启动」"
    }
    return $null
}

# 第一条：被禁用；中间：查到的原因；最后：启动时 Windows 返回的错误（被禁用时就不重复了）
function Join-Causes([string]$Name, $Found, [string]$StartErr) {
    $c = @()
    $d = Get-DisabledHint $Name
    if ($d) { $c += $d }
    $c += @($Found)
    if ($StartErr -and -not $d) { $c += "启动时 Windows 返回的错误：$StartErr" }
    return $c
}

# 原因列表 → 「可能原因：1) …；2) …」
function Format-Causes($Causes, [string]$LogHint) {
    $list = @($Causes | Where-Object { $_ })
    if ($list.Count -eq 0) { return "没查到明显原因，请看日志 $LogHint" }
    $parts = @()
    for ($i = 0; $i -lt $list.Count; $i++) { $parts += "$($i + 1)) $($list[$i])" }
    return '可能原因：' + ($parts -join '；')
}

# ---------------- 检查 ----------------
$problems = [ordered]@{}   # 问题 → 说明

# 数据库：程序服务依赖它，它起不来程序和 Caddy 都起不来（2026-11-27 PostgreSQL 被卸载了一半，以前的报警只说程序服务停了）
$dbSvcName = Get-DbServiceName
if ($dbSvcName) {
    $dbSvc = Get-Service -Name $dbSvcName -ErrorAction SilentlyContinue
    if (-not $dbSvc) {
        $problems["svc:$dbSvcName"] = "数据库服务 $dbSvcName 不存在了（PostgreSQL 被卸载了？）。数据目录不要动，重装同一个大版本的 PostgreSQL，数据目录选原来的"
    } elseif ($dbSvc.Status -ne 'Running') {
        $startErr = Start-Svc $dbSvcName
        $dbSvc = Get-Service -Name $dbSvcName -ErrorAction SilentlyContinue
        if ($dbSvc -and $dbSvc.Status -eq 'Running') {
            Send-Alert "数据库服务 $dbSvcName 停了，已自动重新启动" $true
        } else {
            $problems["svc:$dbSvcName"] = "数据库服务 $dbSvcName 停了，自动启动失败。$(Format-Causes (Join-Causes $dbSvcName (Get-DbCause $dbSvcName) $startErr) 'PostgreSQL 数据目录下的 log 文件夹')"
        }
    }
}

foreach ($name in @($SvcApp, $SvcCaddy)) {
    $svc = Get-Service -Name $name -ErrorAction SilentlyContinue
    if (-not $svc) { continue }   # 没装这个服务（例如还没运行 install.ps1）
    if ($svc.Status -ne 'Running') {
        # 停之前日志里的错误（启动前先记下来，启动后日志会被新内容盖过）
        if ($name -eq $SvcApp) {
            $why = Get-LastErrorLine (Join-Path $LogDir "$SvcApp.err.log") 15 '(Error|Exception)\b|Traceback|ERROR|10048'
            Stop-StaleApp   # 残留进程占着 8000 端口时，不先结束它就启动不了
        } else {
            $why = Get-LastErrorLine (Join-Path $LogDir "$SvcCaddy.err.log") 15 '"level":"(error|fatal)"|Error:'
        }
        $startErr = Start-Svc $name
        $svc = Get-Service -Name $name -ErrorAction SilentlyContinue
        if ($svc -and $svc.Status -eq 'Running') {
            $tail = ''
            if ($why) { $tail = "停之前日志里的错误：$why。" }
            Send-Alert "服务 $name 停了，已自动重新启动。$($tail)日志 $LogDir\$name.err.log" $true
        } else {
            if ($name -eq $SvcApp) { $found = Get-AppCause } else { $found = Get-CaddyCause }
            $causes = Join-Causes $name $found $startErr
            $problems["svc:$name"] = "服务 $name 停了，自动启动失败。$(Format-Causes $causes "$LogDir\$name.err.log")"
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
    if (-not $okHealth) {
        $causes = @()
        if ($dbSvcName) {
            $s = Get-Service -Name $dbSvcName -ErrorAction SilentlyContinue
            if (-not $s -or $s.Status -ne 'Running') { $causes += "数据库服务 $dbSvcName 没在运行" }
        }
        $l = Get-LastErrorLine (Join-Path $LogDir "$SvcApp.err.log") 30 '(Error|Exception)\b|Traceback|ERROR'
        if ($l) { $causes += "程序日志最后的错误：$l" }
        $problems['health'] = "服务 $SvcApp 在运行，但系统没有响应，可以先在「服务」里重启它。$(Format-Causes $causes "$LogDir\$SvcApp.err.log")"
    }
}

$statusFile = Join-Path $DataDir 'backup-status.json'
if (Test-Path $statusFile) {
    try {
        $st = Get-Content -Path $statusFile -Raw -Encoding UTF8 | ConvertFrom-Json
        if (-not $st.ok) {
            $m = ([string]$st.message) -replace '。请看上面的输出。?$', ''
            $m = $m.TrimEnd('。', ' ')
            $causes = @()
            if ($dbSvcName) {
                $s = Get-Service -Name $dbSvcName -ErrorAction SilentlyContinue
                if (-not $s -or $s.Status -ne 'Running') { $causes += "数据库服务 $dbSvcName 没在运行（见数据库那条报警）" }
            }
            if ($m -match '退出码 (-?\d+)') {
                $hint = Get-ExitCodeHint ([long]($Matches[1]))
                if ($hint -and $m -notlike "*$hint*") { $causes += $hint }
            }
            $pgBin = Find-PgBin
            if (-not $pgBin) { $causes += '找不到 PostgreSQL 的程序目录（被卸载了？）' }
            elseif (-not (Test-Path (Join-Path $pgBin 'libpq.dll'))) { $causes += "PostgreSQL 程序目录不完整（$pgBin 里缺 libpq.dll），重装同一个大版本的 PostgreSQL" }
            $problems['backup_failed'] = "备份失败（$($st.at)）：$m。$(Format-Causes $causes "$LogDir\backup.log")"
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
