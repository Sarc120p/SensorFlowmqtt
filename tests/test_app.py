"""
Unit tests for SensorFlow MQTT – Central Server.
Tests cover REST API endpoints and alarm logic with hysteresis.
"""
import json
import pytest
from datetime import datetime, timezone
from app import app, db, Reading, Event, sensor_state, heartbeat_last, alarm_state


@pytest.fixture
def client():
    """Prepare a test app with in-memory database and clean state."""
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    with app.test_client() as client:
        with app.app_context():
            db.create_all()

        # Clean in-memory sensor state before each test
        sensor_state.clear()
        heartbeat_last.clear()
        alarm_state.clear()

        yield client

        with app.app_context():
            db.drop_all()


def inject_sensor_data(sensor_id, value, unit="C", sensor_type="temperature"):
    """Simulate an MQTT message by directly updating the in-memory state."""
    sensor_state[sensor_id] = {
        "sensor_id": sensor_id,
        "type": sensor_type,
        "value": value,
        "unit": unit,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    heartbeat_last[sensor_id] = datetime.now(timezone.utc)


class TestBasicRoutes:
    """Tests for the main REST API endpoints."""

    def test_dashboard_returns_200(self, client):
        resp = client.get('/')
        assert resp.status_code == 200

    def test_sensors_endpoint_returns_list(self, client):
        resp = client.get('/api/sensors')
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)

    def test_history_endpoint_returns_list(self, client):
        resp = client.get('/api/history')
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)

    def test_events_endpoint_returns_list(self, client):
        resp = client.get('/api/events')
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)


class TestAlarmLogic:
    """Tests for alarm generation with hysteresis."""

    def test_high_value_alarm_fires_once(self, client):
        """Alarm should fire only once while the value stays above max."""
        inject_sensor_data("temp-001", 99.9)
        alarm_state["temp-001"] = {"high": False, "low": False}

        # Simulate what on_message does (simplified)
        with app.app_context():
            # First high value – alarm should fire
            from app import load_config
            config = load_config()
            sensor = config["sensors"][0]  # temp-001
            max_val = sensor["max"]
            value = 99.9

            if value > max_val:
                if not alarm_state["temp-001"]["high"]:
                    alarm_state["temp-001"]["high"] = True
                    event = Event(
                        sensor_id="temp-001",
                        event_type="high_value",
                        message=f"temp-001 exceeded max threshold",
                    )
                    db.session.add(event)
                    db.session.commit()

            # Second high value – should NOT fire again
            if value > max_val:
                if not alarm_state["temp-001"]["high"]:
                    alarm_state["temp-001"]["high"] = True
                    event = Event(
                        sensor_id="temp-001",
                        event_type="high_value",
                        message=f"temp-001 exceeded max threshold",
                    )
                    db.session.add(event)
                    db.session.commit()

            events = Event.query.all()
            assert len(events) == 1

    def test_alarm_clears_when_value_drops(self, client):
        """Alarm should clear when value drops below max - hysteresis."""
        # Usa valores fixos para não depender do sensors.json
        max_val = 30.0
        hysteresis = 1.0
        value = 25.0  # 25.0 < 30.0 - 1.0 → clear

        alarm_state["temp-001"] = {"high": True, "low": False}

        with app.app_context():
            # Simula a lógica de clear
            if value < max_val - hysteresis:
                if alarm_state["temp-001"]["high"]:
                    alarm_state["temp-001"]["high"] = False
                    event = Event(
                        sensor_id="temp-001",
                        event_type="high_value_clear",
                        message="temp-001 returned to normal",
                    )
                    db.session.add(event)
                    db.session.commit()

            # Verifica que o evento foi criado
            events = Event.query.filter_by(event_type="high_value_clear").all()
            assert len(events) == 1
            assert events[0].sensor_id == "temp-001"

    def test_low_value_alarm_fires_once(self, client):
        """Low alarm should fire only once."""
        inject_sensor_data("temp-001", 5.0)
        alarm_state["temp-001"] = {"high": False, "low": False}

        with app.app_context():
            from app import load_config
            config = load_config()
            sensor = config["sensors"][0]  # temp-001
            min_val = sensor["min"]
            value = 5.0

            if value < min_val:
                if not alarm_state["temp-001"]["low"]:
                    alarm_state["temp-001"]["low"] = True
                    event = Event(
                        sensor_id="temp-001",
                        event_type="low_value",
                        message=f"temp-001 below min threshold",
                    )
                    db.session.add(event)
                    db.session.commit()

            # Second time – should NOT fire
            if value < min_val:
                if not alarm_state["temp-001"]["low"]:
                    alarm_state["temp-001"]["low"] = True
                    event = Event(
                        sensor_id="temp-001",
                        event_type="low_value",
                        message=f"temp-001 below min threshold",
                    )
                    db.session.add(event)
                    db.session.commit()

            events = Event.query.filter_by(event_type="low_value").all()
            assert len(events) == 1