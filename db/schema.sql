-- Apollo Green Solutions, IoT telemetry store
--
-- Design notes
-- ------------
-- * devices and readings are kept separate so that a device can be renamed or
--   moved without touching millions of rows of history.
-- * ts is timestamptz. Field devices report in UTC and the dashboard renders
--   in local time, so storing a naive timestamp would lose information the
--   moment a site crosses a DST boundary.
-- * The measurement columns are NULLable on purpose. Not every device reports
--   every channel; a plain energy meter has no temperature probe.
-- * (device_id, ts, protocol) is UNIQUE. MQTT at QoS 1 guarantees at least
--   once delivery, which means duplicates are expected and normal. The unique
--   constraint plus ON CONFLICT DO NOTHING makes ingestion idempotent instead
--   of making the broker's job harder.
-- * protocol is part of the key rather than a plain column so that the same
--   physical meter read over both MQTT and Modbus produces two comparable
--   rows instead of silently overwriting one another.

CREATE TABLE IF NOT EXISTS devices (
    device_id   TEXT PRIMARY KEY,
    name        TEXT        NOT NULL,
    site        TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS readings (
    id            BIGSERIAL   PRIMARY KEY,
    device_id     TEXT        NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
    ts            TIMESTAMPTZ NOT NULL,
    protocol      TEXT        NOT NULL CHECK (protocol IN ('mqtt', 'modbus')),
    voltage_v     DOUBLE PRECISION,
    current_a     DOUBLE PRECISION,
    power_w       DOUBLE PRECISION,
    temperature_c DOUBLE PRECISION,
    ingested_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT readings_natural_key UNIQUE (device_id, ts, protocol)
);

-- The dashboard query is always "the last N minutes for this device", so the
-- index is ordered the same way the query reads it.
CREATE INDEX IF NOT EXISTS readings_device_ts_idx
    ON readings (device_id, ts DESC);

-- Supports fleet wide time range scans such as daily energy per site.
CREATE INDEX IF NOT EXISTS readings_ts_idx
    ON readings (ts DESC);

-- Convenience view: the most recent sample per device, which is what a
-- monitoring screen shows first.
CREATE OR REPLACE VIEW latest_readings AS
SELECT DISTINCT ON (device_id)
       device_id, ts, protocol, voltage_v, current_a, power_w, temperature_c
FROM readings
ORDER BY device_id, ts DESC;
