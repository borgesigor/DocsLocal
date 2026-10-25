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
    # Some Python distributions require this adjacent file when constructing TLS contexts.
    $TlsResource = & $Python -c "import ssl; from pathlib import Path; p = Path(ssl.__file__).with_name('codex-rejected-cas.pem'); print(str(p) if p.is_file() else '')"
    if ($LASTEXITCODE -ne 0) { throw 'Não foi possível consultar os recursos TLS do Python.' }
    $TlsArguments = @()
    if ($TlsResource) {
        $TlsArguments = @('--add-data', "$TlsResource;.")
    }
    & $Python -m PyInstaller --noconfirm --clean --onefile --windowed `
        --name DocsLocal `
        --icon 'app/static/docs-local.ico' `
        --add-data 'app/static;app/static' `
        --collect-submodules uvicorn `
        --collect-submodules fastapi `
        @TlsArguments `
        scripts/frozen_entry.py
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller falhou.' }

    $Exe = Join-Path $Root 'dist\DocsLocal.exe'
    $TlsReport = Join-Path $Root 'build\DocsLocal\tls-check.json'
    $TlsCheck = Start-Process -FilePath $Exe -ArgumentList @('--check-tls', "`"$TlsReport`"") -WindowStyle Hidden -Wait -PassThru
    if ($TlsCheck.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $TlsReport)) {
        throw "O executável não passou no teste TLS. Consulte $TlsReport."
    }
    $TlsResult = Get-Content -Raw -LiteralPath $TlsReport | ConvertFrom-Json
    if (-not $TlsResult.tls_ready) { throw 'O executável não conseguiu criar um contexto TLS seguro.' }
} finally {
    Pop-Location
}

$Exe = Join-Path $Root 'dist\DocsLocal.exe'
$Hash = (Get-FileHash -Algorithm SHA256 $Exe).Hash.ToLowerInvariant()
Set-Content -NoNewline -Encoding ascii -Path "$Exe.sha256" -Value "$Hash  DocsLocal.exe"
Write-Host "Build pronta: $Exe"
