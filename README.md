# SensorFlow MQTT — Industrial IoT Monitoring

![Python](https://img.shields.io/badge/python-3.11+-blue.svg)
![Flask](https://img.shields.io/badge/flask-3.0-lightgrey.svg)
![MQTT](https://img.shields.io/badge/protocol-MQTT-orange.svg)
![Docker](https://img.shields.io/badge/docker-ready-blue.svg)
![Tests](https://img.shields.io/badge/tests-7%20passed-brightgreen.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

**SensorFlow** is an open-source industrial IoT monitoring system built with Python, Flask, and MQTT. It simulates a network of industrial sensors, streams live data to a dark-themed SCADA dashboard, triggers intelligent alarms with hysteresis, and exports historical data to CSV.

> **Live demo:** [https://sensorflow.up.railway.app](https://sensorflow.up.railway.app) *(hosted on Railway)*

---

## Overview

```
Sensor Simulator ──MQTT──► Mosquitto Broker ──► Flask Server ──► SQLite
                                                      │
                                              REST API + WebSockets
                                                      │
                                              SCADA Dashboard (browser)
```

Six virtual sensors publish data every 2 seconds. The Flask server subscribes to all topics, evaluates alarm thresholds in real time, persists readings to a local database, and pushes updates to the browser via WebSocket — no polling required.

---

## Features

| Feature | Details |
|---|---|
| Real-time dashboard | Dark SCADA theme, sensor cards, trend charts per sensor type |
| MQTT simulation | 6 sensors (temperature, pressure, humidity) with Brownian motion and random spikes |
| Intelligent alarms | High/low thresholds with configurable hysteresis; auto-clear events when value normalises |
| Heartbeat monitoring | Sensors marked offline after 8 s without a heartbeat |
| Event log | Chronological feed of alarms, clears, and offline events with criticality levels |
| Time-based chart filtering | Switch between 15 min / 1 h / 6 h / 24 h on every trend chart |
| CSV export | Download readings for any sensor or all sensors at once |
| Swagger / OpenAPI | Interactive API docs at `/apidocs` |
| Docker Compose | Entire stack (Flask + Mosquitto) starts with one command |
| Unit tests | 7 tests covering endpoints, alarm logic, and hysteresis |

---

## Quick Start

**Requirements:** Docker and Docker Compose.

```bash
git clone https://github.com/Sarc120p/SensorFlowmqtt.git
cd SensorFlowmqtt
docker compose --profile full up --build
```

| Service | Address |
|---|---|
| Dashboard | http://localhost:5000 |
| API docs (Swagger) | http://localhost:5000/apidocs |
| MQTT broker | localhost:1883 |

To stop:

```bash
docker compose down
```

---

## Manual Installation

**Prerequisites:** Python 3.11+, Mosquitto MQTT broker.

```bash
# 1. Clone and create virtual environment
git clone https://github.com/Sarc120p/SensorFlowmqtt.git
cd SensorFlowmqtt
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. Start the MQTT broker (separate terminal)
mosquitto -v

# 3. Start the sensor simulator (separate terminal)
python sensor_simulator.py

# 4. Start the Flask server (separate terminal)
python app.py
```

Open http://localhost:5000.

Environment variables (optional):

| Variable | Default | Description |
|---|---|---|
| `MQTT_BROKER` | `localhost` | Hostname of the MQTT broker |
| `MQTT_PORT` | `1883` | Port of the MQTT broker |

---

## Sensor Configuration

Sensors are defined in `config/sensors.json`. Each entry controls the alarm thresholds, hysteresis, and criticality level.

```json
{
  "id": "temp-001",
  "type": "temperature",
  "unit": "C",
  "topic": "sensors/temperature/temp-001",
  "min": 20.0,
  "max": 35.0,
  "variation": 1.5,
  "hysteresis": 1.0,
  "criticality": "warning"
}
```

| Field | Description |
|---|---|
| `min` / `max` | Alarm thresholds — an event fires when the value crosses either limit |
| `variation` | Standard deviation for the Brownian motion value generator |
| `hysteresis` | Dead-band around the threshold — prevents rapid repeated alarms |
| `criticality` | `info`, `warning`, or `critical` — controls the event log colour |

---

## API Reference

Full interactive documentation is available at `/apidocs` when the server is running.

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/sensors` | Current state of all sensors (value, online status, last seen) |
| GET | `/api/history` | Historical readings — filter by `sensor_id`, paginate with `limit` |
| GET | `/api/events` | Recent alarm, clear, and offline events |
| GET | `/api/report/csv` | Download readings as a CSV file |

Example:

```bash
# Last 100 readings for temp-001
curl "http://localhost:5000/api/history?sensor_id=temp-001&limit=100"

# Export all sensor data as CSV
curl "http://localhost:5000/api/report/csv" --output report.csv
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11 |
| Web framework | Flask 3.0 |
| Real-time transport | Flask-SocketIO (threading mode) |
| MQTT client | paho-mqtt 2.0 |
| Message broker | Eclipse Mosquitto |
| Database ORM | SQLAlchemy + SQLite |
| Frontend charts | Chart.js 4.4 |
| API documentation | Flasgger / Swagger UI |
| Containerisation | Docker Compose |
| Testing | pytest + pytest-flask |

---

## Running Tests

```bash
pytest tests/ -v
```

The 7 tests cover:

- API endpoint availability and response shape (`/api/sensors`, `/api/history`, `/api/events`)
- CSV export endpoint and file format
- Alarm firing when a value crosses the configured threshold
- Hysteresis — no duplicate alarm events on sustained threshold breach
- Alarm clear event when value returns to the normal range

---

## Project Structure

```
sensorflow-mqtt/
├── app.py                  # Flask server, MQTT client, REST API
├── sensor_simulator.py     # Virtual sensor data generator
├── config/
│   └── sensors.json        # Sensor definitions and alarm thresholds
├── database/
│   └── history.db          # SQLite database (auto-created)
├── templates/
│   └── dashboard.html      # SCADA dashboard
├── static/
│   ├── css/main.css
│   └── js/dashboard.js
├── tests/
│   └── test_api.py
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

---

## Roadmap

- [x] Real-time SCADA dashboard
- [x] MQTT simulation with Brownian motion
- [x] Intelligent alarms with hysteresis and auto-clear
- [x] Heartbeat-based sensor offline detection
- [x] CSV export
- [x] Swagger / OpenAPI documentation
- [x] Docker Compose
- [x] Unit tests
- [ ] Telegram / Discord notifications for critical alarms
- [ ] Web UI for threshold configuration (no JSON editing)
- [ ] CI/CD pipeline with GitHub Actions
- [ ] PostgreSQL support via `DATABASE_URL` environment variable

---

## License

Distributed under the MIT License. See `LICENSE` for details.
