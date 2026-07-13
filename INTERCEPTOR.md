# Counter-Drone Interceptor — how to run it

## Tello demo drone (TELLO-954B1F)

The Tello is the easy demo target. It uses the UDP SDK (`192.168.10.1:8889`) and
its WiFi is **open** (no password). A stock Tello allows only **one** WiFi client,
so the laptop **seizes** the link (the phone drops) and lands it — a clean
interception.

- **Full dashboard demo:** double-click **`Launch-Tello-Interceptor.bat`** →
  joins the Tello, opens the dashboard with LAND armed, restores internet on exit.
- **One-shot land:** double-click **`Land-Tello-Now.bat`** → seizes the link,
  sends LAND, reconnects internet — all in one go (no dashboard).

Set `VITE_SSID=TELLO-954B1F` in `.env.local` (already set) so the UI flags it and
the backend routes LAND to the Tello stack. To switch back to the Pluto, set
`VITE_SSID=PlutoX_2025_1043` and use `Launch-Interceptor.bat`.

---

## Pluto drone (PlutoX_2025_1043)

**Roles:** the phone is the **pilot** (flies the drone). This laptop is the
**interceptor** — when you click **LAND** on the dashboard, it commands your own
Pluto (`PlutoX_2025_1043`) to land, overriding the flight via MSP over TCP
(`192.168.4.1:23`).

## Why there's a launcher

This laptop has **one WiFi radio**, so it can be on the *drone's* WiFi **or** the
*internet* — never both. The dashboard and backend run entirely on `localhost`,
so they work with **no internet**. The launcher just handles the WiFi hand-off
for you and puts it back when you're done.

## Run it

1. Make sure the drone is **powered on** and broadcasting `PlutoX_2025_1043`.
   (Optional: for a clean laptop-controlled LAND, close the phone app first so
   the laptop holds the single control link.)
2. **Double-click `Launch-Interceptor.bat`** (or run
   `powershell -ExecutionPolicy Bypass -File interceptor.ps1`).
3. It will:
   - join the drone WiFi (you'll lose internet — expected),
   - start the backend + dashboard,
   - open `http://localhost:8443`,
   - arm **LAND** for `PlutoX_2025_1043`.
4. On the dashboard: the camera (laptop webcam), map, and log flag the drone as
   **TARGET**. To land: **tap LAND to arm, tap again within 4 s to confirm.**
5. When finished, go back to the launcher window and **press ENTER** — it stops
   the servers and reconnects your internet automatically.

## If you get stuck offline

If the window was closed abruptly and the laptop is stuck on the drone WiFi:

```
powershell -ExecutionPolicy Bypass -File reconnect-internet.ps1
```

## Notes

- The drone SSID lives in `.env.local` (`VITE_SSID`) for the UI, and is passed to
  the backend as `PLUTO_SSID` by the launcher. The WiFi **password** is never
  stored in the repo — it lives only in the saved Windows WiFi profile.
- LAND uses the official `plutocontrol` library (`land()` = controlled autoland).
  If it's ever missing, the backend falls back to a raw-MSP disarm.
- Real landing only happens when the laptop is actually joined to the drone and
  the control link answers; otherwise LAND runs in mock and just reports intent.
