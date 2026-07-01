"""Live runtime layer — the real-time front-end that turns the offline ML stack
(A1-A10) into a continuously-running detector with physical alerts, in the shape
of the original Team-Nayara single-file detector.

    capture.py        live IQ from RTL-SDR (real) or synth (mock fallback)
    wifi_scan.py      nmcli SSID scan + drone-name matching (Team-Nayara style)
    alerts.py         buzzer (GPIO 18) + Telegram + CSV log, with de-dup cooldown
    live_detector.py  the loop: capture -> A1/A2/A6/A5 -> A7 -> A8 -> alert

Everything degrades gracefully: on a laptop with no SDR/GPIO it runs in mock mode
so you can develop and demo; on the Raspberry Pi it auto-switches to real hardware.
"""
