<#
  interceptor.ps1 — turn this laptop into the counter-drone INTERCEPTOR station.

  The laptop has ONE WiFi radio, so it can be on the drone's network OR the
  internet, not both. This script handles the whole hand-off:

    1. remembers your current internet WiFi,
    2. joins the drone's WiFi (PlutoX_2025_1043),
    3. starts the backend + dashboard locally (NO internet needed),
    4. opens the dashboard — the LAND button is armed for your drone,
    5. when you press ENTER, cleanly stops everything and reconnects your internet.

  Phone = pilot. Laptop = interceptor: clicking LAND commands your own Pluto to
  land, overriding the flight, via MSP over TCP (192.168.4.1:23).

  Run it by double-clicking Launch-Interceptor.bat, or:
      powershell -ExecutionPolicy Bypass -File interceptor.ps1
#>
param(
  [string]$DroneSsid = 'PlutoX_2025_1043',
  [string]$DroneHost = '192.168.4.1',
  [string]$DronePort = '23'
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

function Get-CurrentSsid {
  $line = (netsh wlan show interfaces | Select-String '^\s*SSID\s*:' | Select-Object -First 1)
  if ($line) { return ($line.ToString() -replace '^\s*SSID\s*:\s*', '').Trim() }
  return ''
}

# Remember the internet network so we can come back to it.
$origSsid = Get-CurrentSsid
if (-not $origSsid) { $origSsid = 'NxtWave_Te@m' }
Write-Host "Current internet network : $origSsid" -ForegroundColor Cyan

# Stop every auto-connect profile from stealing the adapter mid-session.
$autoProfiles = @()
$profNames = (netsh wlan show profiles) |
  Select-String 'All User Profile\s*:\s*(.+)$' |
  ForEach-Object { $_.Matches[0].Groups[1].Value.Trim() }
foreach ($pn in $profNames) {
  if ($pn -eq $DroneSsid) { continue }
  $modeLine = (netsh wlan show profile name="$pn") | Select-String 'Connection mode'
  if ($modeLine -match 'automatically|auto') {
    $autoProfiles += $pn
    netsh wlan set profileparameter name="$pn" connectionmode=manual | Out-Null
  }
}

function Stop-OnPort([int]$port) {
  try {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
      Select-Object -ExpandProperty OwningProcess -Unique |
      ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
  } catch {}
}

function Restore-Internet {
  Write-Host "`nReconnecting your internet ($origSsid)..." -ForegroundColor Cyan
  foreach ($pn in $autoProfiles) { netsh wlan set profileparameter name="$pn" connectionmode=auto | Out-Null }
  netsh wlan connect name="$origSsid" ssid="$origSsid" 2>$null | Out-Null
  Start-Sleep -Seconds 3
  Write-Host ("Now on: " + (Get-CurrentSsid)) -ForegroundColor Green
}

try {
  # --- 1. Join the drone -----------------------------------------------------
  Write-Host "Joining drone WiFi ($DroneSsid)..." -ForegroundColor Yellow
  netsh wlan set profileparameter name="$DroneSsid" connectionmode=manual | Out-Null
  netsh wlan disconnect | Out-Null
  Start-Sleep -Seconds 2
  netsh wlan connect name="$DroneSsid" ssid="$DroneSsid" | Out-Null

  $joined = $false
  for ($i = 0; $i -lt 12; $i++) {
    Start-Sleep -Seconds 2
    if ((Get-CurrentSsid) -eq $DroneSsid) { $joined = $true; break }
  }
  if (-not $joined) { throw "Could not join $DroneSsid. Is the drone powered on and broadcasting?" }
  Write-Host "Joined $DroneSsid." -ForegroundColor Green

  # Wait for the drone's control link to answer.
  $reachable = $false
  for ($i = 0; $i -lt 10; $i++) {
    if (Test-Connection -ComputerName $DroneHost -Count 1 -Quiet) { $reachable = $true; break }
    Start-Sleep -Seconds 1
  }
  Write-Host ("Drone $DroneHost reachable: $reachable") -ForegroundColor $(if ($reachable) { 'Green' } else { 'Yellow' })

  # --- 2. Launch backend + dashboard (all local) -----------------------------
  $env:PLUTO_SSID = $DroneSsid
  $env:PLUTO_HOST = $DroneHost
  $env:PLUTO_PORT = $DronePort

  Stop-OnPort 8080
  Stop-OnPort 8443

  Write-Host "Starting detection backend (port 8080)..." -ForegroundColor Yellow
  Start-Process -FilePath 'python' `
    -ArgumentList '-m', 'ml.runtime.dashboard', '--host', '127.0.0.1', '--port', '8080', '--no-open' `
    -WorkingDirectory $RepoRoot -WindowStyle Minimized | Out-Null

  Write-Host "Starting dashboard UI (port 8443)..." -ForegroundColor Yellow
  Start-Process -FilePath "$env:ComSpec" `
    -ArgumentList '/c', 'npm run dev' `
    -WorkingDirectory $RepoRoot -WindowStyle Minimized | Out-Null

  # Give the servers a moment, then open the UI.
  $uiUp = $false
  for ($i = 0; $i -lt 15; $i++) {
    Start-Sleep -Seconds 1
    if (Get-NetTCPConnection -LocalPort 8443 -State Listen -ErrorAction SilentlyContinue) { $uiUp = $true; break }
  }
  $url = if ($uiUp) { 'http://localhost:8443' } else { 'http://127.0.0.1:8080' }
  Start-Process $url

  Write-Host "`n================ INTERCEPTOR ONLINE ================" -ForegroundColor Green
  Write-Host "  Dashboard : http://localhost:8443"
  Write-Host "  Backend   : http://127.0.0.1:8080  (fallback console)"
  Write-Host "  Target    : $DroneSsid  ->  ${DroneHost}:${DronePort}"
  Write-Host "  LAND is ARMED. Click LAND (tap once to arm, again to confirm)."
  Write-Host "===================================================" -ForegroundColor Green
  Write-Host "`nPress ENTER here to stop and reconnect your internet..." -ForegroundColor Cyan
  [void][System.Console]::ReadLine()
}
finally {
  Write-Host "`nShutting down interceptor..." -ForegroundColor Yellow
  Stop-OnPort 8080
  Stop-OnPort 8443
  Restore-Internet
  Write-Host "Interceptor stopped. You are back online." -ForegroundColor Green
}
