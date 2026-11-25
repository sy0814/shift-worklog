<#
工作记录系统 · 卸载服务

默认只删除 Windows 服务、防火墙规则、备份和看门狗计划任务，保留数据库、图片、证书、配置和备份。
加 -RemoveProgram 同时删除 C:\WorkRecord\app 和 tools（数据 data、备份 backups 仍保留）。
数据库不会自动删除；确实不要了再手动在 PostgreSQL 里 DROP DATABASE workrecord。
#>
param([switch]$RemoveProgram)

. (Join-Path $PSScriptRoot 'common.ps1')
Assert-Admin

Write-Step '停止并删除服务'
Unregister-ScheduledTask -TaskName $TaskWatchdog -Confirm:$false -ErrorAction SilentlyContinue
Stop-AppServices
foreach ($n in @($SvcCaddy, $SvcApp)) {
    if (Get-Service -Name $n -ErrorAction SilentlyContinue) { Invoke-WinSW $n 'uninstall'; Write-Ok "已删除服务 $n" }
}
Write-Step '删除防火墙规则和备份任务（看门狗任务已在最前面删除）'
Get-NetFirewallRule -DisplayName 'WorkRecord HTTP/HTTPS' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
Unregister-ScheduledTask -TaskName $TaskBackup -Confirm:$false -ErrorAction SilentlyContinue
if ($RemoveProgram) {
    Write-Step '删除程序文件'
    Set-Location $env:TEMP
    Remove-Item $AppDir, $ToolsDir -Recurse -Force -ErrorAction SilentlyContinue
}
Write-Host ''
Write-Host "已卸载。数据仍在 $DataDir，数据库 workrecord 仍在 PostgreSQL 里。" -ForegroundColor Green
