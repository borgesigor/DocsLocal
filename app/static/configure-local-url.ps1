param(
    [ValidateRange(1, 65535)][int]$Port = 8765,
    [ValidateSet('127.0.0.1', 'localhost', '::1')][string]$ServerHost = '127.0.0.1'
)
$ErrorActionPreference = 'Stop'
$Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$Principal = [Security.Principal.WindowsPrincipal]::new($Identity)
if (-not $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Execute como administrador para configurar http://docs.local.'
}
if ($ServerHost -eq 'localhost') { $ServerHost = '127.0.0.1' }
$Protocol = if ($ServerHost -eq '::1') { 'v4tov6' } else { 'v4tov4' }
$HostsPath = Join-Path $env:SystemRoot 'System32\drivers\etc\hosts'
$HostsText = [IO.File]::ReadAllText($HostsPath)
$HasAlias = $false
foreach ($Line in ($HostsText -split '\r?\n')) {
    $Fields = (($Line -split '#', 2)[0].Trim() -split '\s+')
    if ($Fields.Length -gt 1 -and $Fields[1..($Fields.Length - 1)] -contains 'docs.local') {
        if ($Fields[0] -ne '127.0.0.1') { throw 'docs.local ja aponta para outro endereco no arquivo hosts.' }
        $HasAlias = $true
    }
}

$ProxyKey = "HKLM:\SYSTEM\CurrentControlSet\Services\PortProxy\$Protocol\tcp"
$Existing = Get-ItemPropertyValue -LiteralPath $ProxyKey -Name '127.0.0.1/80' -ErrorAction SilentlyContinue
if ($Existing -and $Existing -ne "$ServerHost/$Port") {
    throw 'A porta local 80 ja tem outro encaminhamento. Nenhuma configuracao foi alterada.'
}
$OtherProtocol = if ($Protocol -eq 'v4tov4') { 'v4tov6' } else { 'v4tov4' }
$OtherProxy = Get-ItemPropertyValue -LiteralPath "HKLM:\SYSTEM\CurrentControlSet\Services\PortProxy\$OtherProtocol\tcp" -Name '127.0.0.1/80' -ErrorAction SilentlyContinue
if ($OtherProxy) { throw 'A porta local 80 ja tem outro encaminhamento.' }
$Listeners = @(Get-NetTCPConnection -State Listen -LocalPort 80 -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalAddress -in @('127.0.0.1', '0.0.0.0', '::') })
if ($Listeners.Count -gt 0 -and -not $Existing -and -not ($Port -eq 80 -and $ServerHost -eq '127.0.0.1')) {
    throw 'A porta 80 esta ocupada por outro servico. Libere-a antes de configurar docs.local.'
}
if ($Port -ne 80 -or $ServerHost -ne '127.0.0.1') {
    Start-Service iphlpsvc
    & netsh interface portproxy add $Protocol listenport=80 listenaddress=127.0.0.1 connectport=$Port connectaddress=$ServerHost
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao configurar o encaminhamento local.' }
}
if (-not $HasAlias) {
    [IO.File]::AppendAllText($HostsPath, "`r`n127.0.0.1 docs.local # Docs Local`r`n", [Text.Encoding]::ASCII)
}
Clear-DnsClientCache
Write-Output 'http://docs.local configurado somente neste computador.'
