$ErrorActionPreference = 'SilentlyContinue'
$task = Get-ScheduledTask -TaskName 'Docs Local' -ErrorAction SilentlyContinue
if ($task) { Stop-ScheduledTask -TaskName 'Docs Local' }
$processes = Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe'"
$trayProcesses = $processes | Where-Object { $_.CommandLine -match '\s-m app\.tray\s*$' }
foreach ($process in $trayProcesses) {
    Stop-Process -Id $process.ProcessId -Force
}
