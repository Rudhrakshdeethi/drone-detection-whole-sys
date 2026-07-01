"""Alert cascade — the Team-Nayara output side, rebuilt around the ML verdict.

Three channels, each independently optional and each degrading to a no-op when
its dependency is missing:

    CSV log    always-safe append with header-on-first-write
    buzzer     gpiozero on GPIO 18 (Raspberry Pi); silent elsewhere
    Telegram   Bot API via requests; needs TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID

A cooldown de-dups buzzer/Telegram so a lingering drone doesn't spam you, while
the CSV still records every detection (the same intent as the repo's alert flag).
"""
from __future__ import annotations
import os, sys, csv, time
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from ml.common.config import REPORTS_DIR

DEFAULT_CSV = os.path.join(REPORTS_DIR, "live_detections.csv")
BUZZER_PIN = 18                       # same GPIO pin as the original detector


@dataclass
class AlertConfig:
    csv: bool = True
    buzzer: bool = True
    telegram: bool = True
    csv_path: str = DEFAULT_CSV
    cooldown_sec: float = 30.0        # min gap between buzzer/Telegram alerts
    bot_token: str | None = None
    chat_id: str | None = None

    def __post_init__(self):
        self.bot_token = self.bot_token or os.environ.get("TELEGRAM_BOT_TOKEN")
        self.chat_id = self.chat_id or os.environ.get("TELEGRAM_CHAT_ID")


class AlertManager:
    def __init__(self, cfg: AlertConfig | None = None):
        self.cfg = cfg or AlertConfig()
        self._buzzer = None
        self._buzzer_ready = False
        self._last_alert = 0.0
        self._csv_header_done = os.path.exists(self.cfg.csv_path)

    # ---- channel: CSV ---------------------------------------------------------
    def _log_csv(self, row: dict) -> None:
        if not self.cfg.csv:
            return
        os.makedirs(os.path.dirname(self.cfg.csv_path), exist_ok=True)
        new = not self._csv_header_done
        with open(self.cfg.csv_path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(row.keys()))
            if new:
                w.writeheader()
                self._csv_header_done = True
            w.writerow(row)

    # ---- channel: buzzer ------------------------------------------------------
    def _init_buzzer(self) -> None:
        if self._buzzer_ready:
            return
        self._buzzer_ready = True            # try once; don't retry every alert
        try:
            from gpiozero import Buzzer       # Raspberry Pi only
            self._buzzer = Buzzer(BUZZER_PIN)
        except Exception as e:
            print(f"[alert] buzzer unavailable ({type(e).__name__}); "
                  f"GPIO {BUZZER_PIN} alerts disabled")

    def _buzz(self, beeps: int = 5) -> None:
        if not self.cfg.buzzer:
            return
        self._init_buzzer()
        if self._buzzer is None:
            return
        for _ in range(beeps):              # 5 pulses, like the original
            self._buzzer.on(); time.sleep(0.25)
            self._buzzer.off(); time.sleep(0.25)

    # ---- channel: Telegram ----------------------------------------------------
    def _telegram(self, text: str) -> None:
        if not self.cfg.telegram:
            return
        if not (self.cfg.bot_token and self.cfg.chat_id):
            print("[alert] Telegram not configured (set TELEGRAM_BOT_TOKEN / "
                  "TELEGRAM_CHAT_ID); skipping")
            return
        try:
            import requests
            url = f"https://api.telegram.org/bot{self.cfg.bot_token}/sendMessage"
            requests.post(url, data={"chat_id": self.cfg.chat_id, "text": text},
                          timeout=10)
        except Exception as e:
            print(f"[alert] Telegram send failed ({type(e).__name__})")

    # ---- public ---------------------------------------------------------------
    def fire(self, *, row: dict, message: str, escalate: bool) -> None:
        """Always CSV-log `row`. If `escalate` and past cooldown, buzz + Telegram."""
        self._log_csv(row)
        if not escalate:
            return
        now = time.monotonic()
        if now - self._last_alert < self.cfg.cooldown_sec:
            return                          # de-dup: still ringing from last time
        self._last_alert = now
        print(message)
        self._buzz()
        self._telegram(message)
