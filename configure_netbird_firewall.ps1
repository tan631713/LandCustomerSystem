param()

$ErrorActionPreference = 'Stop'
$netBirdExe = Join-Path $env:ProgramFiles 'NetBird\netbird.exe'
if (-not (Test-Path -LiteralPath $netBirdExe -PathType Leaf)) {
    throw '找不到 NetBird，請重新執行「啟動家中伺服器.bat」。'
}

$vpnIpText = (& $netBirdExe status --ipv4 | Select-Object -First 1).Trim()
$vpnIp = $null
if (-not [Net.IPAddress]::TryParse($vpnIpText, [ref]$vpnIp)) {
    throw 'NetBird is not connected. Complete sign-in first.'
}
$bytes = $vpnIp.GetAddressBytes()
if ($bytes.Length -ne 4 -or $bytes[0] -ne 100 -or $bytes[1] -lt 64 -or $bytes[1] -gt 127) {
    throw "Unexpected NetBird IPv4 address: $vpnIpText"
}
$vpnRange = '100.64.0.0/10'

$rules = @(
    @{ Name = 'Land Customer System NetBird HTTPS'; Port = 8732 },
    @{ Name = 'Land Customer System NetBird Certificate'; Port = 8733 }
)
foreach ($rule in $rules) {
    Remove-NetFirewallRule -DisplayName $rule.Name -ErrorAction SilentlyContinue
    New-NetFirewallRule `
        -DisplayName $rule.Name `
        -Direction Inbound `
        -Action Allow `
        -Protocol TCP `
        -LocalPort $rule.Port `
        -Profile Any `
        -RemoteAddress $vpnRange | Out-Null
}

Write-Output "NetBird IP: $vpnIpText"
Write-Output "Allowed source: $vpnRange"
Write-Output 'Allowed ports: 8732, 8733'
Write-Output 'PostgreSQL 5432: not opened'
