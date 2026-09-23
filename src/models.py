"""Shared data model for a single telemetry sample.

One reading is one moment in time from one device. Every transport in this
project (MQTT and Modbus) produces this same object, which is what lets the
storage layer stay transport agnostic.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True, slots=True)
class TelemetryReading:
    device_id: str
    ts: datetime
    voltage_v: float | None
    current_a: float | None
    power_w: float | None
    temperature_c: float | None
    protocol: str

    def __post_init__(self) -> None:
        if self.ts.tzinfo is None:
            raise ValueError("ts must be timezone aware; use UTC")
        if self.protocol not in ("mqtt", "modbus"):
            raise ValueError(f"unknown protocol: {self.protocol}")

    def to_json(self) -> str:
        payload = asdict(self)
        payload["ts"] = self.ts.isoformat()
        return json.dumps(payload, separators=(",", ":"))

    @classmethod
    def from_json(cls, raw: str | bytes) -> "TelemetryReading":
        data: dict[str, Any] = json.loads(raw)
        return cls(
            device_id=str(data["device_id"]),
            ts=_parse_ts(data["ts"]),
            voltage_v=_opt_float(data.get("voltage_v")),
            current_a=_opt_float(data.get("current_a")),
            power_w=_opt_float(data.get("power_w")),
            temperature_c=_opt_float(data.get("temperature_c")),
            protocol=str(data.get("protocol", "mqtt")),
        )


def _parse_ts(value: str) -> datetime:
    ts = datetime.fromisoformat(value)
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _opt_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)
