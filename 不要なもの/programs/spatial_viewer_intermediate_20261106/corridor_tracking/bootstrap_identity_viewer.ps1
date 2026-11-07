param(
    [Parameter(Mandatory=$true)][string]$ViewerShare,
    [Parameter(Mandatory=$true)][string]$LocalRoot,
    [Parameter(Mandatory=$true)][string]$SourceBundle,
    [Parameter(Mandatory=$true)][string]$CandidateShare,
    [Parameter(Mandatory=$true)][ValidateSet('2','3','4','5')][string]$Group,
    [Parameter(Mandatory=$true)][string]$Recording,
    [ValidatePattern('^[A-Za-z0-9_]+$')][string]$RunId = '20261105_01'
)
$ErrorActionPreference = 'Stop'
$Python = Join-Path $LocalRoot 'analysis_python\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'Existing SSD analysis environment is missing.' }
if (-not (Test-Path -LiteralPath $SourceBundle -PathType Container)) { throw 'Original SSD analysis bundle is missing.' }
$Viewer = Join-Path $LocalRoot (Split-Path -Leaf $ViewerShare)
if (-not (Test-Path -LiteralPath $Viewer)) { Copy-Item -LiteralPath $ViewerShare -Destination $Viewer -Recurse }
Push-Location $Viewer
try {
    & $Python -m corridor_tracking.verify_portable_bundle --bundle $Viewer
    if ($LASTEXITCODE -ne 0) { throw 'Viewer bundle verification failed.' }
    & $Python -m corridor_tracking.portable_depth_replay --local-root $LocalRoot --bundle $SourceBundle --group $Group --recording $Recording --run-id $RunId --candidate-dir $CandidateShare --no-update-index
    if ($LASTEXITCODE -ne 0) { throw 'Candidate replay could not be created. Original data has been retained.' }
} finally {
    Pop-Location
}
