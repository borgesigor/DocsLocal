$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Python = Join-Path $Root '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $Python)) {
    throw "pythonw.exe não foi encontrado em $Python. Crie o ambiente virtual e instale as dependências primeiro."
}

$Action = New-ScheduledTaskAction -Execute $Python -Argument '-m app.tray' -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Days 0)
Register-ScheduledTask -TaskName 'Docs Local' -Action $Action -Trigger $Trigger -Settings $Settings -Description 'Servidor e ícone de bandeja do Docs Local sem janela de terminal' -Force | Out-Null
Write-Host 'Inicialização automática e ícone de bandeja instalados sem janela de terminal.'
