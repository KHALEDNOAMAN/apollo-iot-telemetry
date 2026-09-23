"""Turn a real energy dataset into a stream of TelemetryReading objects.

The device simulators do not know anything about CSV files. They ask this
module for readings and forward them over the wire, which keeps the transport
code and the data source independent of each other.

Supported profiles
------------------
household   UCI / Kaggle "Individual household electric power consumption".
            Real units: Voltage in volts, Global_intensity in amps,
            Global_active_power in kilowatts. It carries no temperature
            channel, so temperature_c is stored as NULL. That is deliberate:
            a real fleet has devices with different sensor sets and the
            schema has to tolerate it.

motor       Kaggle "Electric Motor Temperature" (measures_v2.csv). Has both
            electrical and thermal channels. Note that the published version
            of this dataset is z-scored, so the numbers are unitless unless
            you denormalise them first.

synthetic   No download needed. Generates a plausible three phase load
            profile so that the project runs end to end out of the box.
"""

from __future__ import annotations

import csv
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from .models import TelemetryReading

MISSING = {"", "?", "nan", "NaN", "NA", "null", "None"}


def _num(value: str | None) -> float | None:
    if value is None or value.strip() in MISSING:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _household(path: Path, device_id: str) -> Iterator[TelemetryReading]:
    with path.open(newline="", encoding="utf-8") as fh:
        # The UCI file is semicolon separated. Sniffing keeps it working if
        # someone exports a comma separated copy from Kaggle instead.
        sample = fh.read(4096)
        fh.seek(0)
        delimiter = ";" if sample.count(";") > sample.count(",") else ","
        for row in csv.DictReader(fh, delimiter=delimiter):
            ts = _household_ts(row)
            if ts is None:
                continue
            kw = _num(row.get("Global_active_power"))
            yield TelemetryReading(
                device_id=device_id,
                ts=ts,
                voltage_v=_num(row.get("Voltage")),
                current_a=_num(row.get("Global_intensity")),
                power_w=None if kw is None else kw * 1000.0,
                temperature_c=None,
                protocol="mqtt",
            )


def _household_ts(row: dict[str, str]) -> datetime | None:
    date, time = row.get("Date"), row.get("Time")
    if not date or not time:
        return None
    for fmt in ("%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(f"{date} {time}", fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _motor(path: Path, device_id: str) -> Iterator[TelemetryReading]:
    # The motor dataset has no timestamp column, only an ordered sample index
    # sampled at 2 Hz, so we reconstruct a monotonic clock from the row number.
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with path.open(newline="", encoding="utf-8") as fh:
        for i, row in enumerate(csv.DictReader(fh)):
            u_d, u_q = _num(row.get("u_d")), _num(row.get("u_q"))
            i_d, i_q = _num(row.get("i_d")), _num(row.get("i_q"))
            voltage = _magnitude(u_d, u_q)
            current = _magnitude(i_d, i_q)
            power = None
            if None not in (u_d, u_q, i_d, i_q):
                # Instantaneous power in the rotating dq frame.
                power = 1.5 * (u_d * i_d + u_q * i_q)
            yield TelemetryReading(
                device_id=device_id,
                ts=start + timedelta(milliseconds=500 * i),
                voltage_v=voltage,
                current_a=current,
                power_w=power,
                temperature_c=_num(row.get("stator_winding")),
                protocol="mqtt",
            )


def _magnitude(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return math.sqrt(a * a + b * b)


def _synthetic(device_id: str, rows: int = 5000, seed: int = 7) -> Iterator[TelemetryReading]:
    rng = random.Random(seed)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(rows):
        # Daily load curve plus noise, nominal 230 V grid.
        hour = (i / 60.0) % 24.0
        load = 0.35 + 0.45 * math.sin((hour - 6.0) / 24.0 * 2 * math.pi) ** 2
        current = round(max(0.2, load * 20 + rng.gauss(0, 0.6)), 3)
        voltage = round(rng.gauss(230.0, 1.8), 2)
        yield TelemetryReading(
            device_id=device_id,
            ts=start + timedelta(minutes=i),
            voltage_v=voltage,
            current_a=current,
            power_w=round(voltage * current * 0.95, 2),
            temperature_c=round(28.0 + current * 0.8 + rng.gauss(0, 0.4), 2),
            protocol="mqtt",
        )


def read_dataset(path: str | Path, profile: str, device_id: str) -> Iterator[TelemetryReading]:
    """Yield readings from the configured dataset.

    Falls back to the synthetic generator when the CSV is missing so that a
    reviewer can run the stack without downloading anything first.
    """
    profile = profile.lower()
    if profile == "synthetic":
        yield from _synthetic(device_id)
        return

    csv_path = Path(path)
    if not csv_path.exists():
        print(f"[dataset] {csv_path} not found, falling back to the synthetic profile")
        yield from _synthetic(device_id)
        return

    if profile == "household":
        yield from _household(csv_path, device_id)
    elif profile == "motor":
        yield from _motor(csv_path, device_id)
    else:
        raise ValueError(f"unknown dataset profile: {profile}")
