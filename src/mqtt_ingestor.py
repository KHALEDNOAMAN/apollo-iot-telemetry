"""MQTT subscriber: take everything published under the telemetry prefix and
write it to PostgreSQL in batches.

Two details that matter more than they look:

* Subscribing at QoS 1 means the broker may deliver the same message twice.
  That is the protocol working as designed, not a fault. Deduplication belongs
  here, and it is handled by the UNIQUE constraint in the schema.
* Inserting one row per message would make the database do a round trip per
  sample. Buffering and writing with execute_values turns thousands of round
  trips into one.

Run:  python -m src.mqtt_ingestor
"""

from __future__ import annotations

import logging
import threading
import time

import paho.mqtt.client as mqtt

from .config import settings
from .models import TelemetryReading
from .storage import TelemetryStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s [ingestor] %(message)s")
log = logging.getLogger(__name__)


class Ingestor:
    def __init__(self, store: TelemetryStore) -> None:
        self._store = store
        self._buffer: list[TelemetryReading] = []
        self._lock = threading.Lock()
        self._received = 0
        self._written = 0
        self._last_flush = time.monotonic()

    # -- mqtt callbacks -------------------------------------------------
    def on_connect(self, client: mqtt.Client, _ud, _flags, reason_code, _props=None):
        topic = f"{settings.mqtt_topic_prefix}/#"
        client.subscribe(topic, qos=settings.mqtt_qos)
        log.info("connected (%s), subscribed to %s", reason_code, topic)

    def on_message(self, _client, _ud, message: mqtt.MQTTMessage) -> None:
        if message.topic.endswith("/status"):
            log.info("device status %s: %s", message.topic, message.payload.decode())
            return
        try:
            reading = TelemetryReading.from_json(message.payload)
        except Exception as exc:  # malformed payloads must not kill the loop
            log.warning("dropping bad payload on %s: %s", message.topic, exc)
            return
        with self._lock:
            self._buffer.append(reading)
            self._received += 1

    # -- flushing -------------------------------------------------------
    def flush_if_due(self, force: bool = False) -> None:
        with self._lock:
            due = (
                force
                or len(self._buffer) >= settings.batch_size
                or time.monotonic() - self._last_flush >= settings.batch_seconds
            )
            if not self._buffer or not due:
                return
            batch, self._buffer = self._buffer, []
            self._last_flush = time.monotonic()
        written = self._store.insert_batch(batch)
        self._written += written
        duplicates = len(batch) - written
        log.info(
            "flushed %s rows (%s duplicates ignored), total stored %s",
            written,
            duplicates,
            self._written,
        )


def main() -> None:
    store = TelemetryStore(settings.dsn)
    store.apply_schema()
    store.ensure_device("meter-mqtt-01", "Simulated MQTT meter", "Cologne lab")

    ingestor = Ingestor(store)
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="apollo-ingestor")
    client.on_connect = ingestor.on_connect
    client.on_message = ingestor.on_message
    client.connect(settings.mqtt_host, settings.mqtt_port, keepalive=30)
    client.loop_start()

    try:
        while True:
            time.sleep(0.5)
            ingestor.flush_if_due()
    except KeyboardInterrupt:
        ingestor.flush_if_due(force=True)
        log.info("stopped, %s rows in the database", store.count())
    finally:
        client.loop_stop()
        client.disconnect()
        store.close()


if __name__ == "__main__":
    main()
