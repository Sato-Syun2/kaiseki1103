param(
    [string]$LocalRoot = 'G:\kaiseki1005',
    [string]$Group5Root = 'F:\experiment_data\20261105_group005',
    [string]$SharedRoot = '\\tsclient\_data_experiment_data\kaiseki1103\exchange\depth_group004_005_coordinates_20261106_01'
)
$ErrorActionPreference = 'Stop'
$Template = $PSScriptRoot
$Bundle = Join-Path $LocalRoot 'depth_group004_005_bundle_20261106_01'
$TimelineCache = Join-Path $LocalRoot 'group005_timeline_cache_20261106_01'
$CalibrationExport = Join-Path $LocalRoot 'calibration_preparation\g004_calibration_depth_20261106_01'
$Calibration = Join-Path $LocalRoot 'calibration_preparation\g004_calibration_depth_20261106_01_floor_wall_candidate\zed_corridor_candidate.json'
$AnalysisPython = Join-Path $LocalRoot 'analysis_python\Scripts\python.exe'
$SdkPython = (Get-Command python -ErrorAction Stop).Source
if (-not (Test-Path -LiteralPath $LocalRoot -PathType Container) -or -not (Test-Path -LiteralPath $AnalysisPython -PathType Leaf)) { throw 'SSD root or analysis Python not found.' }
if (-not (Test-Path -LiteralPath $Group5Root -PathType Container)) { throw "Group 5 SVO folder not found: $Group5Root" }
$Active = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
    $_.Name -match '^python(w)?(\.exe)?$' -and $_.CommandLine -match 'local_depth_pipeline|export_depth_clip\.py|export_zed_depth\.py|export_svo_timeline\.py|depth_person_prototype\.py|group004_005_batch'
})
if ($Active.Count -gt 0) { throw 'Another depth analysis is running. Wait for it to finish before starting.' }
$Manifest = Get-Content -LiteralPath (Join-Path $Template 'template_manifest.json') -Raw | ConvertFrom-Json
if ($Manifest.status -ne 'prepared_not_windows_validated') { throw 'Invalid template manifest.' }
foreach ($File in $Manifest.files_sha256.PSObject.Properties) {
    if ($File.Name -match '(^|/)\.\.(/|$)' -or [IO.Path]::IsPathRooted($File.Name)) { throw 'Unsafe template file path.' }
    $Actual = (Get-FileHash -LiteralPath (Join-Path $Template $File.Name) -Algorithm SHA256).Hash
    if ($Actual -ne $File.Value) { throw "Template file verification failed: $($File.Name)" }
}
& $SdkPython -c 'import pyzed.sl'
if ($LASTEXITCODE -ne 0) { throw 'SDK Python cannot import pyzed.' }
& $AnalysisPython -c 'import numpy, cv2, ultralytics; assert tuple(map(int, ultralytics.__version__.split(chr(46)))) == (8, 4, 89)'
if ($LASTEXITCODE -ne 0) { throw 'Analysis Python is missing a required dependency or has the wrong Ultralytics version.' }
New-Item -ItemType Directory -Path $SharedRoot -Force | Out-Null
$env:YOLO_CONFIG_DIR = Join-Path $LocalRoot '.yolo'
if (-not (Test-Path -LiteralPath $Bundle)) {
    Push-Location $Template
    try {
        & $AnalysisPython -m corridor_tracking.prepare_group004_005_bundle --template $Template --output $Bundle --calibration $Calibration --calibration-export $CalibrationExport --group5-root $Group5Root --timeline-cache $TimelineCache --sdk-python $SdkPython
        if ($LASTEXITCODE -ne 0) { throw 'Preparation stopped. Preserve timeline cache and logs.' }
    } finally { Pop-Location }
}
Push-Location $Bundle
try {
    & $AnalysisPython -m corridor_tracking.verify_portable_bundle --bundle $Bundle
    if ($LASTEXITCODE -ne 0) { throw 'Bundle verification failed. Preserve files and inspect.' }
    & $AnalysisPython -m corridor_tracking.group004_005_batch --bundle $Bundle --sdk-python $SdkPython --local-root $LocalRoot --shared-root $SharedRoot --run-id compact_20261106_01
    if ($LASTEXITCODE -ne 0) { throw 'Batch stopped. Preserve local files and logs.' }
} finally { Pop-Location }
