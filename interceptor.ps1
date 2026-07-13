<#
  interceptor.ps1 - turn this laptop into the counter-drone INTERCEPTOR station.

  The laptop has ONE WiFi radio, so it can be on the drone's network OR the
  internet, not both. This script handles the whole hand-off:

    1. remembers your current internet WiFi,
    2. joins the drone's WiFi (creating a profile if needed; open or WPA2),
    3. starts the backend + dashboard locally (NO internet needed),
    4. opens the dashboard - the LAND button is armed for your drone,
    5. when you press ENTER, cleanly stops everything and reconnects your internet.

  Phone = pilot. Laptop = interceptor: clicking LAND commands your own drone to
  land. The backend routes LAND to the right stack by SSID:
    * TELLO-* -> Tello UDP SDK (192.168.10.1:8889)  [single-client: laptop seizes the link]
    * else    -> Pluto MSP over TCP (192.168.4.1:23)

  Examples:
    powershell -ExecutionPolicy Bypass -File interceptor.ps1 -DroneSsid TELLO-954B1F
    powershell -ExecutionPolicy Bypass -File interceptor.ps1 -DroneSsid PlutoX_2025_1043
#>
param(
  [string]$DroneSsid = 'Pluto_2025_2242',
  [string]$Password  = ''            # empty = reuse the existing saved profile (or open network)
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

function Get-CurrentSsid {
  $line = (netsh wlan show interfaces | Select-String '^\s*SSID\s*:' | Select-Object -First 1)
  if ($line) { return ($line.ToString() -replace '^\s*SSID\s*:\s*', '').Trim() }
  return ''
}

function Test-ProfileExists([string]$name) {
  return [bool]((netsh wlan show profiles) | Select-String ([regex]::Escape($name)))
}

# Create a WLAN profile (open or WPA2-PSK) if one isn't already saved.
function Ensure-Profile([string]$ssid, [string]$pass) {
  if (Test-ProfileExists $ssid) { return }
  if ([string]::IsNullOrEmpty($pass)) {
    $sec = @"
    <security><authEncryption><authentication>open</authentication><encryption>none</encryption><useOneX>false</useOneX></authEncryption></security>
"@
  } else {
    $sec = @"
    <security><authEncryption><authentication>WPA2PSK</authentication><encryption>AES</encryption><useOneX>false</useOneX></authEncryption>
    <sharedKey><keyType>passPhrase</keyType><protected>false</protected><keyMaterial>$pass</keyMaterial></sharedKey></security>
"@
  }
  $xml = @"
<?xml version="1.0"?>
<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">
  <name>$ssid</name>
  <SSIDConfig><SSID><name>$ssid</name></SSID></SSIDConfig>
  <connectionType>ESS</connectionType>
  <connectionMode>manual</connectionMode>
  <MSM>
$sec
  </MSM>
</WLANProfile>
"@
  $path = Join-Path $env:TEMP ("wlan_" + ($ssid -replace '[^A-Za-z0-9]', '_') + ".xml")
  $xml | Out-File -FilePath $path -Encoding utf8
  netsh wlan add profile filename="$path" user=current | Out-Null
  Remove-Item $path -Force -ErrorAction SilentlyContinue
}

function Stop-OnPort([int]$port) {
  try {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
      Select-Object -ExpandProperty OwningProcess -Unique |
      ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
  } catch {}
}

# Remember the internet network so we can come back to it.
$origSsid = Get-CurrentSsid
if (-not $origSsid -or $origSsid -eq $DroneSsid) { $origSsid = 'NxtWave_Te@m' }
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

function Restore-Internet {
  Write-Host "`nReconnecting your internet ($origSsid)..." -ForegroundColor Cyan
  foreach ($pn in $autoProfiles) { netsh wlan set profileparameter name="$pn" connectionmode=auto | Out-Null }
  netsh wlan connect name="$origSsid" ssid="$origSsid" 2>$null | Out-Null
  Start-Sleep -Seconds 3
  Write-Host ("Now on: " + (Get-CurrentSsid)) -ForegroundColor Green
}

$backend = $null
try {
  # --- 1. Join the drone -----------------------------------------------------
  Write-Host "Joining drone WiFi ($DroneSsid)..." -ForegroundColor Yellow
  Ensure-Profile $DroneSsid $Password
  netsh wlan set profileparameter name="$DroneSsid" connectionmode=manual | Out-Null
  netsh wlan disconnect | Out-Null
  Start-Sleep -Seconds 2
  netsh wlan connect name="$DroneSsid" ssid="$DroneSsid" | Out-Null

  $joined = $false
  for ($i = 0; $i -lt 25; $i++) {
    Start-Sleep -Seconds 2
    if ((Get-CurrentSsid) -eq $DroneSsid) { $joined = $true; break }
  }
  if (-not $joined) { throw "Could not join $DroneSsid. Is the drone powered on and broadcasting?" }
  Write-Host "Joined $DroneSsid." -ForegroundColor Green

  # Wait for the drone's gateway to answer.
  $gw = (Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway } |
         Select-Object -First 1 -ExpandProperty IPv4DefaultGateway).NextHop
  if ($gw) {
    $reachable = $false
    for ($i = 0; $i -lt 10; $i++) {
      if (Test-Connection -ComputerName $gw -Count 1 -Quiet) { $reachable = $true; break }
      Start-Sleep -Seconds 1
    }
    Write-Host ("Drone gateway $gw reachable: $reachable") -ForegroundColor $(if ($reachable) { 'Green' } else { 'Yellow' })
  }

  # --- 2. Launch backend + dashboard (all local) -----------------------------
  $env:PLUTO_SSID = $DroneSsid   # target token the backend arms + routes on

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
  Write-Host "  Target    : $DroneSsid"
  Write-Host "  LAND is ARMED. Tap LAND to arm, tap again within 4s to confirm."
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
