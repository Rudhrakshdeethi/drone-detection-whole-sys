<#
  probe_drone.ps1 - run AFTER you've connected the laptop to the drone's Wi-Fi.
  Writes a full diagnostic to drone-probe.txt so you can reconnect your internet
  and share the result. No commands are sent to the drone - read-only checks.

  Usage:
    1. Windows Wi-Fi menu -> connect to PlutoX_2025_1129 (password plutox3154)
    2. powershell -ExecutionPolicy Bypass -File probe_drone.ps1
    3. reconnect your normal Wi-Fi, then share drone-probe.txt
#>
$out = Join-Path $PSScriptRoot 'drone-probe.txt'
function W($x) { $x | Out-File -FilePath $out -Append -Encoding utf8 }

"=== drone probe $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" | Out-File -FilePath $out -Encoding utf8

# --- which network are we actually on ---
$ssid = (netsh wlan show interfaces | Select-String '^\s*SSID\s*:' | Select-Object -First 1)
W ("SSID line: " + ($ssid -replace '\s+', ' ').Trim())

# --- IP configuration (did DHCP give us a drone-subnet address?) ---
W "`n--- Get-NetIPConfiguration (Wi-Fi) ---"
W ((Get-NetIPConfiguration -InterfaceAlias 'Wi-Fi' -ErrorAction SilentlyContinue | Out-String))
W "`n--- ipconfig ---"
W ((ipconfig | Out-String))

# --- detect the gateway (the drone's likely control IP) ---
$gw = (Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway } |
       ForEach-Object { $_.IPv4DefaultGateway.NextHop } |
       Where-Object { $_ -like '192.168.*' } | Select-Object -First 1)
if (-not $gw) { $gw = '192.168.4.1' }   # Pluto default fallback
W "`ndetected gateway: $gw"
W ("ping $gw : " + (Test-Connection -ComputerName $gw -Count 2 -Quiet))

# --- is the control server actually listening? (MSP is TCP) ---
foreach ($port in 23, 5760, 80, 8080) {
  $r = Test-NetConnection $gw -Port $port -WarningAction SilentlyContinue
  W ("tcp {0}:{1} open={2}" -f $gw, $port, $r.TcpTestSucceeded)
}

# --- ARP: confirm we can even see the drone at layer 2 ---
W "`n--- arp (neighbors) ---"
W ((Get-NetNeighbor -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -like '192.168.*' } |
    Select-Object IPAddress, LinkLayerAddress, State | Out-String))

W "`n=== done - reconnect your internet, then share drone-probe.txt ==="
Write-Host "Wrote diagnostic to $out" -ForegroundColor Green
Write-Host "Now reconnect your normal Wi-Fi from the tray and share drone-probe.txt." -ForegroundColor Cyan
