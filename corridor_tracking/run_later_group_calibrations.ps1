param(
    [string]$RecordingsRoot = 'F:\experiment_data',
    [string]$LocalRoot = 'G:\kaiseki1005',
    [int[]]$Groups = @(5, 6, 7, 8, 9),
    [string]$RunId = '20261107_01',
    [switch]$Prepare
)
$ErrorActionPreference = 'Stop'
$Stage = Join-Path $LocalRoot 'depth_group005_009_calibration_tools_20261107_02'
$ManifestName = 'package_manifest.json'
function Test-ToolPackage([string]$Folder) {
    $manifest = Get-Content -Raw -LiteralPath (Join-Path $Folder $ManifestName) | ConvertFrom-Json
    foreach ($entry in $manifest.files_sha256.PSObject.Properties) {
        $file = Join-Path $Folder $entry.Name
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Missing tool file: $file" }
        if ((Get-FileHash -Algorithm SHA256 -LiteralPath $file).Hash.ToLowerInvariant() -ne $entry.Value) {
            throw "Tool file hash mismatch: $file"
        }
    }
}
if ($LocalRoot.StartsWith('\\')) { throw 'LocalRoot must be on the Windows SSD, not a network share.' }
if (-not (Test-Path -LiteralPath $LocalRoot -PathType Container)) { throw "LocalRoot not found: $LocalRoot" }
if (-not (Test-Path -LiteralPath $Stage)) {
    Test-ToolPackage $PSScriptRoot
    Copy-Item -LiteralPath $PSScriptRoot -Destination $Stage -Recurse
}
Test-ToolPackage $Stage
$AnalysisPython = Join-Path $LocalRoot 'analysis_python\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $AnalysisPython -PathType Leaf)) { throw "Analysis Python not found: $AnalysisPython" }
$Tool = Join-Path $Stage 'corridor_tracking\prepare_later_group_calibrations.py'
$arguments = @($Tool, '--recordings-root', $RecordingsRoot, '--local-root', $LocalRoot, '--groups')
foreach ($group in $Groups) { $arguments += "$group" }
$arguments += @('--run-id', $RunId)
if ($Prepare) {
    $SdkPython = (Get-Command python -ErrorAction Stop).Source
    & $SdkPython -c 'import pyzed.sl'
    if ($LASTEXITCODE -ne 0) { throw 'Selected SDK Python cannot import pyzed.' }
    $arguments += @('--prepare', '--sdk-python', $SdkPython, '--analysis-python', $AnalysisPython)
}
& $AnalysisPython @arguments
if ($LASTEXITCODE -ne 0) { throw 'Some calibration preparations failed. Preserve local files and the displayed errors.' }
