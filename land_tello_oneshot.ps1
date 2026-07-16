<#
  land_tello_oneshot.ps1 — one-shot Tello interception.

  Seizes the Tello's WiFi link (a stock Tello allows only one client, so this
  bumps the phone), sends the SDK LAND, then reconnects your internet. Because it
  restores networking at the end, the whole thing runs unattended in one go.

      powershell -ExecutionPolicy Bypass -File land_tello_oneshot.ps1

  Own-drone, land-only, allow-list gated to the Tello SSID.
#>
param(
  [string]$DroneSsid = 'TELLO-954B1F',
  [switch]$Emergency   # cut motors instantly instead of a controlled land (drone drops)
)
$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

function Get-CurrentSsid {
  $line = (netsh wlan show interfaces | Select-String '^\s*SSID\s*:' | Select-Object -First 1)
  if ($line) { return ($line.ToString() -replace '^\s*SSID\s*:\s*', '').Trim() }
  return ''
}

$origSsid = Get-CurrentSsid
if (-not $origSsid -or $origSsid -eq $DroneSsid) { $origSsid = 'NxtWave_Te@m' }
Write-Host "Internet network to restore afterwards: $origSsid" -ForegroundColor Cyan

# Ensure an OPEN profile for the Tello exists.
if (-not ((netsh wlan show profiles) | Select-String ([regex]::Escape($DroneSsid)))) {
  $xml = @"
<?xml version="1.0"?>
<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">
  <name>$DroneSsid</name>
  <SSIDConfig><SSID><name>$DroneSsid</name></SSID></SSIDConfig>
  <connectionType>ESS</connectionType><connectionMode>manual</connectionMode>
  <MSM><security><authEncryption><authentication>open</authentication><encryption>none</encryption><useOneX>false</useOneX></authEncryption></security></MSM>
</WLANProfile>
"@
  $path = Join-Path $env:TEMP 'wlan_tello.xml'
  $xml | Out-File -FilePath $path -Encoding utf8
  netsh wlan add profile filename="$path" user=current | Out-Null
  Remove-Item $path -Force -ErrorAction SilentlyContinue
}

# Keep known networks from grabbing the adapter during the shot.
$autoProfiles = @()
foreach ($pn in ((netsh wlan show profiles) | Select-String 'All User Profile\s*:\s*(.+)$' | ForEach-Object { $_.Matches[0].Groups[1].Value.Trim() })) {
  if ($pn -eq $DroneSsid) { continue }
  if (((netsh wlan show profile name="$pn") | Select-String 'Connection mode') -match 'automatically|auto') {
    $autoProfiles += $pn; netsh wlan set profileparameter name="$pn" connectionmode=manual | Out-Null
  }
}

try {
  Write-Host "Seizing Tello link ($DroneSsid)..." -ForegroundColor Yellow
  netsh wlan disconnect | Out-Null
  Start-Sleep -Seconds 2
  netsh wlan connect name="$DroneSsid" ssid="$DroneSsid" | Out-Null
  $joined = $false
  for ($i = 0; $i -lt 25; $i++) { Start-Sleep -Seconds 2; if ((Get-CurrentSsid) -eq $DroneSsid) { $joined = $true; break } }
  if (-not $joined) { throw "Could not join $DroneSsid (is the Tello on?)" }
  Push-Location $RepoRoot
  if ($Emergency) {
    Write-Host "Link seized. Sending EMERGENCY (motor cutoff)..." -ForegroundColor Red
    python -m ml.runtime.tello_control --enabled --authorized $DroneSsid --ssid $DroneSsid --emergency
  } else {
    Write-Host "Link seized. Sending LAND..." -ForegroundColor Green
    python -m ml.runtime.tello_control --enabled --authorized $DroneSsid --ssid $DroneSsid
  }
  Pop-Location
}
finally {
  Write-Host "`nRestoring internet ($origSsid)..." -ForegroundColor Cyan
  foreach ($pn in $autoProfiles) { netsh wlan set profileparameter name="$pn" connectionmode=auto | Out-Null }
  netsh wlan disconnect | Out-Null
  Start-Sleep -Seconds 2
  netsh wlan connect name="$origSsid" ssid="$origSsid" 2>$null | Out-Null
  Start-Sleep -Seconds 3
  Write-Host ("Now on: " + (Get-CurrentSsid)) -ForegroundColor Green
}
