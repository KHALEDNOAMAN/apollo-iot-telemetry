from datetime import datetime, timezone

import pytest

from src.dataset import read_dataset
from src.models import TelemetryReading


def _reading(**kw) -> TelemetryReading:
    base = dict(
        device_id="m1",
        ts=datetime(2026, 1, 1, tzinfo=timezone.utc),
        voltage_v=230.0,
        current_a=5.0,
        power_w=1150.0,
        temperature_c=30.0,
        protocol="mqtt",
    )
    base.update(kw)
    return TelemetryReading(**base)


def test_json_round_trip():
    r = _reading()
    assert TelemetryReading.from_json(r.to_json()) == r


def test_naive_timestamps_are_rejected():
    # A naive timestamp is the classic way telemetry ends up an hour out.
    with pytest.raises(ValueError):
        _reading(ts=datetime(2026, 1, 1))


def test_unknown_protocol_is_rejected():
    with pytest.raises(ValueError):
        _reading(protocol="carrier-pigeon")


def test_null_channels_survive_the_wire():
    r = _reading(temperature_c=None)
    assert TelemetryReading.from_json(r.to_json()).temperature_c is None


def test_household_csv_is_parsed_with_missing_values(tmp_path):
    csv = tmp_path / "household.txt"
    csv.write_text(
        "Date;Time;Global_active_power;Global_reactive_power;Voltage;Global_intensity\n"
        "16/12/2006;17:24:00;4.216;0.418;234.840;18.400\n"
        "16/12/2006;17:25:00;?;?;?;?\n",
        encoding="utf-8",
    )
    rows = list(read_dataset(csv, "household", "m1"))
    assert len(rows) == 2
    assert rows[0].voltage_v == pytest.approx(234.84)
    assert rows[0].power_w == pytest.approx(4216.0)   # kW converted to W
    assert rows[0].temperature_c is None              # dataset has no probe
    assert rows[1].voltage_v is None                  # "?" became NULL, not 0


def test_missing_file_falls_back_to_synthetic(tmp_path):
    rows = []
    for i, r in enumerate(read_dataset(tmp_path / "nope.csv", "household", "m1")):
        rows.append(r)
        if i > 5:
            break
    assert rows and all(r.voltage_v is not None for r in rows)


def test_synthetic_timestamps_are_strictly_increasing():
    rows = []
    for i, r in enumerate(read_dataset("", "synthetic", "m1")):
        rows.append(r)
        if i > 50:
            break
    assert all(b.ts > a.ts for a, b in zip(rows, rows[1:]))
