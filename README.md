# Apollo IoT Telemetry Pipeline

Collects real time telemetry from IoT energy devices over **MQTT** and
**Modbus TCP**, stores it in **PostgreSQL**, and makes it queryable.

Built for the Apollo Green Solutions IoT developer task.

```
                    push                        ┌────────────────┐
  ┌───────────────┐  MQTT   ┌────────────┐      │                │
  │ device        │────────▶│ Mosquitto  │─────▶│  mqtt_ingestor │──┐
  │ (mqtt_publish)│  QoS 1  │  broker    │ sub  │                │  │
  └───────────────┘         └────────────┘      └────────────────┘  │
                                                                     ▼
  ┌───────────────┐         ┌────────────┐      ┌────────────────┐ ┌──────────┐
  │ meter         │◀────────│ modbus     │─────▶│                │ │PostgreSQL│
  │ (modbus_dev)  │  poll   │ _poller    │write │   storage.py   │▶│ readings │
  └───────────────┘ FC 03   └────────────┘      └────────────────┘ └──────────┘
                    pull                                                 │
                                                                    src/query.py
```

Both transports produce the same `TelemetryReading` object, so the storage
layer never learns which wire a sample arrived on. That is the point of the
split: adding a third protocol later means writing one adapter, not touching
the database code.

---

## Quick start

```bash
git clone <this repo>
cd apollo-iot-telemetry
docker compose up --build
```

That starts six containers: PostgreSQL, a Mosquitto broker, a simulated MQTT
device, the MQTT ingestor, a simulated Modbus meter and the Modbus poller.
The schema is applied automatically on the first run.

Rows start landing within a few seconds. To look at them:

```bash
docker compose exec mqtt-ingestor python -m src.query latest
docker compose exec mqtt-ingestor python -m src.query stats
docker compose exec mqtt-ingestor python -m src.query energy meter-mqtt-01
```

It runs out of the box with a built in synthetic load profile. To use the real
dataset instead, follow [`data/README.md`](data/README.md) and set
`DATASET_PROFILE=household`.

### Running without Docker

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then export the variables, or use direnv

createdb apollo && psql apollo -f db/schema.sql

python -m src.mqtt_ingestor &   # terminal 1
python -m src.mqtt_publisher    # terminal 2
python -m src.modbus_device &   # terminal 3
python -m src.modbus_poller     # terminal 4
```

---

## Protocol choices

The task says "appropriate IoT communication protocols", plural. I implemented
two because they solve genuinely different problems, and an energy platform
ends up speaking both.

### MQTT, for devices that report on their own

**Used for:** the modern, network connected meter that pushes readings.

* **Publish and subscribe decouples the fleet from the backend.** The ingestor
  subscribes to `apollo/telemetry/#` once. Whether that is 1 device or 10,000,
  nothing in the backend changes and no device needs to know the backend's
  address.
* **It is cheap on the wire.** The fixed header is 2 bytes. Over a metered
  cellular link at a remote solar site, that difference against HTTP is a real
  line on the bill.
* **QoS 1 is the right trade here.** At most once (QoS 0) loses samples when
  the link flaps, which for billing data is unacceptable. Exactly once (QoS 2)
  costs a four step handshake per message. QoS 1 guarantees delivery and may
  duplicate, so I made ingestion idempotent instead and pay nothing per
  message. The duplicate count is logged on every flush, so the operational
  cost of that choice stays visible.
* **Last will and testament tells us when a device dies.** Each publisher sets
  a retained `offline` will on `.../status`. If a site loses power, the broker
  announces it. Without this, a dead device and an idle device look identical.
* **Retained status messages** mean a dashboard that connects later still
  learns the current state instead of waiting for the next event.

### Modbus TCP, for the equipment already on the wall

**Used for:** the existing panel meter, PLC or inverter that will never speak
MQTT.

* **You do not get a choice.** Modbus is from 1979 and it is still what most
  industrial energy meters expose. Any energy management product has to meet
  that hardware where it is.
* **It is strictly request and response.** The device never initiates, so the
  poll interval *is* the sample rate and a missed poll is a permanent hole.
  That is why `modbus_poller.py` owns its own timing, reconnect and backoff.
* **There are no floats and no units.** A holding register is 16 raw bits.
  Every value has to be encoded as a scaled integer and both ends must agree
  on the scale, which is why the map lives in one shared file,
  [`src/registers.py`](src/registers.py), imported by both the meter and the
  poller. Mismatched scaling is the most common Modbus integration bug and it
  fails silently, with plausible looking wrong numbers.

#### Register map

| Register | Value        | Type   | Encoding              | Range              |
|----------|--------------|--------|-----------------------|--------------------|
| HR 0     | voltage      | uint16 | volts × 10            | 0 to 6553.5 V      |
| HR 1     | current      | uint16 | amps × 100            | 0 to 655.35 A      |
| HR 2..3  | active power | uint32 | watts × 10, high word first | 0 to 429 MW  |
| HR 4     | temperature  | int16  | celsius × 10, two's complement | -3276.8 to 3276.7 °C |
| HR 5..6  | timestamp    | uint32 | unix seconds UTC, high word first | |

Three decisions worth naming:

1. **Power needs 32 bits.** At ×10 scaling a single register tops out at
   6.5 kW, which a single household exceeds. Splitting across two registers
   costs nothing and avoids a wrap that would read as a small number.
2. **Temperature is signed.** An outdoor sensor in Anatolia in January reads
   below zero. An unsigned register would report roughly 6535 °C.
3. **Out of range values are clamped, not wrapped.** A clamped maximum is an
   obviously broken reading. A wrapped one is a plausible lie.

### What I did not use, and why

* **HTTP/REST.** Fine for configuration and for the dashboard API, wasteful
  for a device posting every second, and it makes the device poll for anything
  coming back.
* **CoAP.** A good fit for constrained battery devices over UDP, but these
  meters are mains powered on a stable link, so MQTT's broker and its QoS and
  retained messages are worth more than CoAP's smaller footprint.
* **Kafka.** The right answer at a much larger scale. At this size it is a
  cluster to operate for no gain.

---

## Database schema

Full DDL: [`db/schema.sql`](db/schema.sql).

```
devices                      readings
────────────────────         ──────────────────────────────────────
device_id   TEXT PK   ──┐    id             BIGSERIAL PK
name        TEXT        └───▶ device_id     TEXT FK
site        TEXT             ts             TIMESTAMPTZ
created_at  TIMESTAMPTZ      protocol       TEXT  (mqtt | modbus)
                             voltage_v      DOUBLE PRECISION NULL
                             current_a      DOUBLE PRECISION NULL
                             power_w        DOUBLE PRECISION NULL
                             temperature_c  DOUBLE PRECISION NULL
                             ingested_at    TIMESTAMPTZ
                             UNIQUE (device_id, ts, protocol)
```

**Why it looks like this**

* **Two tables, not one.** Device metadata changes; history does not. Renaming
  a meter should not rewrite a million rows.
* **`ts` is `TIMESTAMPTZ`.** Devices report UTC and operators read local time.
  Storing a naive timestamp loses that distinction the first time a site
  crosses a DST boundary, and Türkiye's own clock history makes that a real
  risk rather than a theoretical one. `ingested_at` is kept separately so that
  a device with a wrong clock can be detected instead of silently corrupting
  the series.
* **Measurement columns are nullable.** Not every device has every sensor.
  NULL means "not measured", 0 means "measured as zero", and collapsing the
  two would quietly ruin every average.
* **`UNIQUE (device_id, ts, protocol)` plus `ON CONFLICT DO NOTHING`.** This is
  what makes QoS 1 safe. Redelivery is absorbed by the database rather than
  being pushed back onto the broker.
* **`protocol` is part of the key, not just a column.** The same physical meter
  read over both transports produces two comparable rows, which is exactly what
  you want when reconciling a gateway against the device behind it.
* **`(device_id, ts DESC)` index.** Every dashboard query is "the last N
  minutes for this device", so the index is stored in the order the query
  reads it. A second index on `ts DESC` supports fleet wide range scans.
* **`latest_readings` view** uses `DISTINCT ON`, the Postgres specific way to
  get the newest row per device without a window function or a self join.

**Next step at volume:** partition `readings` by month, or move to TimescaleDB
hypertables. At a few million rows plain Postgres with these indexes is
comfortable, so adding that now would be complexity without a reason.

---

## Ingestion behaviour

* **Batched writes.** Readings are buffered and flushed on whichever comes
  first, 50 rows or 2 seconds. One round trip instead of fifty, while a quiet
  device still lands within two seconds.
* **Failures are isolated.** A malformed payload is logged and dropped; it does
  not kill the subscriber loop. A database error rolls back that batch only.
* **Reconnection is expected, not exceptional.** The Modbus poller reconnects
  and backs off on its own, because a field link drops regularly.
* **Useful logs.** Every flush prints rows written and duplicates ignored, so
  the effect of the QoS choice is measurable in production rather than assumed.

---

## Tests

```bash
pip install pytest
python -m pytest tests -q
```

13 tests, focused on the parts that fail silently rather than loudly: register
scaling round trips, negative temperatures, 32 bit power, clamping, timezone
aware timestamps, and `?` in the dataset becoming NULL rather than zero.

Verified end to end against a real PostgreSQL 16 instance and a real Mosquitto
broker: 1,131 MQTT messages and 28 Modbus polls stored, 0 duplicates, and
re-sending 50 known rows wrote 0 new rows.

---

## Project layout

```
src/models.py          shared TelemetryReading, the contract between layers
src/dataset.py         dataset to readings, three profiles, synthetic fallback
src/registers.py       Modbus register map and scaling, shared by both sides
src/mqtt_publisher.py  simulated device, publishes at QoS 1 with a last will
src/mqtt_ingestor.py   subscriber, batches and writes
src/modbus_device.py   simulated meter, serves holding registers
src/modbus_poller.py   master, polls and writes
src/storage.py         PostgreSQL access, idempotent batch insert
src/query.py           CLI for latest, stats and hourly energy
db/schema.sql          DDL with the reasoning in comments
```

---

## Known limitations

Worth stating plainly rather than leaving to be discovered:

* **No authentication anywhere.** The broker allows anonymous connections and
  the database uses a demo password. Production needs per device credentials
  and TLS on 8883, plus secrets from the environment rather than compose.
* **Modbus has no authentication by design**, so in the field it belongs on an
  isolated VLAN behind a gateway, never exposed directly.
* **One device per simulator process.** Enough to prove the pipeline. A fleet
  test would need either many publishers or a device loop inside one process.
* **No backfill.** If the ingestor is down, messages published at QoS 1 to a
  broker without a persistent session for that client are lost. A durable
  subscription or a store and forward buffer at the edge would fix it.
* **`pymodbus` is pinned to 3.6.9.** The 3.15 datastore API is a substantial
  rewrite around the simulator; 3.6.9 is the stable, widely documented API and
  pinning it keeps the project reproducible.
