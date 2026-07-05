"""Response layer — LEGAL, deter-only output for a confirmed drone threat.

======================================================================
LEGAL SCOPE — READ THIS FIRST
----------------------------------------------------------------------
This module is **detection + deterrence ONLY**. It drives *passive* visual and
audible deterrents: a spotlight/beam light (via a solid-state relay) and a
buzzer. Its entire purpose is to make an operator aware they have been detected
and to discourage loitering.

It MUST NEVER perform, and this project deliberately contains no code for, any
form of **RF jamming, signal takeover, GPS spoofing, or command injection**
against a drone or its control/telemetry links. In nearly every jurisdiction
(e.g. the US Communications Act / FCC rules) operating a jammer or taking over
an aircraft is a serious federal crime. Deterrence stays on *our* side of the
air gap: light and sound only. Do not add "counter-UAS" transmit behaviour here.
======================================================================

Seamless degradation — identical to alerts.py:
    * gpiozero present on a Raspberry Pi -> real relay + buzzer GPIO.
    * gpiozero/hardware absent (e.g. a Windows laptop) -> mock no-ops that
      print the intended action, so import and `__main__` run anywhere.

    r = ResponseLayer()
    r.engage("WARNING")     # steady spotlight
    r.engage("CRITICAL")    # strobing spotlight + buzzer
    r.disengage()           # everything off
"""
from __future__ import annotations
import os, sys, time, threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

RELAY_PIN = 17             # SSR gate driving the spotlight / beam lights
BUZZER_PIN = 18            # KY-012 active buzzer (matches alerts.py convention)

STROBE_PERIOD_SEC = 0.5    # full on+off cycle time when strobing (2 Hz)


class ResponseLayer:
    """Deter-only physical output (spotlight relay + buzzer) with mock fallback.

    Deterrence ONLY — never RF jamming or drone takeover (illegal); see the
    module docstring. Levels: WARNING = steady light; CRITICAL = strobe + buzzer.
    """

    def __init__(self, relay_pin: int = RELAY_PIN, buzzer_pin: int = BUZZER_PIN,
                 force_mock: bool = False):
        self.relay_pin = int(relay_pin)
        self.buzzer_pin = int(buzzer_pin)
        self._relay = None
        self._buzzer = None
        self._real = False
        self._level = "IDLE"
        # Background strobe so engage()/disengage() return immediately.
        self._strobe_stop = threading.Event()
        self._strobe_thread: threading.Thread | None = None
        if not force_mock:
            self._init_gpio()

    # ---- availability ---------------------------------------------------------
    def _init_gpio(self) -> None:
        """Try once to bring up gpiozero devices; stay mock on any failure."""
        try:
            from gpiozero import OutputDevice, Buzzer      # Raspberry Pi only
            # active_high SSR: .on() closes the relay -> spotlight energised.
            self._relay = OutputDevice(self.relay_pin, active_high=True,
                                       initial_value=False)
            self._buzzer = Buzzer(self.buzzer_pin)
            self._real = True
        except Exception as e:
            print(f"[response] GPIO unavailable ({type(e).__name__}); "
                  f"running in mock mode (actions printed only)")
            self._relay = None
            self._buzzer = None
            self._real = False

    # ---- primitive outputs (no-op / print in mock) ----------------------------
    def _light(self, on: bool) -> None:
        if self._real and self._relay is not None:
            self._relay.on() if on else self._relay.off()
        else:
            print(f"[response:mock] spotlight {'ON' if on else 'off'}")

    def _buzz(self, on: bool) -> None:
        if self._real and self._buzzer is not None:
            self._buzzer.on() if on else self._buzzer.off()
        else:
            print(f"[response:mock] buzzer {'ON' if on else 'off'}")

    # ---- strobe worker --------------------------------------------------------
    def _start_strobe(self) -> None:
        """Blink the spotlight + buzzer in the background until stopped."""
        self._stop_strobe()
        self._strobe_stop.clear()

        def run():
            half = STROBE_PERIOD_SEC / 2.0
            while not self._strobe_stop.is_set():
                self._light(True); self._buzz(True)
                if self._strobe_stop.wait(half):
                    break
                self._light(False); self._buzz(False)
                if self._strobe_stop.wait(half):
                    break

        self._strobe_thread = threading.Thread(target=run, daemon=True)
        self._strobe_thread.start()

    def _stop_strobe(self) -> None:
        self._strobe_stop.set()
        t = self._strobe_thread
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=1.0)
        self._strobe_thread = None

    # ---- public ---------------------------------------------------------------
    def engage(self, level: str) -> None:
        """Activate deterrents for a threat *level*.

        WARNING  -> steady spotlight (make the operator aware they're seen).
        CRITICAL -> strobing spotlight + buzzer (maximum passive deterrence).
        Any other level is treated as stand-down (disengage). Never transmits.
        """
        lvl = str(level).upper()
        self._level = lvl
        if lvl == "WARNING":
            self._stop_strobe()
            self._buzz(False)
            self._light(True)
        elif lvl == "CRITICAL":
            self._start_strobe()
        else:
            self.disengage()

    def disengage(self) -> None:
        """Turn every deterrent off and return to idle."""
        self._stop_strobe()
        self._light(False)
        self._buzz(False)
        self._level = "IDLE"

    @property
    def mode(self) -> str:
        """`"gpio"` when driving real hardware, else `"mock"`."""
        return "gpio" if self._real else "mock"


def main(argv=None):
    """Self-test: cycle IDLE -> WARNING -> CRITICAL -> off in mock mode."""
    r = ResponseLayer(force_mock=True)
    print(f"mode: {r.mode}\n")
    print("-> WARNING (steady spotlight):")
    r.engage("WARNING")
    time.sleep(0.6)
    print("\n-> CRITICAL (strobe + buzzer), ~1.5s of blinks:")
    r.engage("CRITICAL")
    time.sleep(1.5)
    print("\n-> disengage (all off):")
    r.disengage()
    print("\nself-test complete (deter-only; no RF transmit ever performed)")


if __name__ == "__main__":
    main()
