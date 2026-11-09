param(
    [string]$LocalRoot = 'G:\kaiseki1005',
    [string]$Group6Root = 'F:\experiment_data\20261105_group006',
    [string]$Group7Root = 'F:\experiment_data\20261106_group007',
    [string]$Group8Root = 'F:\experiment_data\20261106_group008',
    [string]$Group9Root = 'F:\experiment_data\20261106_group009',
    [string]$Group7Tests = 'F:\experiment_data\20261106_test',
    [string]$SharedRoot = '\\tsclient\_data_experiment_data\kaiseki1103\exchange\depth_group006_009_coordinates_20261107_01',
    [string]$BundleName = 'depth_group006_009_bundle_20261107_01',
    [switch]$PrepareOnly,
    [switch]$SyncOnly
)
$ErrorActionPreference = 'Stop'
if ($BundleName -notmatch '^[A-Za-z0-9_]+$') { throw 'Invalid bundle name.' }
$Stage = Join-Path $LocalRoot 'depth_group006_009_template_20261107_01'
$Bundle = Join-Path $LocalRoot $BundleName
$Python = Join-Path $LocalRoot 'analysis_python\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $LocalRoot -PathType Container) -or $LocalRoot.StartsWith('\\')) { throw 'LocalRoot must be an available SSD folder.' }
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'SSD analysis Python not found.' }
$Active = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
    $_.Name -match '^python(w)?(\.exe)?$' -and $_.CommandLine -match 'local_depth_pipeline|export_depth_clip\.py|depth_person_prototype\.py|group004_005_batch|offline_group004_005|group006_009_batch|offline_group006_009'
})
if ($Active.Count -gt 0) { throw 'Another depth analysis or queue sync is active. Finish it first.' }
function Test-Template([string]$Folder) {
    $manifest = Get-Content -LiteralPath (Join-Path $Folder 'template_manifest.json') -Raw | ConvertFrom-Json
    foreach ($entry in $manifest.files_sha256.PSObject.Properties) {
        if ([IO.Path]::IsPathRooted($entry.Name) -or $entry.Name -match '(^|[\\/])\.\.([\\/]|$)') { throw 'Unsafe template file name.' }
        $file = Join-Path $Folder $entry.Name
        if (-not (Test-Path -LiteralPath $file -PathType Leaf) -or (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.Value) { throw "Template verification failed: $file" }
    }
}
if (-not (Test-Path -LiteralPath $Stage)) {
    Test-Template $PSScriptRoot
    Copy-Item -LiteralPath $PSScriptRoot -Destination $Stage -Recurse
}
Test-Template $Stage
$SdkPython = (Get-Command python -ErrorAction Stop).Source
& $SdkPython -c 'import pyzed.sl'
if ($LASTEXITCODE -ne 0) { throw 'Selected SDK Python cannot import pyzed.' }
if (-not (Test-Path -LiteralPath $Bundle)) {
    if ($SyncOnly) { throw 'Bundle not found; no data was shared.' }
    Push-Location $Stage
    try {
        & $Python -m corridor_tracking.prepare_group006_009_bundle --template $Stage --output $Bundle --g6-root $Group6Root --g7-root $Group7Root --g8-root $Group8Root --g9-root $Group9Root --test-root $Group7Tests --local-root $LocalRoot --sdk-python $SdkPython --timeline-cache (Join-Path $LocalRoot 'timeline_cache_group006_009_20261107_01')
        if ($LASTEXITCODE -ne 0) { throw 'Preparation stopped; preserve local files and send the error.' }
    } finally { Pop-Location }
}
Push-Location $Bundle
try {
    & $Python -m corridor_tracking.verify_portable_bundle --bundle $Bundle
    if ($LASTEXITCODE -ne 0) { throw 'Bundle verification failed; preserve files.' }
    if (-not $PrepareOnly) {
        $Arguments = @('-m','corridor_tracking.offline_group006_009','--bundle',$Bundle,'--sdk-python',$SdkPython,'--local-root',$LocalRoot,'--shared-root',$SharedRoot)
        if ($SyncOnly) { $Arguments += '--sync-only' }
        & $Python @Arguments
        if ($LASTEXITCODE -ne 0) { throw 'Analysis or synchronization stopped; preserve local files and send the error.' }
    }
} finally { Pop-Location }
