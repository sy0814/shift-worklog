# 工作记录系统 · 看门狗：每 5 分钟检查一次（计划任务 WorkRecordWatchdog，以 SYSTEM 运行）
#  - 服务停了（PostgreSQL 数据库 / WorkRecordApp / WorkRecordCaddy）：先尝试启动，再报警；启动不了时在报警里写出
#    查到的可能原因（程序文件不见了、端口被占、配置文件缺失、依赖的服务没起来、日志里最后的错误……），见「找原因」
#  - 系统没有响应（服务在跑但 http://127.0.0.1:8000/api/health 不通）
#  - 备份失败、超过 26 小时没有成功的备份
#  - 磁盘快满（剩余少于 5 GB 或 10%）：程序数据所在的盘、备份所在的盘
# 报警方式：服务器上弹窗（msg.exe，发给所有登录的人）+ Windows 事件日志（应用程序，来源 WorkRecord）+ logs\watchdog.log。
# 同一个问题 60 分钟内只弹一次；问题消失时再提示一次「已恢复」。
# 报警语言：网页「系统设置 → 存储与备份 → 服务器报警语言」，存在 data\watchdog-lang.txt（zh 默认 / sr / en）。
# 所有报警文字都用 T '中文' '塞语' '英语' 写，加新的也要三种都写。
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

# ---------------- 语言 ----------------
$AlertLang = 'zh'
$langFile = Join-Path $DataDir 'watchdog-lang.txt'   # 网页上设置的（backend/app/storage_service.py 写）
if (Test-Path $langFile) {
    $v = ([string](Get-Content -Path $langFile -Raw -Encoding UTF8)).Trim().ToLower()
    if ($v -eq 'sr' -or $v -eq 'en') { $AlertLang = $v }
}

# 按报警语言选一句
function T([string]$Zh, [string]$Sr, [string]$En) {
    if ($AlertLang -eq 'sr') { return $Sr }
    if ($AlertLang -eq 'en') { return $En }
    return $Zh
}

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
    } catch { Write-WatchLog ((T '写事件日志失败：' 'Upis u dnevnik događaja nije uspeo: ' 'Writing to the event log failed: ') + $_.Exception.Message) }
    $msg = Join-Path $env:SystemRoot 'System32\msg.exe'
    if (Test-Path $msg) {
        # 消息里不要有双引号（PowerShell 5.1 传给外部程序时会弄丢）
        $body = (T '工作记录系统：' 'Sistem evidencije rada: ' 'Work record system: ') + ($Text -replace '"', '')
        if ($body.Length -gt 450) {
            $body = $body.Substring(0, 450) + (T "…（完整内容见 $LogFile）" "… (ceo tekst u $LogFile)" "… (full text in $LogFile)")
        }
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

# Windows 服务管理器最近 15 分钟记下的这个服务的错误（例如「系统找不到指定的文件」「拒绝访问」）。
# 这段文字是 Windows 自己的语言，没法翻译
function Get-ScmError([string]$Name) {
    $svc = Get-Service -Name $Name -ErrorAction SilentlyContinue
    if (-not $svc) { return $null }
    $disp = $svc.DisplayName
    $evs = @(Get-WinEvent -FilterHashtable @{ LogName = 'System'; ProviderName = 'Service Control Manager'; Id = 7000, 7009, 7023, 7024, 7031, 7034; StartTime = (Get-Date).AddMinutes(-15) } -MaxEvents 50 -ErrorAction SilentlyContinue)
    foreach ($e in $evs) {
        if ($e.Message -like "*$disp*") { return (T 'Windows 记录的错误：' 'Greška koju je zabeležio Windows: ' 'Error recorded by Windows: ') + (Limit-Text $e.Message 160) }
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
        if ($pr) { $names += "$($pr.ProcessName) ($($pr.Id))" }
    }
    return (@($names | Select-Object -Unique) -join ', ')
}

# 路径所在的盘剩不到 1 GB
function Get-DiskFullHint([string]$Path) {
    if ($Path -notmatch '^([A-Za-z]):') { return $null }
    $drive = Get-PSDrive -Name $Matches[1] -ErrorAction SilentlyContinue
    if ($drive -and ($drive.Free + $drive.Used) -gt 0 -and $drive.Free -lt 1GB) {
        $mb = [math]::Round($drive.Free / 1MB)
        $dn = $drive.Name
        return T "磁盘 ${dn}: 满了（只剩 $mb MB），程序写不了文件，先清理磁盘" "Disk ${dn}: je pun (ostalo samo $mb MB), program ne može da piše fajlove; prvo oslobodite prostor" "Disk ${dn}: is full (only $mb MB left), programs cannot write files; free up space first"
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

$ReinstallPg = T '数据目录不要动，重装同一个大版本的 PostgreSQL，安装目录和数据目录都选原来的' 'Ne dirajte direktorijum sa podacima; ponovo instalirajte PostgreSQL iste glavne verzije, sa istim instalacionim direktorijumom i direktorijumom podataka' 'Do not touch the data directory; reinstall PostgreSQL of the same major version, choosing the original installation and data directories'

function Get-DbCause([string]$Name) {
    $c = @()
    $exe = Get-ServiceExe $Name
    $img = Get-ServiceImage $Name
    $data = $null
    if ($img -match '-D\s+"([^"]+)"') { $data = $Matches[1] } elseif ($img -match '-D\s+(\S+)') { $data = $Matches[1] }
    if ($data -and -not (Test-Path (Join-Path $data 'PG_VERSION'))) {
        $c += T "数据目录 $data 不见了或不完整。不要重装覆盖，先联系技术负责人，用备份恢复（部署指南「10.3 恢复数据」）" "Direktorijum sa podacima $data ne postoji ili je nepotpun. Ne instalirajte preko njega; javite se tehnički odgovornoj osobi i vratite podatke iz rezervne kopije (uputstvo, 10.3)" "The data directory $data is missing or incomplete. Do not reinstall over it; contact the technical lead and restore from a backup (deployment guide, 10.3)"
    }
    if ($exe -and -not (Test-Path $exe)) {
        $c += (T "PostgreSQL 程序文件不见了（$exe），可能被卸载、删除或被杀毒软件隔离。" "Nedostaju programske datoteke PostgreSQL-a ($exe): možda su deinstalirane, obrisane ili ih je antivirus stavio u karantin. " "PostgreSQL program files are missing ($exe): uninstalled, deleted or quarantined by the antivirus. ") + $ReinstallPg
    } elseif ($exe) {
        $bin = Split-Path $exe -Parent
        $miss = @(@('postgres.exe', 'libpq.dll') | Where-Object { -not (Test-Path (Join-Path $bin $_)) })
        if ($miss.Count -gt 0) {
            $list = $miss -join ', '
            $c += (T "PostgreSQL 程序目录不完整（缺 $list）。" "Programski direktorijum PostgreSQL-a je nepotpun (nedostaje $list). " "The PostgreSQL program directory is incomplete (missing $list). ") + $ReinstallPg
        }
    }
    $own = Get-PortOwner 5432
    if ($own -and $own -notmatch 'postgres') {
        $c += T "5432 端口被 $own 占用（另一个数据库？），先关掉它" "Port 5432 zauzima $own (druga baza?), prvo ga zatvorite" "Port 5432 is taken by $own (another database?), close it first"
    }
    if ($data) {
        $h = Get-DiskFullHint $data
        if ($h) { $c += $h }
        $log = Get-ChildItem -Path (Join-Path $data 'log') -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime | Select-Object -Last 1
        if ($log) {
            # PostgreSQL 的日志是系统默认编码（中文 Windows = GBK），Get-Content 不指定编码正好按它读
            $l = Get-LastErrorLine $log.FullName 30 'FATAL|PANIC|致命错误|严重错误'
            if ($l) { $c += (T '数据库日志：' 'Log baze: ' 'Database log: ') + $l }
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
        if (-not $s) {
            $c += T "依赖的数据库服务 $db 不存在了（PostgreSQL 被卸载了？）" "Servis baze $db, od kog zavisi, više ne postoji (PostgreSQL deinstaliran?)" "The database service $db it depends on no longer exists (PostgreSQL uninstalled?)"
        } elseif ($s.Status -ne 'Running') {
            $c += T "依赖的数据库服务 $db 没在运行（见数据库那条报警）" "Servis baze $db, od kog zavisi, ne radi (vidi upozorenje o bazi)" "The database service $db it depends on is not running (see the database alert)"
        }
    }
    $xml = Join-Path $ToolsDir "$SvcApp.xml"
    if (Test-Path $xml) {
        $x = Get-Content -Path $xml -Raw -Encoding UTF8
        if ($x -match '<executable>\s*([^<]+?)\s*</executable>') {
            $py = $Matches[1]
            if (-not (Test-Path $py)) {
                $c += T "找不到 Python（$py），可能被卸载或升级了。装回 Python 后运行 update.ps1" "Python nije pronađen ($py), možda je deinstaliran ili nadograđen. Vratite Python pa pokrenite update.ps1" "Python not found ($py), it may have been uninstalled or upgraded. Reinstall Python, then run update.ps1"
            }
        }
    } else {
        $c += T "服务配置 $xml 不见了，运行 update.ps1" "Nedostaje konfiguracija servisa $xml, pokrenite update.ps1" "The service configuration $xml is missing, run update.ps1"
    }
    if (-not (Test-Path $RunServer)) {
        $c += T '程序文件不完整（缺 run_server.py），运行 update.ps1 -Online 重新下载' 'Programske datoteke su nepotpune (nedostaje run_server.py), pokrenite update.ps1 -Online da se ponovo preuzmu' 'Program files are incomplete (run_server.py missing), run update.ps1 -Online to download them again'
    }
    if (-not (Test-Path (Join-Path $Backend '.venv\pyvenv.cfg'))) {
        $c += T 'Python 虚拟环境 .venv 不见了，运行 update.ps1' 'Nedostaje Python virtuelno okruženje .venv, pokrenite update.ps1' 'The Python virtual environment .venv is missing, run update.ps1'
    }
    if (-not (Test-Path $EnvFile)) {
        $c += T "配置文件 $EnvFile 不见了，从备份目录的 config 里复制回来" "Nedostaje konfiguracioni fajl $EnvFile, kopirajte ga iz foldera config u rezervnoj kopiji" "The configuration file $EnvFile is missing, copy it back from the config folder of the backup"
    }
    $own = Get-PortOwner 8000
    if ($own -and $own -notmatch 'python') {
        $c += T "8000 端口被 $own 占用，不是本系统的程序，先关掉它" "Port 8000 zauzima $own, koji nije deo ovog sistema; prvo ga zatvorite" "Port 8000 is taken by $own, which is not part of this system; close it first"
    }
    $h = Get-DiskFullHint $Backend
    if ($h) { $c += $h }
    $l = Get-LastErrorLine (Join-Path $LogDir "$SvcApp.err.log") 30 '(Error|Exception)\b|Traceback|ERROR|10048'
    if ($l) { $c += (T '程序日志最后的错误：' 'Poslednja greška u logu programa: ' 'Last error in the program log: ') + $l }
    $e = Get-ScmError $SvcApp
    if ($e) { $c += $e }
    return $c
}

function Get-CaddyCause {
    $c = @()
    $app = Get-Service -Name $SvcApp -ErrorAction SilentlyContinue
    if ($app -and $app.Status -ne 'Running') {
        $c += T "依赖的程序服务 $SvcApp 没在运行（见上一条）" "Servis programa $SvcApp, od kog zavisi, ne radi (vidi prethodno upozorenje)" "The program service $SvcApp it depends on is not running (see the previous alert)"
    }
    if (-not (Test-Path (Join-Path $ToolsDir 'caddy.exe'))) {
        $c += T "$ToolsDir\caddy.exe 不见了（被杀毒软件隔离了？），运行 update.ps1" "Nedostaje $ToolsDir\caddy.exe (antivirus ga je stavio u karantin?), pokrenite update.ps1" "$ToolsDir\caddy.exe is missing (quarantined by the antivirus?), run update.ps1"
    }
    if (-not (Test-Path (Join-Path $AppDir 'deploy\Caddyfile'))) {
        $c += T 'deploy\Caddyfile 不见了，运行 update.ps1 -Online' 'Nedostaje deploy\Caddyfile, pokrenite update.ps1 -Online' 'deploy\Caddyfile is missing, run update.ps1 -Online'
    }
    foreach ($port in @(80, 443)) {
        $own = Get-PortOwner $port
        if ($own -and $own -notmatch 'caddy') {
            $c += T "$port 端口被 $own 占用（常见：IIS、别的网页服务器），先关掉它" "Port $port zauzima $own (obično IIS ili drugi web server), prvo ga zatvorite" "Port $port is taken by $own (usually IIS or another web server), close it first"
        }
    }
    $l = Get-LastErrorLine (Join-Path $LogDir "$SvcCaddy.err.log") 30 '"level":"(error|fatal)"|Error:'
    if ($l) {
        if ($l -match '"msg":"([^"]*)"') {
            $m = $Matches[1]
            if ($l -match '"error":"([^"]*)"') { $m = $m + ': ' + $Matches[1] }
            $l = $m
        }
        $c += (T 'Caddy 日志最后的错误：' 'Poslednja greška u logu Caddy-ja: ' 'Last error in the Caddy log: ') + (Limit-Text $l 180)
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
        return T "服务 $Name 被设成了「禁用」：在「服务」里双击它，启动类型改回「自动」，再点「启动」" "Servis $Name je podešen na Disabled (onemogućen): u prozoru Services ga otvorite dvostrukim klikom, Startup type vratite na Automatic, pa kliknite Start" "Service $Name is set to Disabled: in Services double-click it, set Startup type back to Automatic, then click Start"
    }
    return $null
}

# 第一条：被禁用；中间：查到的原因；最后：启动时 Windows 返回的错误（被禁用时就不重复了）
function Join-Causes([string]$Name, $Found, [string]$StartErr) {
    $c = @()
    $d = Get-DisabledHint $Name
    if ($d) { $c += $d }
    $c += @($Found)
    if ($StartErr -and -not $d) { $c += (T '启动时 Windows 返回的错误：' 'Greška koju je Windows vratio pri pokretanju: ' 'Error Windows returned when starting it: ') + $StartErr }
    return $c
}

# 原因列表 → 「可能原因：1) …；2) …」
function Format-Causes($Causes, [string]$LogHint) {
    $list = @($Causes | Where-Object { $_ })
    if ($list.Count -eq 0) {
        return T "没查到明显原因，请看日志 $LogHint" "Nije pronađen očigledan uzrok, pogledajte log $LogHint" "No obvious cause found, see the log $LogHint"
    }
    $parts = @()
    for ($i = 0; $i -lt $list.Count; $i++) { $parts += "$($i + 1)) $($list[$i])" }
    return (T '可能原因：' 'Mogući uzroci: ' 'Likely causes: ') + ($parts -join (T '；' '; ' '; '))
}

# ---------------- 检查 ----------------
$problems = [ordered]@{}   # 问题 → 说明

# 数据库：程序服务依赖它，它起不来程序和 Caddy 都起不来（2026-11-27 PostgreSQL 被卸载了一半，以前的报警只说程序服务停了）
$dbSvcName = Get-DbServiceName
if ($dbSvcName) {
    $dbSvc = Get-Service -Name $dbSvcName -ErrorAction SilentlyContinue
    if (-not $dbSvc) {
        $problems["svc:$dbSvcName"] = (T "数据库服务 $dbSvcName 不存在了（PostgreSQL 被卸载了？）。" "Servis baze $dbSvcName više ne postoji (PostgreSQL deinstaliran?). " "The database service $dbSvcName no longer exists (PostgreSQL uninstalled?). ") + $ReinstallPg
    } elseif ($dbSvc.Status -ne 'Running') {
        $startErr = Start-Svc $dbSvcName
        $dbSvc = Get-Service -Name $dbSvcName -ErrorAction SilentlyContinue
        if ($dbSvc -and $dbSvc.Status -eq 'Running') {
            Send-Alert (T "数据库服务 $dbSvcName 停了，已自动重新启动" "Servis baze $dbSvcName je stao i automatski je ponovo pokrenut" "The database service $dbSvcName stopped and was restarted automatically") $true
        } else {
            $causes = Format-Causes (Join-Causes $dbSvcName (Get-DbCause $dbSvcName) $startErr) (T 'PostgreSQL 数据目录下的 log 文件夹' 'folder log u direktorijumu podataka PostgreSQL-a' 'the log folder in the PostgreSQL data directory')
            $problems["svc:$dbSvcName"] = (T "数据库服务 $dbSvcName 停了，自动启动失败。" "Servis baze $dbSvcName je stao i ne može automatski da se pokrene. " "The database service $dbSvcName stopped and could not be started automatically. ") + $causes
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
        $logPath = "$LogDir\$name.err.log"
        if ($svc -and $svc.Status -eq 'Running') {
            $tail = ''
            if ($why) { $tail = T "停之前日志里的错误：$why。" "Greška u logu pre zaustavljanja: $why. " "Error in the log before it stopped: $why. " }
            Send-Alert ((T "服务 $name 停了，已自动重新启动。" "Servis $name je stao i automatski je ponovo pokrenut. " "Service $name stopped and was restarted automatically. ") + $tail + (T "日志 $logPath" "Log: $logPath" "Log: $logPath")) $true
        } else {
            if ($name -eq $SvcApp) { $found = Get-AppCause } else { $found = Get-CaddyCause }
            $causes = Format-Causes (Join-Causes $name $found $startErr) $logPath
            $problems["svc:$name"] = (T "服务 $name 停了，自动启动失败。" "Servis $name je stao i ne može automatski da se pokrene. " "Service $name stopped and could not be started automatically. ") + $causes
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
    $who = "$($pr.ProcessName) $($pr.Id)"
    Send-Alert (T "8000 端口被残留的旧进程占着（$who），已结束它并重新启动服务 $SvcApp" "Port 8000 je držao zaostali stari proces ($who); završen je i servis $SvcApp je ponovo pokrenut" "Port 8000 was held by a leftover old process ($who); it was ended and service $SvcApp restarted") $true
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
            if (-not $s -or $s.Status -ne 'Running') { $causes += T "数据库服务 $dbSvcName 没在运行" "Servis baze $dbSvcName ne radi" "The database service $dbSvcName is not running" }
        }
        $l = Get-LastErrorLine (Join-Path $LogDir "$SvcApp.err.log") 30 '(Error|Exception)\b|Traceback|ERROR'
        if ($l) { $causes += (T '程序日志最后的错误：' 'Poslednja greška u logu programa: ' 'Last error in the program log: ') + $l }
        $problems['health'] = (T "服务 $SvcApp 在运行，但系统没有响应，可以先在「服务」里重启它。" "Servis $SvcApp radi, ali sistem ne odgovara; prvo ga ponovo pokrenite u prozoru Services. " "Service $SvcApp is running but the system does not respond; first restart it in Services. ") + (Format-Causes $causes "$LogDir\$SvcApp.err.log")
    }
}

$statusFile = Join-Path $DataDir 'backup-status.json'
if (Test-Path $statusFile) {
    try {
        $st = Get-Content -Path $statusFile -Raw -Encoding UTF8 | ConvertFrom-Json
        $at = [string]$st.at
        if (-not $st.ok) {
            # backup.ps1 写的错误说明是中文的：中文报警原样带上，其他语言只带退出码，原因由下面翻译
            $m = ([string]$st.message) -replace '。请看上面的输出。?$', ''
            $m = $m.TrimEnd('。', ' ')
            $causes = @()
            if ($dbSvcName) {
                $s = Get-Service -Name $dbSvcName -ErrorAction SilentlyContinue
                if (-not $s -or $s.Status -ne 'Running') { $causes += T "数据库服务 $dbSvcName 没在运行（见数据库那条报警）" "Servis baze $dbSvcName ne radi (vidi upozorenje o bazi)" "The database service $dbSvcName is not running (see the database alert)" }
            }
            $code = $null
            if ($m -match '退出码 (-?\d+)') {
                $code = $Matches[1]
                $hint = Get-ExitCodeHint ([long]$code) $AlertLang
                if ($hint -and $m -notlike "*$hint*") { $causes += $hint }
            }
            $pgBin = Find-PgBin
            if (-not $pgBin) {
                $causes += T '找不到 PostgreSQL 的程序目录（被卸载了？）' 'Programski direktorijum PostgreSQL-a nije pronađen (deinstaliran?)' 'The PostgreSQL program directory was not found (uninstalled?)'
            } elseif (-not (Test-Path (Join-Path $pgBin 'libpq.dll'))) {
                $causes += T "PostgreSQL 程序目录不完整（$pgBin 里缺 libpq.dll），重装同一个大版本的 PostgreSQL" "Programski direktorijum PostgreSQL-a je nepotpun (u $pgBin nedostaje libpq.dll), ponovo instalirajte PostgreSQL iste glavne verzije" "The PostgreSQL program directory is incomplete (libpq.dll missing in $pgBin), reinstall PostgreSQL of the same major version"
            }
            $codeText = ''
            if ($code) { $codeText = T '' " (izlazni kod $code)" " (exit code $code)" }
            $head = T "备份失败（$at）：$m。" "Rezervna kopija nije uspela ($at)$codeText. " "Backup failed ($at)$codeText. "
            $problems['backup_failed'] = $head + (Format-Causes $causes "$LogDir\backup.log")
        } else {
            $atTime = [datetime]::ParseExact($at, 'yyyy-MM-dd HH:mm', [Globalization.CultureInfo]::InvariantCulture)
            if (((Get-Date) - $atTime).TotalHours -gt $BackupMaxAgeH) {
                $problems['backup_old'] = T "超过 $BackupMaxAgeH 小时没有成功的备份（最后一次 $at）。请检查计划任务 $TaskBackup" "Više od $BackupMaxAgeH sati nema uspešne rezervne kopije (poslednja $at). Proverite zakazani zadatak $TaskBackup" "No successful backup for more than $BackupMaxAgeH hours (last one $at). Check the scheduled task $TaskBackup"
            }
        }
    } catch {
        $problems['backup_status'] = T "读不了备份结果文件 $statusFile" "Ne mogu da pročitam fajl sa rezultatom kopije $statusFile" "Cannot read the backup result file $statusFile"
    }
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
        $problems["disk:$letter"] = T "磁盘 ${letter}: 快满了，只剩 $freeGb GB（$pct%）。请清理或把备份 / 原图归档挪到别的盘" "Disk ${letter}: je skoro pun, ostalo je samo $freeGb GB ($pct%). Oslobodite prostor ili premestite kopije / arhivu originalnih slika na drugi disk" "Disk ${letter}: is almost full, only $freeGb GB ($pct%) left. Free up space or move the backups / original photo archive to another disk"
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
    if (-not $problems.Contains($k)) { Send-Alert ((T '已恢复：' 'Rešeno: ' 'Recovered: ') + $k) $false }
}
Write-Utf8NoBom $StateFile ($newState | ConvertTo-Json)
