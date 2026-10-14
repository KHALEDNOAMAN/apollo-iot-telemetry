"""Out of range and missing values must decode to None, never to a number.

This file started as the bug report. The codec used to clamp, so a 20 kV
reading came back as a plausible 6553.5 V, a miswired sensor reading -1 V came
back as a healthy 0.0 V, and None and 0.0 encoded to identical registers, so a
device with no temperature probe stored 0.0 over Modbus and NULL over MQTT.

src/registers.py now reserves one value per channel to mean "no reading"
(0xFFFF unsigned, 0x8000 signed), and decode returns None for it, which
PostgreSQL stores as NULL. These tests pin that contract so the clamping
cannot come back.

The one remaining limit is the uint32 timestamp, which wraps on 2106-02-07.
That is the wire format, not a codec bug, so it is asserted as the documented
behaviour rather than marked as a failure.
"""
from datetime import datetime, timezone

from hypothesis import given, settings, strategies as st

from src import registers

TS = datetime(2026, 1, 1, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# out of range decodes to None, not to the range limit
# --------------------------------------------------------------------------

@given(v=st.floats(min_value=6553.5, max_value=100_000, allow_nan=False))
@settings(max_examples=300, deadline=None)
def test_overvoltage_decodes_to_none(v):
    out = registers.decode(registers.encode(v, 0, 0, 0, TS))
    assert out["voltage_v"] is None, (
        f"{v} V decoded as {out['voltage_v']}, which looks like a real reading")


@given(v=st.floats(min_value=-10_000, max_value=-0.1, allow_nan=False))
@settings(max_examples=300, deadline=None)
def test_negative_voltage_decodes_to_none(v):
    """A miswired sensor must not read as a healthy zero."""
    out = registers.decode(registers.encode(v, 0, 0, 0, TS))
    assert out["voltage_v"] is None, f"{v} V decoded as {out['voltage_v']}"


@given(c=st.floats(min_value=655.35, max_value=10_000, allow_nan=False))
@settings(max_examples=300, deadline=None)
def test_overcurrent_decodes_to_none(c):
    out = registers.decode(registers.encode(0, c, 0, 0, TS))
    assert out["current_a"] is None


@given(t=st.floats(min_value=3276.8, max_value=10_000, allow_nan=False))
@settings(max_examples=300, deadline=None)
def test_overtemperature_decodes_to_none(t):
    out = registers.decode(registers.encode(0, 0, 0, t, TS))
    assert out["temperature_c"] is None, f"{t} C decoded as {out['temperature_c']}"


@given(t=st.floats(min_value=-10_000, max_value=-3276.8, allow_nan=False))
@settings(max_examples=300, deadline=None)
def test_undertemperature_decodes_to_none(t):
    out = registers.decode(registers.encode(0, 0, 0, t, TS))
    assert out["temperature_c"] is None


@given(p=st.floats(min_value=429496729.5, max_value=1e12, allow_nan=False))
@settings(max_examples=300, deadline=None)
def test_overpower_decodes_to_none(p):
    """The uint32 power channel has a sentinel too, not just the uint16 ones."""
    out = registers.decode(registers.encode(0, 0, p, 0, TS))
    assert out["power_w"] is None


# --------------------------------------------------------------------------
# a missing channel is distinguishable from a real zero
# --------------------------------------------------------------------------

def test_none_and_zero_encode_differently():
    """dataset.py stores NULL for a device with no probe. Modbus must agree."""
    enc_none = registers.encode(230.0, 10.0, 2300.0, None, TS)
    enc_zero = registers.encode(230.0, 10.0, 2300.0, 0.0, TS)
    assert enc_none != enc_zero, "None and 0.0 C encode to the SAME registers"


def test_none_round_trips_as_none_on_every_channel():
    out = registers.decode(registers.encode(None, None, None, None, TS))
    assert out["voltage_v"] is None
    assert out["current_a"] is None
    assert out["power_w"] is None
    assert out["temperature_c"] is None


def test_zero_round_trips_as_zero_not_none():
    """The sentinel must not swallow a genuine zero."""
    out = registers.decode(registers.encode(0.0, 0.0, 0.0, 0.0, TS))
    assert out["voltage_v"] == 0.0
    assert out["current_a"] == 0.0
    assert out["power_w"] == 0.0
    assert out["temperature_c"] == 0.0


def test_range_limits_still_encode():
    """One count below the sentinel is a real value and must survive."""
    out = registers.decode(registers.encode(6553.4, 655.34, 0, 3276.7, TS))
    assert out["voltage_v"] == 6553.4
    assert out["current_a"] == 655.34
    assert out["temperature_c"] == 3276.7


# --------------------------------------------------------------------------
# a limit of the wire format, asserted so it cannot change unnoticed
# --------------------------------------------------------------------------

def test_timestamp_wraps_after_2106_as_documented():
    """unix seconds in uint32 run out on 2106-02-07. Documented, not hidden."""
    out = registers.decode(registers.encode(0, 0, 0, 0,
                                            datetime(2110, 1, 1, tzinfo=timezone.utc)))
    assert out["ts"].year == 2106, (
        "the uint32 epoch wrap changed; update the register map if this is "
        "now a 64 bit timestamp")
