param(
    [Parameter(Mandatory=$true)][string]$InventoryCsv,
    [Parameter(Mandatory=$true)][string]$OutputRoot,
    [Parameter(Mandatory=$true)][string]$Tag,
    [string]$Python = "python",
    [int]$First = 1,
    [int]$Last = 48,
    [switch]$Heads
)
$ErrorActionPreference = "Stop"
Get-Command $Python -ErrorAction Stop | Out-Null
function Invoke-LoggedPython {
    param([string[]]$Arguments, [string]$LogPath)
    $previousPreference = $ErrorActionPreference
    try {
        # Windows PowerShell can wrap native stderr as ErrorRecord even on success.
        # Preserve those messages and use the native process exit code.
        $ErrorActionPreference = "Continue"
        & $Python @Arguments 2>&1 | Tee-Object -FilePath $LogPath | Out-Host
        $nativeExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    return $nativeExitCode
}
if ($First -lt 1 -or $Last -lt $First) { throw "Require 1 <= First <= Last" }
if ($Tag -notmatch '^[A-Za-z0-9_-]+$') { throw "Tag must be a single directory name" }
$inventory = @(Import-Csv -LiteralPath $InventoryCsv)
$batch = Join-Path $OutputRoot $Tag
if (Test-Path -LiteralPath $batch) { throw "Choose a new tag; existing output is preserved: $batch" }
# Validate the entire requested inventory before any expensive SDK work.
$selected = @()
foreach ($number in $First..$Last) {
    $recording = "recording_{0:D3}" -f $number
    $matches = @($inventory | Where-Object { $_.recording -eq $recording })
    if ($matches.Count -ne 1) { throw "Need exactly one inventory row for $recording" }
    $entry = $matches[0]
    if (-not (Test-Path -LiteralPath $entry.svo_path -PathType Leaf)) { throw "Missing SVO: $($entry.svo_path)" }
    if ([string]::IsNullOrWhiteSpace($entry.setup_id)) { throw "Missing measured setup_id for $recording" }
    $selected += $entry
}
New-Item -ItemType Directory -Path $batch | Out-Null
Copy-Item -LiteralPath $InventoryCsv -Destination (Join-Path $batch "input_inventory.csv")
$summary = @()
$failed = $false
foreach ($entry in $selected) {
    $recordRoot = Join-Path $batch $entry.recording
    New-Item -ItemType Directory -Path $recordRoot | Out-Null
    $modes = @("body")
    if ($Heads) { $modes += "heads" }
    foreach ($mode in $modes) {
        $destination = Join-Path $recordRoot $mode
        $log = Join-Path $recordRoot "$mode.log"
        Write-Host "Export $($entry.recording) / $mode"
        $status = "failed"
        $message = ""
        try {
            $exportArguments = @((Join-Path $PSScriptRoot "export_tracking.py"), $entry.svo_path,
                "--output", $destination, "--mode", $mode, "--setup-id", $entry.setup_id,
                "--image-period-s", "0.1", "--depth-mode", "NEURAL", "--detection-confidence", "35",
                "--minimum-keypoints", "8", "--prediction-timeout-s", "0.2", "--skeleton-smoothing", "0")
            $code = Invoke-LoggedPython -Arguments $exportArguments -LogPath $log
            if ($code -ne 0) { throw "Exporter exited with $code; see $log" }
            $validationArguments = @((Join-Path $PSScriptRoot "validate_export.py"), $destination)
            $code = Invoke-LoggedPython -Arguments $validationArguments -LogPath (Join-Path $recordRoot "$mode.validation.log")
            if ($code -ne 0) { throw "Validator exited with $code" }
            $status = "validated_full_svo"
        } catch {
            $failed = $true
            $message = $_.Exception.Message
            Write-Warning $message
        }
        $summary += [PSCustomObject]@{recording=$entry.recording;mode=$mode;status=$status;output=$destination;error=$message}
        $summary | Export-Csv -NoTypeInformation -Encoding UTF8 -LiteralPath (Join-Path $batch "batch_summary.csv")
    }
}
if ($failed) { exit 1 }
exit 0
