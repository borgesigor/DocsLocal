$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Executable = @(
    (Join-Path $Root 'DocsLocal.exe'),
    (Join-Path $Root 'dist\DocsLocal.exe')
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Executable) {
    throw 'Autostart is available only for the packaged production executable. Use scripts\start.ps1 for development.'
}

$Action = New-ScheduledTaskAction -Execute $Executable -WorkingDirectory (Split-Path $Executable)
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Days 0)
Register-ScheduledTask -TaskName 'Docs Local' -Action $Action -Trigger $Trigger -Settings $Settings -Description 'Docs Local production app' -Force | Out-Null
Write-Host 'Production autostart installed.'
