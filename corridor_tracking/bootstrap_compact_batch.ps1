param(
    [Parameter(Mandatory=$true)][string]$BundleShare,
    [Parameter(Mandatory=$true)][string]$LocalRoot,
    [Parameter(Mandatory=$true)][string]$SharedRoot,
    [ValidatePattern('^compact_[A-Za-z0-9_]+$')][string]$RunId = 'compact_20261105_01'
)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $LocalRoot -PathType Container) -or -not (Test-Path -LiteralPath $SharedRoot -PathType Container)) { throw 'SSD root or shared coordinate folder not found.' }
$Active = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
    $_.Name -match '^python(w)?(\.exe)?$' -and $_.CommandLine -match 'corridor_tracking[./\\]local_depth_pipeline|export_depth_clip\.py|export_zed_depth\.py|depth_person_prototype\.py'
})
if ($Active.Count -gt 0) { throw 'An earlier depth process is still running. Stop it and wait for its terminal prompt before resuming.' }
$SdkPython = (Get-Command python -ErrorAction Stop).Source
$AnalysisPython = Join-Path $LocalRoot 'analysis_python\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $AnalysisPython -PathType Leaf)) { throw 'The existing SSD analysis Python was not found.' }
& $SdkPython -c 'import pyzed.sl'
if ($LASTEXITCODE -ne 0) { throw 'The selected SDK Python cannot import pyzed.' }
$Bundle = Join-Path $LocalRoot (Split-Path -Leaf $BundleShare)
if (-not (Test-Path -LiteralPath $Bundle)) { Copy-Item -LiteralPath $BundleShare -Destination $Bundle -Recurse }
Push-Location $Bundle
try {
    & $AnalysisPython -m corridor_tracking.verify_portable_bundle --bundle $Bundle
    if ($LASTEXITCODE -ne 0) { throw 'Portable bundle verification failed; existing files are preserved.' }
    $env:YOLO_CONFIG_DIR = Join-Path $LocalRoot '.yolo'
    & $AnalysisPython -m corridor_tracking.compact_batch --bundle $Bundle --sdk-python $SdkPython --local-root $LocalRoot --shared-root $SharedRoot --run-id $RunId
    if ($LASTEXITCODE -ne 0) { throw 'Compact batch stopped. Preserve the local outputs and logs.' }
} finally { Pop-Location }
