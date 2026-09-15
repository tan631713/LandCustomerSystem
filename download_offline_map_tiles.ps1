# Downloads every tile listed in offline_tile_manifest.txt into
# offline_map_tiles\{z}\{x}\{y}.png, next to this script.
#
# Run this ONCE on the actual company laptop (not on a dev machine, and
# not as part of building/packaging a release -- see
# customer_offline_map.py's module docstring for why this stays a
# separate, one-time step). Safe to re-run: already-downloaded tiles are
# skipped, so an interrupted run just picks up where it left off.
#
# Deliberately uses curl.exe (built into Windows 10/11), not
# Invoke-WebRequest and not a Python script -- two real findings from
# building this feature:
#   1. The company laptop this runs on has no Python installed at all;
#      it only runs the packaged EXE.
#   2. 國土測繪中心's WMTS server has a certificate that Python's own
#      ssl module rejects (a missing Subject Key Identifier extension),
#      while curl.exe -- via Windows' own certificate trust -- and every
#      normal browser accept it fine. Rather than have this script
#      quietly disable certificate verification to route around that,
#      it uses the client that already validates it correctly.

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$manifestPath = Join-Path $scriptDir "offline_tile_manifest.txt"
$tileRoot = Join-Path $scriptDir "offline_map_tiles"

if (-not (Test-Path $manifestPath)) {
    Write-Host "找不到 offline_tile_manifest.txt，請確認這個檔案跟本腳本放在同一個資料夾。"
    exit 1
}

$curl = "$env:WINDIR\System32\curl.exe"
if (-not (Test-Path $curl)) {
    Write-Host "找不到 Windows 內建的 curl.exe（$curl）。這台電腦的 Windows 版本可能太舊（需要 Windows 10 1803 以後）。"
    exit 1
}

$entries = Get-Content $manifestPath | Where-Object { $_.Trim() -ne "" }
$total = $entries.Count
$downloaded = 0
$skipped = 0
$failed = 0
$index = 0

Write-Host "共 $total 個圖磚，開始下載到：$tileRoot"
Write-Host "（已經下載過的圖磚會自動跳過，可以隨時中斷、之後重新執行這個腳本繼續下載）"

foreach ($entry in $entries) {
    $index++
    $parts = $entry.Split("/")
    if ($parts.Count -ne 3) { continue }
    $z, $x, $y = $parts

    $outDir = Join-Path $tileRoot (Join-Path $z $x)
    $outPath = Join-Path $outDir "$y.png"

    if ((Test-Path $outPath) -and ((Get-Item $outPath).Length -gt 0)) {
        $skipped++
    } else {
        New-Item -ItemType Directory -Force -Path $outDir | Out-Null
        $tempPath = "$outPath.downloading"
        $url = "https://wmts.nlsc.gov.tw/wmts/EMAP/default/GoogleMapsCompatible/$z/$y/$x"
        & $curl "-s" "-f" "--max-time" "20" "-o" $tempPath $url
        if (($LASTEXITCODE -eq 0) -and (Test-Path $tempPath) -and ((Get-Item $tempPath).Length -gt 0)) {
            Move-Item -Force $tempPath $outPath
            $downloaded++
        } else {
            Remove-Item -Force -ErrorAction SilentlyContinue $tempPath
            $failed++
        }
    }

    if (($index % 200) -eq 0) {
        Write-Host "進度：$index / $total（新下載 $downloaded、已存在跳過 $skipped、失敗 $failed）"
    }
}

Write-Host ""
Write-Host "完成。新下載 $downloaded 個、已存在跳過 $skipped 個、失敗 $failed 個。"
if ($failed -gt 0) {
    Write-Host "有下載失敗的圖磚，通常是暫時的網路問題——重新執行這個腳本一次即可補齊。"
}
