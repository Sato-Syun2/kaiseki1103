param([string]$LocalRoot = 'G:\kaiseki1005')
$ErrorActionPreference = 'Stop'
$Source = $PSScriptRoot
$ManifestPath = Join-Path $Source 'package_manifest.json'
$Manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
if (-not (Test-Path -LiteralPath $LocalRoot -PathType Container)) { throw "SSD root is missing: $LocalRoot" }
$Tools = Join-Path $LocalRoot 'body_sdk_tools_20261109_01'
if (-not (Test-Path -LiteralPath $Tools)) {
    $Stage = Join-Path $LocalRoot ('.body_sdk_tools_staging_' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $Stage | Out-Null
    foreach ($File in $Manifest.files.PSObject.Properties) {
        if ([IO.Path]::IsPathRooted($File.Name) -or $File.Name -match '(^|[\\/])\.\.([\\/]|$)') { throw 'Unsafe package filename.' }
        $Original = Join-Path $Source $File.Name
        if ((Get-FileHash -LiteralPath $Original -Algorithm SHA256).Hash -ne $File.Value) { throw "Source hash mismatch: $($File.Name)" }
        Copy-Item -LiteralPath $Original -Destination (Join-Path $Stage $File.Name)
        if ((Get-FileHash -LiteralPath (Join-Path $Stage $File.Name) -Algorithm SHA256).Hash -ne $File.Value) { throw "Copied hash mismatch: $($File.Name)" }
    }
    Copy-Item -LiteralPath $ManifestPath -Destination (Join-Path $Stage 'package_manifest.json')
    Move-Item -LiteralPath $Stage -Destination $Tools
}
if ((Get-FileHash -LiteralPath $ManifestPath -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath (Join-Path $Tools 'package_manifest.json') -Algorithm SHA256).Hash) { throw 'Existing SSD tools are from a different package; preserve them.' }
foreach ($File in $Manifest.files.PSObject.Properties) {
    if ((Get-FileHash -LiteralPath (Join-Path $Tools $File.Name) -Algorithm SHA256).Hash -ne $File.Value) { throw "SSD tool hash mismatch: $($File.Name)" }
}
$Python = (Get-Command python -ErrorAction Stop).Source
& $Python -c "import sys, cv2, numpy, pyzed.sl; print('SDK Python:', sys.executable); print('ZED SDK:', pyzed.sl.Camera.get_sdk_version())"
if ($LASTEXITCODE -ne 0) { throw 'The selected Python cannot import the ZED SDK, OpenCV and NumPy.' }
& $Python (Join-Path $Tools 'export_body_local_batch.py') `
    --local-root (Join-Path $LocalRoot 'sdk_body_group007_009_20261109_01') `
    --known-sources (Join-Path $Tools 'known_sources.json') `
    --source 7 'F:\experiment_data\20261106_group007' 'group007_calibration_20261107_01' `
    --source 8 'F:\experiment_data\20261106_group008' 'group008_calibration_20261107_01' `
    --source 9 'F:\experiment_data\20261106_group009' 'group009_calibration_20261107_01' `
    --extra 7 recording_901 'F:\experiment_data\20261106_test\test_001\test_001.svo2' 'group007_calibration_20261107_01' `
    --extra 7 recording_902 'F:\experiment_data\20261106_test\test_002\test_002.svo2' 'group007_calibration_20261107_01'
if ($LASTEXITCODE -ne 0) { throw 'BODY export stopped. Local files and logs were preserved. The same command retries incomplete recordings.' }
