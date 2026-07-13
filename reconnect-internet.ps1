<#
  reconnect-internet.ps1 — emergency "get me back online" button.

  If the interceptor window was closed abruptly and the laptop is stuck on the
  drone's WiFi with no internet, run this to restore normal networking.

      powershell -ExecutionPolicy Bypass -File reconnect-internet.ps1
#>
param([string]$PreferSsid = 'NxtWave_Te@m')

# Re-enable auto-connect on every saved profile except the drone.
$profNames = (netsh wlan show profiles) |
  Select-String 'All User Profile\s*:\s*(.+)$' |
  ForEach-Object { $_.Matches[0].Groups[1].Value.Trim() }
foreach ($pn in $profNames) {
  if ($pn -like 'PlutoX*') { continue }
  netsh wlan set profileparameter name="$pn" connectionmode=auto | Out-Null
}

netsh wlan disconnect | Out-Null
Start-Sleep -Seconds 2
netsh wlan connect name="$PreferSsid" ssid="$PreferSsid" 2>$null | Out-Null
Start-Sleep -Seconds 4

$cur = (netsh wlan show interfaces | Select-String '^\s*SSID\s*:' | Select-Object -First 1)
Write-Host ("Current WiFi: " + ($cur.ToString() -replace '^\s*SSID\s*:\s*',''))
$net = Test-NetConnection -ComputerName 8.8.8.8 -Port 53 -WarningAction SilentlyContinue
Write-Host ("Internet reachable: " + $net.TcpTestSucceeded)
