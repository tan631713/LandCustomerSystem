param(
    [ValidateSet('Check', 'Repair')]
    [string]$Mode = 'Check',
    [switch]$Elevated
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)

$script:ExitReady = 0
$script:ExitFailed = 1
$script:ExitNeedsRepair = 10
$script:ExitPostgreSqlMissing = 20
$script:ExitNetBirdUnavailable = 30

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-NetBirdContext {
    $netBirdExe = Join-Path $env:ProgramFiles 'NetBird\netbird.exe'
    if (-not (Test-Path -LiteralPath $netBirdExe -PathType Leaf)) {
        return $null
    }

    $vpnIpText = (& $netBirdExe status --ipv4 2>$null | Select-Object -First 1)
    if (-not $vpnIpText) {
        return $null
    }
    $vpnIpText = $vpnIpText.Trim()
    $vpnIp = $null
    if (-not [Net.IPAddress]::TryParse($vpnIpText, [ref]$vpnIp)) {
        return $null
    }
    $bytes = $vpnIp.GetAddressBytes()
    if ($bytes.Length -ne 4 -or $bytes[0] -ne 100 -or $bytes[1] -lt 64 -or $bytes[1] -gt 127) {
        return $null
    }

    return [PSCustomObject]@{
        Ip = $vpnIpText
        Range = '100.64.0.0/10'
    }
}

function Get-PostgreSqlService {
    return Get-Service -Name 'postgresql*' -ErrorAction SilentlyContinue |
        Sort-Object @{ Expression = { if ($_.Status -eq 'Running') { 0 } else { 1 } } }, Name |
        Select-Object -First 1
}

function Test-FirewallRule {
    param(
        [Parameter(Mandatory = $true)]
        [string]$DisplayName,
        [Parameter(Mandatory = $true)]
        [int]$Port,
        [Parameter(Mandatory = $true)]
        [string]$RemoteRange
    )

    try {
        $rules = @(Get-NetFirewallRule -DisplayName $DisplayName -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Enabled -eq 'True' -and
                $_.Direction -eq 'Inbound' -and
                $_.Action -eq 'Allow'
            })
        foreach ($rule in $rules) {
            $portFilters = @($rule | Get-NetFirewallPortFilter -ErrorAction Stop)
            $addressFilters = @($rule | Get-NetFirewallAddressFilter -ErrorAction Stop)
            $hasPort = $portFilters | Where-Object {
                [string]$_.Protocol -eq 'TCP' -and
                @([string[]]$_.LocalPort) -contains [string]$Port
            }
            $remoteRangeWithMask = $RemoteRange -replace '/10$', '/255.192.0.0'
            $hasRange = $addressFilters | Where-Object {
                $remoteAddresses = @([string[]]$_.RemoteAddress)
                $remoteAddresses -contains $RemoteRange -or
                    $remoteAddresses -contains $remoteRangeWithMask
            }
            if ($hasPort -and $hasRange) {
                return $true
            }
        }
    } catch {
        return $false
    }
    return $false
}

function Get-PreflightState {
    $netBird = Get-NetBirdContext
    if (-not $netBird) {
        return [PSCustomObject]@{
            ExitCode = $script:ExitNetBirdUnavailable
            NetBird = $null
            PostgreSql = $null
            Reasons = @('NetBird 尚未安裝、登入或連線。')
        }
    }

    $postgres = Get-PostgreSqlService
    if (-not $postgres) {
        return [PSCustomObject]@{
            ExitCode = $script:ExitPostgreSqlMissing
            NetBird = $netBird
            PostgreSql = $null
            Reasons = @('找不到 PostgreSQL Windows 服務。')
        }
    }

    $reasons = [Collections.Generic.List[string]]::new()
    if ($postgres.Status -ne 'Running') {
        $reasons.Add("PostgreSQL 服務 $($postgres.Name) 尚未啟動。")
    }

    $firewallRules = @(
        @{ Name = 'Land Customer System NetBird HTTPS'; Port = 8732 },
        @{ Name = 'Land Customer System NetBird Certificate'; Port = 8733 }
    )
    foreach ($definition in $firewallRules) {
        if (-not (Test-FirewallRule -DisplayName $definition.Name -Port $definition.Port -RemoteRange $netBird.Range)) {
            $reasons.Add("缺少或需要更新防火牆規則：$($definition.Name)。")
        }
    }

    return [PSCustomObject]@{
        ExitCode = if ($reasons.Count -eq 0) { $script:ExitReady } else { $script:ExitNeedsRepair }
        NetBird = $netBird
        PostgreSql = $postgres
        Reasons = @($reasons)
    }
}

function Write-State {
    param([Parameter(Mandatory = $true)]$State)

    if ($State.NetBird) {
        Write-Output "NetBird IP：$($State.NetBird.Ip)"
    }
    if ($State.PostgreSql) {
        Write-Output "PostgreSQL 服務：$($State.PostgreSql.Name) ($($State.PostgreSql.Status))"
    }
    foreach ($reason in $State.Reasons) {
        Write-Output $reason
    }
}

if ($Mode -eq 'Check') {
    $state = Get-PreflightState
    Write-State -State $state
    exit $state.ExitCode
}

if (-not (Test-IsAdministrator)) {
    if ($Elevated) {
        Write-Error '無法取得系統管理員權限。'
        exit $script:ExitFailed
    }

    $argumentLine = '-NoProfile -ExecutionPolicy Bypass -File "{0}" -Mode Repair -Elevated' -f $PSCommandPath
    try {
        $process = Start-Process `
            -FilePath (Join-Path $PSHOME 'powershell.exe') `
            -ArgumentList $argumentLine `
            -Verb RunAs `
            -Wait `
            -PassThru
        exit $process.ExitCode
    } catch {
        Write-Error '系統管理員授權已取消，無法修復服務或防火牆設定。'
        exit $script:ExitFailed
    }
}

try {
    $state = Get-PreflightState
    if ($state.ExitCode -eq $script:ExitNetBirdUnavailable -or
        $state.ExitCode -eq $script:ExitPostgreSqlMissing) {
        Write-State -State $state
        exit $state.ExitCode
    }

    if ($state.PostgreSql.Status -ne 'Running') {
        Write-Output "正在啟動 PostgreSQL 服務：$($state.PostgreSql.Name)"
        Start-Service -Name $state.PostgreSql.Name
        (Get-Service -Name $state.PostgreSql.Name).WaitForStatus('Running', [TimeSpan]::FromSeconds(30))
    }

    Write-Output '正在建立只允許 NetBird 私人網路的防火牆規則...'
    & (Join-Path $PSScriptRoot 'configure_netbird_firewall.ps1')

    $verified = Get-PreflightState
    Write-State -State $verified
    if ($verified.ExitCode -ne $script:ExitReady) {
        Write-Error '修復完成後重新檢查仍未通過。'
        exit $script:ExitFailed
    }
    exit $script:ExitReady
} catch {
    Write-Error ("家中伺服器環境修復失敗：{0}" -f $_.Exception.Message)
    exit $script:ExitFailed
}
