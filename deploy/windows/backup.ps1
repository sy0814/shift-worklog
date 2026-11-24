<#
工作记录系统 · 备份（install.ps1 已设为每天 03:40 自动运行；也可以手动运行）

备份内容：数据库（pg_dump）、任务图片、HTTPS 证书、配置文件 .env
备份位置：C:\WorkRecord\data\backup-target.txt 里写的目录（安装时设置，也可以在网页「系统设置 → 存储与备份」里改），
          默认 C:\WorkRecord\backups
第二份：  C:\WorkRecord\data\backup-copy.txt 里写的目录（可不设）：另一块硬盘、网络共享，或云盘同步文件夹
          （例如 OneDrive / 坚果云 / 百度网盘同步盘的文件夹，云盘客户端会自动传到云上）
数据库备份保留 30 天；图片是增量复制（只新增不删除）。
每次运行的结果写进 C:\WorkRecord\data\backup-status.json，网页上能看到。

注意：备份里的 .env 含数据库密码和密钥，备份目录要放在只有管理员能访问的地方。
#>
param([string]$Target)

. (Join-Path $PSScriptRoot 'common.ps1')
if (-not $Target -and (Test-Path $BackupCfg)) { $Target = (Get-Content $BackupCfg -Raw -Encoding UTF8).Trim() }
if (-not $Target) { $Target = Join-Path $Root 'backups' }
$CopyCfg = Join-Path $DataDir 'backup-copy.txt'
$Copy = ''
if (Test-Path $CopyCfg) { $Copy = (Get-Content $CopyCfg -Raw -Encoding UTF8).Trim() }
$StatusFile = Join-Path $DataDir 'backup-status.json'
$started = Get-Date
$stamp = Get-Date -Format 'yyyyMMdd-HHmm'
$log = Join-Path $LogDir 'backup.log'
New-Item -ItemType Directory -Force -Path $LogDir, (Join-Path $Target 'db'), (Join-Path $Target 'config') | Out-Null

function Log([string]$Msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $Msg"
    Write-Host $line
    Add-Content -Path $log -Value $line -Encoding UTF8
}

# 结果写给网页看（系统设置 → 存储与备份）
function Write-Status([bool]$Ok, [string]$Msg, $SizeMb, [string]$CopyResult) {
    $st = [ordered]@{
        ok = $Ok; at = $started.ToString('yyyy-MM-dd HH:mm'); seconds = [int](((Get-Date) - $started).TotalSeconds)
        target = $Target; copy = $Copy; copy_result = $CopyResult; size_mb = $SizeMb; message = $Msg
    }
    try {
        $drive = Get-PSDrive -Name $Target.Substring(0, 1) -ErrorAction SilentlyContinue
        if ($drive -and $Target -match '^[A-Za-z]:') { $st['free_gb'] = [math]::Round($drive.Free / 1GB, 1) }
    } catch { }
    Write-Utf8NoBom $StatusFile ($st | ConvertTo-Json)
}

try {
    # 1. 数据库
    $cfg = Read-EnvFile $EnvFile
    if ($cfg['DATABASE_URL'] -notmatch '^postgresql\+psycopg://([^:]+):([^@]+)@([^:/]+):(\d+)/(.+)$') { throw 'backend\.env 里的 DATABASE_URL 格式不对' }
    $pgBin = Find-PgBin
    if (-not $pgBin) { throw '找不到 PostgreSQL 的 pg_dump' }
    $dump = Join-Path $Target "db\workrecord-$stamp.dump"
    $env:PGPASSWORD = $Matches[2]
    Invoke-Native (Join-Path $pgBin 'pg_dump.exe') @('-h', $Matches[3], '-p', $Matches[4], '-U', $Matches[1], '-d', $Matches[5], '-Fc', '-f', $dump) '数据库备份（pg_dump）'
    Remove-Item Env:\PGPASSWORD
    $sizeMb = [math]::Round((Get-Item $dump).Length / 1MB, 1)
    Log "数据库 → $dump（$sizeMb MB）"

    # 2. 图片（增量，只新增不删除）
    $up = Join-Path $DataDir 'uploads'
    if (Test-Path $up) {
        & robocopy $up (Join-Path $Target 'uploads') /E /XO /NFL /NDL /NJH /NJS /NP | Out-Null
        if ($LASTEXITCODE -ge 8) { throw "图片备份失败（robocopy 退出码 $LASTEXITCODE）" }
        Log '图片 → uploads（增量）'
    }

    # 3. HTTPS 证书（根证书丢了所有手机要重装）和配置
    $pki = Join-Path $DataDir 'caddy\caddy\pki'
    if (Test-Path $pki) {
        & robocopy $pki (Join-Path $Target 'caddy-pki') /E /NFL /NDL /NJH /NJS /NP | Out-Null
        if ($LASTEXITCODE -ge 8) { throw "证书备份失败（robocopy 退出码 $LASTEXITCODE）" }
    }
    Copy-Item $EnvFile (Join-Path $Target 'config\backend.env') -Force
    Copy-Item (Join-Path $DataDir '*.txt') (Join-Path $Target 'config') -Force -ErrorAction SilentlyContinue
    $global:LASTEXITCODE = 0
    Log '证书、配置 → caddy-pki、config'

    # 4. 清理 30 天前的数据库备份
    $old = Get-ChildItem (Join-Path $Target 'db') -Filter 'workrecord-*.dump' | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) }
    foreach ($f in $old) { Remove-Item $f.FullName -Force; Log "删除旧备份 $($f.Name)" }
    Log '备份完成'

    # 5. 第二份（另一块盘 / 网络共享 / 云盘同步文件夹）：失败只记下来，不算整个备份失败
    $copyResult = ''
    if ($Copy) {
        try {
            New-Item -ItemType Directory -Force -Path $Copy | Out-Null
            & robocopy $Target $Copy /E /XO /R:2 /W:5 /NFL /NDL /NJH /NJS /NP | Out-Null
            if ($LASTEXITCODE -ge 8) { throw "robocopy 退出码 $LASTEXITCODE" }
            $global:LASTEXITCODE = 0
            $oldCopy = Get-ChildItem (Join-Path $Copy 'db') -Filter 'workrecord-*.dump' -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) }
            foreach ($f in $oldCopy) { Remove-Item $f.FullName -Force }
            $copyResult = 'ok'
            Log "第二份 → $Copy"
        } catch {
            $copyResult = $_.Exception.Message
            Log "第二份备份失败：$copyResult"
        }
    }
    Write-Status $true '' $sizeMb $copyResult
} catch {
    Log "备份失败：$($_.Exception.Message)"
    try { Write-Status $false $_.Exception.Message $null '' } catch { }
    exit 1
}
