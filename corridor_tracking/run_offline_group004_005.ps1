param(
    [string]$LocalRoot = 'G:\kaiseki1005',
    [string]$SharedRoot = '\\tsclient\_data_experiment_data\kaiseki1103\exchange\depth_group004_005_coordinates_20261106_01',
    [switch]$SyncOnly
)
$ErrorActionPreference = 'Stop'
$Bundle = Join-Path $LocalRoot 'depth_group004_005_bundle_20261106_01'
$Python = Join-Path $LocalRoot 'analysis_python\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Bundle -PathType Container) -or -not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'SSD bundle or analysis Python missing.' }
$Active = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
    $_.Name -match '^python(w)?(\.exe)?$' -and $_.CommandLine -match 'local_depth_pipeline|export_depth_clip\.py|depth_person_prototype\.py|group004_005_batch|offline_group004_005\.py|recover_merged_depth\.py'
})
if ($Active.Count -gt 0) { throw 'Another depth analysis or queue sync is active. Stop it before starting this program.' }
$Manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'offline_manifest.json') -Raw | ConvertFrom-Json
foreach ($File in $Manifest.files_sha256.PSObject.Properties) {
    if ([IO.Path]::IsPathRooted($File.Name) -or $File.Name -match '(^|[\\/])\.\.([\\/]|$)') { throw 'Unsafe package file name.' }
    if ((Get-FileHash -LiteralPath (Join-Path $PSScriptRoot $File.Name) -Algorithm SHA256).Hash -ne $File.Value) { throw "Package verification failed: $($File.Name)" }
}
Set-Location -LiteralPath $LocalRoot
$Sdk = (Get-Command python -ErrorAction Stop).Source
$env:YOLO_CONFIG_DIR = Join-Path $LocalRoot '.yolo'
Push-Location $Bundle
try { & $Python -m corridor_tracking.verify_portable_bundle --bundle $Bundle }
finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { throw 'SSD bundle verification failed.' }
$Arguments = @((Join-Path $PSScriptRoot 'offline_group004_005.py'), '--bundle', $Bundle, '--sdk-python', $Sdk,
    '--local-root', $LocalRoot, '--shared-root', $SharedRoot, '--snapshot', (Join-Path $PSScriptRoot 'completed_snapshot.json'))
if ($SyncOnly) { $Arguments += '--sync-only' }
& $Python @Arguments
if ($LASTEXITCODE -ne 0) { throw 'Analysis or synchronization stopped. Local data is preserved; send the displayed details.' }
