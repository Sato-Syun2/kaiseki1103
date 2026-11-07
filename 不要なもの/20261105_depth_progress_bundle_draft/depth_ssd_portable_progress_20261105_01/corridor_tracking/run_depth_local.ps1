param(
    [Parameter(Mandatory=$true)][string]$Bundle,
    [Parameter(Mandatory=$true)][string]$SdkPython,
    [Parameter(Mandatory=$true)][string]$AnalysisPython,
    [Parameter(Mandatory=$true)][string]$LocalRoot,
    [Parameter(Mandatory=$true)][string]$SharedRoot,
    [ValidateSet('pilot','all')][string]$Mode = 'pilot',
    [string]$RunId = '20261105_01'
)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $Bundle -PathType Container)) { throw 'Local bundle not found.' }
if (-not (Test-Path -LiteralPath $SdkPython -PathType Leaf) -or -not (Test-Path -LiteralPath $AnalysisPython -PathType Leaf)) { throw 'SDK or analysis Python not found.' }
& $SdkPython -c 'import pyzed.sl'
if ($LASTEXITCODE -ne 0) { throw 'SDK Python cannot import pyzed.' }
& $AnalysisPython -c 'import cv2,numpy,ultralytics'
if ($LASTEXITCODE -ne 0) { throw 'Analysis Python dependencies are unavailable or version differs.' }
$Rows = @(Import-Csv -LiteralPath (Join-Path $Bundle 'inventory.csv'))
if ($Mode -eq 'pilot') { $Rows = @($Rows | Where-Object { $_.recording -eq 'recording_001' }) }
if (($Mode -eq 'pilot' -and $Rows.Count -ne 2) -or ($Mode -eq 'all' -and $Rows.Count -ne 109)) { throw 'Unexpected inventory size.' }
$Done = 0
$NewCompleted = 0
[double]$NewElapsedSeconds = 0
$RemainingNew = 0
foreach ($Candidate in $Rows) {
    $CandidateTag = 'g{0:D3}_{1}_{2}' -f [int]$Candidate.group,$Candidate.recording,$RunId
    if (-not (Test-Path -LiteralPath (Join-Path $SharedRoot $CandidateTag))) { $RemainingNew++ }
}
Write-Host "[Progress] 0/$($Rows.Count) recordings checked; $RemainingNew new recordings remain. ETA is estimated from completed work."
Push-Location $Bundle
try {
    foreach ($Row in $Rows) {
        $Tag = 'g{0:D3}_{1}_{2}' -f [int]$Row.group,$Row.recording,$RunId
        $Existing = Join-Path $SharedRoot $Tag
        if (Test-Path -LiteralPath $Existing) {
            $Files = @(Get-ChildItem -LiteralPath $Existing -Force)
            if ($Files.Count -ne 2 -or -not (Test-Path -LiteralPath (Join-Path $Existing 'positions.json') -PathType Leaf) -or -not (Test-Path -LiteralPath (Join-Path $Existing 'manifest.json') -PathType Leaf)) { throw "Invalid existing coordinate share: $Existing" }
            $M = Get-Content -LiteralPath (Join-Path $Existing 'manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
            $Actual = (Get-FileHash -LiteralPath (Join-Path $Existing 'positions.json') -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($M.status -ne 'complete' -or $M.source_svo_sha256 -ne $Row.source_svo_sha256 -or $M.recording -ne $Row.recording -or [int]$M.group -ne [int]$Row.group -or [int]$M.frame_count -ne [int]$Row.frame_count -or $M.positions_sha256 -ne $Actual) { throw "Existing coordinates failed validation: $Existing" }
            Write-Host "Already shared and validated: $Tag. Checking SSD data and replay."
            & $AnalysisPython -m corridor_tracking.portable_depth_replay --local-root $LocalRoot --bundle $Bundle --group $Row.group --recording $Row.recording --run-id $RunId
            if ($LASTEXITCODE -ne 0) { throw "SSD data or replay is unavailable for $Tag. Preserve the source and SSD outputs." }
            $Done++
            Write-Host "[Progress] $Done/$($Rows.Count) recordings complete or checked; $RemainingNew new recordings remain."
            continue
        }
        Write-Host "[Progress] $Done/$($Rows.Count) recordings complete; starting group $($Row.group) $($Row.recording)."
        [double]$AverageSeconds = if ($NewCompleted -gt 0) { $NewElapsedSeconds / $NewCompleted } else { 0 }
        $AverageText = $AverageSeconds.ToString([System.Globalization.CultureInfo]::InvariantCulture)
        $Timer = [System.Diagnostics.Stopwatch]::StartNew()
        & $AnalysisPython -m corridor_tracking.local_depth_pipeline --bundle $Bundle --sdk-python $SdkPython --local-root $LocalRoot --shared-root $SharedRoot --group $Row.group --recording $Row.recording --run-id $RunId --batch-completed $Done --batch-total $Rows.Count --batch-pending-new $RemainingNew --batch-average-seconds $AverageText
        if ($LASTEXITCODE -ne 0) { throw "Stopped at group $($Row.group) $($Row.recording). Preserve local files and logs." }
        $Timer.Stop()
        $NewElapsedSeconds += $Timer.Elapsed.TotalSeconds
        $NewCompleted++
        $RemainingNew--
        $Done++
        Write-Host "[Progress] $Done/$($Rows.Count) recordings complete or checked; $RemainingNew new recordings remain."
    }
    Write-Host "Completed mode: $Mode"
} finally {
    Pop-Location
}
