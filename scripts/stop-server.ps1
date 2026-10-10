#Requires -Version 5.1
<#
.SYNOPSIS
  结束监听 127.0.0.1:8765（或指定端口）的本机助手进程。
#>
param(
  [int]$Port = 8765
)

$ErrorActionPreference = "Stop"

function Get-PidsOnPort([int]$p) {
  $pids = @()
  try {
    $conns = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
    if ($conns) {
      $pids = @($conns | Select-Object -ExpandProperty OwningProcess -Unique)
    }
  } catch {
    # fallback: netstat
  }
  if (-not $pids -or $pids.Count -eq 0) {
    $lines = netstat -ano -p TCP | Select-String (":$p\s+")
    foreach ($line in $lines) {
      if ($line -match "LISTENING\s+(\d+)\s*$") {
        $pids += [int]$Matches[1]
      }
    }
    $pids = @($pids | Select-Object -Unique)
  }
  return $pids
}

$found = Get-PidsOnPort $Port
if (-not $found -or $found.Count -eq 0) {
  Write-Host ("No listener on port {0}." -f $Port)
  exit 0
}

foreach ($procId in $found) {
  if ($procId -le 4) { continue }
  try {
    $proc = Get-Process -Id $procId -ErrorAction Stop
    Write-Host ("Stopping PID {0} ({1})" -f $procId, $proc.ProcessName)
    Stop-Process -Id $procId -Force -ErrorAction Stop
  } catch {
    Write-Warning ("Could not stop PID {0}: {1}" -f $procId, $_.Exception.Message)
  }
}

Start-Sleep -Milliseconds 400
$left = Get-PidsOnPort $Port
if ($left -and $left.Count -gt 0) {
  Write-Warning ("Port {0} still held by: {1}" -f $Port, ($left -join ", "))
  exit 1
}
Write-Host ("Port {0} is free." -f $Port)
exit 0
