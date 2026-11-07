param(
    [string]$LocalRoot = 'G:\kaiseki1005',
    [string]$SharedRoot = '\\tsclient\_data_experiment_data\kaiseki1103\exchange\depth_group004_005_coordinates_20261106_01'
)
$ErrorActionPreference = 'Stop'
$Python = Join-Path $LocalRoot 'analysis_python\Scripts\python.exe'
$Bundle = Join-Path $LocalRoot 'depth_group004_005_bundle_20261106_01'
$Batch = Join-Path $LocalRoot 'depth_group004_005_batch_20261106_03\run_group004_005.ps1'
if (-not (Test-Path -LiteralPath $Python -PathType Leaf) -or -not (Test-Path -LiteralPath $Bundle -PathType Container) -or -not (Test-Path -LiteralPath $Batch -PathType Leaf)) { throw 'SSD analysis environment or original bundle is missing.' }
if (-not (Test-Path -LiteralPath $SharedRoot -PathType Container)) { throw 'Shared folder is unavailable. Reconnect the remote desktop drive and retry; existing SSD data is retained.' }
$Active = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
    $_.Name -match '^python(w)?(\.exe)?$' -and $_.CommandLine -match 'local_depth_pipeline|export_depth_clip\.py|export_zed_depth\.py|depth_person_prototype\.py|group004_005_batch|recover_merged_depth\.py'
})
if ($Active.Count -gt 0) { throw 'An analysis or recovery process is still running. Wait for it to finish.' }
$Manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'recovery_manifest.json') -Raw | ConvertFrom-Json
foreach ($File in $Manifest.files_sha256.PSObject.Properties) {
    if ([IO.Path]::IsPathRooted($File.Name) -or $File.Name -match '(^|[\\/])\.\.([\\/]|$)') { throw 'Unsafe recovery file name.' }
    $Actual = (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot $File.Name) -Algorithm SHA256).Hash
    if ($Actual -ne $File.Value) { throw "Recovery package verification failed: $($File.Name)" }
}
Set-Location -LiteralPath $LocalRoot
$Existing = @(Get-ChildItem -LiteralPath $SharedRoot -Directory -Filter 'g004_recording_032_compact_20261106_01*' | Where-Object { $_.Name -match '^g004_recording_032_compact_20261106_01(?:_retry\d+)?$' })
if ($Existing.Count -gt 1) { throw 'Multiple recording 032 results found; inspect before continuing.' }
if ($Existing.Count -eq 0) {
    & $Python (Join-Path $PSScriptRoot 'recover_merged_depth.py') --bundle $Bundle --local-root $LocalRoot --shared-root $SharedRoot --group 4 --recording recording_032 --old-run-id compact_20261106_01 --run-prefix compact_20261106_01
    if ($LASTEXITCODE -ne 0) { throw 'Recovery stopped. All original and any new local files are retained.' }
} else {
    Write-Host 'A shared result for recording 032 already exists; the batch will validate it before continuing.'
}
Write-Host 'Recovery finished or an existing result was found. Resuming the batch from the SSD.'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Batch
if ($LASTEXITCODE -ne 0) { throw 'The batch stopped. Preserve local files and send the error.' }
