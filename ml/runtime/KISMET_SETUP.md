# Kismet + Wavenex AR271 — 2.4 GHz Drone-RF Setup Guide

This guide sets up the **real Wi-Fi drone-RF detection path** for CampusShield on a
**Raspberry Pi 5 (Raspberry Pi OS, Bookworm, 64-bit)** using a **Wavenex AR271 USB
Wi-Fi adapter** in monitor mode, driven by **Kismet**. Everything here is
**free / open-source** — no paid services, no cloud accounts.

When Kismet is up, `ml/runtime/kismet_scan.py` (`KismetScanner`) polls Kismet's REST
API and turns each detected DJI DroneID / Remote ID broadcast into a rich hit
(manufacturer, model, serial, **drone GPS + operator GPS**) that flows straight into
the live detector's threat fuser.

---

## 1. Overview — why Kismet + AR271 is the real 2.4 GHz path

The project already carries an **RTL-SDR V4** for wideband RF energy detection, but
that dongle tops out around **1.766 GHz**. It physically **cannot tune to 2.4 GHz**,
which is exactly where consumer drones live. So RF-energy alone can *notice* something,
but it can't identify a drone on the 2.4 GHz Wi-Fi band.

Modern drones, however, announce themselves at the **protocol layer**:

- **DJI DroneID** — DJI drones embed a DroneID payload inside their **Wi-Fi beacons**
  (OUI `26:37:12`). This payload carries live telemetry, the **drone's GPS position**,
  and the **operator's GPS position**.
- **FAA / EU Remote ID** — regulatory Remote ID drones broadcast their ID and
  telemetry over **Wi-Fi (NaN / Beacon)** and Bluetooth.

**Kismet** (free, open-source) decodes **both of these natively** using any
monitor-mode Wi-Fi card. The **Wavenex AR271** (MediaTek/Ralink chipset,
monitor-mode capable) is that sniffing radio. Kismet listens passively on 2.4 GHz,
decodes DroneID/Remote ID, and exposes everything over a local REST API on port
`2501`, which our scanner reads.

> In short: **RTL-SDR = wideband energy, AR271 + Kismet = actual drone identity + GPS
> on 2.4 GHz.** The two are complementary.

---

## 2. Installing Kismet the recommended way (official apt repo)

Do **not** use the older `kismet` package from the stock Raspberry Pi OS / Debian
repository — it is usually years out of date and may lack current DroneID/Remote ID
decoding. Use the **official Kismet apt repository** at
[kismetwireless.net](https://www.kismetwireless.net/packages/).

**Step 1 — add the Kismet repo signing key:**

```bash
wget -O - https://www.kismetwireless.net/repos/kismet-release.gpg.key --quiet \
  | gpg --dearmor \
  | sudo tee /usr/share/keyrings/kismet-archive-keyring.gpg >/dev/null
```

**Step 2 — add the Bookworm repository** (Raspberry Pi OS Bookworm tracks Debian
Bookworm; the arm64 packages match the Pi 5):

```bash
echo 'deb [signed-by=/usr/share/keyrings/kismet-archive-keyring.gpg] https://www.kismetwireless.net/repos/apt/release/bookworm bookworm main' \
  | sudo tee /etc/apt/sources.list.d/kismet.list >/dev/null
```

**Step 3 — update and install:**

```bash
sudo apt update
sudo apt install kismet
```

During install, the package will ask whether Kismet should be installed with
**suid-root helper / group access** — answer **Yes**. This is what lets a normal user
capture packets without running the whole of Kismet as root.

**Step 4 — add your user to the `kismet` group:**

```bash
sudo usermod -aG kismet $USER
```

**Why the group matters:** Kismet's packet-capture helpers are owned by the `kismet`
group. Being in that group lets you run Kismet as **your normal user** (not `sudo` /
root), which is the recommended, safer way to run it. Group membership only takes
effect in a **new login session**, so **log out and back in (or reboot the Pi)** after
this step:

```bash
sudo reboot
```

After the reboot, confirm you're in the group:

```bash
groups        # should list: ... kismet ...
```

---

## 3. Identifying and preparing the AR271 interface

Plug the AR271 into a USB port on the Pi 5. It will appear as a **second** wireless
interface (the Pi's built-in Wi-Fi is usually `wlan0`, so the AR271 is often `wlan1`).

**List wireless interfaces:**

```bash
iw dev
```

or:

```bash
ip link
```

Look for the new interface (e.g. `wlan1`). Note its name — you'll hand it to Kismet.

**Confirm it supports monitor mode.** Find the *phy* the AR271 maps to (shown in
`iw dev`, e.g. `phy1`) and check its capabilities:

```bash
iw list
```

In the output, find the block for the AR271's phy and look under
**`Supported interface modes:`** — it must list **`monitor`**:

```
Supported interface modes:
         * IBSS
         * managed
         * AP
         * monitor          <-- this line must be present
         * mesh point
```

If `monitor` is present, the card can sniff. **You do not need to run `airmon-ng` or
manually flip the card into monitor mode** — **Kismet puts the interface into monitor
mode itself** when you hand it the interface name. Just make sure nothing else (e.g.
NetworkManager trying to connect the AR271 to a network) is fighting Kismet for the
card; if it is, leave the AR271 unmanaged and only use the Pi's built-in `wlan0` for
your normal network connection.

---

## 4. First run + creating the admin login

Start Kismet as your normal user (thanks to the `kismet` group), pointing it at the
AR271 interface (using `wlan1` as the example):

```bash
kismet -c wlan1
```

Kismet will bring the card into monitor mode and start channel-hopping on 2.4 GHz.

> **Optional — make the source permanent.** Instead of passing `-c` each time, add a
> source line to `/etc/kismet/kismet_site.conf` (the local override file that survives
> package upgrades):
>
> ```
> source=wlan1:name=ar271
> ```
>
> Then you can just run `kismet` with no arguments.

**Create the admin login (first launch only):** open the web UI in a browser:

```
http://<pi-ip>:2501
```

(Use the Pi's LAN IP, or `http://localhost:2501` from a desktop on the Pi itself.) On
the very first launch Kismet shows a **"Create initial user"** screen — set an **admin
username and password**. These are the credentials our scanner needs.

Kismet stores these HTTP credentials in:

```
~/.kismet/kismet_httpd.conf
```

(under the home directory of the user that ran Kismet). If you ever forget them, you
can stop Kismet, delete/edit that file, and restart to be prompted again.

---

## 5. Confirming DroneID / Remote ID works

Kismet detects **DJI DroneID out of the box** (DroneID beacons carry OUI `26:37:12`)
and **FAA/EU Remote ID** as well — no extra plugin or license required. The
manufacturer / UAV matchers ship with Kismet in **`kismet_uav.conf`**, so DJI and
common Remote ID vendors are recognized automatically.

**Where drones show up in the UI:** in the **Devices** list. A decoded drone appears
with **type `UAV` / `Drone`**, and clicking it reveals the DroneID/Remote ID details —
manufacturer, model, serial, and the **drone + operator GPS coordinates** when the
drone is broadcasting them.

You will only see a device here when a **real drone is actually broadcasting** nearby.
To prove the *decoding + UI* path with no drone at all, see Section 7 (simulate).

---

## 6. Wiring it to the CampusShield detector

Our detector auto-discovers Kismet. `make_drone_rf_scanner()` in
`ml/runtime/kismet_scan.py` (used by `ml/runtime/live_detector.py`) does a fast TCP
probe of `localhost:2501`:

- **Kismet reachable** → it queries the REST API and emits rich DroneID/Remote ID hits.
- **Kismet not running** → it seamlessly **falls back** to `nmcli` SSID matching
  (`WifiScanner`), and if that's unavailable too, to nothing — the loop keeps running
  either way, free.

The scanner reads these environment variables (all optional):

| Variable            | Default     | Meaning                                        |
|---------------------|-------------|------------------------------------------------|
| `KISMET_HOST`       | `localhost` | Kismet host                                    |
| `KISMET_PORT`       | `2501`      | Kismet REST API port                           |
| `KISMET_USER`       | *(none)*    | Admin username created in Section 4            |
| `KISMET_PASS`       | *(none)*    | Admin password                                 |
| `KISMET_RECENT_SEC` | `30`        | How many seconds back to ask Kismet for devices|

**On the Raspberry Pi (Linux) — set the credentials and run:**

```bash
export KISMET_USER="admin"
export KISMET_PASS="your-password"
# optional, only if Kismet runs on another host:
# export KISMET_HOST="127.0.0.1"
# export KISMET_PORT="2501"

python -m ml.runtime.live_detector
```

**On a Windows dev laptop (PowerShell)** — same idea, different syntax. (Note: the AR271
sniffing only happens on the Pi where Kismet runs; on the laptop this is mainly for
pointing at a remote Kismet or running the simulate demo.)

```powershell
$env:KISMET_USER = "admin"
$env:KISMET_PASS = "your-password"
# $env:KISMET_HOST = "192.168.1.50"   # the Pi's IP, if Kismet is remote

python -m ml.runtime.live_detector
```

When Kismet is up and a drone is broadcasting, the detector's Wi-Fi stage will report
`source: kismet` hits with drone + operator GPS, which feed straight into the A7 threat
score and the alert cascade.

---

## 7. Run it FREE with no hardware (simulate)

You do **not** need a Pi, an AR271, Kismet, or a real drone to see the full pipeline
work end-to-end. The scanner can emit **one realistic DroneID hit** — including a
complete Remote ID payload with **drone GPS *and* pilot GPS** — from a single flag:

```bash
python -m ml.runtime.live_detector --once --simulate-ssid DJI-Mavic-1A2B --no-buzzer --no-telegram
```

- `--simulate-ssid DJI-Mavic-1A2B` routes through Kismet's simulation path and produces
  a decoded DJI hit (manufacturer `DJI`, a model inferred from the SSID, a serial, and
  drone + operator coordinates near the demo origin).
- `--once` runs a single pass (smoke test).
- `--no-buzzer` / `--no-telegram` keep the demo silent and offline.

You can also exercise just the scanner in isolation:

```bash
python -m ml.runtime.kismet_scan --simulate-ssid DJI-Mavic-1A2B
```

This prints the full JSON hit (drone lat/lon/alt + pilot lat/lon), proving the parse
→ fuse → alert chain without any radio at all.

---

## 8. Troubleshooting

**Permission denied / can't open capture source**
You're likely not in the `kismet` group yet, or you added yourself but didn't start a
new session. Run `groups` — if `kismet` isn't listed, redo Section 2's `usermod` and
**reboot** (`sudo reboot`). Do **not** work around it by running Kismet as root.

**AR271 doesn't show up in `iw dev` / `ip link`**
Check it enumerated on USB:

```bash
lsusb                 # look for a MediaTek / Ralink device
dmesg | tail -n 40    # kernel messages about the adapter / driver
```

If it enumerates on `lsusb` but has no `wlanX` interface, the driver may be missing —
install the appropriate MediaTek/Ralink firmware/driver package, then replug and
recheck. Try a different USB port (prefer a directly-powered port on the Pi 5).

**`iw list` shows no `monitor` under supported modes**
That interface/chipset can't sniff, so Kismet can't use it for capture. Confirm you're
reading the AR271's phy (not the Pi's built-in `wlan0`), and that the correct
monitor-capable driver is loaded.

**Can't reach `http://<pi-ip>:2501` from another machine**
The Pi's firewall may be blocking the port. Allow it (example with `ufw`):

```bash
sudo ufw allow 2501/tcp
```

Also confirm Kismet is actually running and that you're using the Pi's real LAN IP.

**HTTP 401 / auth errors from the detector**
`KISMET_USER` / `KISMET_PASS` don't match the admin login you created on first launch.
Verify them, or re-check `~/.kismet/kismet_httpd.conf`. Re-`export` (Linux) or re-set
`$env:` (PowerShell) the correct values, then rerun. The scanner prints a one-line
`[kismet] query failed ...` warning when a query fails and keeps the loop alive.

**Kismet runs but no drones appear**
This is expected unless a **real drone is actively broadcasting** DroneID/Remote ID
nearby. Kismet is passive — it only sees what's on the air. To prove your *software*
pipeline is correct without a drone, use the **simulate** command in Section 7. Once a
real drone is in range, it will appear as a `UAV`/`Drone` device in the Kismet UI and
flow through as `source: kismet` hits.

---

## 9. Optional — run Kismet as a systemd service (always-on)

For a permanent, always-on sensor you can run Kismet under **systemd** so it starts at
boot and restarts on failure. The Kismet apt package installs with systemd integration;
enable and start it with:

```bash
sudo systemctl enable kismet
sudo systemctl start kismet
sudo systemctl status kismet
```

Make sure your capture source (e.g. `source=wlan1:name=ar271`) is set in
`/etc/kismet/kismet_site.conf` so the service picks it up automatically. This step is
**optional** — for development and testing, running `kismet -c wlan1` by hand is
perfectly fine.

---

### Sources
- [Kismet — Packages / apt install](https://www.kismetwireless.net/packages/)
- [Kismet docs — packages README](https://github.com/kismetwireless/kismet-docs/blob/master/readme/006-packages.md)
