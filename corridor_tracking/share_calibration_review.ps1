param(
    [string]$LocalRoot = 'G:\kaiseki1005',
    [string]$SharedRoot = '\\tsclient\_data_experiment_data\kaiseki1103\exchange'
)
$ErrorActionPreference = 'Stop'
$Work = Join-Path $LocalRoot 'calibration_preparation'
if (-not (Test-Path -LiteralPath $Work -PathType Container)) { throw "Calibration folder not found: $Work" }
if (-not (Test-Path -LiteralPath $SharedRoot -PathType Container)) { throw "Shared folder not available: $SharedRoot" }
$Candidates = @(Get-ChildItem -LiteralPath $Work -Directory | Where-Object {
    $_.Name -match '^g00[5-9]_calibration_depth_[A-Za-z0-9_]+_floor_wall_candidate$'
})
if ($Candidates.Count -eq 0) { throw "No group 5-9 calibration candidates found under $Work. Send the final output of the earlier command." }
$Id = (Get-Date -Format 'yyyyMMdd_HHmmss') + '_' + [Guid]::NewGuid().ToString('N').Substring(0,8)
$Destination = Join-Path $SharedRoot ("calibration_review_metadata_" + $Id)
$Temporary = Join-Path $SharedRoot (".calibration_review_metadata_" + $Id + '.partial')
if ((Test-Path -LiteralPath $Destination) -or (Test-Path -LiteralPath $Temporary)) { throw 'New destination already exists.' }
$null = New-Item -ItemType Directory -Path $Temporary
$Count = 0
foreach ($Candidate in $Candidates) {
    $Tag = $Candidate.Name -replace '_floor_wall_candidate$', ''
    $Export = Join-Path $Work $Tag
    $Sources = @(
        @{ Source = (Join-Path $Candidate.FullName 'zed_corridor_candidate.json'); Name = 'zed_corridor_candidate.json' },
        @{ Source = (Join-Path $Export 'batch_summary.json'); Name = 'batch_summary.json' },
        @{ Source = (Join-Path $Export 'depth\camera.json'); Name = 'camera.json' },
        @{ Source = (Join-Path $Export 'depth\manifest.json'); Name = 'depth_manifest.json' }
    )
    $Missing = @($Sources | Where-Object { -not (Test-Path -LiteralPath $_.Source -PathType Leaf) })
    if ($Missing.Count -gt 0) {
        Write-Warning "Skipping incomplete candidate $Tag; preserve local files."
        continue
    }
    $Target = Join-Path $Temporary $Tag
    $null = New-Item -ItemType Directory -Path $Target
    foreach ($Item in $Sources) {
        $TargetFile = Join-Path $Target $Item.Name
        Copy-Item -LiteralPath $Item.Source -Destination $TargetFile
        if ((Get-FileHash -LiteralPath $Item.Source -Algorithm SHA256).Hash -ne
            (Get-FileHash -LiteralPath $TargetFile -Algorithm SHA256).Hash) {
            throw "Copy verification failed: $TargetFile; partial directory preserved."
        }
    }
    $Count++
    Write-Host "Copied calibration metadata: $Tag"
}
if ($Count -eq 0) { throw "No complete metadata sets found; partial directory preserved: $Temporary" }
Move-Item -LiteralPath $Temporary -Destination $Destination
Write-Host "Metadata-only review folder: $Destination"
Write-Host 'No SVO, depth points, images, or video were copied.'
