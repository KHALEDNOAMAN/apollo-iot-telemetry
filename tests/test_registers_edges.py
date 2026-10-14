"""Out of range behaviour. These are expected to FAIL on the current codec.

This file is the bug report, written as code. Five ways a reading can be
silently corrupted:

  20000 V   -> 6553.5 V      a plausible looking wrong number
  -1.0 V    -> 0.0 V         a miswired sensor reads as a healthy zero
  3277 C    -> 3276.7 C      same clamp, same silence
  None      -> 0.0 C         a device with no probe reports zero, not NULL
  year 2110 -> 2106-02-07    uint32 epoch wrap

The module docstring in src/registers.py says the worst Modbus bug is "a
plausible looking but wrong number". Clamping produces exactly that.

The fix is an explicit N/A sentinel (0xFFFF for uint16, 0x8000 for int16,
both outside every documented range) so decode returns None and PostgreSQL
stores NULL, which is what db/schema.sql already promises.

Mark these xfail if you want a green suite before the fix lands:
  pytest.mark.xfail(reason="silent clamping, see migration notes", strict=True)
"""
from datetime import datetime, timezone

from hypothesis import given, settings, strategies as st

from src import registers

TS = datetime(2026, 1, 1, tzinfo=timezone.utc)


@given(v=st.floats(min_value=6553.6, max_value=100000, allow_nan=False))
@settings(max_examples=200, deadline=None)
def test_overvoltage_is_not_silently_wrong(v):
    out = registers.decode(registers.encode(v, 0, 0, 0, TS))
    assert out["voltage_v"] >= v - 0.1, (
        f"{v} V encoded then decoded as {out['voltage_v']} V")


@given(v=st.floats(min_value=-10000, max_value=-0.1, allow_nan=False))
@settings(max_examples=200, deadline=None)
def test_negative_voltage_is_not_silently_zero(v):
    out = registers.decode(registers.encode(v, 0, 0, 0, TS))
    assert out["voltage_v"] < 0, (
        f"{v} V encoded then decoded as {out['voltage_v']} V")


@given(t=st.floats(min_value=3276.8, max_value=10000, allow_nan=False))
@settings(max_examples=200, deadline=None)
def test_overtemperature_is_not_silently_wrong(t):
    out = registers.decode(registers.encode(0, 0, 0, t, TS))
    assert out["temperature_c"] >= t - 0.1, (
        f"{t} C encoded then decoded as {out['temperature_c']} C")


def test_null_is_distinguishable_from_zero():
    """dataset.py stores NULL for a missing probe. Modbus must agree."""
    enc_none = registers.encode(230.0, 10.0, 2300.0, None, TS)
    enc_zero = registers.encode(230.0, 10.0, 2300.0, 0.0, TS)
    assert enc_none != enc_zero, "None and 0.0 C encode to the SAME registers"


def test_post_2106_timestamp():
    """unix seconds in uint32 wrap in 2106."""
    far = datetime(2110, 1, 1, tzinfo=timezone.utc)
    out = registers.decode(registers.encode(0, 0, 0, 0, far))
    assert out["ts"].year >= 2110, f"2110 decoded as {out['ts']}"
