"""Configuration, read from environment variables with sane local defaults.

Everything that differs between "my laptop" and "docker compose" lives here so
that no module has to guess where the broker or the database is.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _env_float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


@dataclass(frozen=True)
class Settings:
    # PostgreSQL
    pg_host: str = _env("PG_HOST", "localhost")
    pg_port: int = _env_int("PG_PORT", 5432)
    pg_db: str = _env("PG_DB", "apollo")
    pg_user: str = _env("PG_USER", "apollo")
    pg_password: str = _env("PG_PASSWORD", "apollo")

    # MQTT
    mqtt_host: str = _env("MQTT_HOST", "localhost")
    mqtt_port: int = _env_int("MQTT_PORT", 1883)
    mqtt_topic_prefix: str = _env("MQTT_TOPIC_PREFIX", "apollo/telemetry")
    mqtt_qos: int = _env_int("MQTT_QOS", 1)

    # Modbus TCP
    modbus_host: str = _env("MODBUS_HOST", "localhost")
    modbus_port: int = _env_int("MODBUS_PORT", 5020)
    modbus_unit_id: int = _env_int("MODBUS_UNIT_ID", 1)
    modbus_poll_seconds: float = _env_float("MODBUS_POLL_SECONDS", 2.0)

    # Simulation
    dataset_path: str = _env("DATASET_PATH", "data/telemetry.csv")
    dataset_profile: str = _env("DATASET_PROFILE", "motor")
    sample_interval_seconds: float = _env_float("SAMPLE_INTERVAL_SECONDS", 1.0)
    batch_size: int = _env_int("BATCH_SIZE", 50)
    batch_seconds: float = _env_float("BATCH_SECONDS", 2.0)

    @property
    def dsn(self) -> str:
        return (
            f"host={self.pg_host} port={self.pg_port} dbname={self.pg_db} "
            f"user={self.pg_user} password={self.pg_password}"
        )


settings = Settings()
