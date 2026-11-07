param(
    [string]$Group4Root = 'F:\experiment_data\20261105_group004',
    [string]$LocalRoot = 'G:\kaiseki1005',
    [string]$Tag = 'g004_calibration_depth_20261106_01'
)
$ErrorActionPreference = 'Stop'
if ($Tag -notmatch '^[A-Za-z0-9_.-]+$' -or $Tag -in @('.', '..')) { throw 'Invalid tag.' }
$Bundle = Join-Path $LocalRoot 'depth_ssd_compact_continue_20261105_01'
$Exporter = Join-Path $Bundle 'zed_sdk_package\tracking_v2\export_depth_clip.py'
$AnalysisPython = Join-Path $LocalRoot 'analysis_python\Scripts\python.exe'
$SdkPython = (Get-Command python -ErrorAction Stop).Source
$CalibrationFolder = Join-Path $Group4Root 'calibration_001'
if (-not (Test-Path -LiteralPath $Exporter -PathType Leaf) -or -not (Test-Path -LiteralPath $AnalysisPython -PathType Leaf)) { throw 'Existing SSD bundle or analysis Python not found.' }
if (-not (Test-Path -LiteralPath $CalibrationFolder -PathType Container)) { throw "Calibration folder not found: $CalibrationFolder" }
$Svos = @(Get-ChildItem -LiteralPath $CalibrationFolder -Recurse -File | Where-Object { $_.Extension -in @('.svo', '.svo2') })
if ($Svos.Count -ne 1) { throw "Expected one calibration SVO under $CalibrationFolder; found $($Svos.Count)." }
$Work = Join-Path $LocalRoot 'calibration_preparation'
$Output = Join-Path $Work $Tag
$FitOutput = Join-Path $Work ($Tag + '_floor_wall_candidate')
if ((Test-Path -LiteralPath $Output) -or (Test-Path -LiteralPath $FitOutput)) { throw 'Output exists. Preserve it and retry with a new -Tag.' }
& $SdkPython -c 'import pyzed.sl'
if ($LASTEXITCODE -ne 0) { throw 'Selected Python cannot import pyzed.' }
& $AnalysisPython -c 'import numpy'
if ($LASTEXITCODE -ne 0) { throw 'SSD analysis Python cannot import numpy.' }
Write-Host "Calibration SVO: $($Svos[0].FullName)"
Write-Host 'Exporting 30 frames locally. The SDK reads the full SVO; this may take a while.'
& $SdkPython $Exporter --svo $Svos[0].FullName --setup-id group004_hallway_lower_20261105 --tag $Tag --local-root $Work --local-only --first-frame 0 --frame-count 30 --pixel-stride 6
if ($LASTEXITCODE -ne 0) { throw "Depth export failed. Preserve files under $Output and inspect export.log." }
Write-Host 'Estimating provisional floor and wall from depth. This can take several minutes.'
$env:OPENBLAS_NUM_THREADS = '1'
$env:OMP_NUM_THREADS = '1'
& $AnalysisPython (Join-Path $PSScriptRoot 'analyze_zed_corridor.py') (Join-Path $Output 'depth') --output-dir $FitOutput --label 'Group 4 calibration candidate'
if ($LASTEXITCODE -ne 0) { throw "Floor/wall fit failed. Preserve files under $Output and $FitOutput." }
Write-Host "Candidate stored locally: $FitOutput\zed_corridor_candidate.json"
Write-Host 'No images or depth were copied to shared storage. Send the displayed candidate JSON and final messages for review.'
