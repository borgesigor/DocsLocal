# Recompõe o recurso TLS omitido nos executáveis v1.0.0 e v1.1.0.
# Execute com o Docs Local aberto e depois use Verificar atualizações na bandeja.
$ErrorActionPreference = 'Stop'
$Certificate = Join-Path $PSScriptRoot 'resources\codex-rejected-cas.pem'
if (-not (Test-Path -LiteralPath $Certificate)) {
    throw 'Extraia todos os arquivos do pacote de reparação antes de executar este script.'
}
$ExpectedHash = 'c916ce1b14ed8ca69e9b5c9fab22799a900dd610d6d4ec9b1347f4fd48e53718'
if ((Get-FileHash -LiteralPath $Certificate -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedHash) {
    throw 'O recurso TLS não corresponde ao arquivo esperado.'
}
$TempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
$Repaired = 0
foreach ($Process in (Get-Process -Name 'DocsLocal*' -ErrorAction SilentlyContinue)) {
    try { $Modules = @($Process.Modules) } catch { continue }
    foreach ($Module in $Modules) {
        if ($Module.ModuleName -ne '_ssl.pyd') { continue }
        $Root = [IO.Path]::GetFullPath((Split-Path -Parent $Module.FileName))
        if (-not $Root.StartsWith($TempRoot, [StringComparison]::OrdinalIgnoreCase) -or
            (Split-Path -Leaf $Root) -notlike '_MEI*' -or
            -not (Test-Path -LiteralPath (Join-Path $Root 'app\static\docs-local.ico'))) {
            continue
        }
        $Destination = Join-Path $Root 'codex-rejected-cas.pem'
        if (Test-Path -LiteralPath $Destination) {
            if ((Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedHash) {
                throw "Já existe um recurso TLS diferente em $Root. Nenhum arquivo foi sobrescrito."
            }
        } else {
            Copy-Item -LiteralPath $Certificate -Destination $Destination
        }
        $Repaired++
    }
}
if ($Repaired -eq 0) {
    throw 'Abra o Docs Local v1.0.0 ou v1.1.0 e execute novamente o reparo.'
}
Write-Host "Recurso TLS recomposto em $Repaired instância(s). Use Verificar atualizações no menu da bandeja."
