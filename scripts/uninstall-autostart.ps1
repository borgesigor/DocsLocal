$ErrorActionPreference = 'SilentlyContinue'
$Task = Get-ScheduledTask -TaskName 'Docs Local'
if ($Task) {
    Stop-ScheduledTask -TaskName 'Docs Local'
    Unregister-ScheduledTask -TaskName 'Docs Local' -Confirm:$false
}

$Processes = Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe'"
$TrayProcesses = $Processes | Where-Object { $_.CommandLine -match '\s-m app\.tray\s*$' }
foreach ($Process in $TrayProcesses) {
    Stop-Process -Id $Process.ProcessId -Force
}

Write-Host 'Inicialização automática removida e servidor encerrado.'
