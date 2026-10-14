"""The register map is the easiest thing in the project to get subtly wrong,
so it gets the most tests."""

from datetime import datetime, timezone

import pytest

from src import registers


def _ts() -> datetime:
    return datetime(2026, 3, 1, 12, 30, 45, tzinfo=timezone.utc)


def test_round_trip_keeps_engineering_units():
    ts = _ts()
    regs = registers.encode(230.4, 12.34, 2841.7, 41.2, ts)
    out = registers.decode(regs)
    assert out["voltage_v"] == pytest.approx(230.4, abs=0.05)
    assert out["current_a"] == pytest.approx(12.34, abs=0.005)
    assert out["power_w"] == pytest.approx(2841.7, abs=0.05)
    assert out["temperature_c"] == pytest.approx(41.2, abs=0.05)
    assert out["ts"] == ts


def test_negative_temperature_survives_two_complement():
    regs = registers.encode(230.0, 1.0, 100.0, -17.5, _ts())
    assert registers.decode(regs)["temperature_c"] == pytest.approx(-17.5, abs=0.05)


def test_power_above_16_bits_uses_both_registers():
    # 90 kW scaled by 10 is 900000, far beyond one register.
    regs = registers.encode(400.0, 225.0, 90000.0, 30.0, _ts())
    assert regs[registers.REG_POWER_HI] > 0
    assert registers.decode(regs)["power_w"] == pytest.approx(90000.0, abs=0.05)


def test_missing_channels_decode_as_none_not_zero():
    # This test previously asserted that a missing channel decoded as 0, which
    # is what the codec did. That was the bug: a device with no temperature
    # probe stored 0.0 C over Modbus while the MQTT path stored NULL, so the
    # two rows for one meter were not comparable, which is the whole point of
    # keeping protocol in the natural key. The codec now emits an N/A sentinel
    # and decode returns None, which PostgreSQL stores as NULL.
    regs = registers.encode(None, None, None, None, _ts())
    out = registers.decode(regs)
    assert out["voltage_v"] is None
    assert out["temperature_c"] is None

    # and a real zero is still a real zero
    zero = registers.decode(registers.encode(0.0, 0.0, 0.0, 0.0, _ts()))
    assert zero["voltage_v"] == 0.0
    assert zero["temperature_c"] == 0.0


def test_out_of_range_reports_no_reading_rather_than_the_limit():
    # A wrapped uint16 would report a small number for a huge input. Clamping
    # to the maximum is not much better: 99999 V coming back as 6553.5 V is a
    # number that passes every sanity check downstream. The sentinel makes the
    # failure visible instead.
    regs = registers.encode(99999.0, 99999.0, 0.0, 0.0, _ts())
    assert regs[registers.REG_VOLTAGE] == registers.U16_NA
    assert regs[registers.REG_CURRENT] == registers.U16_NA
    out = registers.decode(regs)
    assert out["voltage_v"] is None
    assert out["current_a"] is None


def test_decode_rejects_short_register_block():
    with pytest.raises(ValueError):
        registers.decode([0, 0, 0])
