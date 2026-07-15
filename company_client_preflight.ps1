param(
    [Parameter(Mandatory = $true)]
    [string]$ServerIp,
    [int]$Port = 8732
)

$ErrorActionPreference = 'Stop'
$parsedIp = $null
if (-not [Net.IPAddress]::TryParse($ServerIp.Trim(), [ref]$parsedIp)) {
    throw "Invalid home server IP: $ServerIp"
}
$bytes = $parsedIp.GetAddressBytes()
if ($bytes.Length -ne 4 -or $bytes[0] -ne 100 -or $bytes[1] -lt 64 -or $bytes[1] -gt 127) {
    throw "Home server IP is outside the NetBird CGNAT range: $ServerIp"
}

$netBirdExe = Join-Path $env:ProgramFiles 'NetBird\netbird.exe'
if (-not (Test-Path -LiteralPath $netBirdExe -PathType Leaf)) {
    throw 'NetBird is not installed.'
}
$clientIpText = (& $netBirdExe status --ipv4 | Select-Object -First 1).Trim()
$clientIp = $null
if (-not [Net.IPAddress]::TryParse($clientIpText, [ref]$clientIp)) {
    throw 'NetBird is not connected.'
}

if (-not (Test-NetConnection -ComputerName $ServerIp -Port $Port -InformationLevel Quiet)) {
    throw "Home server is unreachable through NetBird: $ServerIp`:$Port"
}

Write-Output "NetBird client IP: $clientIpText"
Write-Output "Home server reachable: $ServerIp`:$Port"
