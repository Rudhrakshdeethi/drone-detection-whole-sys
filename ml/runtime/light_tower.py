"""Status light tower — a physical Green->Yellow->Orange->Red stack + buzzer.

Why this exists: an operator watching the ML verdict on a screen is easy to
miss. A cheap SMD-LED signal tower (the kind on factory machines) turns the A7
threat level into an at-a-glance, across-the-room lamp: one lamp lit per level,
with an audible buzzer only when things go CRITICAL. It mirrors the A7 threat
scale exactly, one colour per level:

    SAFE      -> green   (nothing of concern in the airspace)
    WATCH     -> yellow  (possible / low-confidence contact)
    WARNING   -> orange  (probable drone; operator should look)
    CRITICAL  -> red + buzzer (confirmed threat; demand attention)

Seamless degradation — identical to response.py / alerts.py:
    * gpiozero present on a Raspberry Pi -> real LED + buzzer GPIO.
    * gpiozero/hardware absent (e.g. a Windows laptop) -> mock no-ops that
      print the lamp state, so import and `__main__` run anywhere.

    t = LightTower()
    t.set_level("WATCH")      # only the yellow lamp lit
    t.set_level("CRITICAL")   # only the red lamp lit + buzzer beeps
    t.off()                   # every lamp + buzzer off

This is a passive *indicator* only — like response.py it never transmits and
never touches a drone; it just lights local lamps and beeps.
"""
from __future__ import annotations
import os, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Default BCM GPIO pins — one per SMD lamp on the tower, plus the buzzer.
GREEN_PIN = 5
YELLOW_PIN = 6
ORANGE_PIN = 13
RED_PIN = 19
BUZZER_PIN = 26            # active buzzer; beeps on CRITICAL only

# A7 threat level -> which lamp colour lights up.
LEVEL_TO_COLOR = {
    "SAFE": "green",
    "WATCH": "yellow",
    "WARNING": "orange",
    "CRITICAL": "red",
}


class LightTower:
    """Four-colour status tower (green/yellow/orange/red) + buzzer, mock-safe.

    One lamp is lit at a time, chosen from the A7 threat level via
    ``LEVEL_TO_COLOR``. The buzzer sounds only on CRITICAL. Off a Raspberry Pi
    (no gpiozero) every action degrades to a printed mock line. Passive
    indicator only — never transmits, never touches a drone.
    """

    def __init__(self, green_pin: int = GREEN_PIN, yellow_pin: int = YELLOW_PIN,
                 orange_pin: int = ORANGE_PIN, red_pin: int = RED_PIN,
                 buzzer_pin: int = BUZZER_PIN, force_mock: bool = False):
        self.pins = {
            "green": int(green_pin),
            "yellow": int(yellow_pin),
            "orange": int(orange_pin),
            "red": int(red_pin),
        }
        self.buzzer_pin = int(buzzer_pin)
        self._leds: dict[str, object] = {}
        self._buzzer = None
        self._real = False
        self._level = "OFF"
        if not force_mock:
            self._init_gpio()

    # ---- availability ---------------------------------------------------------
    def _init_gpio(self) -> None:
        """Try once to bring up gpiozero devices; stay mock on any failure."""
        try:
            from gpiozero import LED, Buzzer          # Raspberry Pi only
            self._leds = {name: LED(pin) for name, pin in self.pins.items()}
            self._buzzer = Buzzer(self.buzzer_pin)
            self._real = True
        except Exception as e:
            print(f"[tower] GPIO unavailable ({type(e).__name__}); "
                  f"running in mock mode (lamp state printed only)")
            self._leds = {}
            self._buzzer = None
            self._real = False

    # ---- primitive outputs (no-op / print in mock) ----------------------------
    def _lamp(self, color: str, on: bool) -> None:
        if self._real and color in self._leds:
            self._leds[color].on() if on else self._leds[color].off()
        else:
            print(f"[tower:mock] {color:<6} lamp {'ON' if on else 'off'}")

    def _buzz(self, on: bool) -> None:
        if self._real and self._buzzer is not None:
            self._buzzer.on() if on else self._buzzer.off()
        else:
            print(f"[tower:mock] buzzer {'ON' if on else 'off'}")

    # ---- public ---------------------------------------------------------------
    def set_level(self, level: str) -> None:
        """Light the single lamp for a threat *level*; beep only on CRITICAL.

        ``level`` is one of ``SAFE`` / ``WATCH`` / ``WARNING`` / ``CRITICAL``
        (case-insensitive), mapped to green / yellow / orange / red via
        ``LEVEL_TO_COLOR``. Any unknown level clears the tower (same as
        ``off()``). Exactly one lamp is ever lit at a time.
        """
        lvl = str(level).upper()
        color = LEVEL_TO_COLOR.get(lvl)
        if color is None:
            self.off()
            return
        self._level = lvl
        for name in self.pins:                    # light the match, clear the rest
            self._lamp(name, name == color)
        self._buzz(lvl == "CRITICAL")

    def off(self) -> None:
        """Turn every lamp and the buzzer off; return to the OFF state."""
        for name in self.pins:
            self._lamp(name, False)
        self._buzz(False)
        self._level = "OFF"

    @property
    def mode(self) -> str:
        """`"gpio"` when driving real hardware, else `"mock"`."""
        return "gpio" if self._real else "mock"


def main(argv=None):
    """Self-test: cycle SAFE -> WATCH -> WARNING -> CRITICAL in mock mode."""
    t = LightTower(force_mock=True)
    print(f"mode: {t.mode}\n")
    for level in ("SAFE", "WATCH", "WARNING", "CRITICAL"):
        color = LEVEL_TO_COLOR[level]
        print(f"-> {level} (expect only {color} lit"
              f"{', + buzzer' if level == 'CRITICAL' else ''}):")
        t.set_level(level)
        time.sleep(0.4)
        print()
    print("-> off (all clear):")
    t.off()
    print("\nself-test complete (passive indicator; no RF transmit ever performed)")


if __name__ == "__main__":
    main()
