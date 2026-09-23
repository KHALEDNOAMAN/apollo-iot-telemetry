"""Modbus TCP master: poll the meter and store what it reports.

Polling is the part people underestimate. The meter has no idea anyone is
listening, so the poll interval is the sample rate, a missed poll is a
permanent hole in the data, and the client has to reconnect on its own.

Run:  python -m src.modbus_poller
"""

from __future__ import annotations

import logging
import time

from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusException

from . import registers
from .config import settings
from .models import TelemetryReading
from .storage import TelemetryStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s [poller] %(message)s")
log = logging.getLogger(__name__)

DEVICE_ID = "meter-modbus-01"


def poll_once(client: ModbusTcpClient) -> TelemetryReading | None:
    result = client.read_holding_registers(
        0, count=registers.REGISTER_COUNT, slave=settings.modbus_unit_id
    )
    if result.isError():
        log.warning("modbus error: %s", result)
        return None
    values = registers.decode(list(result.registers))
    return TelemetryReading(
        device_id=DEVICE_ID,
        ts=values["ts"],
        voltage_v=values["voltage_v"],
        current_a=values["current_a"],
        power_w=values["power_w"],
        temperature_c=values["temperature_c"],
        protocol="modbus",
    )


def main() -> None:
    store = TelemetryStore(settings.dsn)
    store.ensure_device(DEVICE_ID, "Simulated panel meter", "Athens lab")
    client = ModbusTcpClient(
        settings.modbus_host, port=settings.modbus_port, timeout=3
    )

    buffer: list[TelemetryReading] = []
    last_flush = time.monotonic()
    log.info(
        "polling %s:%s every %ss",
        settings.modbus_host,
        settings.modbus_port,
        settings.modbus_poll_seconds,
    )

    try:
        while True:
            try:
                if not client.connected:
                    client.connect()
                reading = poll_once(client)
                if reading is not None:
                    buffer.append(reading)
            except (ModbusException, OSError) as exc:
                # A field link drops all the time. Log, back off, keep going.
                log.warning("poll failed, retrying: %s", exc)
                client.close()
                time.sleep(2)

            due = (
                len(buffer) >= settings.batch_size
                or time.monotonic() - last_flush >= settings.batch_seconds
            )
            if buffer and due:
                written = store.insert_batch(buffer)
                log.info("stored %s of %s polled rows", written, len(buffer))
                buffer.clear()
                last_flush = time.monotonic()

            time.sleep(settings.modbus_poll_seconds)
    except KeyboardInterrupt:
        if buffer:
            store.insert_batch(buffer)
        log.info("stopped, %s rows in the database", store.count())
    finally:
        client.close()
        store.close()


if __name__ == "__main__":
    main()
