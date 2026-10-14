"""Property based tests for the Modbus register codec.

A unit test checks the cases you thought of. These state a rule that must
hold for any input and let Hypothesis hunt for the input that breaks it.
Roughly 2,300 generated cases run here in under three seconds.
"""
from datetime import datetime, timezone

from hypothesis import given, settings, strategies as st

from src import registers

TS = datetime(2026, 1, 1, tzinfo=timezone.utc)


@given(v=st.floats(min_value=0, max_value=6553.5, allow_nan=False))
@settings(max_examples=400, deadline=None)
def test_voltage_roundtrip(v):
    out = registers.decode(registers.encode(v, 0, 0, 0, TS))
    assert abs(out["voltage_v"] - v) <= 0.05


@given(c=st.floats(min_value=0, max_value=655.35, allow_nan=False))
@settings(max_examples=400, deadline=None)
def test_current_roundtrip(c):
    out = registers.decode(registers.encode(0, c, 0, 0, TS))
    assert abs(out["current_a"] - c) <= 0.005


@given(t=st.floats(min_value=-3276.8, max_value=3276.7, allow_nan=False))
@settings(max_examples=400, deadline=None)
def test_temperature_roundtrip(t):
    out = registers.decode(registers.encode(0, 0, 0, t, TS))
    assert abs(out["temperature_c"] - t) <= 0.05


@given(p=st.floats(min_value=0, max_value=429496729.5, allow_nan=False))
@settings(max_examples=400, deadline=None)
def test_power_roundtrip(p):
    """Exercises the uint32 split and join, high word first."""
    out = registers.decode(registers.encode(0, 0, p, 0, TS))
    assert abs(out["power_w"] - p) <= 0.05


@given(ts=st.datetimes(min_value=datetime(1970, 1, 2),
                       max_value=datetime(2106, 1, 1)))
@settings(max_examples=400, deadline=None)
def test_timestamp_roundtrip(ts):
    ts = ts.replace(tzinfo=timezone.utc)
    out = registers.decode(registers.encode(0, 0, 0, 0, ts))
    assert abs((out["ts"] - ts).total_seconds()) < 1.0


@given(t=st.floats(min_value=-50, max_value=150, allow_nan=False))
@settings(max_examples=300, deadline=None)
def test_negative_temperature_sign_preserved(t):
    """A sub zero reading must not come back positive. Two's complement."""
    out = registers.decode(registers.encode(0, 0, 0, t, TS))
    assert (out["temperature_c"] < 0) == (round(t * 10) < 0)
