param(
    [Parameter(Mandatory=$true)][string]$Bundle,
    [Parameter(Mandatory=$true)][string]$SdkPython,
    [Parameter(Mandatory=$true)][string]$AnalysisPython,
    [Parameter(Mandatory=$true)][string]$LocalRoot,
    [Parameter(Mandatory=$true)][string]$SharedRoot,
    [string]$RunId = '20261105_01',
    [Parameter(Mandatory=$true)][ValidateSet(2,3)][int]$RetryGroup,
    [Parameter(Mandatory=$true)][ValidatePattern('^recording_\d{3}$')][string]$RetryRecording,
    [Parameter(Mandatory=$true)][ValidatePattern('^[A-Za-z0-9_]+$')][string]$RetryRunId,
    [string]$BenchmarkReport
)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $Bundle -PathType Container)) { throw 'Local bundle not found.' }
if (-not (Test-Path -LiteralPath $SdkPython -PathType Leaf) -or -not (Test-Path -LiteralPath $AnalysisPython -PathType Leaf)) { throw 'SDK or analysis Python not found.' }
& $SdkPython -c 'import pyzed.sl'
if ($LASTEXITCODE -ne 0) { throw 'SDK Python cannot import pyzed.' }
& $AnalysisPython -c 'import cv2,numpy,ultralytics'
if ($LASTEXITCODE -ne 0) { throw 'Analysis Python dependencies are unavailable or version differs.' }
if ($RetryRunId -eq $RunId) { throw 'RetryRunId must differ from the original RunId.' }
Push-Location $Bundle
try {
    & $AnalysisPython -m corridor_tracking.verify_portable_bundle --bundle $Bundle
    if ($LASTEXITCODE -ne 0) { throw 'Bundle verification failed.' }
} finally { Pop-Location }
if (-not $BenchmarkReport) {
    $Root = Join-Path $LocalRoot 'benchmarks'
    $Reports = @(Get-ChildItem -LiteralPath $Root -Directory | ForEach-Object {
        $Path = Join-Path $_.FullName 'benchmark_report.json'
        if (Test-Path -LiteralPath $Path -PathType Leaf) { Get-Item -LiteralPath $Path }
    } | Sort-Object LastWriteTime -Descending)
    if ($Reports.Count -eq 0) { throw 'No benchmark report found; preserve the local outputs.' }
    $BenchmarkReport = $Reports[0].FullName
}
$Result = Get-Content -LiteralPath $BenchmarkReport -Raw -Encoding UTF8 | ConvertFrom-Json
if ($Result.status -ne 'complete' -or $Result.selected_clip_frames -notin @(69,90) -or $Result.group -notin @(2,3) -or $Result.recording -notmatch '^recording_\d{3}$' -or $Result.benchmark_id -notmatch '^[A-Za-z0-9_]+$') { throw 'Invalid or incomplete benchmark report.' }
$BenchDir = Split-Path -Parent (Resolve-Path -LiteralPath $BenchmarkReport).Path
if ((Split-Path -Leaf $BenchDir) -ne $Result.benchmark_id) { throw 'Benchmark report directory differs from its ID.' }
$BenchTag = 'g{0:D3}_{1}_benchmark' -f [int]$Result.group,$Result.recording
$BenchCoordinates = Join-Path $BenchDir "baseline_first\coordinates\$BenchTag"
$BenchPositions = Join-Path $BenchCoordinates 'positions.json'
$BenchManifest = Get-Content -LiteralPath (Join-Path $BenchCoordinates 'manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$BenchData = Get-Content -LiteralPath $BenchPositions -Raw -Encoding UTF8 | ConvertFrom-Json
$BenchActual = (Get-FileHash -LiteralPath $BenchPositions -Algorithm SHA256).Hash.ToLowerInvariant()
$BundleActual = (Get-FileHash -LiteralPath (Join-Path $Bundle 'bundle_manifest.json') -Algorithm SHA256).Hash.ToLowerInvariant()
if ($BenchManifest.status -ne 'complete' -or $BenchManifest.positions_sha256 -ne $BenchActual -or $BenchData.metadata.bundle_manifest_sha256 -ne $BundleActual -or $BenchData.metadata.group -ne $Result.group -or $BenchData.metadata.recording -ne $Result.recording) { throw 'Benchmark output does not match the current bundle or report.' }
[int]$ClipFrames = $Result.selected_clip_frames
Write-Host "Benchmark selected $ClipFrames frames. Reason: $($Result.reason)"
Write-Host "Benchmark report: $BenchmarkReport"
$Result.runs | Select-Object name,clip_frames,seconds,success | Format-Table -AutoSize | Out-Host
if ($Result.runs.Count -gt 0 -and $Result.runs[0].stage_totals_seconds) {
    Write-Host 'Baseline stage durations (seconds):'
    $Result.runs[0].stage_totals_seconds | Format-List | Out-Host
}
function Get-RowRunId($Row) {
    if ([int]$Row.group -eq $RetryGroup -and $Row.recording -eq $RetryRecording) {
        $OriginalTag = 'g{0:D3}_{1}_{2}' -f [int]$Row.group,$Row.recording,$RunId
        if (-not (Test-Path -LiteralPath (Join-Path $SharedRoot $OriginalTag))) { return $RetryRunId }
    }
    return $RunId
}
$Rows = @(Import-Csv -LiteralPath (Join-Path $Bundle 'inventory.csv'))
if ($Rows.Count -ne 109 -or @($Rows | Where-Object { [int]$_.group -eq $RetryGroup -and $_.recording -eq $RetryRecording }).Count -ne 1) { throw 'Unexpected inventory or retry recording.' }
$Done = 0
$NewCompleted = 0
[double]$NewElapsedSeconds = 0
$RemainingNew = 0
foreach ($Candidate in $Rows) {
    $CandidateRunId = Get-RowRunId $Candidate
    $CandidateTag = 'g{0:D3}_{1}_{2}' -f [int]$Candidate.group,$Candidate.recording,$CandidateRunId
    if (-not (Test-Path -LiteralPath (Join-Path $SharedRoot $CandidateTag))) { $RemainingNew++ }
}
Write-Host "[Progress] 0/$($Rows.Count) recordings checked; $RemainingNew new recordings remain. ETA is estimated from completed work."
Push-Location $Bundle
try {
    foreach ($Row in $Rows) {
        $CurrentRunId = Get-RowRunId $Row
        $Tag = 'g{0:D3}_{1}_{2}' -f [int]$Row.group,$Row.recording,$CurrentRunId
        $Existing = Join-Path $SharedRoot $Tag
        if (Test-Path -LiteralPath $Existing) {
            $Files = @(Get-ChildItem -LiteralPath $Existing -Force)
            if ($Files.Count -ne 2 -or -not (Test-Path -LiteralPath (Join-Path $Existing 'positions.json') -PathType Leaf) -or -not (Test-Path -LiteralPath (Join-Path $Existing 'manifest.json') -PathType Leaf)) { throw "Invalid existing coordinate share: $Existing" }
            $M = Get-Content -LiteralPath (Join-Path $Existing 'manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
            $Actual = (Get-FileHash -LiteralPath (Join-Path $Existing 'positions.json') -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($M.status -ne 'complete' -or $M.source_svo_sha256 -ne $Row.source_svo_sha256 -or $M.recording -ne $Row.recording -or [int]$M.group -ne [int]$Row.group -or [int]$M.frame_count -ne [int]$Row.frame_count -or $M.positions_sha256 -ne $Actual) { throw "Existing coordinates failed validation: $Existing" }
            Write-Host "Already shared and validated: $Tag. Checking SSD data and replay."
            & $AnalysisPython -m corridor_tracking.portable_depth_replay --local-root $LocalRoot --bundle $Bundle --group $Row.group --recording $Row.recording --run-id $CurrentRunId
            if ($LASTEXITCODE -ne 0) { throw "SSD data or replay is unavailable for $Tag. Preserve the source and SSD outputs." }
            $Done++
            Write-Host "[Progress] $Done/$($Rows.Count) recordings complete or checked; $RemainingNew new recordings remain."
            continue
        }
        Write-Host "[Progress] $Done/$($Rows.Count) recordings complete; starting group $($Row.group) $($Row.recording)."
        [double]$AverageSeconds = if ($NewCompleted -gt 0) { $NewElapsedSeconds / $NewCompleted } else { 0 }
        $AverageText = $AverageSeconds.ToString([System.Globalization.CultureInfo]::InvariantCulture)
        $Timer = [System.Diagnostics.Stopwatch]::StartNew()
        & $AnalysisPython -m corridor_tracking.local_depth_pipeline --bundle $Bundle --sdk-python $SdkPython --local-root $LocalRoot --shared-root $SharedRoot --group $Row.group --recording $Row.recording --run-id $CurrentRunId --clip-frames $ClipFrames --batch-completed $Done --batch-total $Rows.Count --batch-pending-new $RemainingNew --batch-average-seconds $AverageText
        if ($LASTEXITCODE -ne 0) { throw "Stopped at group $($Row.group) $($Row.recording). Preserve local files and logs." }
        $Timer.Stop()
        $NewElapsedSeconds += $Timer.Elapsed.TotalSeconds
        $NewCompleted++
        $RemainingNew--
        $Done++
        Write-Host "[Progress] $Done/$($Rows.Count) recordings complete or checked; $RemainingNew new recordings remain."
    }
    Write-Host 'Completed resumed batch.'
} finally {
    Pop-Location
}
