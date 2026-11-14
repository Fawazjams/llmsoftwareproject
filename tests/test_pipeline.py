"""Offline tests for Surveillance.ai: no camera, no network. Run: python -m pytest -q tests"""
import importlib
import os
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# No Claude / Twilio calls from tests.
os.environ["EMPLOYEE_AI"] = "0"
os.environ["COUNTER_WAIT_SECONDS"] = "20"
os.environ["TWILIO_FROM"] = ""
os.environ["ALERT_TO"] = ""
os.environ["ANTHROPIC_API_KEY"] = ""


# ---------- employee.py ----------
@pytest.fixture
def employee():
    import employee as mod
    return importlib.reload(mod)


BOX = (100, 50, 200, 350)  # x1, y1, x2, y2: a 100x300 person


def _frame(torso_bgr):
    frame = np.full((480, 640, 3), 128, np.uint8)        # mid-grey background
    x1, y1, x2, y2 = BOX
    frame[y1:y2, x1:x2] = (200, 180, 160)                # light clothes
    frame[y1 + 60:y1 + 220, x1:x2] = torso_bgr           # torso band (chest to waist)
    return frame


def test_black_apron_is_employee(employee):
    assert employee.is_employee(_frame((10, 10, 10)), BOX)


def test_white_shirt_is_customer(employee):
    assert not employee.is_employee(_frame((245, 245, 245)), BOX)


def test_feet_in_counter_zone_is_employee(employee):
    zone = (50, 300, 300, 400)  # contains feet point (150, 350)
    assert employee.is_employee(_frame((245, 245, 245)), BOX, zone)


# ---------- stretch.py ----------
@pytest.fixture
def stretch(monkeypatch):
    import stretch as mod
    mod = importlib.reload(mod)
    clock = [1000.0]
    monkeypatch.setattr(mod.time, "time", lambda: clock[0])
    return mod, clock


FRONT = (0, 0, 100, 100)
COUNTER = (200, 0, 300, 100)
CUST = (1, (10, 10, 50, 90), False)
EMP = (2, (210, 10, 250, 90), True)


def test_dwell_suffix(stretch):
    mod, clock = stretch
    mod.on_came_in(1)
    clock[0] += 192
    assert "3m12s" in mod.on_left(1)
    assert any("Avg stay" in line for line in mod.hud_lines())


def test_counter_wait_alert_fires_once(stretch):
    mod, clock = stretch
    alerts = []
    for _ in range(40):
        clock[0] += 1
        alerts += mod.on_frame([CUST], FRONT, COUNTER)
    assert len(alerts) == 1
    assert "waiting at counter" in alerts[0]


def test_no_alert_when_employee_behind_counter(stretch):
    mod, clock = stretch
    alerts = []
    for _ in range(40):
        clock[0] += 1
        alerts += mod.on_frame([CUST, EMP], FRONT, COUNTER)
    assert alerts == []


def test_no_alert_without_front_zone(stretch):
    mod, _ = stretch
    assert mod.on_frame([CUST], None, COUNTER) == []


# ---------- main.py ----------
@pytest.fixture
def main_mod(monkeypatch):
    import cv2

    def no_camera(*a, **k):
        raise AssertionError("importing main.py must not open a camera")

    monkeypatch.setattr(cv2, "VideoCapture", no_camera)
    import main as mod
    return importlib.reload(mod)


@pytest.mark.parametrize("raw,expected", [
    ("0.6,0,1,0.4 # comment", (0.6, 0.0, 1.0, 0.4)),
    ("", None),
    ("# junk", None),
])
def test_zone_parsing(main_mod, monkeypatch, raw, expected):
    monkeypatch.setenv("TEST_ZONE", raw)
    assert main_mod._zone("TEST_ZONE") == expected


# ---------- alerts.py ----------
def test_send_alert_without_twilio_numbers_does_not_raise():
    import alerts
    alerts = importlib.reload(alerts)
    alerts.send_alert("test: customer waiting at counter 20 s")
