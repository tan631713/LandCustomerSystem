param(
    [string]$ServerClientRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$LineBotRoot = "C:\Users\Laptop\Documents\Codex\2026-06-24\new-chat\line_bot_test",
    [string]$OutputDirectory = ""
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$ServerClientRoot = [IO.Path]::GetFullPath($ServerClientRoot)
$LineBotRoot = [IO.Path]::GetFullPath($LineBotRoot)
if (-not (Test-Path -LiteralPath $ServerClientRoot -PathType Container)) {
    throw "Server/client source directory does not exist: $ServerClientRoot"
}
if (-not (Test-Path -LiteralPath $LineBotRoot -PathType Container)) {
    throw "LINE Bot source directory does not exist: $LineBotRoot"
}
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $ServerClientRoot "releases\source-archives"
}
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null

$blockedExtensions = @(
    ".db", ".sqlite", ".sqlite3", ".pem", ".key", ".crt", ".cer",
    ".pfx", ".p12", ".dpapi", ".bin", ".lcsline", ".zip", ".7z",
    ".rar", ".exe", ".dll", ".pyd", ".pyc", ".log", ".sha256"
)
$commonExcludedDirs = @(
    ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "graphify-out"
)
$serverExcludedDirs = $commonExcludedDirs + @(
    ".test-runtime", ".build-preserved-data", "attachments", "backups",
    "build", "dist", "releases", "output", "test-artifacts", "tmp",
    "logs", "LandCustomerSystem"
)
$lineExcludedDirs = $commonExcludedDirs + @(
    ".tools", ".venv", "venv", "logs", "releases", "htmlcov"
)
$blockedFileNames = @(
    "customers.db", "desktop-client-settings.db", "company-client-config.json",
    "home_server_ip.txt", "home-server-diagnostics.json",
    "client-network-diagnostics.json", "local-postgres-setup-report.json",
    "postgres-migration-report.json"
)

function Get-SafeSourceFiles([string]$Root, [string]$Kind) {
    $rootPrefix = $Root.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    $excludedDirs = if ($Kind -eq "server-client") { $serverExcludedDirs } else { $lineExcludedDirs }
    $files = [System.Collections.Generic.List[object]]::new()
    foreach ($file in Get-ChildItem -LiteralPath $Root -Recurse -Force -File) {
        if (-not $file.FullName.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            continue
        }
        $relative = $file.FullName.Substring($rootPrefix.Length)
        $parts = @($relative -split "[\\/]")
        $directoryParts = if ($parts.Count -gt 1) { @($parts[0..($parts.Count - 2)]) } else { @() }
        if (@($directoryParts | Where-Object { $excludedDirs -contains $_ }).Count -gt 0) {
            continue
        }
        # Keep the LINE Bot's synthetic test fixture, but exclude runtime binding state.
        if (
            $Kind -eq "line-bot" -and
            $parts.Count -gt 1 -and
            $parts[0] -eq "data" -and
            $relative -ne "data\fake_data.json"
        ) {
            continue
        }
        $nameLower = $file.Name.ToLowerInvariant()
        $extensionLower = $file.Extension.ToLowerInvariant()
        if ($blockedExtensions -contains $extensionLower) { continue }
        if ($nameLower -match "\.(db|sqlite|sqlite3)(-.+)?$") { continue }
        if ($blockedFileNames -contains $nameLower) { continue }
        if ($nameLower -eq ".env") { continue }
        if ($nameLower -like ".env.*" -and $nameLower -ne ".env.example") { continue }
        if ($nameLower -like "release-acceptance*.json") { continue }
        if ($nameLower -like "*diagnostics*.json") { continue }
        $files.Add(
            [PSCustomObject]@{
                Root = $Root
                Kind = $Kind
                File = $file
                Relative = $relative
            }
        )
    }
    return $files
}

function Get-PythonVersionValue([string]$Path, [string]$Variable) {
    $content = [IO.File]::ReadAllText($Path)
    $match = [regex]::Match(
        $content,
        '(?m)^' + [regex]::Escape($Variable) + '\s*=\s*["'']([^"'']+)["'']'
    )
    if (-not $match.Success) { return "unknown" }
    return $match.Groups[1].Value
}

$serverFiles = @(Get-SafeSourceFiles $ServerClientRoot "server-client")
$lineFiles = @(Get-SafeSourceFiles $LineBotRoot "line-bot")
$allFiles = @($serverFiles + $lineFiles)
if ($serverFiles.Count -eq 0 -or $lineFiles.Count -eq 0) {
    throw "Source file discovery returned an empty project."
}

$textExtensions = @(
    ".py", ".ps1", ".bat", ".cmd", ".sql", ".txt", ".md", ".json",
    ".toml", ".ini", ".cfg", ".yaml", ".yml", ".js", ".css", ".html",
    ".xml", ".spec", ".example"
)
$secretPatterns = @(
    "-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    "(?<![A-Za-z0-9_])(?:sk|ghp)_[A-Za-z0-9_-]{20,}",
    "(?<![A-Za-z0-9_])github_pat_[A-Za-z0-9_]{20,}",
    "(?<![A-Za-z0-9_])AKIA[0-9A-Z]{16}"
)
$secretHits = [System.Collections.Generic.List[string]]::new()
foreach ($item in $allFiles) {
    $extension = $item.File.Extension.ToLowerInvariant()
    if (
        -not ($textExtensions -contains $extension) -and
        -not ($item.File.Name -in @(".gitignore", ".gitattributes", ".env.example"))
    ) {
        continue
    }
    try {
        $content = [IO.File]::ReadAllText($item.File.FullName)
    } catch {
        continue
    }
    foreach ($pattern in $secretPatterns) {
        if ($content -match $pattern) {
            $secretHits.Add("$($item.Kind)/$($item.Relative)")
            break
        }
    }
}
if ($secretHits.Count -gt 0) {
    throw "Potential embedded secrets found in: $((($secretHits | Sort-Object -Unique) -join ', '))"
}

$serverVersionFile = Join-Path $ServerClientRoot "customer_version.py"
$lineVersionFile = Join-Path $LineBotRoot "app.py"
$serverVersion = Get-PythonVersionValue $serverVersionFile "APP_VERSION"
$clientVersion = Get-PythonVersionValue $serverVersionFile "DESKTOP_CLIENT_VERSION"
$lineVersion = Get-PythonVersionValue $lineVersionFile "APP_VERSION"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$bundleName = "LandCustomerSystem-All-Source-server-client-linebot-$stamp"
$zipPath = Join-Path $OutputDirectory "$bundleName.zip"
$checksumPath = Join-Path $OutputDirectory "$bundleName.sha256.txt"
if (Test-Path -LiteralPath $zipPath) {
    throw "Archive already exists: $zipPath"
}

$manifestFiles = [System.Collections.Generic.List[object]]::new()
$archive = [IO.Compression.ZipFile]::Open(
    $zipPath,
    [System.IO.Compression.ZipArchiveMode]::Create
)
try {
    foreach ($item in ($allFiles | Sort-Object Kind, Relative)) {
        $subfolder = if ($item.Kind -eq "server-client") { "01-server-client" } else { "02-line-bot" }
        $entryRelative = $item.Relative.Replace("\", "/")
        $entryName = "$bundleName/$subfolder/$entryRelative"
        [IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $archive,
            $item.File.FullName,
            $entryName,
            [IO.Compression.CompressionLevel]::Optimal
        ) | Out-Null
        $manifestFiles.Add(
            [PSCustomObject]@{
                project = $item.Kind
                path = $entryRelative
                bytes = $item.File.Length
                sha256 = (Get-FileHash -LiteralPath $item.File.FullName -Algorithm SHA256).Hash
            }
        )
    }

    $manifest = [ordered]@{
        package = $bundleName
        created_at = (Get-Date).ToUniversalTime().ToString("o")
        server_version = $serverVersion
        desktop_client_version = $clientVersion
        line_bot_version = $lineVersion
        source_layout = [ordered]@{
            "01-server-client" = "Home server and Windows desktop client shared working-tree source"
            "02-line-bot" = "LINE Bot working-tree source"
        }
        includes_uncommitted_working_tree_changes = $true
        server_client_file_count = $serverFiles.Count
        line_bot_file_count = $lineFiles.Count
        excluded = @(
            "customer databases and LINE binding state",
            "attachments, backups and logs",
            "credentials, .env files, certificates and protected DSNs",
            "build, dist, releases, executables and binary dependencies",
            "Git metadata, caches and Graphify generated output"
        )
        files = $manifestFiles
    }
    $manifestEntry = $archive.CreateEntry(
        "$bundleName/SOURCE_FILE_MANIFEST.json",
        [IO.Compression.CompressionLevel]::Optimal
    )
    $manifestWriter = [IO.StreamWriter]::new(
        $manifestEntry.Open(),
        [Text.UTF8Encoding]::new($false)
    )
    try {
        $manifestWriter.Write(($manifest | ConvertTo-Json -Depth 6))
    } finally {
        $manifestWriter.Dispose()
    }

    $readme = @(
        "Land Customer System - Complete Source Archive",
        "",
        "01-server-client: shared source for the home server and Windows desktop client.",
        "02-line-bot: LINE Bot source.",
        "",
        "This archive preserves current working-tree changes.",
        "It excludes customer databases, attachments, backups, logs, LINE binding state, .env files, passwords, certificates, private keys, protected database settings, executables, and old release archives.",
        "Before deployment, follow each project README and create machine-specific settings and certificates.",
        ""
    ) -join "`r`n"
    $readmeEntry = $archive.CreateEntry(
        "$bundleName/README_SOURCE_ARCHIVE.txt",
        [IO.Compression.CompressionLevel]::Optimal
    )
    $readmeWriter = [IO.StreamWriter]::new(
        $readmeEntry.Open(),
        [Text.UTF8Encoding]::new($false)
    )
    try {
        $readmeWriter.Write($readme)
    } finally {
        $readmeWriter.Dispose()
    }
} finally {
    $archive.Dispose()
}

$hash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash
[IO.File]::WriteAllText(
    $checksumPath,
    "$hash  $([IO.Path]::GetFileName($zipPath))`r`n",
    [Text.Encoding]::ASCII
)
[PSCustomObject]@{
    ZipPath = $zipPath
    ChecksumPath = $checksumPath
    ServerVersion = $serverVersion
    DesktopClientVersion = $clientVersion
    LineBotVersion = $lineVersion
    ServerClientFiles = $serverFiles.Count
    LineBotFiles = $lineFiles.Count
    TotalSourceFiles = $allFiles.Count
    ZipBytes = (Get-Item -LiteralPath $zipPath).Length
    SHA256 = $hash
}
