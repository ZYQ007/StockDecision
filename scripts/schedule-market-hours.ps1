#Requires -Version 5.1
param(
  [ValidateSet("Register", "Unregister", "Status")]
  [string]$Action = "Status",
  [string]$StartTime = "09:10",
  [string]$StopTime = "15:10"
)

$ErrorActionPreference = "Stop"
$TaskStart = "StockDecision-Start"
$TaskStop = "StockDecision-Stop"
$TaskLogon = "StockDecision-StartOnLogon"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$StopScript = Join-Path $PSScriptRoot "stop-server.ps1"
$CatchupScript = Join-Path $PSScriptRoot "start-if-market-hours.ps1"

function Resolve-StartCommand {
  $payloadBat = Join-Path $Root "packaging\payload\Start.bat"
  if (Test-Path $payloadBat) {
    return @{
      Exe  = "cmd.exe"
      Args = '/c "' + $payloadBat + '"'
      Work = (Split-Path $payloadBat -Parent)
      Kind = "payload-Start.bat"
    }
  }
  $candidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\买入时机\Start.bat"),
    (Join-Path $env:ProgramFiles "买入时机\Start.bat")
  )
  foreach ($bat in $candidates) {
    if ($bat -and (Test-Path $bat)) {
      return @{
        Exe  = "cmd.exe"
        Args = '/c "' + $bat + '"'
        Work = (Split-Path $bat -Parent)
        Kind = "installed-Start.bat"
      }
    }
  }
  $launcher = Join-Path $Root "scripts\launcher.py"
  if (-not (Test-Path $launcher)) {
    throw "launcher.py not found: $launcher"
  }
  $py = $null
  $venvPy = Join-Path $Root ".venv\Scripts\python.exe"
  if (Test-Path $venvPy) { $py = $venvPy }
  if (-not $py) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { $py = $cmd.Source }
  }
  if (-not $py) {
    throw "No python found. Create .venv or install Python."
  }
  return @{
    Exe  = $py
    Args = '"' + $launcher + '"'
    Work = $Root
    Kind = "project-launcher"
  }
}

function New-WeekdayTrigger([string]$at) {
  return New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At $at
}

function Register-MarketTasks {
  if (-not (Test-Path $StopScript)) { throw "Missing $StopScript" }
  if (-not (Test-Path $CatchupScript)) { throw "Missing $CatchupScript" }

  $start = Resolve-StartCommand
  Write-Host ("Start via: {0} ({1})" -f $start.Kind, $start.Exe)

  foreach ($name in @($TaskStart, $TaskStop, $TaskLogon)) {
    if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
      Unregister-ScheduledTask -TaskName $name -Confirm:$false
    }
  }

  $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

  # Fixed 09:10 start + StartWhenAvailable (run soon after PC wakes if missed)
  $startAction = New-ScheduledTaskAction -Execute $start.Exe -Argument $start.Args -WorkingDirectory $start.Work
  $startTrigger = New-WeekdayTrigger $StartTime
  $startSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 12)
  Register-ScheduledTask -TaskName $TaskStart -Action $startAction -Trigger $startTrigger -Settings $startSettings -Principal $principal -Description "StockDecision fixed weekday start; StartWhenAvailable if PC was off" -Force | Out-Null

  # Logon catch-up: only starts if still inside market window
  $catchArgs = '-NoProfile -ExecutionPolicy Bypass -File "' + $CatchupScript + '" -WindowStart "' + $StartTime + '" -WindowEnd "' + $StopTime + '"'
  $logonAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $catchArgs -WorkingDirectory $PSScriptRoot
  $logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
  $logonSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
  Register-ScheduledTask -TaskName $TaskLogon -Action $logonAction -Trigger $logonTrigger -Settings $logonSettings -Principal $principal -Description "StockDecision catch-up start on logon if still in market hours" -Force | Out-Null

  $stopArgs = '-NoProfile -ExecutionPolicy Bypass -File "' + $StopScript + '"'
  $stopAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $stopArgs -WorkingDirectory $PSScriptRoot
  $stopTrigger = New-WeekdayTrigger $StopTime
  $stopSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
  Register-ScheduledTask -TaskName $TaskStop -Action $stopAction -Trigger $stopTrigger -Settings $stopSettings -Principal $principal -Description "StockDecision stop after A-share close (weekdays)" -Force | Out-Null

  Write-Host "Registered:"
  Write-Host ("  {0}        weekdays {1} (+StartWhenAvailable)" -f $TaskStart, $StartTime)
  Write-Host ("  {0}  at logon if still in {1}-{2}" -f $TaskLogon, $StartTime, $StopTime)
  Write-Host ("  {0}         weekdays {1}" -f $TaskStop, $StopTime)
  Write-Host "If you boot at 10:00, logon catch-up starts the app; 15:10 still stops it."
}

function Unregister-MarketTasks {
  foreach ($name in @($TaskStart, $TaskStop, $TaskLogon)) {
    if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
      Unregister-ScheduledTask -TaskName $name -Confirm:$false
      Write-Host ("Removed {0}" -f $name)
    } else {
      Write-Host ("Not found: {0}" -f $name)
    }
  }
}

function Show-MarketTaskStatus {
  foreach ($name in @($TaskStart, $TaskLogon, $TaskStop)) {
    $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if (-not $task) {
      Write-Host ("{0}: not registered" -f $name)
      continue
    }
    $info = Get-ScheduledTaskInfo -TaskName $name
    Write-Host ("{0}:" -f $name)
    Write-Host ("  State:      {0}" -f $task.State)
    Write-Host ("  LastRun:    {0}" -f $info.LastRunTime)
    Write-Host ("  LastResult: {0}" -f $info.LastTaskResult)
    Write-Host ("  NextRun:    {0}" -f $info.NextRunTime)
  }
}

switch ($Action) {
  "Register" {
    Register-MarketTasks
    Show-MarketTaskStatus
  }
  "Unregister" {
    Unregister-MarketTasks
  }
  "Status" {
    Show-MarketTaskStatus
  }
}
