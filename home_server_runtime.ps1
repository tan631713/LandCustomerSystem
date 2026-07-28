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
$protectedPostgresDsn = Join-Path $env:LOCALAPPDATA 'LandCustomerSystem\postgres-dsn.dpapi'
$certificateDirectory = Join-Path $env:LOCALAPPDATA 'LandCustomerSystem\certificates'
$serverCertificate = Join-Path $certificateDirectory 'land-customer-server-cert.pem'
$serverPrivateKey = Join-Path $certificateDirectory 'land-customer-server-key.pem'
$caCertificate = Join-Path $certificateDirectory 'land-customer-local-ca.cer'
$serverExecutable = Join-Path $packagePath 'LandCustomerServer\LandCustomerServer.exe'
$serverScript = Join-Path $packagePath 'start_api_server.py'
$pythonExecutable = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python314\python.exe'
$preflightScript = Join-Path $supportPath 'home_server_preflight.ps1'
$netBirdExecutable = Join-Path $env:ProgramFiles 'NetBird\netbird.exe'
$adminRecoveryRequest = Join-Path $packagePath 'recover-admin-password.request'

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
    recovery_account_status = 'not_found'
    recovery_account_username = ''
    admin_password_recovery = 'not_requested'
    migration_package_status = 'not_found'
    migration_package_name = ''
    migration_backup = ''
    schema_version = $null
    record_count = $null
    https_certificate = ''
    certificate_url = ''
    certificate_sha256 = ''
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
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        # Windows PowerShell 會把原生程式的 stderr 包裝成 ErrorRecord。
        # 維護命令以非零代碼回報「需要修復」是正常控制流程，不能在尚未
        # 取得 $LASTEXITCODE 前就被全域 Stop 設定中止。
        $ErrorActionPreference = 'Continue'
        if (Test-Path -LiteralPath $serverExecutable -PathType Leaf) {
            & $serverExecutable @Arguments 2>&1 | Out-Host
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
        & $script:pythonExecutable $serverScript @Arguments 2>&1 | Out-Host
        return [int]$LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
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

    $recoveryFiles = @(Get-ChildItem -LiteralPath $packagePath -Filter '*.lcs-account' -File -ErrorAction SilentlyContinue)
    if ($recoveryFiles.Count -gt 1) {
        throw '啟動檔旁有多個 .lcs-account 帳號恢復檔；請只保留本次要匯入的一個檔案。'
    }
    if ($recoveryFiles.Count -eq 1) {
        $state.recovery_account_status = 'pending'
        Save-Diagnostics
    }
    $adminRecoveryRequested = Test-Path -LiteralPath $adminRecoveryRequest -PathType Leaf
    if ($adminRecoveryRequested) {
        $state.admin_password_recovery = 'pending'
        Save-Diagnostics
    }
    $migrationFiles = @(Get-ChildItem -LiteralPath $packagePath -Filter '*.lcs-migration.zip' -File -ErrorAction SilentlyContinue)
    if ($migrationFiles.Count -gt 1) {
        throw '啟動檔旁有多個 .lcs-migration.zip；請只保留本次要匯入的一個遷移包。'
    }
    if ($migrationFiles.Count -eq 1) {
        $state.migration_package_status = 'pending'
        $state.migration_package_name = $migrationFiles[0].Name
        Save-Diagnostics
    }

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

    $script:existingServerProcess = $null
    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort 8732 -ErrorAction SilentlyContinue)
    if ($listeners.Count -gt 0) {
        if (Test-ExistingServer) {
            $script:existingServerProcess = [int]$listeners[0].OwningProcess
            if ($migrationFiles.Count -eq 1) {
                throw '偵測到待匯入的單機資料，但家中伺服器仍在執行。請關閉原本的伺服器視窗，再重新開啟本啟動檔。'
            }
            if ($recoveryFiles.Count -eq 0 -and -not $adminRecoveryRequested) {
                $state.status = 'already_running'
                $state.stage = 'ready'
                $state.message = '家中伺服器已在執行，不需要重複啟動。'
                $state.process_id = $script:existingServerProcess
                Save-Diagnostics
                Write-Host $state.message
                Write-Host "手機網址：$($state.api_url)"
                exit 0
            }
            Write-Host '家中伺服器已在執行；偵測到帳號恢復檔，將繼續處理帳號匯入。'
        }
        if (-not $script:existingServerProcess) {
            $owner = [int]$listeners[0].OwningProcess
            throw "連接埠 8732 已被其他程式占用（PID $owner），請關閉舊伺服器視窗後再試。"
        }
    }

    if ($Mode -eq 'Start' -and (Test-Path -LiteralPath $protectedPostgresDsn -PathType Leaf)) {
        Set-Stage -Name 'pre_upgrade_backup' -Description '[4/8] 升級前確認 PostgreSQL 完整備份...'
        $preUpgradeBackupCode = Invoke-ServerTool -Arguments @('--postgres', '--backup-if-due-hours', '24', '--backup-label', 'pre-upgrade')
        if ($preUpgradeBackupCode -ne 0) {
            Write-Warning '既有 PostgreSQL 連線設定無法完成備份，現在先修復專案帳號連線。'
            Write-Host '請輸入安裝 PostgreSQL 時設定的 postgres 管理密碼；系統不會顯示或保存這個密碼。'
            $repairCode = Invoke-ServerTool -Arguments @('--setup-postgresql')
            if ($repairCode -ne 0) {
                throw 'PostgreSQL 連線設定修復失敗，本次不會檢查或升級資料結構。'
            }
            $preUpgradeBackupCode = Invoke-ServerTool -Arguments @('--postgres', '--backup', '--backup-label', 'pre-upgrade-repaired')
            if ($preUpgradeBackupCode -ne 0) {
                throw '連線設定已修復，但升級前完整備份仍失敗，本次不會檢查或升級資料結構。'
            }
        }
        $state.backup_status = 'ok'
    }

    Set-Stage -Name 'database' -Description '[5/8] 檢查 PostgreSQL 專案資料庫...'
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

    if ($recoveryFiles.Count -eq 1) {
        if ($Mode -eq 'Check') {
            throw '偵測到待匯入的帳號恢復檔；請使用「啟動家中伺服器.bat」完成匯入。'
        }
        $recoveryFile = $recoveryFiles[0]
        Write-Host ''
        Write-Host "偵測到帳號恢復檔：$($recoveryFile.Name)" -ForegroundColor Yellow
        Write-Host '匯入只會新增一個登入帳號，不會覆蓋地主、土地、持分或案件資料。'
        $importAnswer = (Read-Host '是否現在匯入？請輸入 Y 或 N').Trim()
        if ($importAnswer -match '^(?i:y|yes|是)$') {
            $recoveryCode = Invoke-ServerTool -Arguments @(
                '--postgres', '--import-recovery-account', $recoveryFile.FullName
            )
            if ($recoveryCode -ne 0) {
                $state.recovery_account_status = 'error'
                Save-Diagnostics
                throw '帳號恢復檔匯入失敗；土地與客戶資料未被修改。'
            }
            $state.recovery_account_status = 'imported'
            $state.recovery_account_username = $recoveryFile.BaseName
            Save-Diagnostics
            Write-Host '帳號已安全匯入。請先用手機測試登入。' -ForegroundColor Green
            $deleteAnswer = (Read-Host '是否刪除已使用的帳號恢復檔？建議輸入 Y').Trim()
            if ($deleteAnswer -match '^(?i:y|yes|是)$') {
                Remove-Item -LiteralPath $recoveryFile.FullName -Force
                Write-Host '帳號恢復檔已刪除。'
            } else {
                Write-Warning '帳號恢復檔含有密碼雜湊，請移到安全的離線位置保存。'
            }
        } else {
            $state.recovery_account_status = 'declined'
            Save-Diagnostics
            Write-Warning '已略過帳號匯入；下次啟動仍會再次詢問。'
        }
    }

    if ($adminRecoveryRequested) {
        if ($Mode -eq 'Check') {
            throw '偵測到 admin 密碼恢復要求；請使用「啟動家中伺服器.bat」完成操作。'
        }
        Write-Host ''
        Write-Host '偵測到 admin 密碼恢復要求。' -ForegroundColor Yellow
        Write-Host '此操作只在家中主機本地執行，會先驗證既有帳號與資料金鑰。'
        Write-Host '不會修改地主、土地、持分、案件或附件資料。'
        $adminRecoveryAnswer = (Read-Host '是否現在重設 admin 密碼？請輸入 Y 或 N').Trim()
        if ($adminRecoveryAnswer -match '^(?i:y|yes|是)$') {
            $adminRecoveryCode = Invoke-ServerTool -Arguments @(
                '--postgres', '--recover-admin-password'
            )
            if ($adminRecoveryCode -ne 0) {
                $state.admin_password_recovery = 'error'
                Save-Diagnostics
                throw 'admin 密碼恢復失敗；原密碼與所有正式資料均未修改。'
            }
            $state.admin_password_recovery = 'complete'
            Save-Diagnostics
            Remove-Item -LiteralPath $adminRecoveryRequest -Force
            Write-Host 'admin 密碼已安全重設；恢復要求檔已自動刪除。' -ForegroundColor Green
        } else {
            $state.admin_password_recovery = 'declined'
            Save-Diagnostics
            Write-Warning '已略過 admin 密碼恢復；下次啟動仍會再次詢問。'
        }
    }

    if ($migrationFiles.Count -eq 1) {
        if ($Mode -eq 'Check') {
            throw '偵測到待匯入的單機資料遷移包；請使用「啟動家中伺服器.bat」完成匯入。'
        }
        $migrationFile = $migrationFiles[0]
        Write-Host ''
        Write-Host "偵測到單機資料遷移包：$($migrationFile.Name)" -ForegroundColor Yellow
        Write-Host '系統會先驗證單機帳號與家中伺服器 admin，並建立匯入前 PostgreSQL 備份。'
        Write-Host '家中伺服器的帳號與密碼會保留；單機資料會改用伺服器共用金鑰重新加密。'
        Write-Host '先前刪除測試資料留下的孤立地主／土地會安全清理；回收桶與操作紀錄會保留。'
        Write-Host '若伺服器已有正式業務資料，系統會停止，避免覆蓋或重複匯入。'
        $migrationAnswer = (Read-Host '是否現在匯入？請輸入 Y 或 N').Trim()
        if ($migrationAnswer -match '^(?i:y|yes|是)$') {
            $migrationCode = Invoke-ServerTool -Arguments @(
                '--postgres', '--import-migration-package', $migrationFile.FullName
            )
            if ($migrationCode -ne 0) {
                $state.migration_package_status = 'error'
                Save-Diagnostics
                throw '單機資料遷移失敗；請保留遷移包與診斷檔，原伺服器帳號未被覆蓋。'
            }
            $state.migration_package_status = 'imported'
            $state.migration_backup = Join-Path $env:LOCALAPPDATA 'LandCustomerSystem\postgres-backups'
            Save-Diagnostics
            Write-Host '單機資料已匯入並通過筆數與關聯驗證。' -ForegroundColor Green
            $deleteMigration = (Read-Host '是否刪除已使用的遷移包？建議驗證手機與筆電後再刪除，現在請輸入 Y 或 N').Trim()
            if ($deleteMigration -match '^(?i:y|yes|是)$') {
                Remove-Item -LiteralPath $migrationFile.FullName -Force
                Write-Host '遷移包已刪除。'
            } else {
                $migrationArchiveDirectory = Join-Path $env:LOCALAPPDATA 'LandCustomerSystem\migration-archives'
                New-Item -ItemType Directory -Path $migrationArchiveDirectory -Force | Out-Null
                $archivedMigration = Join-Path $migrationArchiveDirectory $migrationFile.Name
                if (Test-Path -LiteralPath $archivedMigration -PathType Leaf) {
                    $archiveStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
                    $archivedMigration = Join-Path $migrationArchiveDirectory ("{0}-{1}.zip" -f $migrationFile.BaseName, $archiveStamp)
                }
                Move-Item -LiteralPath $migrationFile.FullName -Destination $archivedMigration
                Write-Warning "遷移包已移到安全封存位置，避免下次重複匯入：$archivedMigration"
            }
        } else {
            $state.migration_package_status = 'declined'
            Save-Diagnostics
            Write-Warning '已略過資料遷移；下次啟動仍會再次詢問。'
        }
    }

    if ($script:existingServerProcess) {
        $state.status = 'already_running'
        $state.stage = 'ready'
        $state.message = '帳號處理完成；家中伺服器原本已在執行。'
        $state.process_id = $script:existingServerProcess
        Save-Diagnostics
        Write-Host $state.message
        Write-Host "手機網址：$($state.api_url)"
        exit 0
    }

    if ($Mode -eq 'Check') {
        $state.status = 'ok'
        $state.stage = 'complete'
        $state.message = '家中伺服器必要環境檢查完成。'
        Save-Diagnostics
        Write-Host $state.message
        exit 0
    }

    Set-Stage -Name 'https' -Description '[6/8] 建立包含目前 NetBird IP 的 HTTPS 憑證...'
    $httpsCode = Invoke-ServerTool -Arguments @('--setup-https', '--prefer-vpn')
    if ($httpsCode -ne 0 -or
        -not (Test-Path -LiteralPath $serverCertificate -PathType Leaf) -or
        -not (Test-Path -LiteralPath $serverPrivateKey -PathType Leaf)) {
        throw 'HTTPS 憑證建立失敗。'
    }
    $state.https_certificate = $serverCertificate
    if (Test-Path -LiteralPath $caCertificate -PathType Leaf) {
        $state.certificate_sha256 = (Get-FileHash -LiteralPath $caCertificate -Algorithm SHA256).Hash
    }
    Save-Diagnostics

    $state.certificate_url = "http://${vpnIp}:8733/"
    $script:certificateProcess = Start-CertificateService
    if ($script:certificateProcess) {
        Start-Sleep -Seconds 1
    }
    Save-Diagnostics

    Set-Stage -Name 'backup' -Description '[7/8] 檢查每日 PostgreSQL 備份...'
    $backupCode = Invoke-ServerTool -Arguments @('--postgres', '--backup-if-due-hours', '24', '--backup-label', 'auto')
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
    Write-Host "公開 CA SHA-256 指紋：$($state.certificate_sha256)"
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
