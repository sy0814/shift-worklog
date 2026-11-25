<#
工作记录系统 · 更新到新版本

用法：把新版本的代码解压到任意目录（或 git pull），然后以管理员身份：
    Set-ExecutionPolicy -Scope Process Bypass -Force
    cd <新版本目录>\deploy\windows
    .\update.ps1

会先自动备份一次，再停服务、覆盖程序（保留 .env、数据、图片、证书）、重装依赖、重新构建、
升级数据库结构（数据保留；万一升级失败，用刚才的备份按 README「备份与恢复」还原）、启动。
#>
. (Join-Path $PSScriptRoot 'common.ps1')
Assert-Admin
$Source = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if (-not (Test-Path $EnvFile)) { throw "没有找到 $EnvFile，看起来还没安装过。请先运行 install.ps1。" }

Write-Step '1/4 更新前先备份'
& (Join-Path $PSScriptRoot 'backup.ps1')

Write-Step '2/4 停止服务、复制新程序'
Disable-Watchdog
Stop-AppServices
if ($Source.TrimEnd('\') -ne $AppDir.TrimEnd('\')) { Copy-Source $Source }

Write-Step '3/4 安装依赖、构建网页、升级数据库'
$python = Find-Python
$npm = Find-Npm
if (-not $python -or -not $npm) { throw '找不到 Python 或 Node.js，请先运行一次 install.ps1。' }
Build-App $python $npm
Invoke-Migrate

Write-Step '4/4 启动服务'
# 服务配置按新版本重写（现在直接用基础 Python 运行，停服务时不会再留下进程占着 8000 端口）
if (Get-Service -Name $SvcApp -ErrorAction SilentlyContinue) {
    Write-Utf8NoBom (Join-Path $ToolsDir "$SvcApp.xml") (Get-AppServiceXml (Get-PgServiceName))
    Write-Ok "已更新服务配置 $SvcApp.xml"
}
Start-AppServices
Wait-Health
Register-Watchdog
Write-Ok '看门狗已开启（每 5 分钟检查服务、备份、磁盘）'
Write-Host ''
Write-Host '更新完成。手机打开系统时会提示「有新版本」，点刷新即可。' -ForegroundColor Green
