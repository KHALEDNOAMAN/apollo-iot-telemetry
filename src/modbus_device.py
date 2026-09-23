"""Simulated Modbus TCP energy meter.

This stands in for a real panel meter or PLC. It holds the current reading in
holding registers and refreshes them from the dataset on a timer. It never
pushes anything: a Modbus device only answers when it is asked, which is the
whole reason the ingestion side has to poll.

Run:  python -m src.modbus_device
"""

from __future__ import annotations

import logging
import threading
import time

from pymodbus.datastore import (
    ModbusSequentialDataBlock,
    ModbusServerContext,
    ModbusSlaveContext,
)
from pymodbus.server import StartTcpServer

from . import registers
from .config import settings
from .dataset import read_dataset

logging.basicConfig(level=logging.INFO, format="%(asctime)s [meter] %(message)s")
log = logging.getLogger(__name__)

DEVICE_ID = "meter-modbus-01"


def _refresh_loop(context: ModbusServerContext, interval: float) -> None:
    """Walk the dataset and keep the register block up to date."""
    slave = context[settings.modbus_unit_id]
    while True:
        for reading in read_dataset(settings.dataset_path, settings.dataset_profile, DEVICE_ID):
            regs = registers.encode(
                reading.voltage_v,
                reading.current_a,
                reading.power_w,
                reading.temperature_c,
                reading.ts,
            )
            # Function code 3 is "read holding registers"; setValues writes the
            # block the server will answer with.
            slave.setValues(3, 0, regs)
            time.sleep(interval)
        log.info("dataset exhausted, looping from the start")


def main() -> None:
    block = ModbusSequentialDataBlock(0, [0] * registers.REGISTER_COUNT)
    slave = ModbusSlaveContext(hr=block, zero_mode=True)
    context = ModbusServerContext(slaves={settings.modbus_unit_id: slave}, single=False)

    worker = threading.Thread(
        target=_refresh_loop,
        args=(context, settings.sample_interval_seconds),
        daemon=True,
    )
    worker.start()

    log.info(
        "listening on %s:%s unit %s, %s registers",
        settings.modbus_host,
        settings.modbus_port,
        settings.modbus_unit_id,
        registers.REGISTER_COUNT,
    )
    StartTcpServer(context=context, address=("0.0.0.0", settings.modbus_port))


if __name__ == "__main__":
    main()
