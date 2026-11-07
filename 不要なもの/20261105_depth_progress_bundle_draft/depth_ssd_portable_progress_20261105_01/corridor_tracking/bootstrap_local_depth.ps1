param(
    [Parameter(Mandatory=$true)][string]$BundleShare,
    [Parameter(Mandatory=$true)][string]$LocalRoot,
    [Parameter(Mandatory=$true)][string]$SharedRoot,
    [string]$PriorLocalRoot,
    [ValidateSet('pilot','all')][string]$Mode = 'pilot'
)
$ErrorActionPreference = 'Stop'
$SdkPython = (Get-Command python -ErrorAction Stop).Source
New-Item -ItemType Directory -Force -Path $LocalRoot | Out-Null
$Bundle = Join-Path $LocalRoot (Split-Path -Leaf $BundleShare)
if (-not (Test-Path -LiteralPath $Bundle)) {
    Copy-Item -LiteralPath $BundleShare -Destination $Bundle -Recurse
}
Push-Location $Bundle
try {
    & $SdkPython -m corridor_tracking.verify_portable_bundle --bundle $Bundle
    if ($LASTEXITCODE -ne 0) { throw 'Local bundle verification failed; preserve existing files.' }
} finally {
    Pop-Location
}
$Venv = Join-Path $LocalRoot 'analysis_python'
$AnalysisPython = Join-Path $Venv 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $AnalysisPython)) {
    & $SdkPython -m venv $Venv
    if ($LASTEXITCODE -ne 0) { throw 'Unable to create the separate analysis environment.' }
}
& $AnalysisPython -m pip install 'ultralytics==8.4.89'
if ($LASTEXITCODE -ne 0) { throw 'Unable to install analysis dependencies.' }
$env:YOLO_CONFIG_DIR = Join-Path $LocalRoot '.yolo'
if ($PriorLocalRoot -and (Test-Path -LiteralPath $PriorLocalRoot -PathType Container)) {
    Push-Location $Bundle
    try {
        & $AnalysisPython -m corridor_tracking.migrate_depth_results --source-root $PriorLocalRoot --destination-root $LocalRoot
        if ($LASTEXITCODE -ne 0) { throw 'Copy to SSD failed or differed. Source and destination have been preserved.' }
    } finally {
        Pop-Location
    }
}
& (Join-Path $Bundle 'corridor_tracking\run_depth_local.ps1') -Bundle $Bundle -SdkPython $SdkPython -AnalysisPython $AnalysisPython -LocalRoot $LocalRoot -SharedRoot $SharedRoot -Mode $Mode
if ($LASTEXITCODE -ne 0) { throw 'The local depth pipeline stopped. Preserve the local outputs and logs.' }
