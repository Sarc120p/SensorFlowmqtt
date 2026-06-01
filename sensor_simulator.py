"""
SensorFlow MQTT – Sensor Simulator
Simulates multiple industrial sensors and publishes data via MQTT.
Each sensor has its own topic, realistic random variation, and heartbeat.
Alarm limits (min/max) are used only for alarm evaluation in the server;
the simulator uses realistic operational ranges for each sensor type.
"""
import os
import json
import random
import time
import threading
from pathlib import Path
import paho.mqtt.client as mqtt


# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------
CONFIG_PATH = Path(__file__).parent / "config" / "sensors.json"
BROKER = os.environ.get("MQTT_BROKER", "localhost")
PORT = int(os.environ.get("MQTT_PORT", 1883))
HEARTBEAT_INTERVAL = 5  # seconds between heartbeat messages


def load_config():
    """Load sensor definitions from JSON configuration file."""
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Configuration file not found: {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


class Sensor:
    """Represents a single simulated sensor."""

    # Realistic operational ranges – independent of alarm limits
    OPERATIONAL_RANGES = {
        "temperature": (15.0, 40.0),
        "pressure": (96.0, 110.0),
        "humidity": (35.0, 80.0),
    }

    def __init__(self, sensor_id, sensor_type, unit, topic, min_val, max_val, variation, heartbeat_topic):
        self.sensor_id = sensor_id
        self.sensor_type = sensor_type
        self.unit = unit
        self.topic = topic
        self.min_val = min_val        # alarm lower limit (not used for generation)
        self.max_val = max_val        # alarm upper limit (not used for generation)
        self.variation = variation
        self.heartbeat_topic = heartbeat_topic
        self.value = random.uniform(*self.OPERATIONAL_RANGES.get(sensor_type, (min_val, max_val)))

    def generate_value(self):
        """Generate next realistic value within the operational range."""
        op_min, op_max = self.OPERATIONAL_RANGES.get(
            self.sensor_type, (self.min_val, self.max_val)
        )

        # Brownian motion: base variation + occasional spike
        delta = random.gauss(0, self.variation)
        # 5% chance of a larger spike (simulates a real event)
        if random.random() < 0.05:
            delta *= random.uniform(2, 5) * random.choice([-1, 1])

        self.value = max(op_min, min(op_max, self.value + delta))
        return round(self.value, 2)


class SensorSimulator:
    """Manages multiple sensors and publishes their data via MQTT."""

    def __init__(self, broker, port):
        self.sensors = []
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.broker = broker
        self.port = port

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            print(f"[OK] Connected to MQTT broker at {self.broker}:{self.port}")
        else:
            print(f"[ERROR] Connection failed with code {reason_code}")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        print("[WARNING] Disconnected from MQTT broker. Retrying...")

    def connect(self):
        """Connect to MQTT broker with retry logic."""
        while True:
            try:
                self.client.connect(self.broker, self.port, keepalive=60)
                self.client.loop_start()
                return
            except ConnectionRefusedError:
                print(f"[RETRY] Broker not available at {self.broker}:{self.port}. Retrying in 5s...")
                time.sleep(5)

    def load_from_config(self, config):
        """Create Sensor instances from configuration dictionary."""
        for sensor_cfg in config.get("sensors", []):
            sensor = Sensor(
                sensor_id=sensor_cfg["id"],
                sensor_type=sensor_cfg["type"],
                unit=sensor_cfg["unit"],
                topic=sensor_cfg["topic"],
                min_val=sensor_cfg["min"],
                max_val=sensor_cfg["max"],
                variation=sensor_cfg["variation"],
                heartbeat_topic=sensor_cfg.get("heartbeat", f"heartbeat/{sensor_cfg['id']}"),
            )
            self.sensors.append(sensor)
            print(f"  [LOADED] {sensor.sensor_id} ({sensor.sensor_type}) -> {sensor.topic}")

    def publish_data(self):
        """Publish current data for all sensors."""
        for sensor in self.sensors:
            value = sensor.generate_value()
            payload = json.dumps({
                "sensor_id": sensor.sensor_id,
                "type": sensor.sensor_type,
                "value": value,
                "unit": sensor.unit,
                "timestamp": time.time(),
            })
            self.client.publish(sensor.topic, payload, qos=1)

    def publish_heartbeats(self):
        """Publish heartbeat for all sensors."""
        while True:
            for sensor in self.sensors:
                payload = json.dumps({
                    "sensor_id": sensor.sensor_id,
                    "status": "online",
                    "timestamp": time.time(),
                })
                self.client.publish(sensor.heartbeat_topic, payload, qos=1)
            time.sleep(HEARTBEAT_INTERVAL)

    def run(self, interval=2):
        """Main loop: publish data continuously."""
        # Start heartbeat thread
        heartbeat_thread = threading.Thread(target=self.publish_heartbeats, daemon=True)
        heartbeat_thread.start()

        print(f"\n[RUNNING] Publishing {len(self.sensors)} sensors every {interval}s. Ctrl+C to stop.\n")
        try:
            while True:
                self.publish_data()
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\n[OK] Simulator stopped.")
            self.client.loop_stop()
            self.client.disconnect()


# ------------------------------------------------------------
# Entry point
# ------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 60)
    print("SensorFlow MQTT – Industrial Sensor Simulator")
    print("=" * 60)

    # Load configuration
    config = load_config()
    print(f"\n[CONFIG] Loaded from {CONFIG_PATH}")

    # Create and configure simulator
    sim = SensorSimulator(BROKER, PORT)
    sim.load_from_config(config)

    # Read publish interval from config (default 2s)
    publish_interval = config.get("publish_interval", 2)

    # Connect to broker and start
    print(f"\n[CONNECT] Connecting to MQTT broker at {BROKER}:{PORT}...")
    sim.connect()
    sim.run(publish_interval)
