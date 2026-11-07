param(
    [string]$RecordingRoot = "F:\experiment_data\20261104_test",
    [string]$SharedRecordingRoot = "\\tsclient\_data_experiment_data\recordings\20261104_test",
    [string]$Test002Svo = "",
    [string]$Test005Svo = "F:\experiment_data\20261104_test\test_005\test_005.svo2",
    [string]$ExchangeRoot = "\\tsclient\_data_experiment_data\kaiseki1103\exchange\test_20261104_candidate",
    [string]$SetupId002 = "test_hallway_20261104_test002_candidate",
    [string]$SetupId005 = "test_hallway_20261104_test005_candidate",
    [string]$Python = "python"
)
$ErrorActionPreference = "Stop"
$package = $PSScriptRoot
$test2 = if ([string]::IsNullOrWhiteSpace($Test002Svo)) { Join-Path $RecordingRoot "test_002\test_002.svo2" } else { $Test002Svo }
if ([string]::IsNullOrWhiteSpace($Test002Svo) -and -not (Test-Path -LiteralPath $test2 -PathType Leaf)) {
    $test2 = Join-Path $SharedRecordingRoot "test_002\test_002.svo2"
    Write-Host "Local test_002 copy not found; falling back to shared input: $test2"
}
$test5 = $Test005Svo
$test2Root = Join-Path $ExchangeRoot "test_002"
$test5Root = Join-Path $ExchangeRoot "test_005"
$outputs = @(
    (Join-Path $test2Root "depth_export"),
    (Join-Path $test2Root "body"),
    (Join-Path $test5Root "depth_export")
)

Get-Command $Python -ErrorAction Stop | Out-Null
foreach ($source in @($test2, $test5)) {
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "SVO not found: $source. Pass -Test002Svo or -Test005Svo with the local SVO path."
    }
}
if (Test-Path -LiteralPath $ExchangeRoot) {
    throw "Choose a new ExchangeRoot; existing output is preserved: $ExchangeRoot"
}
foreach ($output in $outputs) {
    if (Test-Path -LiteralPath $output) { throw "Output already exists: $output" }
}

$env:CUDA_CACHE_DISABLE = "1"
$env:PYTHONDONTWRITEBYTECODE = "1"
& $Python -c "import pyzed.sl as sl; import cv2; import numpy; print(sl.Camera.get_sdk_version())"
if ($LASTEXITCODE -ne 0) { throw "The selected Python cannot import the installed ZED SDK, OpenCV, and NumPy." }

New-Item -ItemType Directory -Path $ExchangeRoot | Out-Null
New-Item -ItemType Directory -Path $test2Root | Out-Null
New-Item -ItemType Directory -Path $test5Root | Out-Null

$summary = New-Object System.Collections.Generic.List[object]
function Invoke-LoggedPython {
    param(
        [string]$Operation,
        [string]$Source,
        [string]$Output,
        [string]$LogPath,
        [string[]]$Arguments
    )
    $start = Get-Date
    $exitCode = 1
    try {
        $previousPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        & $Python @Arguments 2>&1 | Tee-Object -FilePath $LogPath | Out-Host
        $exitCode = $LASTEXITCODE
        $ErrorActionPreference = $previousPreference
    } catch {
        $_ | Out-String | Add-Content -LiteralPath $LogPath
        $exitCode = 1
        $ErrorActionPreference = "Stop"
    }
    $summary.Add([pscustomobject]@{
        operation = $Operation
        source_svo = $Source
        output = $Output
        status = if ($exitCode -eq 0) { "success" } else { "failed" }
        exit_code = $exitCode
        started_at = $start.ToString("o")
        log = [System.IO.Path]::GetFileName($LogPath)
    })
    return ($exitCode -eq 0)
}

$depthTool = Join-Path $package "export_zed_depth.py"
$bodyTool = Join-Path $package "export_tracking.py"
$validator = Join-Path $package "validate_export.py"
$test2Depth = Join-Path $test2Root "depth_export"
$test5Depth = Join-Path $test5Root "depth_export"
$test2Body = Join-Path $test2Root "body"

[void](Invoke-LoggedPython "test_002_depth" $test2 $test2Depth (Join-Path $test2Root "depth_export.log") @(
    $depthTool, $test2, "--output", $test2Depth, "--setup-id", $SetupId002,
    "--every-seconds", "0.5", "--pixel-stride", "8", "--depth-mode", "NEURAL"
))
[void](Invoke-LoggedPython "test_005_depth" $test5 $test5Depth (Join-Path $test5Root "depth_export.log") @(
    $depthTool, $test5, "--output", $test5Depth, "--setup-id", $SetupId005,
    "--every-seconds", "0.5", "--pixel-stride", "8", "--depth-mode", "NEURAL"
))
$bodySucceeded = Invoke-LoggedPython "test_002_body" $test2 $test2Body (Join-Path $test2Root "body.log") @(
    $bodyTool, $test2, "--output", $test2Body, "--mode", "body",
    "--setup-id", $SetupId002, "--image-period-s", "0.1", "--depth-mode", "NEURAL",
    "--detection-confidence", "35", "--minimum-keypoints", "8",
    "--prediction-timeout-s", "0.2", "--skeleton-smoothing", "0"
)
if ($bodySucceeded) {
    [void](Invoke-LoggedPython "test_002_body_validation" $test2 $test2Body (Join-Path $test2Root "body.validation.log") @(
        $validator, $test2Body
    ))
}

$summary | Export-Csv -LiteralPath (Join-Path $ExchangeRoot "batch_summary.csv") -NoTypeInformation -Encoding UTF8
@(
    [pscustomobject]@{recording="test_002";svo_path=$test2;setup_id=$SetupId002},
    [pscustomobject]@{recording="test_005";svo_path=$test5;setup_id=$SetupId005}
) | Export-Csv -LiteralPath (Join-Path $ExchangeRoot "input_inventory.csv") -NoTypeInformation -Encoding UTF8

if (@($summary | Where-Object { $_.status -eq "failed" }).Count -gt 0) {
    throw "One or more exports failed. Review batch_summary.csv and the per-recording logs: $ExchangeRoot"
}
Write-Host "SDK exports complete. Return the full folder: $ExchangeRoot"
Write-Host "Setup IDs are separate by default. Set them to one shared ID only after confirming the camera was not moved between recordings."
