# Counter-Drone Interceptor - hardware provisioning checklist

What the hardware team must configure **before the unit is placed / demoed.**
Architecture: **ESP deauther (ESP8266 or ESP32) + Raspberry Pi 5 (interceptor brain) + laptop (console)**.
Roles:
- **ESP deauther (ESP8266/ESP32)** - transmits 802.11 deauth to knock the pilot's phone off the drone's WiFi (the one radio job the Pi/laptop can't do).
- **Pi 5** - detects, triggers the ESP deauther, joins the freed drone link, sends LAND; hosts the backend.
- **Laptop** - operator console (DRONEWATCH dashboard) over the shared house WiFi.

> **Scope / legal:** this deauths **your own drone + your own phone** in your own
> authorized demo only. Never target third-party devices - untargeted deauth is illegal.

---

## 1. ESP32 deauther module (Marauder — what we use)
We drive an **ESP32 running Marauder**. It is the software default (firmware token
`marauder`), so no flag is needed. The driver (`ml/runtime/deauth_esp32.py`) also
supports an ESP8266 as a fallback — see the note at the end.

- [ ] Identify the ESP32 variant (ESP32 / S2 / S3 / C3) and USB-serial chip (**CP210x or CH340**) - install the matching driver.
- [ ] Flash **ESP32 Marauder** firmware (serial CLI so the Pi can drive it headless). ESP Web Tools flasher or esptool.
- [ ] Confirm serial control at **115200 baud**: `scanap` -> `list -a` -> `select -a <id>` -> `attack -t deauth` -> `stop`.
- [ ] Verify it **actually deauths a client**: connect the demo phone to the drone AP, run the deauth, confirm the phone drops (2.4 GHz - Pluto/Tello are 2.4 GHz, good).
- [ ] Prefer **targeted** deauth (the one drone AP) over broadcast, so it does not also kick the Pi. The driver refuses any SSID not on the allow-list.
- [ ] If a scan lists no APs, pass an explicit `--index N` (the drone AP is usually the strongest/only `Pluto_*`) to skip the scan.
- [ ] Note **MAC randomization**: modern phones use a random MAC per SSID - capture the phone's actual MAC on the drone network if you target by client MAC.
- [ ] Antenna: if range is weak, use an ESP32 board with a u.FL external antenna.

> **ESP8266 fallback:** if you only have an ESP8266 (NodeMCU / Wemos), flash Spacehuhn's
> "ESP8266 Deauther 2.x" with the serial CLI enabled (115200) and run the software with
> `--deauth-firmware deauther` (or `export DEAUTH_FW=deauther`). Its CLI is
> `scan ap / show ap / select ap <id> / attack deauth / stop`. Note some ESP8266 builds
> are web-UI-only and ignore serial — in that case use `--index N`.

## 2. Raspberry Pi 5 (interceptor brain)
- [ ] Raspberry Pi OS (64-bit), fully updated; **SSH enabled**; a fixed hostname (e.g. `interceptor.local`) so the laptop can reach it without Ethernet (mDNS).
- [ ] Python 3 + pip; install **plutocontrol**, **pyserial** (`pip install plutocontrol pyserial`).
- [ ] Clone this repo onto the Pi.
- [ ] Add the Pi user to the **dialout** group (serial access to the ESP deauther over USB).
- [ ] Store WiFi credentials for **both**: the **house WiFi** (SSH/monitoring) and the **drone WiFi** (NetworkManager profiles). The drone SSID changes each session (`Pluto_2025_XXXX`) - the join script must match on the `Pluto` prefix, not a fixed name.
- [ ] The intercept script must run **autonomously** (systemd unit / `nohup`/`setsid`) so it survives the Pi's WiFi hop from house -> drone -> house.
- [ ] Power: Pi 5 needs a **5V / 5A USB-C PD** supply (or equivalent power bank) for field use; the ESP deauther is powered from a Pi USB port.

## 3. Networking / integration
- [ ] Pi and laptop on the **same house WiFi** for SSH (no Ethernet cable on hand).
- [ ] Dashboard on the laptop points at the Pi: set `VITE_API_BASE=http://interceptor.local:8080` (backend runs on the Pi).
- [ ] Confirm the laptop can SSH to the Pi by hostname before the demo.

## 4. Drone-side facts to CAPTURE and verify (still open)
- [ ] **Control link:** confirm the drone's gateway IP and control port. Pluto default is MSP over **TCP 192.168.4.1:23**, but this unit's gateway has not been confirmed - read it after joining and set `PLUTO_HOST`/`PLUTO_PORT`.
- [ ] **Land actually works:** verify `plutocontrol` `land()` brings THIS drone down (never confirmed live yet - the laptop kept losing the link before landing).
- [ ] **Single-client behaviour:** this drone rejects a second client while the phone holds it (first-connection-holds) - that is *why* the deauth is required.
- [ ] **This-session WiFi password** (it changes; e.g. this session `plutox3156`).

## 5. Pre-deployment acceptance test (all must pass)
1. Phone flies the drone.
2. Operator clicks **INTERCEPT** on the laptop.
3. ESP deauth fires; **phone visibly loses control** (no manual disconnect).
4. Pi joins the freed drone slot within a few seconds.
5. Pi sends LAND; **drone lands**.
6. Pi rejoins house WiFi; laptop SSH/dashboard reconnects; log shows `commanded land`.

## 6. Open risks for the team to close
- ESP deauth vs **MAC randomization** and **PMF/802.11w** (if the drone AP enables Protected Management Frames, deauth is blocked - verify the AP does NOT). Note the ESP8266 Deauther only does 2.4 GHz - fine here.
- Deauth **range/reliability** vs the phone's proximity.
- Timing window: deauth -> stop -> Pi seizes the single slot before the phone reconnects.
- Field **power budget** and enclosure/mounting.
