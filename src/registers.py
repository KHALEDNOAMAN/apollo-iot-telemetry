"""Modbus register map and the scaling that goes with it.

Modbus has no floating point and no units. A holding register is 16 bits and
nothing more, so every real world value has to be encoded as a scaled integer
and both ends have to agree on the scale. Getting this wrong is the single
most common Modbus bug, so the map lives in one file that the simulated meter
and the poller both import.

Holding register map for an Apollo energy meter
-----------------------------------------------
  HR 0      voltage       uint16   value = volts * 10          0 .. 6553.5 V
  HR 1      current       uint16   value = amps * 100          0 .. 655.35 A
  HR 2..3   active power  uint32   value = watts * 10          high word first
  HR 4      temperature   int16    value = celsius * 10      -3276.8 .. 3276.7
  HR 5..6   timestamp     uint32   unix seconds, UTC           high word first

uint32 values are transmitted high word first, which is the convention most
Turkish and European meter vendors follow. The alternative, low word first,
is why so many integrations read a plausible looking but wrong number.
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


def _clamp_u16(value: int) -> int:
    return max(0, min(_U16_MAX, value))


def _to_i16(value: int) -> int:
    """Two's complement encoding for a signed value in one register."""
    value = max(-32768, min(32767, value))
    return value & _U16_MAX


def _from_i16(raw: int) -> int:
    return raw - 0x10000 if raw >= 0x8000 else raw


def _split_u32(value: int) -> tuple[int, int]:
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
    """Pack one reading into the register block the meter exposes."""
    power_hi, power_lo = _split_u32(int(round((power_w or 0.0) * SCALE_POWER)))
    ts_hi, ts_lo = _split_u32(int(ts.timestamp()))
    regs = [0] * REGISTER_COUNT
    regs[REG_VOLTAGE] = _clamp_u16(int(round((voltage_v or 0.0) * SCALE_VOLTAGE)))
    regs[REG_CURRENT] = _clamp_u16(int(round((current_a or 0.0) * SCALE_CURRENT)))
    regs[REG_POWER_HI] = power_hi
    regs[REG_POWER_LO] = power_lo
    regs[REG_TEMPERATURE] = _to_i16(int(round((temperature_c or 0.0) * SCALE_TEMPERATURE)))
    regs[REG_TS_HI] = ts_hi
    regs[REG_TS_LO] = ts_lo
    return regs


def decode(regs: list[int]) -> dict[str, object]:
    """Unpack a register block back into engineering units."""
    if len(regs) < REGISTER_COUNT:
        raise ValueError(f"expected {REGISTER_COUNT} registers, got {len(regs)}")
    ts_epoch = _join_u32(regs[REG_TS_HI], regs[REG_TS_LO])
    return {
        "voltage_v": regs[REG_VOLTAGE] / SCALE_VOLTAGE,
        "current_a": regs[REG_CURRENT] / SCALE_CURRENT,
        "power_w": _join_u32(regs[REG_POWER_HI], regs[REG_POWER_LO]) / SCALE_POWER,
        "temperature_c": _from_i16(regs[REG_TEMPERATURE]) / SCALE_TEMPERATURE,
        "ts": datetime.fromtimestamp(ts_epoch, tz=timezone.utc),
    }
