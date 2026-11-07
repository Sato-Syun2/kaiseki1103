param(
    [Parameter(Mandatory=$true)][string]$Inventory,
    [Parameter(Mandatory=$true)][ValidateSet('2','3')][string]$Group,
    [Parameter(Mandatory=$true)][string]$Recording,
    [Parameter(Mandatory=$true)][string]$ExchangeRoot,
    [string]$LocalRoot = (Join-Path $env:USERPROFILE 'kaiseki1103_exchange'),
    [string]$RunId = '20261105_01',
    [int]$ClipFrames = 69
)
$ErrorActionPreference = 'Stop'
if ($Recording -notmatch '^recording_[0-9]{3}$' -or $RunId -notmatch '^[A-Za-z0-9_]+$' -or $ClipFrames -lt 1 -or $ClipFrames -gt 90) { throw 'Invalid recording, run ID or clip size.' }
$Rows = @(Import-Csv -LiteralPath $Inventory | Where-Object { $_.group -eq $Group -and $_.recording -eq $Recording })
if ($Rows.Count -ne 1) { throw 'Recording is absent or duplicated in inventory.' }
$Row = $Rows[0]
if ($Row.existing_depth -eq 'yes') { throw 'This recording already has complete depth output; reuse it.' }
$Frames = [int]$Row.frame_count
if ($Frames -lt 1 -or $Row.source_svo_sha256 -notmatch '^[0-9a-f]{64}$' -or -not (Test-Path -LiteralPath $Row.svo_path -PathType Leaf)) { throw 'Invalid frame count, source hash or missing SVO.' }
if (-not (Test-Path -LiteralPath $ExchangeRoot -PathType Container)) { throw 'Shared exchange folder is missing.' }
New-Item -ItemType Directory -Force -Path $LocalRoot | Out-Null
$RequiredBytes = [long]$Frames * 8MB
$LocalDrive = [System.IO.DriveInfo]::new([System.IO.Path]::GetPathRoot((Resolve-Path -LiteralPath $LocalRoot).Path))
if ($LocalDrive.AvailableFreeSpace -lt ($RequiredBytes + 5GB)) { throw 'Insufficient local disk space: allow approximately 8 MiB per frame plus 5 GiB reserve.' }
$Package = $PSScriptRoot
for ($Start=0; $Start -lt $Frames; $Start += $ClipFrames) {
    $Count = [Math]::Min($ClipFrames, $Frames - $Start)
    $Last = $Start + $Count - 1
    $Tag = 'g{0:D3}_{1}_depth_{2:D6}_{3:D6}_{4}' -f [int]$Group,$Recording,$Start,$Last,$RunId
    if ((Test-Path -LiteralPath (Join-Path $LocalRoot $Tag)) -or (Test-Path -LiteralPath (Join-Path $ExchangeRoot $Tag))) { throw "Output already exists: $Tag. Preserve it and select a new run ID after checking." }
}
for ($Start=0; $Start -lt $Frames; $Start += $ClipFrames) {
    $Count = [Math]::Min($ClipFrames, $Frames - $Start)
    $Last = $Start + $Count - 1
    $Tag = 'g{0:D3}_{1}_depth_{2:D6}_{3:D6}_{4}' -f [int]$Group,$Recording,$Start,$Last,$RunId
    Write-Host "Exporting $Recording frames $Start-$Last"
    python (Join-Path $Package 'export_depth_clip.py') --svo $Row.svo_path --setup-id $Row.setup_id --tag $Tag --shared-dir (Join-Path $ExchangeRoot $Tag) --local-root $LocalRoot --first-frame $Start --frame-count $Count --pixel-stride 2 --expected-svo-sha256 $Row.source_svo_sha256
    if ($LASTEXITCODE -ne 0) { throw "Export or mirror failed: $Tag. Preserve local outputs and logs." }
}
Write-Host "Completed all $Frames frames: group $Group $Recording"
