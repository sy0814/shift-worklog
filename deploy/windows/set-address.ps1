<#
工作记录系统 · 修改访问地址（服务器 IP 变了、或想加一个电脑名作为地址时用）

用法：右键「以管理员身份运行」PowerShell，然后：
    Set-ExecutionPolicy -Scope Process Bypass -Force
    cd C:\WorkRecord\app\deploy\windows
    .\set-address.ps1 192.168.1.60

多个地址用英文逗号隔开（加引号）：
    .\set-address.ps1 '192.168.1.60, worklog-server'

只改 HTTPS 入口的地址并重启它；数据、程序、密码都不动。
根证书不变，所以手机不用重装证书，只要改用新地址打开即可。

也可以在网页「系统设置 → 访问地址」里改：网页把新地址写进 data\site-hosts-request.txt，
再启动计划任务 WorkRecordSetAddress，它以 SYSTEM 运行「set-address.ps1 -FromFile」，结果写进 data\site-hosts-status.json。
#>
param([Parameter(Position = 0)][string]$SiteHosts = '', [switch]$FromFile)

. (Join-Path $PSScriptRoot 'common.ps1')
$requestFile = Join-Path $DataDir 'site-hosts-request.txt'
$statusFile = Join-Path $DataDir 'site-hosts-status.json'

# 网页上改的：把结果写给网页看（成功 / 失败和原因）
function Write-AddressStatus([bool]$Ok, [string]$Hosts, [string]$Message) {
    $o = [ordered]@{ ok = $Ok; at = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'); hosts = $Hosts; message = $Message }
    Write-Utf8NoBom $statusFile ($o | ConvertTo-Json)
}

if ($FromFile) {
    if (-not (Test-Path $requestFile)) { exit 0 }
    $SiteHosts = ([string](Get-Content -Path $requestFile -Raw -Encoding UTF8)).Trim()
    Remove-Item -Path $requestFile -Force -ErrorAction SilentlyContinue
}
try {
Assert-Admin
if (-not $SiteHosts) { throw '没有填地址。例：.\set-address.ps1 192.168.1.60' }

# 检查地址格式：IPv4 或电脑名 / 域名，逗号分隔
$hosts = @($SiteHosts -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
if (-not $hosts.Count) { throw '没有填地址。例：.\set-address.ps1 192.168.1.60' }
foreach ($h in $hosts) {
    $ipv4 = $h -match '^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$'
    if ($ipv4) {
        foreach ($n in 1..4) { if ([int]$Matches[$n] -gt 255) { throw "IP 地址不对：$h" } }
    } elseif ($h -notmatch '^[A-Za-z0-9]([A-Za-z0-9\-\.]*[A-Za-z0-9])?$') {
        throw "地址格式不对：$h（只能是 IP 地址或电脑名，不要带 http:// 或端口号）"
    }
}
$SiteHosts = $hosts -join ', '

$xmlPath = Join-Path $ToolsDir "$SvcCaddy.xml"
if (-not (Test-Path $xmlPath)) { throw "没有找到 $xmlPath，看起来还没安装过。请先运行 install.ps1。" }

Write-Step "把访问地址改为：$SiteHosts"
$xml = [IO.File]::ReadAllText($xmlPath)
$old = ''
if ($xml -match '<env name="SITE_HOSTS" value="([^"]*)"/>') { $old = $Matches[1] }
$new = [regex]::Replace($xml, '<env name="SITE_HOSTS" value="[^"]*"/>', "<env name=""SITE_HOSTS"" value=""$SiteHosts""/>")
if ($new -eq $xml -and $old -ne $SiteHosts) { throw "在 $xmlPath 里没找到 SITE_HOSTS 设置，请重新运行 install.ps1。" }
Write-Utf8NoBom $xmlPath $new
Write-Utf8NoBom (Join-Path $DataDir 'site-hosts.txt') $SiteHosts
Write-Ok "原来的地址：$old"

Write-Step '重启 HTTPS 服务'
Restart-Service -Name $SvcCaddy -Force
$ok = $false
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 2
    try {
        $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 -Uri 'http://127.0.0.1/install'
        if ($r.StatusCode -eq 200) { $ok = $true; break }
    } catch { }
}
if (-not $ok) { throw "HTTPS 服务没有正常启动，请查看日志：$LogDir\$SvcCaddy.err.log" }
Write-Ok 'HTTPS 服务已重启'
if ($FromFile) { Write-AddressStatus $true $SiteHosts "原来的地址：$old" }
} catch {
    if ($FromFile) { Write-AddressStatus $false $SiteHosts $_.Exception.Message }
    throw
}

$first = $hosts[0]
Write-Host ''
Write-Host '地址已修改。' -ForegroundColor Green
Write-Host "  现在用         https://$first   访问"
Write-Host "  新手机先打开   http://$first/install   安装证书（已经装过证书的手机不用重装）"
Write-Host ''
Write-Note '记得告诉大家新地址；手机桌面上的旧图标打不开了，要用新地址重新「添加到主屏幕」。'
