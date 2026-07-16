<#
  detect_drone.ps1 - simple "is a drone here?" detector via Wi-Fi scan.

  Scans the air for known drone SSID patterns (Pluto / Tello / DJI / ...) and
  reports DETECTED or clear, with signal strength + channel. Uses the laptop's
  own Wi-Fi, so it works WITHOUT disconnecting from the internet.

  Usage:
    powershell -ExecutionPolicy Bypass -File detect_drone.ps1           # one scan
    powershell -ExecutionPolicy Bypass -File detect_drone.ps1 -Watch    # keep watching
    powershell -ExecutionPolicy Bypass -File detect_drone.ps1 -Watch -IntervalSec 2
#>
param(
  [string[]]$Patterns = @('Pluto', 'Tello', 'RMTT', 'DJI', 'Mavic', 'Anafi', 'Parrot', 'Autel'),
  [switch]$Watch,
  [int]$IntervalSec = 3
)

function Get-Networks {
  $raw = netsh wlan show networks mode=bssid
  $nets = @(); $cur = $null
  foreach ($line in $raw) {
    if ($line -match '^\s*SSID\s+\d+\s*:\s*(.*)$') {
      if ($cur) { $nets += $cur }
      $cur = [pscustomobject]@{ SSID = $matches[1].Trim(); Signal = ''; Channel = ''; BSSID = '' }
    }
    elseif ($cur -and $line -match '^\s*BSSID\s+\d+\s*:\s*(.*)$') { if (-not $cur.BSSID) { $cur.BSSID = $matches[1].Trim() } }
    elseif ($cur -and $line -match '^\s*Signal\s*:\s*(.*)$')      { if (-not $cur.Signal) { $cur.Signal = $matches[1].Trim() } }
    elseif ($cur -and $line -match '^\s*Channel\s*:\s*(.*)$')     { if (-not $cur.Channel) { $cur.Channel = $matches[1].Trim() } }
  }
  if ($cur) { $nets += $cur }
  return $nets
}

function Proximity([string]$sig) {
  $p = 0; if ($sig -match '(\d+)') { $p = [int]$matches[1] }
  if ($p -ge 70) { return 'CLOSE' } elseif ($p -ge 40) { return 'MEDIUM' } else { return 'FAR' }
}

do {
  $ts = Get-Date -Format 'HH:mm:ss'
  $nets = Get-Networks
  $hits = $nets | Where-Object { $ssid = $_.SSID; ($Patterns | Where-Object { $ssid -match [regex]::Escape($_) }).Count -gt 0 }

  if ($hits) {
    foreach ($h in $hits) {
      Write-Host ("[{0}]  DRONE DETECTED  ->  {1}   signal={2} ({3})  ch={4}  {5}" -f `
        $ts, $h.SSID, $h.Signal, (Proximity $h.Signal), $h.Channel, $h.BSSID) -ForegroundColor Red
    }
  }
  else {
    Write-Host ("[{0}]  clear - no drone SSID in range" -f $ts) -ForegroundColor Green
  }
  if ($Watch) { Start-Sleep -Seconds $IntervalSec }
} while ($Watch)
