"""PostgreSQL persistence.

Both ingestion paths write through this one class, so batching, retries and
idempotency are implemented once instead of twice.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, Sequence

import psycopg2
from psycopg2.extras import execute_values

from .models import TelemetryReading

log = logging.getLogger(__name__)

_INSERT = """
INSERT INTO readings
    (device_id, ts, protocol, voltage_v, current_a, power_w, temperature_c)
VALUES %s
ON CONFLICT ON CONSTRAINT readings_natural_key DO NOTHING
"""

_UPSERT_DEVICE = """
INSERT INTO devices (device_id, name, site)
VALUES (%s, %s, %s)
ON CONFLICT (device_id) DO NOTHING
"""


class TelemetryStore:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._conn = psycopg2.connect(dsn)
        self._conn.autocommit = False

    # -- schema ---------------------------------------------------------
    def apply_schema(self, schema_path: str | Path = "db/schema.sql") -> None:
        sql = Path(schema_path).read_text(encoding="utf-8")
        with self._conn.cursor() as cur:
            cur.execute(sql)
        self._conn.commit()
        log.info("schema applied from %s", schema_path)

    def ensure_device(self, device_id: str, name: str, site: str | None = None) -> None:
        with self._conn.cursor() as cur:
            cur.execute(_UPSERT_DEVICE, (device_id, name, site))
        self._conn.commit()

    # -- writes ---------------------------------------------------------
    def insert_batch(self, readings: Sequence[TelemetryReading]) -> int:
        """Insert a batch, ignoring rows that are already stored.

        Returns the number of rows actually written, which is the useful
        number to log: a gap between len(readings) and the return value is
        duplicate delivery, not data loss.
        """
        if not readings:
            return 0
        rows: Iterable[tuple] = [
            (
                r.device_id,
                r.ts,
                r.protocol,
                r.voltage_v,
                r.current_a,
                r.power_w,
                r.temperature_c,
            )
            for r in readings
        ]
        try:
            with self._conn.cursor() as cur:
                execute_values(cur, _INSERT, rows, page_size=len(readings))
                written = cur.rowcount
            self._conn.commit()
            return max(written, 0)
        except psycopg2.Error:
            self._conn.rollback()
            raise

    # -- reads ----------------------------------------------------------
    def latest(self, limit: int = 20) -> list[tuple]:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT device_id, ts, protocol, voltage_v, current_a, power_w,"
                " temperature_c FROM latest_readings ORDER BY device_id LIMIT %s",
                (limit,),
            )
            return cur.fetchall()

    def stats(self) -> list[tuple]:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT device_id,
                       protocol,
                       count(*)              AS samples,
                       min(ts)               AS first_seen,
                       max(ts)               AS last_seen,
                       round(avg(voltage_v)::numeric, 2) AS avg_voltage_v,
                       round(avg(power_w)::numeric, 2)   AS avg_power_w
                FROM readings
                GROUP BY device_id, protocol
                ORDER BY device_id, protocol
                """
            )
            return cur.fetchall()

    def hourly_energy(self, device_id: str) -> list[tuple]:
        """Average power per hour, and the energy that implies in kWh."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT date_trunc('hour', ts) AS hour,
                       round(avg(power_w)::numeric, 1) AS avg_power_w,
                       round((avg(power_w) / 1000.0)::numeric, 3) AS kwh
                FROM readings
                WHERE device_id = %s AND power_w IS NOT NULL
                GROUP BY 1
                ORDER BY 1 DESC
                LIMIT 24
                """,
                (device_id,),
            )
            return cur.fetchall()

    def count(self) -> int:
        with self._conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM readings")
            return cur.fetchone()[0]

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "TelemetryStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
