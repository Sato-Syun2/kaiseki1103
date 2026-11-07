param(
    [string]$LocalRoot = 'G:\kaiseki1005',
    [string]$SharedRoot = '\\tsclient\_data_experiment_data\kaiseki1103\exchange\depth_group002_005_trusted10_20261106_01'
)
$ErrorActionPreference = 'Stop'
$Python = Join-Path $LocalRoot 'analysis_python\Scripts\python.exe'
$Bundle = Join-Path $LocalRoot 'depth_group004_005_bundle_20261106_01'
$Output = Join-Path $LocalRoot 'trusted10_replays_20261106_01'
if (-not (Test-Path -LiteralPath $Python -PathType Leaf) -or -not (Test-Path -LiteralPath $Bundle -PathType Container)) { throw 'SSD analysis environment or existing depth bundle is missing.' }
if (-not (Test-Path -LiteralPath $SharedRoot -PathType Container)) { throw '10m coordinate share unavailable. Reconnect the remote desktop drive and retry.' }
$Manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'replay_package_manifest.json') -Raw | ConvertFrom-Json
foreach ($Item in $Manifest.files_sha256.PSObject.Properties) {
    if ([IO.Path]::IsPathRooted($Item.Name) -or $Item.Name -match '(^|[\\/])\.\.([\\/]|$)') { throw 'Unsafe package file path.' }
    if ((Get-FileHash -LiteralPath (Join-Path $PSScriptRoot $Item.Name) -Algorithm SHA256).Hash -ne $Item.Value) { throw "Package hash mismatch: $($Item.Name)" }
}
Set-Location -LiteralPath $LocalRoot
$env:PYTHONUTF8 = '1'
& $Python (Join-Path $PSScriptRoot 'build_trusted10_replays.py') --local-root $LocalRoot --bundle $Bundle --shared-root $SharedRoot --output $Output
if ($LASTEXITCODE -ne 0) { throw 'Some replays were not created. Existing data and completed replays are retained; check the displayed list.' }
Write-Host "10m replay index: $Output\index.html"
