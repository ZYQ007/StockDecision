#Requires -Version 5.1
<#
.SYNOPSIS
  If weekday and within A-share session window (default 09:10-15:10 local),
  start the assistant when not already listening on :8765.
  Used when PC boots after the fixed 09:10 task was missed.
#>
param(
  [string]$WindowStart = "09:10",
  [string]$WindowEnd = "15:10",
  [int]$Port = 8765
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Test-PortListening([int]$p) {
  try {
    $c = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
    if ($c) { return $true }
  } catch {}
  $hit = netstat -ano -p TCP | Select-String (":$p\s+.*LISTENING")
  return [bool]$hit
}

function Resolve-StartCommand {
  $payloadBat = Join-Path $Root "packaging\payload\Start.bat"
  if (Test-Path $payloadBat) {
    return @{ Exe = "cmd.exe"; Args = '/c "' + $payloadBat + '"'; Work = (Split-Path $payloadBat -Parent) }
  }
  $candidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\买入时机\Start.bat"),
    (Join-Path $env:ProgramFiles "买入时机\Start.bat")
  )
  foreach ($bat in $candidates) {
    if ($bat -and (Test-Path $bat)) {
      return @{ Exe = "cmd.exe"; Args = '/c "' + $bat + '"'; Work = (Split-Path $bat -Parent) }
    }
  }
  $launcher = Join-Path $Root "scripts\launcher.py"
  $venvPy = Join-Path $Root ".venv\Scripts\python.exe"
  $py = $null
  if (Test-Path $venvPy) { $py = $venvPy }
  if (-not $py) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { $py = $cmd.Source }
  }
  if (-not $py -or -not (Test-Path $launcher)) {
    throw "Cannot resolve start command"
  }
  return @{ Exe = $py; Args = '"' + $launcher + '"'; Work = $Root }
}

$now = Get-Date
# Monday=1 .. Sunday=7 in .DayOfWeek; PowerShell DayOfWeek enum Sunday=0
$dow = [int]$now.DayOfWeek
if ($dow -eq 0 -or $dow -eq 6) {
  Write-Host "Weekend; skip start."
  exit 0
}

$startTod = [TimeSpan]::Parse($WindowStart)
$endTod = [TimeSpan]::Parse($WindowEnd)
$tod = $now.TimeOfDay
if ($tod -lt $startTod -or $tod -ge $endTod) {
  Write-Host ("Outside market window {0}-{1}; skip start." -f $WindowStart, $WindowEnd)
  exit 0
}

if (Test-PortListening $Port) {
  Write-Host ("Already listening on {0}; skip." -f $Port)
  exit 0
}

$start = Resolve-StartCommand
Write-Host ("Catch-up start: {0} {1}" -f $start.Exe, $start.Args)
Start-Process -FilePath $start.Exe -ArgumentList $start.Args -WorkingDirectory $start.Work
exit 0
