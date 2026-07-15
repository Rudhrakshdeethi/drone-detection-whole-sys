# esp32setup.md — your ESP32 job, start to finish

**This is the ESP32 part of the counter-drone system, written as a checklist you can
work through.** It covers *only* the ESP32 — what it is for, how to flash it, how to
prove it works, and how to hand it to the Raspberry Pi. When every box here is ticked,
the ESP32 is "done" and the Pi/interceptor code will drive it automatically.

> **Legal scope — read once.** The ESP32 transmits an 802.11 **deauth** burst. You may
> only aim it at **your own demo drone's Wi-Fi + your own phone** in an authorized demo.
> Untargeted / broadcast deauth against anyone else's device is illegal in nearly every
> jurisdiction. The software refuses any SSID that isn't on your allow-list
> (`Pluto_*` / `TELLO-*`) — keep it that way.

---

## 1. Why the ESP32 exists (the one job)

The demo drone's access point (Pluto / Tello) is **first-connection-holds**: while the
pilot's phone holds the single client slot, the Raspberry Pi is *refused* — it cannot
join to send LAND. The Pi's Wi-Fi radio can join a network but can't cleanly transmit
deauth frames.

So the ESP32 does exactly one thing: **transmit a short, targeted 802.11 deauth at your
drone's AP** so the phone drops. The Pi then grabs the freed slot within a couple of
seconds and commands LAND.

```
[phone] --holds--> [drone AP]        ESP32 deauths the phone off
                       ▲                        │
                       │  Pi refused (slot full) ▼
                    [Pi 5] ---- grabs freed slot ----> sends LAND
```

Three boxes, one radio each: **ESP32** (deauth) + **Pi 5** (brain/LAND) + **laptop**
(dashboard). You are building and verifying the ESP32 box.

---

## 2. What you need

- [ ] An **ESP32** dev board (original ESP32, or S2 / S3 / C3 — all fine). Marauder runs
      on all of them. A board with a **u.FL external antenna** helps range but isn't
      required for a bench demo.
- [ ] A **USB data cable** (not a charge-only cable).
- [ ] Know your board's **USB-serial chip**: **CP210x** (Silicon Labs) or **CH340**
      (WCH). You must install the matching Windows driver or the board won't show up as
      a COM port.
- [ ] Your **demo drone** (Pluto / Tello) and a **phone** to fly it — needed for the
      real verification in §6.

> **Note:** the deauth board defaults to **ESP32 running Marauder** — that's what this
> guide targets, and no software flag is needed for it. (An ESP8266 running Spacehuhn's
> Deauther 2.x is a supported fallback; if that's what you have, see §8.)

---

## 3. Install the USB-serial driver (Windows)

1. Plug the ESP32 in.
2. Open **Device Manager → Ports (COM & LPT)**.
   - If you see something like `Silicon Labs CP210x (COM5)` or `USB-SERIAL CH340 (COM5)`,
     the driver is already there — **note the COM number**.
   - If you see an **unknown device** / nothing under Ports, install the driver:
     - CP210x → Silicon Labs "CP210x Universal Windows Driver".
     - CH340 → WCH "CH341SER" driver.
   - Re-plug after installing and confirm a COM port appears.

- [ ] ESP32 shows up as a COM port (write it down, e.g. `COM5`).

---

## 4. Flash Marauder onto the ESP32

You are putting **ESP32 Marauder** firmware on the board, with its **serial CLI** so the
Pi can drive it headless over USB.

**Easiest path — ESP Web Tools (browser flasher):**

1. Open the official **Marauder web flasher** in **Chrome or Edge** (WebSerial only works
   in Chromium browsers).
2. Pick the build that matches your exact board variant (ESP32 / S2 / S3 / C3).
3. Click **Connect**, choose your ESP32's COM port, and **Install / Flash**.
4. Let it finish and reboot the board.

**Alternative — esptool (command line):**

```powershell
pip install esptool
# put the board in download mode if needed (hold BOOT, tap EN/RST, release BOOT)
esptool.py --chip esp32 --port COM5 --baud 921600 write_flash 0x0 marauder_esp32.bin
```
(Use the address/offsets specified by the build you downloaded.)

- [ ] Marauder is flashed and the board reboots.

---

## 5. Prove the serial CLI works (do this on any laptop)

This is the acceptance test for the flash. Open a serial terminal to the board's COM
port at **115200 baud** (Arduino IDE Serial Monitor, PuTTY, or `screen`). Send these
commands and watch the responses:

```
scanap                 # start scanning for access points
list -a                # list the APs it found (each row starts with an index number)
select -a 0            # select AP index 0 (use your drone's index from the list)
attack -t deauth       # start the deauth
stop                   # stop it
```

You should see Marauder list APs after `scanap` + `list -a`, and acknowledge
`select` / `attack` / `stop`. **These are the exact commands the Python driver sends** —
see `FIRMWARES["marauder"]` in `ml/runtime/deauth_esp32.py`.

- [ ] The board answers on serial at 115200 and the five commands above behave.

---

## 6. Prove it actually deauths YOUR drone (the real test)

A CLI that responds isn't enough — you must confirm the deauth **drops a real client**.

1. Power your demo drone; connect the **phone** to the drone's Wi-Fi (`Pluto_2025_XXXX`
   or `TELLO-XXXXXX`). Both Pluto and Tello are **2.4 GHz** — exactly what Marauder can
   hit. Good.
2. From the serial terminal: `scanap` → `list -a`, find the row whose SSID is your drone,
   note its **index**.
3. `select -a <that index>` → `attack -t deauth`.
4. **Watch the phone**: it should lose the drone link / drop off the Wi-Fi without you
   manually disconnecting. Then `stop`.

- [ ] Running the deauth **visibly kicks the phone off the drone AP**.

Things to get right here:

- **Target the ONE drone AP, not broadcast.** Selecting your drone's AP avoids also
  kicking the Pi. (The Python driver enforces this — it refuses any SSID not on your
  allow-list.)
- **PMF / 802.11w:** if the drone AP enforces Protected Management Frames, deauth is
  blocked and the phone won't drop. Verify your drone AP does **not** enable PMF.
- **MAC randomization:** modern phones use a random MAC per SSID. You're targeting the
  **AP**, so this is usually fine — only matters if you ever target by client MAC.
- **Range:** if it's flaky, move closer or use a board with a u.FL external antenna.

---

## 7. Hand the ESP32 to the Pi (integration test)

The whole point is that the Pi drives this board automatically. Once §5 and §6 pass:

1. Plug the ESP32 into a **USB port on the Raspberry Pi 5** (it's powered from the Pi).
2. On the Pi, make sure the user can read the serial port:
   ```bash
   sudo usermod -aG dialout $USER     # then LOG OUT and back IN
   ls /dev/ttyUSB* /dev/ttyACM*       # your ESP32 should appear
   ```
3. **Self-test the board through the driver** (sends no attack — just checks the port
   opened and the firmware replies):
   ```bash
   python -m ml.runtime.deauth_esp32 --selftest
   ```
   Expect `"ok": true`. If it says `"ok": false` or prints `(mock)`, the board wasn't
   opened — check the cable, the `dialout` group (re-login), and pass the port
   explicitly (see below).
4. **Fire a real targeted deauth of your drone through the driver:**
   ```bash
   python -m ml.runtime.deauth_esp32 --ssid Pluto_2025_XXXX --duration 6
   ```
   Marauder is the **default** firmware, so no `--firmware` flag is needed.
5. **If the scan lists no APs** (some builds print a different list layout), skip the
   scan and target the AP index directly — the drone AP is usually the strongest / only
   `Pluto_*`:
   ```bash
   python -m ml.runtime.deauth_esp32 --ssid Pluto_2025_XXXX --index 0
   ```

Useful overrides:

| Thing | How |
|-------|-----|
| Serial port isn't auto-found | `--port /dev/ttyUSB0`  (or `$DEAUTH_PORT=/dev/ttyUSB0`) |
| Change baud | `$DEAUTH_BAUD` (default 115200) |
| Prove refusal works | driver declines any SSID not matching `Pluto` / `TELLO` — a non-allow-listed SSID returns `{"action":"none"}` |

- [ ] `--selftest` returns `"ok": true` on the Pi.
- [ ] A real `--ssid` (or `--index`) run drops the phone off the drone.

---

## 8. Full-intercept test (ESP32 in the loop)

This is where the ESP32 does its job inside the real hand-off. The interceptor fires the
deauth, then the Pi joins the drone and lands it. Marauder/ESP32 is the default deauth
board.

```bash
# Dry run first (mock — proves the sequence, touches no radio):
python -m ml.runtime.interceptor --dry-run --deauth \
  --drone-ssid Pluto_2025_XXXX --house YOUR_HOME_WIFI

# Real (on the Pi, ESP32 plugged in):
python -m ml.runtime.interceptor --deauth \
  --drone-prefix Pluto --password THIS_SESSION_PW --house YOUR_HOME_WIFI
```

Deauth-related interceptor flags that concern the ESP32:

| Flag | Meaning |
|------|---------|
| `--deauth` | fire the ESP deauth to free the slot before joining |
| `--deauth-seconds N` | how long to hold the deauth (default 6) |
| `--deauth-index N` | skip the ESP scan and deauth this AP index directly (use if the scan list is empty) |
| `--deauth-firmware marauder\|deauther` | board firmware; **default `marauder` (ESP32)** — you won't change this |

Because the Pi leaves the house Wi-Fi mid-run, launch the real intercept so it
**survives the hop** (`setsid` / systemd — see `RUN.md` §4), not from an SSH shell that
will drop.

---

## 9. ESP8266 fallback (only if you don't have an ESP32)

If you were handed an **ESP8266** (NodeMCU / Wemos) instead:

- Flash **Spacehuhn's "ESP8266 Deauther 2.x"** with the **serial CLI enabled** (115200).
- Its CLI words differ: `scan ap` / `show ap` / `select ap <id>` / `attack deauth` / `stop`.
- Tell the software it's an ESP8266: `--deauth-firmware deauther` (or
  `export DEAUTH_FW=deauther`). Everything else in this guide is the same.
- ESP8266 is 2.4 GHz only — still fine for Pluto/Tello. Note some ESP8266 builds are
  web-UI-only and ignore serial; in that case drive it with `--index N`.

---

## 10. Troubleshooting (ESP32-specific)

| Symptom | Fix |
|---------|-----|
| No COM port in Device Manager | Wrong/charge-only cable, or missing CP210x/CH340 driver (§3). |
| Serial terminal shows garbage | Baud isn't 115200 — set it to 115200. |
| Driver prints `(mock)` on the Pi | Board not opened. `--selftest`, check `dialout` group (re-login), `ls /dev/ttyUSB*`, pass `--port`. |
| `AP '<ssid>' not seen in scan` | Scan list layout differs — pass `--index N` (drone AP is the strongest `Pluto_*`). |
| Deauth runs but phone doesn't drop | AP may enforce **PMF/802.11w** (deauth blocked) — verify the drone AP has PMF off. Or move closer / add antenna. |
| It kicks the Pi too | You broadcast instead of targeting — always `select` the one drone AP (the driver does this for you). |

---

## 11. Definition of done (your ESP32 hand-off)

- [ ] ESP32 flashed with **Marauder**, serial CLI working at **115200** (§4–§5).
- [ ] Deauth **visibly drops your phone** off your own drone AP (§6).
- [ ] On the Pi, `deauth_esp32 --selftest` returns `"ok": true` and a real
      `--ssid`/`--index` run drops the phone (§7).
- [ ] `interceptor --deauth` dry-run passes, and the real run fires the ESP32 in the loop
      (§8).

When these are ticked, the ESP32 part is complete — the rest (join + LAND + rejoin) is
the Pi's job.

---

**See also:** `RUN.md` §5 (deauth board commands) · `learn.md` §5a (how
`deauth_esp32.py` works, method by method) · `HARDWARE.md` §1 (pre-demo provisioning
checklist) · `ml/runtime/deauth_esp32.py` (the driver itself).
