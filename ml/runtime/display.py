"""Compact status HUD for a 0.96" SSD1306 OLED (128x64) on the Raspberry Pi.

The field kit shows the live threat verdict on a tiny I2C OLED so an operator can
read state at a glance without a laptop. Two driver stacks are supported, either
optional:

    * luma.oled          (luma.core canvas drawing) — preferred if present.
    * adafruit_ssd1306   (+ PIL) — used as a fallback.

Seamless degradation — identical to the rest of the runtime:
    * OLED wired + a driver installed  -> real frames pushed to the panel.
    * Laptop / no I2C / no driver       -> a mock that prints the frame to stdout
                                           so you can still see exactly what would
                                           show, with zero hardware.

    disp = StatusDisplay()
    disp.show("HIGH", 0.91, extra="DJI Mavic 3")
"""
from __future__ import annotations
import os, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

OLED_WIDTH = 128
OLED_HEIGHT = 64
OLED_ADDR = int(os.environ.get("OLED_ADDR", "0x3C"), 0)
I2C_PORT = int(os.environ.get("OLED_BUS", "1"))


class StatusDisplay:
    """Render a 2-3 line threat status to an SSD1306 OLED (with mock fallback)."""

    def __init__(self, addr: int = OLED_ADDR, port: int = I2C_PORT,
                 width: int = OLED_WIDTH, height: int = OLED_HEIGHT,
                 force_mock: bool = False):
        self.addr = addr
        self.port = port
        self.width = width
        self.height = height
        self.force_mock = force_mock
        self._backend = "mock"      # "luma" | "adafruit" | "mock"
        self._device = None         # luma device
        self._oled = None           # adafruit device
        self._image = None          # PIL image (adafruit path)
        self._draw = None
        self._font = None
        self._warned = False
        self.real = not force_mock and self._init_panel()

    # ---- availability ---------------------------------------------------------
    def _init_panel(self) -> bool:
        """Try luma first, then adafruit; any failure -> mock."""
        try:
            from luma.core.interface.serial import i2c   # type: ignore
            from luma.oled.device import ssd1306          # type: ignore
            serial = i2c(port=self.port, address=self.addr)
            self._device = ssd1306(serial, width=self.width, height=self.height)
            self._backend = "luma"
            return True
        except Exception:
            self._device = None
        try:
            import board                                  # type: ignore
            import adafruit_ssd1306                        # type: ignore
            from PIL import Image, ImageDraw, ImageFont    # type: ignore
            self._oled = adafruit_ssd1306.SSD1306_I2C(
                self.width, self.height, board.I2C(), addr=self.addr)
            self._image = Image.new("1", (self.width, self.height))
            self._draw = ImageDraw.Draw(self._image)
            self._font = ImageFont.load_default()
            self._backend = "adafruit"
            return True
        except Exception as e:
            if not self._warned:
                print(f"[display] OLED unavailable ({type(e).__name__}); "
                      f"printing frames to stdout")
                self._warned = True
            self._backend = "mock"
            return False

    # ---- frame composition ----------------------------------------------------
    def _lines(self, threat_level: str, score: float, extra: str) -> list[str]:
        """Build the 2-3 short lines shown on the panel."""
        lines = [
            f"THREAT: {str(threat_level).upper()}",
            f"score: {float(score):.2f}",
        ]
        if extra:
            lines.append(extra[:21])          # ~21 chars fit at the default font
        return lines

    # ---- backends -------------------------------------------------------------
    def _show_luma(self, lines: list[str]) -> None:
        from luma.core.render import canvas   # type: ignore
        with canvas(self._device) as draw:
            for i, text in enumerate(lines):
                draw.text((0, i * 18), text, fill="white")

    def _show_adafruit(self, lines: list[str]) -> None:
        self._draw.rectangle((0, 0, self.width, self.height), outline=0, fill=0)
        for i, text in enumerate(lines):
            self._draw.text((0, i * 18), text, font=self._font, fill=255)
        self._oled.image(self._image)
        self._oled.show()

    def _show_mock(self, lines: list[str]) -> None:
        """Print an ASCII-boxed approximation of the OLED frame to stdout."""
        inner = self.width // 6                # ~6px per default-font char
        bar = "+" + "-" * inner + "+"
        print(bar)
        for text in lines:
            print("|" + text.ljust(inner)[:inner] + "|")
        print(bar)

    # ---- public ---------------------------------------------------------------
    def show(self, threat_level: str, score: float, extra: str = "") -> None:
        """Render the current threat status; never raises."""
        lines = self._lines(threat_level, score, extra)
        try:
            if self.real and self._backend == "luma":
                self._show_luma(lines)
            elif self.real and self._backend == "adafruit":
                self._show_adafruit(lines)
            else:
                self._show_mock(lines)
        except Exception as e:      # panel yanked / bus glitch -> degrade live
            if not self._warned:
                print(f"[display] push failed ({type(e).__name__}); "
                      f"falling back to stdout")
                self._warned = True
            self.real = False
            self._backend = "mock"
            self._show_mock(lines)

    def clear(self) -> None:
        """Blank the panel (no-op / newline in mock)."""
        try:
            if self.real and self._backend == "luma":
                self._device.clear()
            elif self.real and self._backend == "adafruit":
                self._draw.rectangle((0, 0, self.width, self.height),
                                     outline=0, fill=0)
                self._oled.image(self._image)
                self._oled.show()
            else:
                print()
        except Exception:
            pass

    @property
    def mode(self) -> str:
        return self._backend if self.real else "mock"


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description="SSD1306 OLED status display")
    p.add_argument("--mock", action="store_true", help="force stdout mock frames")
    args = p.parse_args(argv)
    disp = StatusDisplay(force_mock=args.mock)
    print(f"mode: {disp.mode}")
    frames = [
        ("LOW", 0.12, "all clear"),
        ("MEDIUM", 0.58, "RF anomaly"),
        ("HIGH", 0.91, "DJI Mavic 3"),
    ]
    for level, score, extra in frames:
        disp.show(level, score, extra)
        time.sleep(0.2)
    disp.clear()


if __name__ == "__main__":
    main()
