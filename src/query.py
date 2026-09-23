"""Small CLI so the stored data can actually be queried, which is the point.

  python -m src.query latest
  python -m src.query stats
  python -m src.query energy meter-mqtt-01
"""

from __future__ import annotations

import sys

from .config import settings
from .storage import TelemetryStore


def _table(rows: list[tuple], headers: list[str]) -> None:
    if not rows:
        print("(no rows)")
        return
    widths = [len(h) for h in headers]
    text = [[("" if v is None else str(v)) for v in row] for row in rows]
    for row in text:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    print(line)
    print("  ".join("-" * w for w in widths))
    for row in text:
        print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "latest"
    with TelemetryStore(settings.dsn) as store:
        if command == "latest":
            _table(
                store.latest(),
                ["device_id", "ts", "protocol", "voltage_v", "current_a", "power_w", "temp_c"],
            )
        elif command == "stats":
            _table(
                store.stats(),
                ["device_id", "protocol", "samples", "first_seen", "last_seen",
                 "avg_voltage_v", "avg_power_w"],
            )
        elif command == "energy":
            if len(sys.argv) < 3:
                print("usage: python -m src.query energy <device_id>")
                return 2
            _table(store.hourly_energy(sys.argv[2]), ["hour", "avg_power_w", "kwh"])
        else:
            print(__doc__)
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
