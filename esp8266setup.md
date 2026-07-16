# esp8266setup.md — ESP8266 deauther, step by step

Your board is an **ESP8266** (NodeMCU / Wemos D1). It is now the **default** deauth board
for this system — no firmware flag needed anywhere.

**Its one job:** transmit a short, targeted 802.11 deauth at *your own* drone's Wi-Fi so
the pilot's phone drops the single client slot. The Pi then grabs that slot and sends
LAND. That's it.

> **Legal:** deauth **only** your own demo drone + your own phone in an authorized demo.
> The software refuses any SSID not on your allow-list (`Pluto_*` / `TELLO-*`). Never aim
> it at anyone else — untargeted deauth is illegal.

---

## 1. Parts

- ESP8266 board (NodeMCU / Wemos D1 mini).
- USB **data** cable (not charge-only).
- USB-serial chip is either **CP2102** (Silicon Labs) or **CH340** (WCH) — check which
  (step 2) and install the matching driver. *Our board is a NodeMCU with a **CP2102**.*
- Your Pluto/Tello drone + a phone to fly it (for the real test in step 5).

---

## 2. Install the driver, find the COM port

1. Plug in the ESP8266.
2. Device Manager → **Ports (COM & LPT)** → look for `Silicon Labs CP210x (COMx)` or
   `USB-SERIAL CH340 (COMx)`. Or list from the repo:
   ```powershell
   python -m serial.tools.list_ports -v
   ```
   The entry whose desc says **CP210x** / **CH340** is your board (ignore any
   `Standard Serial over Bluetooth` ports — those are not it).
3. **No port, or a ⚠️ device that fails to install?** The driver is missing/broken. This is
   the single most common blocker (a CP2102 in `CM_PROB_FAILED_INSTALL` / Code 28 state
   shows no COM port). Fix it:

   **CP2102 (Silicon Labs) — what our board uses:** install the **CP210x Universal Windows
   Driver**. Automated (what worked for us):
   ```powershell
   # download the official Silicon Labs CP210x driver
   [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
   $d="$env:TEMP\cp210x"; ni -ItemType Directory -Force $d | Out-Null
   iwr "https://www.silabs.com/documents/public/software/CP210x_Universal_Windows_Driver.zip" -OutFile "$d\cp210x.zip"
   Expand-Archive "$d\cp210x.zip" $d -Force
   # install it (needs admin — triggers a UAC prompt, click Yes)
   Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile','-Command',"pnputil /add-driver `"$d\silabser.inf`" /install; pnputil /scan-devices"
   ```
   Or manually: Device Manager → right-click the ⚠️ device → **Update driver** →
   *Search automatically* (needs internet), or *Browse* to the unzipped folder.

   **CH340 (WCH):** install the **CH341SER** driver instead, then re-plug.
4. Confirm it's healthy and note the COM number:
   ```powershell
   python -m serial.tools.list_ports -v   # want a NEW "CP210x"/"CH340" port
   ```
   *(Our board came up as `COM8` — `Silicon Labs CP210x USB to UART Bridge`.)*

---

## 3. Flash the firmware — Spacehuhn Deauther 2.x

You do **not** write firmware for this. The "code" that runs on the ESP8266 is
Spacehuhn's open-source **ESP8266 Deauther 2.x** precompiled binary. You must use a build
with the **serial CLI enabled** (so the Pi can drive it over USB at 115200).

**Easiest — web flasher (Chrome/Edge only):**
1. Open the official **ESP8266 Deauther web installer** (`deauther.com` → install).
2. Connect → pick your COM port → Install.
3. Pick a **serial-enabled** build for your board (NodeMCU / Wemos).

**Or — esptool from the command line (what we did, fully repeatable).** Every official
Deauther build has the serial CLI, so just pick the one matching your board — for a
**NodeMCU** use the `NODEMCU` bin (Wemos D1 mini → `WEMOS_D1_MINI`). Replace `COM8` with
your port:
```powershell
pip install esptool

# 1. download the NodeMCU build of the latest Deauther (2.6.1 here)
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$bin="$env:TEMP\deauther_nodemcu.bin"
iwr "https://github.com/SpacehuhnTech/esp8266_deauther/releases/download/2.6.1/esp8266_deauther_2.6.1_NODEMCU.bin" -OutFile $bin

# 2. confirm esptool sees the board (auto-resets via RTS — no buttons needed)
python -m esptool --port COM8 --baud 115200 flash_id

# 3. erase, then flash at 0x0, then verify
python -m esptool --port COM8 --baud 460800 erase_flash
python -m esptool --port COM8 --baud 460800 write_flash 0x00000 $bin
```
A good flash ends with `Hash of data verified.` (Browse all board builds:
`https://github.com/SpacehuhnTech/esp8266_deauther/releases` — the web installer at
`deauther.com` flashes the same bins if you prefer clicking.)

> Some **custom** Deauther builds are web-UI only and ignore serial. The official
> `NODEMCU` / `WEMOS_D1_MINI` bins above are **not** — they answer the serial CLI. If a
> board ever won't answer, drive it by index instead of scan (step 6, `--index`).

---

## 4. Test the serial CLI

Fastest check — from the repo, confirm the firmware answers (sends **no** attack):
```powershell
python -m ml.runtime.deauth_esp32 --selftest --port COM8
# want: mode: serial ... "ok": true, "responded": true
# (a healthy board echoes e.g. "# stop / Stopped scan / Cleared CLI command queue")
```
`mode: mock` or `"ok": false` instead → the port didn't open (wrong port, or a serial
monitor is holding it — see the one-owner note at the bottom).

Or drive it by hand in a serial terminal at **115200 baud** (Arduino Serial Monitor /
PuTTY) — these are exactly what the Python driver sends:
```
scan ap            # scan for access points
show ap            # list them (each row starts with an index number)
select ap 0        # select the AP by index (use your drone's index)
attack deauth      # start deauth
stop               # stop
```

Board lists APs and acks the commands → CLI works. (These live in
`FIRMWARES["deauther"]` in `ml/runtime/deauth_esp32.py`.)

---

## 5. Test it actually drops your drone

1. Connect your **phone** to the drone AP (`Pluto_2025_XXXX` / `TELLO-XXXXXX`). Both are
   2.4 GHz — ESP8266 is 2.4 GHz only, so that's fine.
2. `scan ap` → `show ap`, find your drone's row + index.
3. `select ap <index>` → `attack deauth`.
4. **The phone should drop off the drone** on its own. Then `stop`.

If it doesn't drop: the AP may enforce **PMF/802.11w** (deauth blocked) — verify PMF is
off. Or move closer.

---

## 6. Drive it from the Pi (integration)

ESP8266/deauther is now the **default**, so no `--firmware` flag is needed.

On the Pi (Linux) the CP2102/CH340 need **no driver install** — the `cp210x`/`ch341`
kernel modules are built in, so the board just appears as `/dev/ttyUSB0`. (The Windows
driver hassle in step 2 is Windows-only.)

```bash
# on the Pi: allow serial access, then LOG OUT and back IN
sudo usermod -aG dialout $USER
ls /dev/ttyUSB* /dev/ttyACM*                          # board should appear

# is the board answering on serial? (sends NO attack)
python -m ml.runtime.deauth_esp32 --selftest          # expect "ok": true

# real targeted deauth of your drone
python -m ml.runtime.deauth_esp32 --ssid Pluto_2025_XXXX --duration 6

# if the scan lists no APs, skip it and hit the index directly:
python -m ml.runtime.deauth_esp32 --ssid Pluto_2025_XXXX --index 0
```

On a laptop with no board it prints `(mock)` and does nothing — safe to rehearse:
```bash
python -m ml.runtime.deauth_esp32 --force-mock --ssid Pluto_2025_XXXX
```

Overrides: `--port /dev/ttyUSB0` (or `$DEAUTH_PORT`) if the port isn't auto-found.

---

## 7. Full intercept (ESP8266 in the loop)

```bash
# dry run (mock, proves the sequence):
python -m ml.runtime.interceptor --dry-run --deauth \
  --drone-ssid Pluto_2025_XXXX --house YOUR_HOME_WIFI

# real (Pi, ESP8266 plugged in — deauther is default):
python -m ml.runtime.interceptor --deauth \
  --drone-prefix Pluto --password THIS_SESSION_PW --house YOUR_HOME_WIFI
```
Launch the real one with `setsid`/systemd so it survives the Wi-Fi hop (see `RUN.md` §4).

**On Windows (laptop, one command):** `npm run intercept` now runs the full chain —
ESP8266 deauth → join Pluto → LAND → rejoin internet. Pin the serial port if auto-detect
grabs the wrong one:
```powershell
powershell -ExecutionPolicy Bypass -File interceptor.ps1 -DroneSsid PlutoX_2025_XXXX -Deauth -DeauthPort COM8
```
(`npm run land` is LAND-only and can't get past a phone holding the slot — use
`intercept`.)

---

## 8. Troubleshooting

| Symptom | Fix |
|---------|-----|
| No COM port (Windows) | charge-only cable, or missing/broken driver — a ⚠️ device in `CM_PROB_FAILED_INSTALL`/Code 28 = install the CP210x (or CH340) driver (step 2). |
| Serial shows garbage | set baud to **115200**. |
| Driver prints `(mock)` on Pi | board not opened — check cable, `dialout` group (re-login), `ls /dev/ttyUSB*`, pass `--port`. |
| `show ap` does nothing / CLI silent | web-UI-only build — flash a **serial** build, or use `--index N`. |
| `AP '<ssid>' not seen in scan` | pass `--index N` (drone AP is the strongest `Pluto_*`). |
| Deauth runs, phone won't drop | AP enforces **PMF/802.11w** — turn it off. Or move closer. |

---

## 9. Done when

- [ ] Deauther 2.x (serial build) flashed; CLI works at 115200 (steps 3–4).
- [ ] Deauth **visibly drops your phone** off your own drone (step 5).
- [ ] On the Pi, `--selftest` → `"ok": true`, real `--ssid`/`--index` drops the phone (step 6).
- [ ] `interceptor --deauth` dry-run passes and the real run fires the ESP8266 (step 7).

---

See `RUN.md` §5 (deauth commands) · `learn.md` §5a (how the driver works) · `HARDWARE.md`
§1 (provisioning) · `ml/runtime/deauth_esp32.py` (the driver).
