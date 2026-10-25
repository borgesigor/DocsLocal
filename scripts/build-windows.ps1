$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Python = Join-Path $Root '.venv\Scripts\python.exe'

if (-not (Test-Path $Python)) {
    $Python = (Get-Command python -ErrorAction Stop).Source
}
if (-not (Test-Path (Join-Path $Root 'app\static\dist\index.html'))) {
    throw 'A build da interface está ausente. Execute npm ci e npm run build em frontend.'
}

Push-Location $Root
try {
    & $Python -m PyInstaller --noconfirm --clean --onefile --windowed `
        --name DocsLocal `
        --add-data 'app/static;app/static' `
        --collect-submodules uvicorn `
        --collect-submodules fastapi `
        scripts/frozen_entry.py
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller falhou.' }
} finally {
    Pop-Location
}

$Exe = Join-Path $Root 'dist\DocsLocal.exe'
$Hash = (Get-FileHash -Algorithm SHA256 $Exe).Hash.ToLowerInvariant()
Set-Content -NoNewline -Encoding ascii -Path "$Exe.sha256" -Value "$Hash  DocsLocal.exe"
Write-Host "Build pronta: $Exe"
