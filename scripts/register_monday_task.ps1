# Register Monday 09:00 (local time; this PC is IST) weekly send.
# Requires the machine to be on (or wake from sleep). Re-run this script to update the task.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = (Get-Command python -ErrorAction Stop).Source
$TaskName = "GrowwWeeklyPulse"

$Action = New-ScheduledTaskAction `
  -Execute $Python `
  -Argument "-m pulse.weekly --fetch --raw-dir data/raw" `
  -WorkingDirectory $Root

$Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At 9:00AM
$Settings = New-ScheduledTaskSettingsSet `
  -StartWhenAvailable `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask `
  -TaskName $TaskName `
  -Action $Action `
  -Trigger $Trigger `
  -Settings $Settings `
  -Description "Fetch Groww reviews and classify the weekly pulse at Monday 09:00 IST." `
  -Force | Out-Null

Write-Host "Registered '$TaskName': Monday 09:00, working directory $Root"
Write-Host "Runs: $Python -m pulse.weekly --fetch --raw-dir data/raw"
Write-Host "Verify: Get-ScheduledTask -TaskName $TaskName"
Write-Host "Test now: python -m pulse.weekly --fetch"
