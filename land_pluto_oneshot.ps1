<#
  land_pluto_oneshot.ps1 — one-shot PlutoX interception (join-and-land).

  The Pluto is multi-client, so the laptop joins ALONGSIDE the phone (no one gets
  kicked) and sends a controlled LAND that overrides the pilot's sticks, via the
  official plutocontrol library (MSP over TCP 192.168.4.1:23). Reconnects your
  internet at the end, so it runs unattended in one shot.

      powershell -ExecutionPolicy Bypass -File land_pluto_oneshot.ps1

  Tries the known passwords in order; own-drone, land-only, allow-list gated.
#>
param(
  [string]$DroneSsid = 'PlutoX_2025_1043',
  [string[]]$Passwords = @('4267pluto', 'plutox3068')
)
$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

function Cur {
  $m = (netsh wlan show interfaces | Select-String '^\s*SSID\s*:' | Select-Object -First 1)
  if ($m) { return ($m.ToString() -replace '^\s*SSID\s*:\s*', '').Trim() }
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
function TryJoin([string]$pass) {
  Add-Prof $pass
  netsh wlan disconnect | Out-Null; Start-Sleep 2
  netsh wlan connect name="$DroneSsid" ssid="$DroneSsid" | Out-Null
  for ($i = 0; $i -lt 20; $i++) { Start-Sleep 2; if ((Cur) -eq $DroneSsid) { return $true } }
  return $false
}

$orig = Cur
if (-not $orig -or $orig -eq $DroneSsid) { $orig = 'NxtWave_Te@m' }
Write-Host "Internet to restore afterwards: $orig" -ForegroundColor Cyan

$autos = @()
foreach ($pn in ((netsh wlan show profiles) | Select-String 'All User Profile\s*:\s*(.+)$' | ForEach-Object { $_.Matches[0].Groups[1].Value.Trim() })) {
  if ($pn -eq $DroneSsid) { continue }
  if (((netsh wlan show profile name="$pn") | Select-String 'Connection mode') -match 'automatically|auto') {
    $autos += $pn; netsh wlan set profileparameter name="$pn" connectionmode=manual | Out-Null
  }
}

try {
  $joined = $false
  foreach ($p in $Passwords) {
    Write-Host "Joining $DroneSsid ..." -ForegroundColor Yellow
    if (TryJoin $p) { $joined = $true; Write-Host "Joined." -ForegroundColor Green; break }
  }
  if (-not $joined) { throw "Could not join $DroneSsid (drone out of range / off, or password changed). Move the laptop next to the drone." }

  Start-Sleep 2
  $gw = (Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway } | Select-Object -First 1 -ExpandProperty IPv4DefaultGateway).NextHop
  Write-Host "On drone network (gateway $gw). Sending controlled LAND..." -ForegroundColor Green

  Push-Location $RepoRoot
  $env:PLUTO_HOST = '192.168.4.1'; $env:PLUTO_PORT = '23'
  python -m ml.runtime.pluto_control --enabled --authorized $DroneSsid --ssid $DroneSsid
  Pop-Location
}
finally {
  Write-Host "`nRestoring internet ($orig)..." -ForegroundColor Cyan
  foreach ($pn in $autos) { netsh wlan set profileparameter name="$pn" connectionmode=auto | Out-Null }
  netsh wlan disconnect | Out-Null; Start-Sleep 2
  netsh wlan connect name="$orig" ssid="$orig" 2>$null | Out-Null; Start-Sleep 4
  Write-Host ("Now on: " + (Cur)) -ForegroundColor Green
}
