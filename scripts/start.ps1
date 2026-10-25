$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Python = Join-Path $Root '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $Python)) {
    throw "pythonw.exe não foi encontrado em $Python. Crie o ambiente virtual e instale as dependências primeiro."
}

Start-Process `
    -FilePath $Python `
    -ArgumentList @('-m', 'app.tray') `
    -WorkingDirectory $Root `
    -WindowStyle Hidden
