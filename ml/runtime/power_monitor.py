"""Battery / power telemetry via an INA219 I2C current+voltage monitor.

The field kit runs off a Li-ion pack; an INA219 on the Raspberry Pi 5's I2C bus
(default address 0x40) reports bus voltage and shunt current so the runtime can
show remaining charge and shut things down gracefully before a brown-out.

Seamless degradation — identical to the rest of the runtime:
    * INA219 present + smbus2 installed  -> real voltage/current/power reads.
    * Laptop / no I2C / no smbus2         -> a mock slowly-draining battery so
                                             every consumer (display, logs) still
                                             works with zero hardware.

    pm = PowerMonitor()
    pm.read()   # {"voltage_v","current_ma","power_mw","percent","source"}

The INA219 registers are read directly over smbus2 (no adafruit dependency
required), but `adafruit_ina219` is honoured first if it happens to be present.
"""
from __future__ import annotations
import os, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# INA219 defaults for a common breakout: address 0x40, 32V / 2A calibration.
INA219_ADDR = int(os.environ.get("INA219_ADDR", "0x40"), 0)
I2C_BUS = int(os.environ.get("INA219_BUS", "1"))

# Li-ion single-cell voltage window used to estimate charge percent.
LIION_EMPTY_V = 3.0
LIION_FULL_V = 4.2

# INA219 register map (datasheet).
_REG_BUSVOLTAGE = 0x02
_REG_POWER = 0x03
_REG_CURRENT = 0x04
_REG_CALIBRATION = 0x05


def _liion_percent(voltage_v: float) -> float:
    """Map a single-cell Li-ion voltage (3.0..4.2 V) to a 0-100 % estimate."""
    frac = (voltage_v - LIION_EMPTY_V) / (LIION_FULL_V - LIION_EMPTY_V)
    return round(max(0.0, min(1.0, frac)) * 100.0, 1)


class PowerMonitor:
    """Read pack voltage/current/power from an INA219 (with mock fallback)."""

    def __init__(self, addr: int = INA219_ADDR, bus: int = I2C_BUS,
                 force_mock: bool = False):
        self.addr = addr
        self.bus_num = bus
        self.force_mock = force_mock
        self._bus = None            # smbus2 handle (raw register path)
        self._adafruit = None       # adafruit_ina219.INA219 instance, if used
        self._warned = False
        # Mock battery state: start near full, drain a little on every read.
        self._mock_voltage = 4.10
        self.real = not force_mock and self._init_sensor()

    # ---- availability ---------------------------------------------------------
    def _init_sensor(self) -> bool:
        """Bring up the INA219 once; any failure routes us to the mock."""
        # Preferred: Adafruit's high-level driver if the user already has it.
        try:
            import board                       # type: ignore
            import adafruit_ina219             # type: ignore
            self._adafruit = adafruit_ina219.INA219(board.I2C(), self.addr)
            return True
        except Exception:
            self._adafruit = None
        # Fallback: talk to the chip directly over smbus2.
        try:
            from smbus2 import SMBus           # type: ignore
            self._bus = SMBus(self.bus_num)
            # 32V / 2A calibration (datasheet value 4096 -> 0.1 mA/bit current LSB).
            self._write_u16(_REG_CALIBRATION, 4096)
            self._read_u16(_REG_BUSVOLTAGE)     # probe read; raises if absent
            return True
        except Exception as e:
            if not self._warned:
                print(f"[power] INA219 unavailable ({type(e).__name__}); "
                      f"using mock battery")
                self._warned = True
            self._bus = None
            return False

    # ---- raw smbus2 register helpers -----------------------------------------
    def _write_u16(self, reg: int, value: int) -> None:
        # INA219 is big-endian; smbus word writes are little-endian, so swap.
        swapped = ((value << 8) & 0xFF00) | (value >> 8)
        self._bus.write_word_data(self.addr, reg, swapped)

    def _read_u16(self, reg: int) -> int:
        raw = self._bus.read_word_data(self.addr, reg)
        return ((raw << 8) & 0xFF00) | (raw >> 8)

    def _read_ina219(self) -> dict:
        """Read voltage/current/power from the live chip (adafruit or smbus2)."""
        if self._adafruit is not None:
            v = float(self._adafruit.bus_voltage) + float(self._adafruit.shunt_voltage)
            i = float(self._adafruit.current)      # already mA
            p = float(self._adafruit.power) * 1000.0  # W -> mW
            return {"voltage_v": v, "current_ma": i, "power_mw": p}
        # Raw path: bus-voltage register is bits [15:3], LSB = 4 mV.
        bus_raw = self._read_ina219_reg(_REG_BUSVOLTAGE)
        voltage_v = (bus_raw >> 3) * 0.004
        # Current LSB = 0.1 mA/bit (from the 4096 calibration above); signed.
        cur_raw = self._read_ina219_reg(_REG_CURRENT)
        if cur_raw > 0x7FFF:
            cur_raw -= 0x10000
        current_ma = cur_raw * 0.1
        power_mw = self._read_ina219_reg(_REG_POWER) * 2.0  # power LSB = 2 mW
        return {"voltage_v": voltage_v, "current_ma": current_ma,
                "power_mw": power_mw}

    def _read_ina219_reg(self, reg: int) -> int:
        return self._read_u16(reg)

    # ---- mock -----------------------------------------------------------------
    def _read_mock(self) -> dict:
        """A gently-draining ~1-cell Li-ion pack, so demos look plausible."""
        self._mock_voltage = max(LIION_EMPTY_V, self._mock_voltage - 0.004)
        current_ma = 480.0        # steady field-kit draw
        power_mw = self._mock_voltage * current_ma
        return {"voltage_v": round(self._mock_voltage, 3),
                "current_ma": current_ma,
                "power_mw": round(power_mw, 1)}

    # ---- public ---------------------------------------------------------------
    def read(self) -> dict:
        """Return one power sample as a plain dict (never raises)."""
        if self.real:
            try:
                m = self._read_ina219()
                self._warned = False
            except Exception as e:      # bus glitch mid-run -> fall back this read
                if not self._warned:
                    print(f"[power] INA219 read failed ({type(e).__name__}); "
                          f"mock this sample")
                    self._warned = True
                m = self._read_mock()
                source = "mock"
                return {**{k: round(v, 3) for k, v in m.items()},
                        "percent": _liion_percent(m["voltage_v"]),
                        "source": source}
            source = "ina219"
        else:
            m = self._read_mock()
            source = "mock"
        return {
            "voltage_v": round(m["voltage_v"], 3),
            "current_ma": round(m["current_ma"], 1),
            "power_mw": round(m["power_mw"], 1),
            "percent": _liion_percent(m["voltage_v"]),
            "source": source,
        }

    @property
    def mode(self) -> str:
        return "ina219" if self.real else "mock"


def main(argv=None):
    import argparse, json
    p = argparse.ArgumentParser(description="INA219 battery/power monitor")
    p.add_argument("--mock", action="store_true", help="force the mock battery")
    p.add_argument("-n", type=int, default=3, help="number of samples")
    args = p.parse_args(argv)
    pm = PowerMonitor(force_mock=args.mock)
    print(f"mode: {pm.mode}")
    for _ in range(max(1, args.n)):
        print(json.dumps(pm.read()))
        time.sleep(0.05)


if __name__ == "__main__":
    main()
