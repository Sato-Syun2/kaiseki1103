param(
    [string]$LocalRoot = 'G:\kaiseki1005',
    [string]$FilteredRoot = '\\tsclient\_data_experiment_data\kaiseki1103\exchange\depth_group004_005_spatial_20261106_01',
    [string]$CandidateRoot = '\\tsclient\_data_experiment_data\kaiseki1103\exchange\depth_group004_identity_candidates_20261106_01',
    [string]$FilteredRoot23 = '\\tsclient\_data_experiment_data\kaiseki1103\exchange\depth_group002_003_spatial_20261106_01',
    [string]$CandidateRoot23 = '\\tsclient\_data_experiment_data\kaiseki1103\exchange\depth_identity_candidates_20261105_01',
    [ValidateSet('current','previous','all')][string]$Selection = 'current'
)
$ErrorActionPreference = 'Stop'
$ViewerShare = Split-Path -Parent $PSScriptRoot
$Viewer = Join-Path $LocalRoot (Split-Path -Leaf $ViewerShare)
$Python = Join-Path $LocalRoot 'analysis_python\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'SSD analysis Python is missing.' }
if (-not (Test-Path -LiteralPath $Viewer)) { Copy-Item -LiteralPath $ViewerShare -Destination $Viewer -Recurse }
$Datasets = @(
    @{ Kind='current'; Filtered=$FilteredRoot; Candidates=$CandidateRoot; Bundle=(Join-Path $LocalRoot 'depth_group004_005_bundle_20261106_01') },
    @{ Kind='previous'; Filtered=$FilteredRoot23; Candidates=$CandidateRoot23; Bundle=(Join-Path $LocalRoot 'depth_ssd_compact_continue_20261105_01') }
)
$Links = @()
$Skipped = 0
Push-Location $Viewer
try {
    & $Python -m corridor_tracking.verify_portable_bundle --bundle $Viewer
    if ($LASTEXITCODE -ne 0) { throw 'Viewer bundle verification failed.' }
    foreach ($Dataset in $Datasets) {
      if ($Selection -ne 'all' -and $Selection -ne $Dataset.Kind) { continue }
      $Originals = Join-Path $Dataset.Filtered 'originals'
      if (-not (Test-Path -LiteralPath $Originals -PathType Container) -or -not (Test-Path -LiteralPath $Dataset.Bundle -PathType Container)) { Write-Host "Dataset not available, skipped: $Originals"; continue }
      $Packets = @(Get-ChildItem -LiteralPath $Originals -Directory | Where-Object { $_.Name -match '^g00[2345]_recording_\d{3}_[A-Za-z0-9_]+$' } | Sort-Object Name)
      foreach ($Packet in $Packets) {
        if ($Packet.Name -notmatch '^g00([2345])_(recording_\d{3})_([A-Za-z0-9_]+)$') { throw 'Invalid source name.' }
        $Group = $Matches[1]; $Recording = $Matches[2]; $RunId = $Matches[3]
        $Coord = Join-Path $LocalRoot "coordinates\$($Packet.Name)\positions.json"
        $Person = Join-Path $LocalRoot "analysis\$($Packet.Name)\merged\manifest.json"
        if (-not (Test-Path -LiteralPath $Coord -PathType Leaf) -or -not (Test-Path -LiteralPath $Person -PathType Leaf)) {
            Write-Host "SSD files not ready, skipped: $($Packet.Name)"; $Skipped++; continue
        }
        $FilteredManifest = Get-Content -LiteralPath (Join-Path $Packet.FullName 'manifest.json') -Raw | ConvertFrom-Json
        if ((Get-FileHash -LiteralPath $Coord -Algorithm SHA256).Hash -ne $FilteredManifest.source_positions_sha256) { throw "SSD source differs: $($Packet.Name)" }
        Write-Host "Filtered replay: $($Packet.Name)"
        & $Python -m corridor_tracking.portable_depth_replay --local-root $LocalRoot --bundle $Dataset.Bundle --group $Group --recording $Recording --run-id $RunId --filtered-dir $Packet.FullName --no-update-index
        if ($LASTEXITCODE -ne 0) { throw "Filtered replay failed: $($Packet.Name). Existing files are retained." }
        $Links += "<li><a href='analysis/$($Packet.Name)/merged/portable_spatial_replay.html'>G00$Group $Recording</a></li>"
        $CandidateFolder = Join-Path $Dataset.Filtered 'candidates'
        if (Test-Path -LiteralPath $CandidateFolder -PathType Container) {
          $FilteredHash = (Get-FileHash -LiteralPath (Join-Path $Packet.FullName 'positions.json') -Algorithm SHA256).Hash
          $Found = @(Get-ChildItem -LiteralPath $CandidateFolder -Directory -Filter "g00${Group}_${Recording}_*" | Where-Object {
              $ManifestPath = Join-Path $_.FullName 'manifest.json'
              (Test-Path -LiteralPath $ManifestPath -PathType Leaf) -and ((Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json).source_positions_sha256 -eq $FilteredHash)
          })
          if ($Found.Count -gt 1) { throw "Multiple matching candidate packets: $($Packet.Name)" }
          if ($Found.Count -eq 1) {
                $RawCandidate = Join-Path $Dataset.Candidates $Found[0].Name
                if (-not (Test-Path -LiteralPath $RawCandidate -PathType Container)) { throw "Original candidate missing: $RawCandidate" }
                & $Python -m corridor_tracking.portable_depth_replay --local-root $LocalRoot --bundle $Dataset.Bundle --group $Group --recording $Recording --run-id $RunId --candidate-dir $RawCandidate --filtered-dir $Found[0].FullName --no-update-index
                if ($LASTEXITCODE -ne 0) { throw "Filtered candidate replay failed: $($Packet.Name). Existing files are retained." }
                $Links += "<li><a href='analysis/$($Packet.Name)/merged/portable_candidate_spatial_replay.html'>G00$Group $Recording - ID candidate</a></li>"
          }
        }
      }
    }
} finally { Pop-Location }
$Index = Join-Path $LocalRoot "depth_spatial_replay_${Selection}.html"
$Marker = '<meta name="depth-spatial-replay-index" content="1">'
if ((Test-Path -LiteralPath $Index) -and -not ((Get-Content -LiteralPath $Index -Raw) -like "*$Marker*")) { throw 'Existing filtered index was not generated by this tool; it was not overwritten.' }
$Content = '<!doctype html><meta charset="utf-8">' + $Marker + '<title>Filtered corridor replay</title><h1>Filtered corridor replay</h1><p>Positions beyond X=15 m or outside the provisional walls are excluded. Original image annotations may remain visible.</p><ul>' + ($Links -join '') + '</ul>'
$Temp = Join-Path $LocalRoot ('spatial_replay_index_' + [guid]::NewGuid().ToString('N') + '.tmp')
Set-Content -LiteralPath $Temp -Value $Content -Encoding UTF8
Move-Item -LiteralPath $Temp -Destination $Index -Force
Write-Host "Filtered replay index: $Index; skipped until SSD files are ready: $Skipped"
