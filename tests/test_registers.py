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


def test_missing_channels_encode_as_zero_not_garbage():
    regs = registers.encode(None, None, None, None, _ts())
    out = registers.decode(regs)
    assert out["voltage_v"] == 0
    assert out["temperature_c"] == 0


def test_values_are_clamped_rather_than_wrapping():
    # A wrapped uint16 would silently report a small number for a huge input,
    # which is far more dangerous than a clamped maximum.
    regs = registers.encode(99999.0, 99999.0, 0.0, 0.0, _ts())
    assert regs[registers.REG_VOLTAGE] == 0xFFFF
    assert regs[registers.REG_CURRENT] == 0xFFFF


def test_decode_rejects_short_register_block():
    with pytest.raises(ValueError):
        registers.decode([0, 0, 0])
