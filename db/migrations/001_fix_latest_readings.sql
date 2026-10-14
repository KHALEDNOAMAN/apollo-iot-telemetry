-- Apollo, migration 001
--
-- Two problems measured against a real PostgreSQL 16.15 loaded with 500,000
-- rows generated from db/schema.sql.
--
-- 1. latest_readings took 506 ms. DISTINCT ON cannot skip ahead inside an
--    index, so it walked all 500,000 rows to return 49. The LATERAL form
--    does one index lookup per device.
--      measured: 506.0 ms -> 1.9 ms as a view, same 49 rows, same values.
--
-- 2. readings_device_ts_idx (15 MB) is redundant. readings_natural_key is
--    already (device_id, ts, protocol), so it serves
--    "WHERE device_id = ? ORDER BY ts DESC" with a backward index scan at
--    the same speed.
--      measured: 0.310 ms with it, 0.831 ms without, both sub millisecond.
--      LATERAL view: 0.931 ms with it, 0.785 ms without.
--    Dropping it frees 15 MB and removes one index write from every INSERT
--    on a table whose whole job is ingestion.

-- ---------------------------------------------------------------------------
-- 1. Rewrite the view as a loose index scan
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW latest_readings AS
SELECT r.device_id, r.ts, r.protocol,
       r.voltage_v, r.current_a, r.power_w, r.temperature_c
FROM devices d
CROSS JOIN LATERAL (
    SELECT device_id, ts, protocol, voltage_v, current_a, power_w, temperature_c
    FROM readings
    WHERE device_id = d.device_id
    ORDER BY ts DESC
    LIMIT 1
) r;

-- ---------------------------------------------------------------------------
-- 2. Drop the redundant index
-- ---------------------------------------------------------------------------
-- Confirm it is unused on YOUR workload first:
--   SELECT indexrelname, idx_scan, pg_size_pretty(pg_relation_size(indexrelid))
--   FROM pg_stat_user_indexes WHERE relname = 'readings';
--
-- CONCURRENTLY keeps the table unlocked. It cannot run inside a transaction,
-- so run this statement on its own.
DROP INDEX CONCURRENTLY IF EXISTS readings_device_ts_idx;
