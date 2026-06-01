# SensorFlow MQTT – Industrial IoT Monitoring

![Python](https://img.shields.io/badge/python-3.9+-blue.svg)
![Flask](https://img.shields.io/badge/flask-3.0-lightgrey.svg)
![MQTT](https://img.shields.io/badge/protocol-MQTT-orange.svg)
![Docker](https://img.shields.io/badge/docker-ready-blue.svg)
![Tests](https://img.shields.io/badge/tests-7%20passed-brightgreen.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

**SensorFlow** is an open-source industrial IoT monitoring system built with **Python**, **Flask**, and **MQTT**.
It simulates a network of industrial sensors, displays real-time data on a dark-themed SCADA dashboard, triggers intelligent alarms with hysteresis, and exports historical data to CSV.

> **Live demo:** [https://sensorflow.up.railway.app](https://sensorflow.up.railway.app) *(powered by Railway)*
---

## Features

- **MQTT Sensor Simulation** – 6 virtual sensors (temperature, pressure, humidity) publish realistic data every 2 seconds.
- **Real-time SCADA Dashboard** – Dark industrial theme, gauges, trend charts (Chart.js), and live status indicators.
- **Intelligent Alarms** – High/low thresholds with configurable hysteresis; alarm clear events are recorded automatically.
- **Event Log** – Chronological record of alarms, clears, and sensor offline notifications.
- **Time-based Chart Filtering** – Switch between 15 min, 1 h, 6 h and 24 h views on every trend chart.
- **CSV Export** – Download historical sensor readings with one click.
- **Swagger/OpenAPI Docs** – Interactive API documentation at `/apidocs`.
- **Docker Compose** – Full stack (Flask + Mosquitto MQTT broker) ready in one command.
- **Unit Tests** – 7 tests covering API endpoints and alarm hysteresis logic.

---

## Quick Start (Docker)

```bash
git clone https://github.com/Sarc120p/Sensorflowmqtt.git
cd sensorflow-mqtt
docker compose --profile full up --build
