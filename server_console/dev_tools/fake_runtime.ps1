# Dev/test only stand-in for home_server_runtime.ps1 (console loads it through
# LCS_CONSOLE_RUNTIME_SCRIPT when NOT frozen). Writes a diagnostics file the
# same shape as the real script and then behaves per -Scenario.
param(
    [string]$PackageRoot, [string]$SupportRoot, [string]$Mode, [switch]$NonInteractive,
    [string]$Scenario = 'starting'
)
$scenario = $env:LCS_FAKE_SCENARIO
if (-not $scenario) { $scenario = $Scenario }
$path = Join-Path $env:LOCALAPPDATA 'LandCustomerSystem\home-server-diagnostics.json'
$names = '檢查必要軟體','檢查 NetBird 連線','啟動 PostgreSQL','檢查資料庫','遷移與帳號恢復','自動備份','啟動 HTTPS 伺服器'
$keys = 'prerequisites','netbird','postgresql','database','migration_recovery','backup','server'
function Save($status, $stage, $message, $statuses, $reasons, $extra) {
    $steps = @(for ($i = 0; $i -lt 7; $i++) {
        [ordered]@{ n = $i + 1; key = $keys[$i]; name = $names[$i]; status = $statuses[$i]; reason = $reasons[$i] }
    })
    $state = [ordered]@{
        checked_at = [DateTimeOffset]::Now.ToString('o'); status = $status; stage = $stage; message = $message
        missing_software = @(); winget_available = $false; software_check = 'ok'
        netbird_ip = '100.107.93.232'; api_url = 'https://100.107.93.232:8732/mobile/'
        certificate_url = 'http://100.107.93.232:8733/'
        certificate_sha256 = '4BD97AB29BE2A50140021BB95E562D924223C769870237597E0A1212FCF84F76'
        postgresql_service = 'postgresql-x64-18'; postgresql_status = 'Running'; database_status = 'ok'
        account_count = 3; record_count = 267; schema_version = 13; steps = $steps
    }
    foreach ($key in $extra.Keys) { $state[$key] = $extra[$key] }
    $state | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $path -Encoding UTF8
}
$blank = '', '', '', '', '', '', ''
switch ($scenario) {
    'starting' {
        Save 'starting' 'windows_services' '[3/7]' @('done','done','running','pending','pending','pending','pending') `
            @('','NetBird 私人 VPN 已就緒 100.107.93.232','','','','','') @{}
        Write-Host '[3/7] 檢查 PostgreSQL 服務與 NetBird 防火牆...'
        Start-Sleep -Seconds 600
    }
    'missing_software' {
        Save 'error' 'prerequisites' '缺少必要軟體，而且找不到 Windows 套件管理員 winget；請先從 Microsoft Store 安裝「應用程式安裝程式」。' `
            @('failed','pending','pending','pending','pending','pending','pending') @('缺少 PostgreSQL Server 18','','','','','','') `
            @{ missing_software = @('PostgreSQL Server 18'); winget_available = $false; software_check = 'missing'; netbird_ip = ''; api_url = '' }
        exit 1
    }
    'netbird' {
        Save 'error' 'netbird' 'NetBird 尚未登入或連線；請完成瀏覽器登入後再執行一次。' `
            @('done','failed','pending','pending','pending','pending','pending') @('','NetBird 尚未登入或連線','','','','','') @{ netbird_ip = ''; api_url = '' }
        exit 1
    }
    'no_accounts' {
        Save 'running' 'server' 'HTTPS 伺服器執行中。' `
            @('done','done','done','done','done','skipped','running') `
            @('','NetBird 私人 VPN 已就緒 100.107.93.232','PostgreSQL 服務 postgresql-x64-18 Running','資料庫連線正常','無待匯入遷移包、無密碼恢復要求','24 小時內已有備份，略過自動備份','啟動 HTTPS 伺服器…') `
            @{ account_count = 0 }
        Start-Sleep -Seconds 5
        Write-Host 'INFO:     Started server process [13800]'
        Start-Sleep -Seconds 600
    }
    default {
        Save 'running' 'server' 'HTTPS 伺服器執行中。' `
            @('done','done','done','done','done','skipped','running') `
            @('','NetBird 私人 VPN 已就緒 100.107.93.232','PostgreSQL 服務 postgresql-x64-18 Running','資料庫連線正常','無待匯入遷移包、無密碼恢復要求','24 小時內已有備份，略過自動備份','啟動 HTTPS 伺服器…') @{}
        Start-Sleep -Seconds 5
        Write-Host 'INFO:     Started server process [13800]'
        Start-Sleep -Seconds 600
    }
}
