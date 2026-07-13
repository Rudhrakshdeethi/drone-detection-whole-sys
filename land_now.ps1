<#
  land_now.ps1 - send LAND to the drone you are ALREADY connected to.

  No WiFi switching. You connect the laptop to the drone from the Windows WiFi
  menu (most reliable), then run this. It confirms you are on the drone network,
  checks the control link, sends a controlled LAND, and logs everything to
  land-log.txt. Afterwards, reconnect your normal WiFi from the tray.

      npm run land:now
#>
param([string]$DroneSsid = 'Pluto_2025_2242')
$ErrorActionPreference = 'Continue'
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogPath  = Join-Path $RepoRoot 'land-log.txt'
"" | Out-File $LogPath -Encoding utf8

function Log([string]$m) {
  $t = (Get-Date).ToString('HH:mm:ss'); $line = "$t  $m"
  Write-Host $line; $line | Out-File -FilePath $LogPath -Append -Encoding utf8
}
function Cur {
  $m = (netsh wlan show interfaces | Select-String '^\s*SSID\s*:' | Select-Object -First 1)
  if ($m) { return ($m.ToString() -replace '^\s*SSID\s*:\s*', '').Trim() }
  return ''
}

Log "=== land_now start ==="
$cur = Cur
Log "current WiFi: $cur"

# The Pluto's SSID changes every session, so target whatever Pluto* network the
# laptop is actually connected to right now.
if ($cur -like 'Pluto*') {
  $DroneSsid = $cur
  Log "targeting connected drone: $DroneSsid"
} else {
  Log "NOT on the drone. Open the Windows WiFi menu, connect to the drone's Pluto_* network (this session's password), wait for 'Connected', then run: npm run land:now"
  Log "=== end ==="
  exit 1
}

$ipc = Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway } | Select-Object -First 1
$ip = ($ipc.IPv4Address.IPAddress -join ',')
$gw = $ipc.IPv4DefaultGateway.NextHop
Log "on drone network: ip=$ip gateway=$gw"
if ($gw) {
  $ping = Test-Connection $gw -Count 2 -Quiet
  $msp = (Test-NetConnection $gw -Port 23 -WarningAction SilentlyContinue).TcpTestSucceeded
  Log "gateway ping=$ping   MSP tcp/23 open=$msp"
}

Log "sending controlled LAND via pluto_control ..."
Push-Location $RepoRoot
$env:PLUTO_HOST = if ($gw) { $gw } else { '192.168.4.1' }
$env:PLUTO_PORT = '23'
$out = (python -m ml.runtime.pluto_control --enabled --authorized $DroneSsid --ssid $DroneSsid 2>&1 | Out-String)
Pop-Location
foreach ($line in ($out -split "`r?`n")) { if ($line.Trim()) { Log ("  " + $line.Trim()) } }

Log "=== done. If you saw 'commanded land via plutocontrol/msp' the drone is landing. Reconnect your WiFi from the tray. ==="
