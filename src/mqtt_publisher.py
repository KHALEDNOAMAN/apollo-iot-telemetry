"""Simulated MQTT device: replay the dataset as if a meter were transmitting.

MQTT is the opposite of Modbus here. The device decides when to speak, the
broker fans the message out, and the ingestor never has to know how many
devices exist or where they are.

Run:  python -m src.mqtt_publisher
"""

from __future__ import annotations

import logging
import time

import paho.mqtt.client as mqtt

from .config import settings
from .dataset import read_dataset

logging.basicConfig(level=logging.INFO, format="%(asctime)s [device] %(message)s")
log = logging.getLogger(__name__)

DEVICE_ID = "meter-mqtt-01"


def build_client(client_id: str) -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    # Last will: if this device disappears without saying goodbye, the broker
    # tells everyone else. That is how a fleet dashboard knows a site is down
    # instead of just showing stale numbers.
    client.will_set(
        f"{settings.mqtt_topic_prefix}/{DEVICE_ID}/status",
        payload="offline",
        qos=1,
        retain=True,
    )
    return client


def main() -> None:
    topic = f"{settings.mqtt_topic_prefix}/{DEVICE_ID}"
    client = build_client(f"pub-{DEVICE_ID}")
    client.connect(settings.mqtt_host, settings.mqtt_port, keepalive=30)
    client.loop_start()
    client.publish(f"{topic}/status", "online", qos=1, retain=True)
    log.info("publishing to %s at qos %s", topic, settings.mqtt_qos)

    sent = 0
    try:
        for reading in read_dataset(
            settings.dataset_path, settings.dataset_profile, DEVICE_ID
        ):
            client.publish(topic, reading.to_json(), qos=settings.mqtt_qos)
            sent += 1
            if sent % 100 == 0:
                log.info("published %s messages", sent)
            time.sleep(settings.sample_interval_seconds)
    except KeyboardInterrupt:
        pass
    finally:
        client.publish(f"{topic}/status", "offline", qos=1, retain=True)
        client.loop_stop()
        client.disconnect()
        log.info("stopped after %s messages", sent)


if __name__ == "__main__":
    main()
