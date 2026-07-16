param(
    [Parameter(Mandatory = $true)]
    [string]$PackageRoot,
    [Parameter(Mandatory = $true)]
    [string]$SupportRoot,
    [ValidateSet('Start', 'Check')]
    [string]$Mode = 'Start'
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)

$packagePath = [IO.Path]::GetFullPath($PackageRoot)
$supportPath = [IO.Path]::GetFullPath($SupportRoot)
$diagnosticsPath = Join-Path $env:LOCALAPPDATA 'LandCustomerSystem\home-server-diagnostics.json'
$certificateDirectory = Join-Path $env:LOCALAPPDATA 'LandCustomerSystem\certificates'
$serverCertificate = Join-Path $certificateDirectory 'land-customer-server-cert.pem'
$serverPrivateKey = Join-Path $certificateDirectory 'land-customer-server-key.pem'
$serverExecutable = Join-Path $packagePath 'LandCustomerServer\LandCustomerServer.exe'
$serverScript = Join-Path $packagePath 'start_api_server.py'
$pythonExecutable = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python314\python.exe'
$preflightScript = Join-Path $supportPath 'home_server_preflight.ps1'
$netBirdExecutable = Join-Path $env:ProgramFiles 'NetBird\netbird.exe'

$state = [ordered]@{
    checked_at = [DateTimeOffset]::Now.ToString('o')
    status = 'starting'
    stage = 'initializing'
    message = ''
    software_check = 'not_checked'
    missing_software = @()
    install_decision = 'not_required'
    installed_software = @()
    winget_available = $false
    netbird_ip = ''
    netbird_allowed_range = '100.64.0.0/10'
    postgresql_service = ''
    postgresql_status = ''
    database_status = ''
    schema_version = $null
    record_count = $null
    https_certificate = ''
    certificate_url = ''
    backup_status = 'not_checked'
    api_url = ''
    process_id = $null
}

function Save-Diagnostics {
    $state.checked_at = [DateTimeOffset]::Now.ToString('o')
    $directory = Split-Path -Parent $diagnosticsPath
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    $state | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $diagnosticsPath -Encoding UTF8
}

function Set-Stage {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Description
    )
    $state.stage = $Name
    $state.message = $Description
    Save-Diagnostics
    Write-Host $Description
}

function Get-PostgreSqlService {
    return Get-Service -Name 'postgresql*' -ErrorAction SilentlyContinue |
        Sort-Object @{ Expression = { if ($_.Status -eq 'Running') { 0 } else { 1 } } }, Name |
        Select-Object -First 1
}

function Get-PostgreSqlBackupTool {
    $command = Get-Command pg_dump -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    $root = Join-Path $env:ProgramFiles 'PostgreSQL'
    if (-not (Test-Path -LiteralPath $root -PathType Container)) {
        return ''
    }
    $tool = Get-ChildItem -LiteralPath $root -Filter 'pg_dump.exe' -File -Recurse -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1
    if ($tool) {
        return $tool.FullName
    }
    return ''
}

function Get-PrerequisiteState {
    $missing = [Collections.Generic.List[object]]::new()
    $postgresService = Get-PostgreSqlService
    $postgresBackupTool = Get-PostgreSqlBackupTool
    if (-not (Test-Path -LiteralPath $netBirdExecutable -PathType Leaf)) {
        $missing.Add([PSCustomObject]@{
            Key = 'netbird'
            Name = 'NetBird 私人 VPN'
            Reason = '手機與公司筆電需要透過私人 VPN 連回家中主機。'
        })
    }
    if (-not $postgresService) {
        $missing.Add([PSCustomObject]@{
            Key = 'postgresql'
            Name = 'PostgreSQL Server 18'
            Reason = '正式地主、土地、持分與聯絡資料儲存在 PostgreSQL。'
        })
    } elseif (-not $postgresBackupTool) {
        $missing.Add([PSCustomObject]@{
            Key = 'postgresql_tools'
            Name = 'PostgreSQL pg_dump 備份工具'
            Reason = '每日壓縮備份需要 PostgreSQL 官方 pg_dump。'
        })
    }
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    return [PSCustomObject]@{
        Missing = @($missing)
        Winget = $winget
        PostgreSqlService = $postgresService
        PostgreSqlBackupTool = $postgresBackupTool
    }
}

function Confirm-PrerequisiteInstallation {
    param([Parameter(Mandatory = $true)][object[]]$Missing)
    Write-Host ''
    Write-Host '偵測到尚未安裝的必要軟體：' -ForegroundColor Yellow
    for ($index = 0; $index -lt $Missing.Count; $index++) {
        Write-Host ("  {0}. {1}" -f ($index + 1), $Missing[$index].Name)
        Write-Host ("     {0}" -f $Missing[$index].Reason)
    }
    Write-Host ''
    $answer = (Read-Host '是否現在由系統協助安裝以上軟體？請輸入 Y 或 N').Trim()
    return $answer -match '^(?i:y|yes|是)$'
}

function Resolve-PostgreSqlWingetId {
    param([Parameter(Mandatory = $true)]$Winget)
    foreach ($candidate in @(
        'PostgreSQL.PostgreSQL.18',
        'PostgreSQL.PostgreSQL.17',
        'PostgreSQL.PostgreSQL.16'
    )) {
        & $Winget.Source show --id $candidate --exact --source winget --accept-source-agreements *> $null
        if ($LASTEXITCODE -eq 0) {
            return $candidate
        }
    }
    throw 'Windows 套件來源中找不到可用的 PostgreSQL 安裝套件。'
}

function Install-WingetPackage {
    param(
        [Parameter(Mandatory = $true)]$Winget,
        [Parameter(Mandatory = $true)][string]$PackageId,
        [switch]$Interactive,
        [switch]$Force
    )
    $arguments = [Collections.Generic.List[string]]::new()
    foreach ($value in @(
        'install', '--id', $PackageId, '--exact', '--source', 'winget',
        '--accept-package-agreements', '--accept-source-agreements'
    )) {
        $arguments.Add($value)
    }
    if ($Interactive) {
        $arguments.Add('--interactive')
    } else {
        $arguments.Add('--silent')
    }
    if ($Force) {
        $arguments.Add('--force')
    }
    & $Winget.Source @arguments | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "必要軟體安裝失敗：$PackageId（錯誤代碼 $LASTEXITCODE）。"
    }
}

function Install-MissingPrerequisites {
    param(
        [Parameter(Mandatory = $true)][object[]]$Missing,
        [Parameter(Mandatory = $true)]$Winget
    )
    $installed = [Collections.Generic.List[string]]::new()
    $keys = @($Missing | ForEach-Object { $_.Key })
    if ($keys -contains 'netbird') {
        Write-Host '正在安裝 NetBird 官方用戶端...'
        Install-WingetPackage -Winget $Winget -PackageId 'Netbird.Netbird'
        $installed.Add('NetBird 私人 VPN')
    }
    if ($keys -contains 'postgresql' -or $keys -contains 'postgresql_tools') {
        $postgresPackage = Resolve-PostgreSqlWingetId -Winget $Winget
        Write-Host '即將開啟 PostgreSQL 官方互動安裝程式。'
        Write-Host '請自行設定並記住 postgres 管理員密碼；系統不會保存這個密碼。'
        Install-WingetPackage `
            -Winget $Winget `
            -PackageId $postgresPackage `
            -Interactive `
            -Force:($keys -contains 'postgresql_tools')
        $installed.Add('PostgreSQL Server 與備份工具')
    }
    return @($installed)
}

function Get-NetBirdIp {
    if (-not (Test-Path -LiteralPath $netBirdExecutable -PathType Leaf)) {
        return ''
    }
    $lines = @(& $netBirdExecutable status --ipv4 2>$null)
    foreach ($line in $lines) {
        $candidate = ([string]$line).Trim()
        $address = $null
        if (-not [Net.IPAddress]::TryParse($candidate, [ref]$address)) {
            continue
        }
        $bytes = $address.GetAddressBytes()
        if ($bytes.Length -eq 4 -and $bytes[0] -eq 100 -and $bytes[1] -ge 64 -and $bytes[1] -le 127) {
            return $candidate
        }
    }
    return ''
}

function Invoke-ServerTool {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    if (Test-Path -LiteralPath $serverExecutable -PathType Leaf) {
        & $serverExecutable @Arguments | Out-Host
        return [int]$LASTEXITCODE
    }
    if (-not (Test-Path -LiteralPath $pythonExecutable -PathType Leaf)) {
        $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if ($pythonCommand) {
            $script:pythonExecutable = $pythonCommand.Source
        }
    }
    if (-not (Test-Path -LiteralPath $serverScript -PathType Leaf) -or -not $script:pythonExecutable) {
        throw '找不到 LandCustomerServer.exe，伺服器封裝可能不完整。'
    }
    & $script:pythonExecutable $serverScript @Arguments | Out-Host
    return [int]$LASTEXITCODE
}

function Test-ExistingServer {
    $previousCallback = [Net.ServicePointManager]::ServerCertificateValidationCallback
    try {
        [Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
        $health = Invoke-RestMethod -Uri 'https://127.0.0.1:8732/health' -TimeoutSec 5
        return $health.status -eq 'ok' -and $health.backend -eq 'postgresql'
    } catch {
        return $false
    } finally {
        [Net.ServicePointManager]::ServerCertificateValidationCallback = $previousCallback
    }
}

function Start-CertificateService {
    $existing = @(Get-NetTCPConnection -State Listen -LocalPort 8733 -ErrorAction SilentlyContinue)
    if ($existing.Count -gt 0) {
        return $null
    }
    if (Test-Path -LiteralPath $serverExecutable -PathType Leaf) {
        return Start-Process -FilePath $serverExecutable `
            -ArgumentList '--install-iphone-certificate --prefer-vpn' `
            -NoNewWindow -PassThru
    }
    if (Test-Path -LiteralPath $serverScript -PathType Leaf -and $script:pythonExecutable) {
        $arguments = ('"{0}" --install-iphone-certificate --prefer-vpn' -f $serverScript)
        return Start-Process -FilePath $script:pythonExecutable `
            -ArgumentList $arguments -NoNewWindow -PassThru
    }
    return $null
}

try {
    Save-Diagnostics

    Set-Stage -Name 'prerequisites' -Description '[1/7] 檢查必要軟體...'
    $prerequisites = Get-PrerequisiteState
    $state.winget_available = [bool]$prerequisites.Winget
    $state.missing_software = @($prerequisites.Missing | ForEach-Object { $_.Name })
    $state.software_check = if ($prerequisites.Missing.Count -eq 0) { 'ok' } else { 'missing' }
    Save-Diagnostics
    if ($prerequisites.Missing.Count -gt 0) {
        if ($Mode -eq 'Check') {
            throw ("缺少必要軟體：{0}。" -f ($state.missing_software -join '、'))
        }
        if (-not $prerequisites.Winget) {
            $state.install_decision = 'unavailable'
            Save-Diagnostics
            throw '缺少必要軟體，而且找不到 Windows 套件管理員 winget；請先從 Microsoft Store 安裝「應用程式安裝程式」。'
        }
        if (-not (Confirm-PrerequisiteInstallation -Missing $prerequisites.Missing)) {
            $state.install_decision = 'declined'
            Save-Diagnostics
            throw '使用者選擇不安裝必要軟體，伺服器未啟動。'
        }
        $state.install_decision = 'approved'
        Save-Diagnostics
        $state.installed_software = @(Install-MissingPrerequisites `
            -Missing $prerequisites.Missing `
            -Winget $prerequisites.Winget)
        $verifiedPrerequisites = Get-PrerequisiteState
        $state.missing_software = @($verifiedPrerequisites.Missing | ForEach-Object { $_.Name })
        if ($verifiedPrerequisites.Missing.Count -gt 0) {
            Save-Diagnostics
            throw ("安裝完成後仍缺少：{0}。請重新啟動 Windows 後再試。" -f ($state.missing_software -join '、'))
        }
        $state.software_check = 'ok'
        Save-Diagnostics
    }

    Set-Stage -Name 'netbird' -Description '[2/7] 檢查 NetBird 私人 VPN...'
    $vpnIp = Get-NetBirdIp
    if (-not $vpnIp -and $Mode -eq 'Start') {
        Write-Host 'NetBird 尚未登入，接下來會開啟官方登入頁。'
        & $netBirdExecutable up | Out-Host
        for ($attempt = 0; $attempt -lt 10 -and -not $vpnIp; $attempt++) {
            Start-Sleep -Seconds 2
            $vpnIp = Get-NetBirdIp
        }
    }
    if (-not $vpnIp) {
        throw 'NetBird 尚未登入或連線；請完成瀏覽器登入後再執行一次。'
    }
    $state.netbird_ip = $vpnIp
    $state.api_url = "https://${vpnIp}:8732/mobile/"
    Save-Diagnostics
    Write-Host "NetBird IP：$vpnIp"

    Set-Stage -Name 'windows_services' -Description '[3/7] 檢查 PostgreSQL 服務與 NetBird 防火牆...'
    if (-not (Test-Path -LiteralPath $preflightScript -PathType Leaf)) {
        throw '找不到伺服器環境檢查檔，封裝可能不完整。'
    }
    & (Join-Path $PSHOME 'powershell.exe') -NoProfile -ExecutionPolicy Bypass -File $preflightScript -Mode Check | Out-Host
    $preflightCode = $LASTEXITCODE
    if ($preflightCode -eq 10 -and $Mode -eq 'Start') {
        Write-Host '需要啟動 PostgreSQL 或更新防火牆，請在權限視窗按「是」。'
        & (Join-Path $PSHOME 'powershell.exe') -NoProfile -ExecutionPolicy Bypass -File $preflightScript -Mode Repair | Out-Host
        $preflightCode = $LASTEXITCODE
    }
    if ($preflightCode -eq 20) {
        throw '找不到 PostgreSQL Windows 服務，請先安裝 PostgreSQL。'
    }
    if ($preflightCode -ne 0) {
        throw 'PostgreSQL 服務或 NetBird 防火牆檢查未通過。'
    }
    $postgresService = Get-Service -Name 'postgresql*' -ErrorAction SilentlyContinue |
        Sort-Object Name | Select-Object -First 1
    if ($postgresService) {
        $state.postgresql_service = $postgresService.Name
        $state.postgresql_status = [string]$postgresService.Status
    }
    Save-Diagnostics

    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort 8732 -ErrorAction SilentlyContinue)
    if ($listeners.Count -gt 0) {
        if (Test-ExistingServer) {
            $state.status = 'already_running'
            $state.stage = 'ready'
            $state.message = '家中伺服器已在執行，不需要重複啟動。'
            $state.process_id = [int]$listeners[0].OwningProcess
            Save-Diagnostics
            Write-Host $state.message
            Write-Host "手機網址：$($state.api_url)"
            exit 0
        }
        $owner = [int]$listeners[0].OwningProcess
        throw "連接埠 8732 已被其他程式占用（PID $owner），請關閉舊伺服器視窗後再試。"
    }

    Set-Stage -Name 'database' -Description '[4/7] 檢查 PostgreSQL 專案資料庫...'
    $databaseCode = Invoke-ServerTool -Arguments @('--postgres', '--check')
    if ($databaseCode -ne 0 -and $Mode -eq 'Start') {
        Write-Host '尚未完成這台 Windows 使用者的資料庫設定，現在進行一次性設定。'
        $setupCode = Invoke-ServerTool -Arguments @('--setup-postgresql')
        if ($setupCode -ne 0) {
            throw 'PostgreSQL 專案資料庫設定失敗。'
        }
        $databaseCode = Invoke-ServerTool -Arguments @('--postgres', '--check')
    }
    if ($databaseCode -ne 0) {
        throw 'PostgreSQL 專案資料庫檢查失敗。'
    }
    $state.database_status = 'ok'
    Save-Diagnostics

    if ($Mode -eq 'Check') {
        $state.status = 'ok'
        $state.stage = 'complete'
        $state.message = '家中伺服器必要環境檢查完成。'
        Save-Diagnostics
        Write-Host $state.message
        exit 0
    }

    Set-Stage -Name 'https' -Description '[5/7] 建立包含目前 NetBird IP 的 HTTPS 憑證...'
    $httpsCode = Invoke-ServerTool -Arguments @('--setup-https', '--prefer-vpn')
    if ($httpsCode -ne 0 -or
        -not (Test-Path -LiteralPath $serverCertificate -PathType Leaf) -or
        -not (Test-Path -LiteralPath $serverPrivateKey -PathType Leaf)) {
        throw 'HTTPS 憑證建立失敗。'
    }
    $state.https_certificate = $serverCertificate
    Save-Diagnostics

    $state.certificate_url = "http://${vpnIp}:8733/"
    $script:certificateProcess = Start-CertificateService
    if ($script:certificateProcess) {
        Start-Sleep -Seconds 1
    }
    Save-Diagnostics

    Set-Stage -Name 'backup' -Description '[6/7] 檢查每日 PostgreSQL 備份...'
    $backupCode = Invoke-ServerTool -Arguments @('--backup-if-due-hours', '24', '--backup-label', 'auto')
    if ($backupCode -eq 0) {
        $state.backup_status = 'ok'
    } else {
        $state.backup_status = 'warning'
        Write-Warning '自動備份未完成；資料庫可用，因此本次仍會啟動伺服器。請稍後檢查備份設定。'
    }
    Save-Diagnostics

    Set-Stage -Name 'server' -Description '[7/7] 啟動 HTTPS 伺服器...'
    Write-Host ''
    Write-Host 'NetBird 私人 VPN 已就緒。'
    Write-Host "手機瀏覽器：$($state.api_url)"
    Write-Host "iPhone 首次安裝公開憑證：$($state.certificate_url)"
    Write-Host '公司筆電請使用同一個 NetBird 帳號及新版客戶端。'
    Write-Host '請勿在路由器開放 8732、8733 或 PostgreSQL 5432。'
    Write-Host ''
    $state.status = 'running'
    $state.message = 'HTTPS 伺服器執行中。'
    Save-Diagnostics
    $serverCode = Invoke-ServerTool -Arguments @(
        '--postgres', '--lan', '--prefer-vpn',
        '--ssl-certfile', $serverCertificate,
        '--ssl-keyfile', $serverPrivateKey
    )
    if ($serverCode -ne 0) {
        throw "伺服器意外停止，錯誤代碼：$serverCode。"
    }
    if ($script:certificateProcess -and -not $script:certificateProcess.HasExited) {
        Stop-Process -Id $script:certificateProcess.Id -Force -ErrorAction SilentlyContinue
    }
    $state.status = 'stopped'
    $state.stage = 'complete'
    $state.message = '家中伺服器已正常停止。'
    Save-Diagnostics
    exit 0
} catch {
    if ($script:certificateProcess -and -not $script:certificateProcess.HasExited) {
        Stop-Process -Id $script:certificateProcess.Id -Force -ErrorAction SilentlyContinue
    }
    $state.status = 'error'
    $state.message = $_.Exception.Message
    Save-Diagnostics
    Write-Host ''
    Write-Error $state.message
    Write-Host "診斷檔：$diagnosticsPath"
    exit 1
}
