<#
  land_pluto_oneshot.ps1 - one-shot PlutoX interception (join-and-land), with a log.

  The Pluto is multi-client, so the laptop joins ALONGSIDE the phone and sends a
  controlled LAND (plutocontrol land() over MSP, 192.168.4.1:23), overriding the
  pilot. It writes everything to land-log.txt and reconnects your internet at the
  end, so you can run it offline and we can read the log afterward to see exactly
  what happened.

      npm run land
      # or: powershell -ExecutionPolicy Bypass -File land_pluto_oneshot.ps1
#>
param(
  [string]$DroneSsid = 'Pluto_2025_2242',
  [string[]]$Passwords = @('4267pluto', 'plutox3068')
)
$ErrorActionPreference = 'Continue'
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogPath  = Join-Path $RepoRoot 'land-log.txt'
"" | Out-File $LogPath -Encoding utf8   # truncate previous log

function Log([string]$m) {
  $t = (Get-Date).ToString('HH:mm:ss')
  $line = "$t  $m"
  Write-Host $line
  $line | Out-File -FilePath $LogPath -Append -Encoding utf8
}
function Cur {
  $m = (netsh wlan show interfaces | Select-String '^\s*SSID\s*:' | Select-Object -First 1)
  if ($m) { return ($m.ToString() -replace '^\s*SSID\s*:\s*', '').Trim() }
  return ''
}
function St {
  $m = (netsh wlan show interfaces | Select-String '^\s*State\s*:' | Select-Object -First 1)
  if ($m) { return ($m.ToString() -replace '^\s*State\s*:\s*', '').Trim() }
  return ''
}
function Add-Prof([string]$pass) {
  $xml = @"
<?xml version="1.0"?>
<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">
<name>$DroneSsid</name><SSIDConfig><SSID><name>$DroneSsid</name></SSID></SSIDConfig>
<connectionType>ESS</connectionType><connectionMode>manual</connectionMode>
<MSM><security><authEncryption><authentication>WPA2PSK</authentication><encryption>AES</encryption><useOneX>false</useOneX></authEncryption>
<sharedKey><keyType>passPhrase</keyType><protected>false</protected><keyMaterial>$pass</keyMaterial></sharedKey></security></MSM>
</WLANProfile>
"@
  $f = Join-Path $env:TEMP 'wlan_pluto.xml'
  $xml | Out-File $f -Encoding utf8
  netsh wlan add profile filename="$f" user=current | Out-Null
  Remove-Item $f -Force -ErrorAction SilentlyContinue
}

$orig = Cur
if (-not $orig -or $orig -eq $DroneSsid) { $orig = 'NxtWave_Te@m' }
Log "=== land_pluto_oneshot start ==="
Log "target=$DroneSsid  internet-to-restore=$orig"

# Keep other saved networks from grabbing the adapter mid-run.
$autos = @()
foreach ($pn in ((netsh wlan show profiles) | Select-String '(?:All User|Current User) Profile\s*:\s*(.+)$' | ForEach-Object { $_.Matches[0].Groups[1].Value.Trim() })) {
  if ($pn -eq $DroneSsid) { continue }
  $autos += $pn
  netsh wlan set profileparameter name="$pn" connectionmode=manual | Out-Null
}
Log ("forced to manual so they can't grab the adapter: " + ($autos -join ', '))

try {
  # Is the drone even visible?
  $vis = netsh wlan show networks mode=bssid | Select-String ([regex]::Escape($DroneSsid)) -Context 0,5
  Log ("drone visible in scan: " + [bool]$vis)
  if ($vis) { ($vis.ToString() -split "`n" | Where-Object { $_ -match 'Signal' } | ForEach-Object { Log ("  " + $_.Trim()) }) }

  # Connect + wait, re-issuing the connect each cycle so the drone wins the
  # adapter even if Windows keeps trying to auto-reconnect elsewhere.
  function ConnectWait {
    netsh wlan disconnect | Out-Null; Start-Sleep 2
    for ($i = 0; $i -lt 25; $i++) {
      if ((Cur) -eq $DroneSsid) { return $true }
      $r = (netsh wlan connect name="$DroneSsid" ssid="$DroneSsid" 2>&1 | Out-String).Trim()
      Start-Sleep 2
      $c = Cur; $s = St
      if ($i % 2 -eq 0) { Log ("  t+{0}s state={1} ssid={2} connect='{3}'" -f (($i + 1) * 2), $s, $c, $r) }
      if ($c -eq $DroneSsid) { return $true }
    }
    return $false
  }

  $joined = $false
  # Prefer the existing saved profile (it already holds the correct key).
  if ((netsh wlan show profiles) | Select-String ([regex]::Escape($DroneSsid))) {
    Log "using saved profile for $DroneSsid ..."
    if (ConnectWait) { $joined = $true; Log "JOINED via saved profile" }
    else { Log "  -> saved profile did not associate" }
  }
  # Fall back to creating a profile with each candidate password.
  if (-not $joined) {
    foreach ($p in $Passwords) {
      Log "joining with password '$p' ..."
      Add-Prof $p
      if (ConnectWait) { $joined = $true; Log "JOINED with '$p'"; break }
      Log "  -> did not associate with '$p'"
    }
  }

  if (-not $joined) {
    Log "RESULT: could not join $DroneSsid - drone out of range/off, or password wrong."
    Log "Fix: keep the laptop within ~1 m of the powered-on drone, confirm the phone connects to this exact SSID."
  } else {
    Start-Sleep 2
    $ipc = Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway } | Select-Object -First 1
    $ip = ($ipc.IPv4Address.IPAddress -join ',')
    $gw = $ipc.IPv4DefaultGateway.NextHop
    Log "network: ip=$ip gateway=$gw"
    $ping = Test-Connection $gw -Count 2 -Quiet
    $msp = (Test-NetConnection $gw -Port 23 -WarningAction SilentlyContinue).TcpTestSucceeded
    Log "gateway ping=$ping   MSP tcp/23 open=$msp"

    Log "sending LAND via pluto_control ..."
    Push-Location $RepoRoot
    $env:PLUTO_HOST = '192.168.4.1'; $env:PLUTO_PORT = '23'
    $out = (python -m ml.runtime.pluto_control --enabled --authorized $DroneSsid --ssid $DroneSsid 2>&1 | Out-String)
    Pop-Location
    foreach ($line in ($out -split "`r?`n")) { if ($line.Trim()) { Log ("  " + $line.Trim()) } }
    Log "RESULT: land command sent (see lines above for plutocontrol/msp/mock)."
  }
}
catch {
  Log ("ERROR: " + $_.Exception.Message)
}
finally {
  Log "restoring internet ($orig) ..."
  foreach ($pn in $autos) { netsh wlan set profileparameter name="$pn" connectionmode=auto | Out-Null }
  netsh wlan disconnect | Out-Null; Start-Sleep 2
  netsh wlan connect name="$orig" ssid="$orig" 2>$null | Out-Null; Start-Sleep 4
  Log ("now on: " + (Cur))
  Log "=== end. log saved to land-log.txt ==="
}
