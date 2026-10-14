"""Modbus register map and the scaling that goes with it.

Modbus has no floating point and no units. A holding register is 16 bits and
nothing more, so every real world value has to be encoded as a scaled integer
and both ends have to agree on the scale. Getting this wrong is the single
most common Modbus bug, so the map lives in one file that the simulated meter
and the poller both import.

Holding register map for an Apollo energy meter
-----------------------------------------------
  HR 0      voltage       uint16   value = volts * 10          0 .. 6553.4 V
  HR 1      current       uint16   value = amps * 100          0 .. 655.34 A
  HR 2..3   active power  uint32   value = watts * 10          high word first
  HR 4      temperature   int16    value = celsius * 10      -3276.7 .. 3276.7
  HR 5..6   timestamp     uint32   unix seconds, UTC           high word first

uint32 values are transmitted high word first, which is the convention most
Turkish and European meter vendors follow. The alternative, low word first,
is why so many integrations read a plausible looking but wrong number.

Missing and out of range values
-------------------------------
A holding register cannot carry "no reading", so one value in each channel is
reserved for it: 0xFFFF for the unsigned channels and 0x8000 for the signed
one. Reserving a value costs one count off the top of each range, which is
why the ranges above end one LSB short of the raw maximum. encode() emits the
sentinel when a value is absent or out of range, and decode() returns None,
which PostgreSQL stores as NULL.

The alternative, clamping to the range limit, is worse than useless: a 20 kV
reading would come back as a plausible 6553.5 V and a miswired sensor reading
-1 V would come back as a healthy 0.0 V. A reading that is wrong and looks
right is the failure this file exists to prevent.

The uint32 timestamp wraps on 2106-02-07. That is a limit of the wire format,
not something this module hides.
"""

from __future__ import annotations

from datetime import datetime, timezone

REG_VOLTAGE = 0
REG_CURRENT = 1
REG_POWER_HI = 2
REG_POWER_LO = 3
REG_TEMPERATURE = 4
REG_TS_HI = 5
REG_TS_LO = 6
REGISTER_COUNT = 7

SCALE_VOLTAGE = 10
SCALE_CURRENT = 100
SCALE_POWER = 10
SCALE_TEMPERATURE = 10

_U16_MAX = 0xFFFF
_U32_MAX = 0xFFFFFFFF

# Reserved to mean "no reading". Outside every documented channel range.
U16_NA = 0xFFFF
I16_NA = 0x8000  # -32768, the one two's complement value with no positive twin
U32_NA = 0xFFFFFFFF


def _enc_u16(value: float | None, scale: int) -> int:
    """Scale into one unsigned register, or the N/A sentinel.

    Out of range is NOT clamped. Clamping returns a number that looks real.
    """
    if value is None:
        return U16_NA
    raw = int(round(value * scale))
    if raw < 0 or raw >= U16_NA:
        return U16_NA
    return raw


def _dec_u16(raw: int, scale: int) -> float | None:
    return None if raw == U16_NA else raw / scale


def _enc_i16(value: float | None, scale: int) -> int:
    """Two's complement encoding for a signed value in one register."""
    if value is None:
        return I16_NA
    raw = int(round(value * scale))
    if raw <= -32768 or raw > 32767:
        return I16_NA
    return raw & _U16_MAX


def _dec_i16(raw: int, scale: int) -> float | None:
    if raw == I16_NA:
        return None
    return (raw - 0x10000 if raw >= 0x8000 else raw) / scale


def _enc_u32(value: float | None, scale: int) -> tuple[int, int]:
    """Scale into two registers, high word first, or the N/A sentinel."""
    if value is None:
        return (U32_NA >> 16) & _U16_MAX, U32_NA & _U16_MAX
    raw = int(round(value * scale))
    if raw < 0 or raw >= U32_NA:
        return (U32_NA >> 16) & _U16_MAX, U32_NA & _U16_MAX
    return (raw >> 16) & _U16_MAX, raw & _U16_MAX


def _dec_u32(high: int, low: int, scale: int) -> float | None:
    raw = ((high & _U16_MAX) << 16) | (low & _U16_MAX)
    return None if raw == U32_NA else raw / scale


def _split_u32(value: int) -> tuple[int, int]:
    """Raw uint32 split, no sentinel. Used for the timestamp."""
    value = max(0, min(_U32_MAX, value))
    return (value >> 16) & _U16_MAX, value & _U16_MAX


def _join_u32(high: int, low: int) -> int:
    return ((high & _U16_MAX) << 16) | (low & _U16_MAX)


def encode(
    voltage_v: float | None,
    current_a: float | None,
    power_w: float | None,
    temperature_c: float | None,
    ts: datetime,
) -> list[int]:
    """Pack one reading into the register block the meter exposes.

    A value that is None, or outside its documented range, is encoded as the
    channel's N/A sentinel rather than clamped to the range limit.
    """
    power_hi, power_lo = _enc_u32(power_w, SCALE_POWER)
    ts_hi, ts_lo = _split_u32(int(ts.timestamp()))
    regs = [0] * REGISTER_COUNT
    regs[REG_VOLTAGE] = _enc_u16(voltage_v, SCALE_VOLTAGE)
    regs[REG_CURRENT] = _enc_u16(current_a, SCALE_CURRENT)
    regs[REG_POWER_HI] = power_hi
    regs[REG_POWER_LO] = power_lo
    regs[REG_TEMPERATURE] = _enc_i16(temperature_c, SCALE_TEMPERATURE)
    regs[REG_TS_HI] = ts_hi
    regs[REG_TS_LO] = ts_lo
    return regs


def decode(regs: list[int]) -> dict[str, object]:
    """Unpack a register block back into engineering units."""
    if len(regs) < REGISTER_COUNT:
        raise ValueError(f"expected {REGISTER_COUNT} registers, got {len(regs)}")
    ts_epoch = _join_u32(regs[REG_TS_HI], regs[REG_TS_LO])
    return {
        "voltage_v": _dec_u16(regs[REG_VOLTAGE], SCALE_VOLTAGE),
        "current_a": _dec_u16(regs[REG_CURRENT], SCALE_CURRENT),
        "power_w": _dec_u32(regs[REG_POWER_HI], regs[REG_POWER_LO], SCALE_POWER),
        "temperature_c": _dec_i16(regs[REG_TEMPERATURE], SCALE_TEMPERATURE),
        "ts": datetime.fromtimestamp(ts_epoch, tz=timezone.utc),
    }
