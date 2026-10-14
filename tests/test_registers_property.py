"""Property based tests for the Modbus register codec.

A unit test checks the cases you thought of. These state a rule that must
hold for any input and let Hypothesis hunt for the input that breaks it.

Ranges here end one count short of the raw register maximum, because that
value is reserved to mean "no reading". See the register map in
src/registers.py.

Note on the assertions: an earlier version of this file compared with a
tolerance of 0.05, exactly half the 0.1 V quantum. Hypothesis found 1.05 V,
where the rounding error is 0.050000000000000044 in binary floating point,
so the test failed about half the time. A tolerance set to the exact
worst case is a flaky test. These assertions compute the expected
quantized value instead, which is exact and deterministic.
"""
from datetime import datetime, timezone

from hypothesis import given, settings, strategies as st

from src import registers

TS = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _quantized(value, scale):
    """What the codec must return: scaled, rounded to an integer, unscaled."""
    return round(value * scale) / scale


@given(v=st.floats(min_value=0, max_value=6553.4, allow_nan=False))
@settings(max_examples=500, deadline=None)
def test_voltage_roundtrip(v):
    out = registers.decode(registers.encode(v, 0, 0, 0, TS))
    assert out["voltage_v"] == _quantized(v, registers.SCALE_VOLTAGE)


@given(c=st.floats(min_value=0, max_value=655.34, allow_nan=False))
@settings(max_examples=500, deadline=None)
def test_current_roundtrip(c):
    out = registers.decode(registers.encode(0, c, 0, 0, TS))
    assert out["current_a"] == _quantized(c, registers.SCALE_CURRENT)


@given(t=st.floats(min_value=-3276.7, max_value=3276.7, allow_nan=False))
@settings(max_examples=500, deadline=None)
def test_temperature_roundtrip(t):
    """Covers the two's complement path for negative readings."""
    out = registers.decode(registers.encode(0, 0, 0, t, TS))
    assert out["temperature_c"] == _quantized(t, registers.SCALE_TEMPERATURE)


@given(p=st.floats(min_value=0, max_value=429496729.4, allow_nan=False))
@settings(max_examples=500, deadline=None)
def test_power_roundtrip(p):
    """Exercises the uint32 split and join, high word first."""
    out = registers.decode(registers.encode(0, 0, p, 0, TS))
    assert out["power_w"] == _quantized(p, registers.SCALE_POWER)


@given(ts=st.datetimes(min_value=datetime(1970, 1, 2),
                       max_value=datetime(2106, 1, 1)))
@settings(max_examples=500, deadline=None)
def test_timestamp_roundtrip(ts):
    ts = ts.replace(tzinfo=timezone.utc)
    out = registers.decode(registers.encode(0, 0, 0, 0, ts))
    assert abs((out["ts"] - ts).total_seconds()) < 1.0


@given(t=st.floats(min_value=-50, max_value=150, allow_nan=False))
@settings(max_examples=300, deadline=None)
def test_negative_temperature_sign_preserved(t):
    """A sub zero reading must not come back positive."""
    out = registers.decode(registers.encode(0, 0, 0, t, TS))
    assert (out["temperature_c"] < 0) == (round(t * registers.SCALE_TEMPERATURE) < 0)
