"""
SensorFlow MQTT – Central Server
Subscribes to MQTT sensor data, stores history in SQLite,
provides a REST API, and pushes real-time updates via WebSockets.
"""
import os
import json
import time
import uuid
import threading
import csv
import io
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template, request, Response
from flask_socketio import SocketIO
from flask_sqlalchemy import SQLAlchemy
from flasgger import Swagger
import paho.mqtt.client as mqtt

app = Flask(__name__)

# Use native threading – no eventlet, no gevent, no monkey-patching required.
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------
BASEDIR = Path(__file__).parent
CONFIG_PATH = BASEDIR / "config" / "sensors.json"
DB_PATH = BASEDIR / "database" / "history.db"

DB_PATH.parent.mkdir(parents=True, exist_ok=True)
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# MQTT broker address – overridable via environment variable
BROKER = os.environ.get("MQTT_BROKER", "broker.hivemq.com")
PORT = int(os.environ.get("MQTT_PORT", 1883))

# ------------------------------------------------------------
# Swagger / OpenAPI configuration
# ------------------------------------------------------------
swagger_config = {
    "headers": [],
    "specs": [
        {
            "endpoint": 'apispec',
            "route": '/apispec.json',
            "rule_filter": lambda rule: True,
            "model_filter": lambda tag: True,
        }
    ],
    "static_url_path": "/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/apidocs/"
}

swagger_template = {
    "swagger": "2.0",
    "info": {
        "title": "SensorFlow MQTT API",
        "description": "Industrial IoT sensor monitoring system with real-time alerts, "
                       "historical data, and CSV export.",
        "version": "1.0.0",
        "contact": {
            "name": "SensorFlow",
            "url": "https://github.com/your-username/sensorflow-mqtt"
        }
    },
    "host": "localhost:5000",
    "basePath": "/",
    "schemes": ["http"]
}

swagger = Swagger(app, config=swagger_config, template=swagger_template)

# ------------------------------------------------------------
# Database Models
# ------------------------------------------------------------
class Reading(db.Model):
    """Stores a single sensor reading."""
    __tablename__ = "readings"
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    sensor_id = db.Column(db.String(50), nullable=False)
    sensor_type = db.Column(db.String(50))
    value = db.Column(db.Float)
    unit = db.Column(db.String(20))


class Event(db.Model):
    """Stores an alert or system event."""
    __tablename__ = "events"
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    sensor_id = db.Column(db.String(50))
    event_type = db.Column(db.String(50))
    message = db.Column(db.String(200))


# ------------------------------------------------------------
# In-Memory Sensor State
# ------------------------------------------------------------
sensor_state = {}          # sensor_id -> last known value dict
sensor_last_seen = {}      # sensor_id -> timestamp of last data
heartbeat_last = {}        # sensor_id -> timestamp of last heartbeat
alarm_state = {}           # sensor_id -> {"high": bool, "low": bool}

_db_lock = threading.Lock()  # Protects concurrent SQLite writes


def load_config():
    """Load sensor definitions from the JSON configuration file."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ------------------------------------------------------------
# MQTT Callbacks
# ------------------------------------------------------------
def on_connect(client, userdata, flags, reason_code, properties):
    """Called when the MQTT client connects. Subscribes to sensor topics."""
    if reason_code == 0:
        print("[MQTT] Connected to broker")
        config = load_config()
        for s in config["sensors"]:
            client.subscribe(s["topic"], qos=1)
            client.subscribe(s.get("heartbeat", f"heartbeat/{s['id']}"), qos=1)
            print(f"[MQTT] Subscribed -> {s['topic']}")
    else:
        print(f"[MQTT] Connection failed with reason code: {reason_code}")


def on_message(client, userdata, msg):
    """Processes incoming MQTT messages (data or heartbeat)."""
    try:
        payload = json.loads(msg.payload.decode())
    except json.JSONDecodeError:
        return

    sensor_id = payload.get("sensor_id")
    now = datetime.now(timezone.utc)

    # Heartbeat message – update timestamp only
    if "heartbeat" in msg.topic:
        heartbeat_last[sensor_id] = now
        socketio.emit("sensor_heartbeat", {
            "sensor_id": sensor_id,
            "timestamp": now.isoformat(),
        })
        return

    # Data message – store state and broadcast via WebSocket
    sensor_last_seen[sensor_id] = now
    sensor_state[sensor_id] = payload
    socketio.emit("sensor_update", {
        "sensor_id": sensor_id,
        "type": payload.get("type"),
        "value": payload.get("value"),
        "unit": payload.get("unit"),
        "timestamp": now.isoformat(),
    })

    # Persist to database and evaluate alarms
    with _db_lock:
        with app.app_context():
            reading = Reading(
                sensor_id=sensor_id,
                sensor_type=payload.get("type"),
                value=payload.get("value"),
                unit=payload.get("unit"),
            )
            db.session.add(reading)
            db.session.commit()

            # Check thresholds with hysteresis
            config = load_config()
            for s in config["sensors"]:
                if s["id"] != sensor_id:
                    continue

                hysteresis = s.get("hysteresis", 1.0)
                criticality = s.get("criticality", "warning")
                value = payload.get("value", 0)

                if sensor_id not in alarm_state:
                    alarm_state[sensor_id] = {"high": False, "low": False}

                # ---- High-value alarm (with hysteresis) ----
                if value > s.get("max", 999):
                    if not alarm_state[sensor_id]["high"]:
                        alarm_state[sensor_id]["high"] = True
                        event = Event(
                            sensor_id=sensor_id,
                            event_type="high_value",
                            message=f"{sensor_id} exceeded max threshold ({value} > {s['max']})",
                        )
                        db.session.add(event)
                        db.session.commit()
                        socketio.emit("new_event", {
                            "sensor_id": sensor_id,
                            "type": "high_value",
                            "criticality": criticality,
                            "message": event.message,
                            "timestamp": now.isoformat(),
                        })
                elif value < s.get("max", 999) - hysteresis:
                    if alarm_state[sensor_id]["high"]:
                        alarm_state[sensor_id]["high"] = False
                        event = Event(
                            sensor_id=sensor_id,
                            event_type="high_value_clear",
                            message=f"{sensor_id} returned to normal (value: {value})",
                        )
                        db.session.add(event)
                        db.session.commit()
                        socketio.emit("new_event", {
                            "sensor_id": sensor_id,
                            "type": "high_value_clear",
                            "criticality": "info",
                            "message": event.message,
                            "timestamp": now.isoformat(),
                        })

                # ---- Low-value alarm (with hysteresis) ----
                if value < s.get("min", -999):
                    if not alarm_state[sensor_id]["low"]:
                        alarm_state[sensor_id]["low"] = True
                        event = Event(
                            sensor_id=sensor_id,
                            event_type="low_value",
                            message=f"{sensor_id} below min threshold ({value} < {s['min']})",
                        )
                        db.session.add(event)
                        db.session.commit()
                        socketio.emit("new_event", {
                            "sensor_id": sensor_id,
                            "type": "low_value",
                            "criticality": criticality,
                            "message": event.message,
                            "timestamp": now.isoformat(),
                        })
                elif value > s.get("min", -999) + hysteresis:
                    if alarm_state[sensor_id]["low"]:
                        alarm_state[sensor_id]["low"] = False
                        event = Event(
                            sensor_id=sensor_id,
                            event_type="low_value_clear",
                            message=f"{sensor_id} returned to normal (value: {value})",
                        )
                        db.session.add(event)
                        db.session.commit()
                        socketio.emit("new_event", {
                            "sensor_id": sensor_id,
                            "type": "low_value_clear",
                            "criticality": "info",
                            "message": event.message,
                            "timestamp": now.isoformat(),
                        })

                break  # Sensor found, stop searching


def on_disconnect(client, userdata, flags, reason_code, properties):
    """Called when the MQTT client disconnects."""
    print(f"[MQTT] Disconnected (reason code: {reason_code})")


# ------------------------------------------------------------
# MQTT Thread
# ------------------------------------------------------------
def start_mqtt():
    """
    MQTT client thread.
    Uses a fresh client ID on every connection attempt to avoid
    broker-side session conflicts.  Supervision loop restarts
    automatically after any disconnection.
    """
    print("[MQTT] Thread started.")

    while True:
        client = None
        connected = False

        try:
            client_id = f"sensorflow-{uuid.uuid4().hex[:8]}"
            client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2,
                client_id=client_id,
            )
            client.on_connect = on_connect
            client.on_message = on_message
            client.on_disconnect = on_disconnect

            print(f"[MQTT] Connecting to {BROKER}:{PORT} (id={client_id})...")
            client.connect(BROKER, PORT, keepalive=60)
            client.loop_start()
            print("[MQTT] loop_start() OK – waiting for CONNACK...")

            # Wait up to 10 seconds for the CONNACK
            deadline = time.time() + 10
            while time.time() < deadline:
                if client.is_connected():
                    connected = True
                    break
                time.sleep(0.5)

            if not connected:
                raise OSError("Timeout – CONNACK not received within 10 seconds")

            print("[MQTT] Connected – entering supervision loop")

            # Supervision: stay here while the connection is alive
            while client.is_connected():
                time.sleep(2)

            print("[MQTT] Connection lost. Reconnecting...")

        except ConnectionRefusedError:
            print(f"[MQTT] Connection refused ({BROKER}:{PORT}). Retrying in 5s...")
        except OSError as e:
            print(f"[MQTT] OS error: {e}. Retrying in 5s...")
        except Exception as e:
            print(f"[MQTT] Unexpected error: {type(e).__name__} - {e}. Retrying in 5s...")
        finally:
            if client:
                try:
                    client.loop_stop()
                    client.disconnect()
                except Exception:
                    pass

        time.sleep(5)


# ------------------------------------------------------------
# REST API
# ------------------------------------------------------------
@app.route("/")
def dashboard():
    """Main monitoring dashboard.
    ---
    responses:
      200:
        description: HTML page of the SCADA dashboard
    """
    return render_template("dashboard.html")


@app.route("/api/sensors")
def api_sensors():
    """Current state of all sensors.
    ---
    responses:
      200:
        description: List of sensor objects with current value,
                     online status, and last-seen timestamp.
        schema:
          type: array
          items:
            type: object
            properties:
              sensor_id:
                type: string
                example: "temp-001"
              type:
                type: string
                example: "temperature"
              unit:
                type: string
                example: "C"
              value:
                type: number
                example: 25.5
              online:
                type: boolean
                example: true
              last_seen:
                type: string
                format: date-time
                example: "2026-05-30T12:00:00+00:00"
    """
    now = datetime.now(timezone.utc)
    config = load_config()
    result = []
    for s in config["sensors"]:
        sid = s["id"]
        last_data = sensor_state.get(sid)
        online = (
            sid in heartbeat_last
            and (now - heartbeat_last[sid]).seconds < 15
        )
        result.append({
            "sensor_id": sid,
            "type": s["type"],
            "unit": s["unit"],
            "value": last_data["value"] if last_data else None,
            "online": online,
            "last_seen": sensor_last_seen[sid].isoformat() if sid in sensor_last_seen else None,
        })
    return jsonify(result)


@app.route("/api/history")
def api_history():
    """Historical sensor readings.
    ---
    parameters:
      - name: sensor_id
        in: query
        type: string
        required: false
        description: Filter by sensor identifier (e.g., temp-001)
      - name: limit
        in: query
        type: integer
        required: false
        default: 50
        description: Maximum number of records to return
    responses:
      200:
        description: Array of readings ordered by timestamp (oldest first)
        schema:
          type: array
          items:
            type: object
            properties:
              timestamp:
                type: string
                format: date-time
              sensor_id:
                type: string
              type:
                type: string
              value:
                type: number
              unit:
                type: string
    """
    sensor_id = request.args.get("sensor_id")
    limit = request.args.get("limit", 50, type=int)
    query = Reading.query.order_by(Reading.timestamp.desc())
    if sensor_id:
        query = query.filter_by(sensor_id=sensor_id)
    readings = query.limit(limit).all()
    return jsonify([{
        "timestamp": r.timestamp.isoformat(),
        "sensor_id": r.sensor_id,
        "type": r.sensor_type,
        "value": r.value,
        "unit": r.unit,
    } for r in readings[::-1]])


@app.route("/api/events")
def api_events():
    """Recent system events (alarms, clears, offline notifications).
    ---
    parameters:
      - name: limit
        in: query
        type: integer
        required: false
        default: 50
        description: Maximum number of events to return
    responses:
      200:
        description: Array of event objects ordered by timestamp (oldest first)
        schema:
          type: array
          items:
            type: object
            properties:
              timestamp:
                type: string
                format: date-time
              sensor_id:
                type: string
              type:
                type: string
                enum: [high_value, low_value, high_value_clear,
                       low_value_clear, sensor_offline]
              message:
                type: string
    """
    limit = request.args.get("limit", 50, type=int)
    events = Event.query.order_by(Event.timestamp.desc()).limit(limit).all()
    return jsonify([{
        "timestamp": e.timestamp.isoformat(),
        "sensor_id": e.sensor_id,
        "type": e.event_type,
        "message": e.message,
    } for e in events[::-1]])


@app.route("/api/report/csv")
def api_report_csv():
    """Export historical readings as a downloadable CSV file.
    ---
    parameters:
      - name: sensor_id
        in: query
        type: string
        required: false
        description: Filter by sensor identifier. Omit for all sensors.
      - name: limit
        in: query
        type: integer
        required: false
        default: 1000
        description: Maximum number of rows to include
    responses:
      200:
        description: CSV file download
        headers:
          Content-Disposition:
            type: string
            description: attachment; filename with sensor id and timestamp
        content:
          text/csv:
            schema:
              type: string
              format: binary
    """
    sensor_id = request.args.get("sensor_id")
    limit = request.args.get("limit", 1000, type=int)

    query = Reading.query.order_by(Reading.timestamp.asc())
    if sensor_id:
        query = query.filter_by(sensor_id=sensor_id)
    readings = query.limit(limit).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["timestamp", "sensor_id", "type", "value", "unit"])
    for r in readings:
        writer.writerow([
            r.timestamp.isoformat(),
            r.sensor_id,
            r.sensor_type,
            r.value,
            r.unit
        ])

    output.seek(0)
    filename = (
        f"report_{sensor_id or 'all'}_"
        f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    )
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename={filename}"}
    )


# ------------------------------------------------------------
# Health check thread
# ------------------------------------------------------------
def check_sensor_health():
    """
    Periodically inspects heartbeats and emits offline events
    when a sensor has been silent for more than 8 seconds.
    """
    with app.app_context():
        while True:
            now = datetime.now(timezone.utc)
            config = load_config()
            for sensor_id, last_hb in list(heartbeat_last.items()):
                if (now - last_hb).seconds > 8:
                    criticality = "critical"
                    for s in config["sensors"]:
                        if s["id"] == sensor_id:
                            criticality = s.get("criticality", "critical")
                            break
                    with _db_lock:
                        event = Event(
                            sensor_id=sensor_id,
                            event_type="sensor_offline",
                            message=f"{sensor_id} connection lost",
                        )
                        db.session.add(event)
                        db.session.commit()
                    socketio.emit("new_event", {
                        "sensor_id": sensor_id,
                        "type": "sensor_offline",
                        "criticality": criticality,
                        "message": event.message,
                        "timestamp": now.isoformat(),
                    })
            time.sleep(3)


# ------------------------------------------------------------
# Startup
# ------------------------------------------------------------
if __name__ == "__main__":
    with app.app_context():
        db.create_all()

    # Launch MQTT client in a background daemon thread
    threading.Thread(target=start_mqtt, daemon=True).start()
    print("[DEBUG] MQTT thread started")

    # Launch health-check thread
    threading.Thread(target=check_sensor_health, daemon=True).start()
    print("[DEBUG] Health-check thread started")

    print("[SensorFlow] Server starting at http://localhost:5000")
    socketio.run(app, debug=False, allow_unsafe_werkzeug=True,
                 host="0.0.0.0", port=5000)