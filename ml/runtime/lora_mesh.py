"""LoRa mesh reporting over an SX1262 module on the Pi's UART.

Multiple field nodes share detections over long-range LoRa so a single operator
sees the whole net. This module speaks to an SX1262 breakout that exposes a
transparent serial bridge (e.g. Waveshare SX1262 HAT in AT/transparent mode):
each detection is written as one compact JSON line, and inbound JSON lines from
peer nodes are parsed back into dicts.

Seamless degradation — identical to the rest of the runtime:
    * SX1262 on a serial port + pyserial installed -> real mesh TX/RX.
    * Laptop / no port / no pyserial               -> a mock that loops every sent
                                                      message back through an
                                                      internal buffer, so poll()
                                                      round-trips with no hardware.

    mesh = LoraMesh()
    mesh.send({"threat": "HIGH", "score": 0.91})
    inbound = mesh.poll()   # -> [{...}, ...]
"""
from __future__ import annotations
import os, sys, json, collections

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

LORA_PORT = os.environ.get("LORA_PORT")          # e.g. /dev/ttyS0, /dev/ttyAMA0
LORA_BAUD = int(os.environ.get("LORA_BAUD", "115200"))
NODE_ID = os.environ.get("LORA_NODE_ID", "node-0")


class LoraMesh:
    """Send/receive detection JSON over an SX1262 serial link (with mock loopback)."""

    def __init__(self, port: str | None = None, baud: int = LORA_BAUD,
                 force_mock: bool = False, node_id: str = NODE_ID):
        self.port = port if port is not None else LORA_PORT
        self.baud = int(baud)
        self.node_id = node_id
        self.force_mock = force_mock
        self._serial = None
        self._rx_buf = ""                            # partial-line accumulator (real)
        self._loopback: collections.deque = collections.deque()  # mock inbox
        self._warned = False
        self.real = (not force_mock and self.port is not None
                     and self._init_serial())

    # ---- availability ---------------------------------------------------------
    def _init_serial(self) -> bool:
        """Open the UART once; any failure -> mock loopback."""
        try:
            import serial                            # type: ignore  (pyserial)
            self._serial = serial.Serial(self.port, self.baud, timeout=0)
            return True
        except Exception as e:
            if not self._warned:
                print(f"[lora] serial unavailable ({type(e).__name__}); "
                      f"using mock loopback")
                self._warned = True
            self._serial = None
            return False

    # ---- public ---------------------------------------------------------------
    def send(self, detection: dict) -> bool:
        """Write one compact JSON line. Returns True if it went out (or looped)."""
        payload = dict(detection)
        payload.setdefault("node", self.node_id)
        line = json.dumps(payload, separators=(",", ":"), default=str) + "\n"
        if self.real and self._serial is not None:
            try:
                self._serial.write(line.encode("utf-8"))
                self._warned = False
                return True
            except Exception as e:      # cable pulled mid-run -> degrade to mock
                if not self._warned:
                    print(f"[lora] write failed ({type(e).__name__}); "
                          f"loopback this send")
                    self._warned = True
                self.real = False
        # Mock: loop the message back so poll() returns it.
        self._loopback.append(line)
        return True

    def poll(self) -> list[dict]:
        """Return any complete inbound JSON messages as dicts (never raises)."""
        if self.real and self._serial is not None:
            try:
                chunk = self._serial.read(4096)
            except Exception as e:
                if not self._warned:
                    print(f"[lora] read failed ({type(e).__name__})")
                    self._warned = True
                return []
            if chunk:
                self._rx_buf += chunk.decode("utf-8", errors="ignore")
            lines, self._rx_buf = self._split_buffer(self._rx_buf)
        else:
            lines = [self._loopback.popleft()
                     for _ in range(len(self._loopback))]
        out: list[dict] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except (ValueError, TypeError):
                continue                # skip garbage / partial frames
        return out

    @staticmethod
    def _split_buffer(buf: str) -> tuple[list[str], str]:
        """Split accumulated RX text into complete lines + a trailing remainder."""
        if "\n" not in buf:
            return [], buf
        *complete, remainder = buf.split("\n")
        return complete, remainder

    def close(self) -> None:
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass

    @property
    def mode(self) -> str:
        return "sx1262" if self.real else "mock"


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description="SX1262 LoRa mesh reporter")
    p.add_argument("--port", default=None, help="serial port (e.g. /dev/ttyS0)")
    p.add_argument("--baud", type=int, default=LORA_BAUD)
    p.add_argument("--mock", action="store_true", help="force mock loopback")
    args = p.parse_args(argv)
    mesh = LoraMesh(port=args.port, baud=args.baud, force_mock=args.mock)
    print(f"mode: {mesh.mode}")
    mesh.send({"threat": "HIGH", "score": 0.91, "model": "DJI Mavic 3"})
    mesh.send({"threat": "MEDIUM", "score": 0.55, "model": "unknown"})
    inbound = mesh.poll()
    print(f"polled {len(inbound)} message(s) back:")
    for msg in inbound:
        print(json.dumps(msg))
    mesh.close()


if __name__ == "__main__":
    main()
