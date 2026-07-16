param(
    [Parameter(Mandatory = $true)]
    [string]$ServerIp,
    [Parameter(Mandatory = $true)]
    [string]$DesktopExe,
    [int]$Port = 8732,
    [int]$TcpTimeoutSeconds = 5,
    [string]$DiagnosticsPath = ''
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)

if (-not $DiagnosticsPath) {
    $DiagnosticsPath = Join-Path $env:LOCALAPPDATA 'LandCustomerSystem\client-network-diagnostics.json'
}
$diagnosticsFullPath = [IO.Path]::GetFullPath($DiagnosticsPath)

function Write-DiagnosticFailure {
    param(
        [int]$Code,
        [string]$Message,
        [string]$ClientIp = ''
    )

    $directory = Split-Path -Parent $diagnosticsFullPath
    if (-not (Test-Path -LiteralPath $directory)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }
    [PSCustomObject]@{
        checked_at = [DateTimeOffset]::UtcNow.ToString('o')
        status = 'error'
        code = $Code
        message = $Message
        server_ip = $ServerIp.Trim()
        port = $Port
        netbird_client_ip = $ClientIp
    } | ConvertTo-Json | Set-Content -LiteralPath $diagnosticsFullPath -Encoding UTF8
    Write-Output $Message
    Write-Output "診斷報告：$diagnosticsFullPath"
    exit $Code
}

$normalizedServerIp = $ServerIp.Trim()
$parsedIp = $null
if (-not [Net.IPAddress]::TryParse($normalizedServerIp, [ref]$parsedIp)) {
    Write-DiagnosticFailure 50 '家中主機 IP 格式不正確，請重新取得客戶端包。'
}
$bytes = $parsedIp.GetAddressBytes()
if ($bytes.Length -ne 4 -or $bytes[0] -ne 100 -or $bytes[1] -lt 64 -or $bytes[1] -gt 127) {
    Write-DiagnosticFailure 50 '家中主機 IP 不在 NetBird 私人網路範圍內。'
}
if ($Port -ne 8732) {
    Write-DiagnosticFailure 50 '公司客戶端只允許連線到家中 HTTPS 8732。'
}

$desktopFullPath = [IO.Path]::GetFullPath($DesktopExe)
if (-not (Test-Path -LiteralPath $desktopFullPath -PathType Leaf)) {
    Write-DiagnosticFailure 50 '找不到完整桌面程式，客戶端包可能未完整解壓縮。'
}

$netBirdExe = Join-Path $env:ProgramFiles 'NetBird\netbird.exe'
if (-not (Test-Path -LiteralPath $netBirdExe -PathType Leaf)) {
    Write-DiagnosticFailure 10 '尚未安裝 NetBird，請重新執行客戶端啟動檔。'
}
$clientIpText = (& $netBirdExe status --ipv4 2>$null | Select-Object -First 1)
if (-not $clientIpText) {
    Write-DiagnosticFailure 10 'NetBird 尚未連線，請完成登入後再試一次。'
}
$clientIpText = $clientIpText.Trim()
$clientIp = $null
if (-not [Net.IPAddress]::TryParse($clientIpText, [ref]$clientIp)) {
    Write-DiagnosticFailure 10 'NetBird 尚未取得可用的私人 IP。'
}
$clientBytes = $clientIp.GetAddressBytes()
if ($clientBytes.Length -ne 4 -or $clientBytes[0] -ne 100 -or $clientBytes[1] -lt 64 -or $clientBytes[1] -gt 127) {
    Write-DiagnosticFailure 10 'NetBird 回傳了非私人網路 IP，請重新連線。'
}

$tcpClient = [Net.Sockets.TcpClient]::new()
try {
    $connectTask = $tcpClient.ConnectAsync($normalizedServerIp, $Port)
    if (-not $connectTask.Wait([TimeSpan]::FromSeconds([Math]::Max(1, $TcpTimeoutSeconds)))) {
        Write-DiagnosticFailure 20 '無法在 5 秒內連到家中主機。請確認主機未休眠且伺服器視窗保持開啟。' $clientIpText
    }
    if (-not $tcpClient.Connected) {
        Write-DiagnosticFailure 20 '無法透過 NetBird 連到家中主機 8732。' $clientIpText
    }
} catch {
    Write-DiagnosticFailure 20 '無法透過 NetBird 連到家中主機。請先確認家中伺服器已啟動。' $clientIpText
} finally {
    $tcpClient.Dispose()
}

if (Test-Path -LiteralPath $diagnosticsFullPath -PathType Leaf) {
    Remove-Item -LiteralPath $diagnosticsFullPath -Force
}
$argumentLine = '--client-health-report "{0}"' -f $diagnosticsFullPath
try {
    $process = Start-Process `
        -FilePath $desktopFullPath `
        -ArgumentList $argumentLine `
        -WindowStyle Hidden `
        -Wait `
        -PassThru
} catch {
    Write-DiagnosticFailure 30 '無法執行客戶端 HTTPS 健康檢查，客戶端檔案可能不完整。' $clientIpText
}

if (-not (Test-Path -LiteralPath $diagnosticsFullPath -PathType Leaf)) {
    Write-DiagnosticFailure 30 '客戶端沒有產生 HTTPS 健康檢查報告，請重新下載完整客戶端包。' $clientIpText
}
try {
    $health = Get-Content -LiteralPath $diagnosticsFullPath -Raw -Encoding UTF8 | ConvertFrom-Json
} catch {
    Write-DiagnosticFailure 30 '客戶端健康檢查報告損壞，請重新下載完整客戶端包。' $clientIpText
}
if ($process.ExitCode -ne 0 -or $health.status -ne 'ok') {
    $detail = [string]$health.message
    if (-not $detail) {
        $detail = 'HTTPS 憑證或家中 API 驗證失敗。'
    }
    Write-Output $detail
    Write-Output '如果訊息提到憑證，請由家中主機重新打包公司筆電客戶端。'
    Write-Output "診斷報告：$diagnosticsFullPath"
    exit 30
}
if ($health.backend -ne 'postgresql' -or [int]$health.schema_version -lt 2) {
    Write-DiagnosticFailure 40 '連線目標不是相容的 PostgreSQL 正式伺服器。' $clientIpText
}

Write-Output "NetBird 客戶端 IP：$clientIpText"
Write-Output "家中 HTTPS API：$normalizedServerIp`:$Port"
Write-Output "伺服器版本：$($health.server_version)"
Write-Output "資料結構：$($health.schema_version)；資料筆數：$($health.record_count)"
Write-Output "診斷報告：$diagnosticsFullPath"
exit 0
