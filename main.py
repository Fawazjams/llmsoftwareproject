"""Surveillance.ai: live customer in/out counter (LLMSoftware x UTD Challenge 1).

OWNER: Jamshed (issue #1). Other modules plug in through fixed functions:
  employee.py (Nandhan), stretch.py (Lokesh), alerts.py (Arpit).

Run:  python main.py      Keys: q = quit, s = AI session summary
"""
import os
import time
from collections import defaultdict, deque

import cv2
from dotenv import load_dotenv
from ultralytics import YOLO

load_dotenv()

import builtins  # noqa: E402

import numpy as np  # noqa: E402

import alerts  # noqa: E402  (after load_dotenv so modules can read env at import)
import employee  # noqa: E402
import stretch  # noqa: E402
from employee import is_employee  # noqa: E402

try:
    import state_export  # optional: feeds the 3D view
except Exception:
    state_export = None

WIN_VIDEO, WIN_LOG = "Surveillance.ai", "Event log"
PANEL_W, PANEL_H = 940, 530
LOG_LINES = deque(maxlen=40)


def _feed(line):
    LOG_LINES.append(line)


def _tee_print(*args, **kwargs):
    builtins.print(*args, **kwargs)
    text = " ".join(str(a) for a in args).strip()
    if text:
        _feed(text.splitlines()[-1] if "AI-verified" not in text else text)


# Lines printed by employee.py (AI-verified) and alerts.py (SMS sent) also show on the panel
employee.print = _tee_print
alerts.print = _tee_print

# CAMERA can be a webcam index ("0", "1") or a path/URL ("nest_backup.mp4")
_src = os.getenv("CAMERA", "1")
SOURCE = int(_src) if _src.isdigit() else _src

DOOR_Y_FRAC = float(os.getenv("DOOR_Y_FRAC", "0.5"))          # door line height, fraction of frame
INSIDE_IS_BELOW = os.getenv("INSIDE_IS_BELOW", "1") == "1"     # flip if the door faces the other way


def _envf(name, default):
    try:
        return float((os.getenv(name) or str(default)).split("#")[0].strip())
    except ValueError:
        return default


def door_config():
    """Door line config: live from state_export.CONFIG (dashboard) if present, else .env.
    axis "y" = horizontal line (compare box center y), "x" = vertical line (compare center x).
    "inside" is the greater-than side unless invert."""
    cfg = getattr(state_export, "CONFIG", None) if state_export is not None else None
    if isinstance(cfg, dict) and cfg.get("axis") in ("x", "y"):
        try:
            return cfg["axis"], min(max(float(cfg.get("pos", 0.5)), 0.0), 1.0), bool(cfg.get("invert", False))
        except (TypeError, ValueError):
            pass
    axis = (os.getenv("DOOR_AXIS") or "y").split("#")[0].strip().lower()
    axis = axis if axis in ("x", "y") else "y"
    pos = _envf("DOOR_X_FRAC" if axis == "x" else "DOOR_Y_FRAC", 0.5)
    return axis, min(max(pos, 0.0), 1.0), not INSIDE_IS_BELOW


CROSS_COOLDOWN = 1.5  # s between counted crossings for the same person (stops jitter double counts)
FORGET_AFTER = 3.0    # s: drop door state for track IDs not seen this long


def _zone(name):
    v = (os.getenv(name) or "").split("#")[0].strip()
    try:
        z = tuple(float(x) for x in v.split(","))
        return z if len(z) == 4 else None
    except ValueError:
        return None


COUNTER_ZONE = _zone("COUNTER_ZONE")              # behind the counter -> employee
COUNTER_FRONT_ZONE = _zone("COUNTER_FRONT_ZONE")  # where customers wait (used by stretch.py)
VOTE_WINDOW = 15  # per-person employee votes kept (stops label flicker)


def stamp():
    return time.strftime("%I:%M:%S %p").lstrip("0")


def log(msg, state=None):
    line = f"[{stamp()}] {msg}"
    if state is not None:
        line = (f"[{stamp()}] {msg:<22} | In store: {state['in_store']} | Came in: {state['came_in']} | "
                f"Left: {state['left']} | Employees: {state['employees']}")
    print(line, flush=True)
    _feed(line)
    with open("events.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def to_px(zone, w, h):
    if not zone:
        return None
    x1, y1, x2, y2 = zone
    return int(x1 * w), int(y1 * h), int(x2 * w), int(y2 * h)


def _line_color(line):
    if "ALERT" in line:
        return (60, 60, 255)      # red
    if "came in" in line:
        return (90, 220, 90)      # green
    if " left" in line:
        return (0, 220, 240)      # yellow
    if "AI-verified" in line:
        return (240, 220, 0)      # cyan
    if "SMS" in line:
        return (255, 160, 200)
    return (220, 220, 220)


def render_log_panel(state):
    img = np.full((PANEL_H, PANEL_W, 3), 24, dtype=np.uint8)
    header = (f"In store: {state['in_store']}   Came in: {state['came_in']}   "
              f"Left: {state['left']}   Employees: {state['employees']}   "
              f"Staff in/out: {state.get('emp_in', 0)}/{state.get('emp_out', 0)}")
    cv2.rectangle(img, (0, 0), (PANEL_W, 48), (45, 45, 45), -1)
    cv2.putText(img, header, (14, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2)
    font, scale = cv2.FONT_HERSHEY_SIMPLEX, 0.5
    max_chars = 105
    y = 78
    for line in LOG_LINES:
        t = line if len(line) <= max_chars else line[:max_chars - 3] + "..."
        cv2.putText(img, t, (12, y), font, scale, _line_color(line), 1, cv2.LINE_AA)
        y += 32
    return img


def open_cap():
    if isinstance(SOURCE, int):
        cap = cv2.VideoCapture(SOURCE, cv2.CAP_DSHOW)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        return cap
    return cv2.VideoCapture(SOURCE)


def main():
    cap = open_cap()
    model = YOLO("yolov8n.pt")  # class 0 = person
    last_side = {}
    last_cross = {}  # pid -> time of last counted crossing
    last_seen = {}   # pid -> time last seen
    votes = defaultdict(lambda: deque(maxlen=VOTE_WINDOW))
    state = {"in_store": 0, "came_in": 0, "left": 0, "employees": 0, "emp_in": 0, "emp_out": 0}
    web_ui = os.getenv("WEB_UI", "1").split("#")[0].strip() == "1" and state_export is not None
    if web_ui:
        print("Open the dashboard: http://localhost:" + (os.getenv("STATE_HTTP_PORT") or "8765").split("#")[0].strip()
              + "   (Ctrl+C here to stop)", flush=True)
    else:
        cv2.namedWindow(WIN_VIDEO, cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)
        cv2.resizeWindow(WIN_VIDEO, PANEL_W, PANEL_H)
        cv2.moveWindow(WIN_VIDEO, 0, 0)
        cv2.namedWindow(WIN_LOG, cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)
        cv2.resizeWindow(WIN_LOG, PANEL_W, PANEL_H)
        cv2.moveWindow(WIN_LOG, 960, 0)

    while True:
        ok, frame = cap.read()
        if not ok:
            print("camera offline, reconnecting...")
            time.sleep(0.5)
            cap = open_cap()
            continue

        h, w = frame.shape[:2]
        axis, pos, invert = door_config()
        line_px = int((h if axis == "y" else w) * pos)
        zone_px = to_px(COUNTER_ZONE, w, h)
        front_px = to_px(COUNTER_FRONT_ZONE, w, h)

        res = model.track(frame, classes=[0], persist=True, verbose=False, tracker="bytetrack.yaml")[0]
        people = []
        if res.boxes.id is not None:
            for box, pid in zip(res.boxes.xyxy.tolist(), res.boxes.id.int().tolist()):
                votes[pid].append(bool(is_employee(frame, box, zone_px, pid=pid)))
                people.append((pid, tuple(box), sum(votes[pid]) > len(votes[pid]) / 2))

        state["employees"] = sum(1 for _, _, emp in people if emp)

        now = time.time()
        for pid in [p for p, t in last_seen.items() if now - t > FORGET_AFTER]:
            last_seen.pop(pid, None)
            last_side.pop(pid, None)
            last_cross.pop(pid, None)

        margin = int((h if axis == "y" else w) * 0.03)  # dead band so jitter on the line doesn't count
        for pid, box, employee in people:
            last_seen[pid] = now
            c = (box[1] + box[3]) / 2 if axis == "y" else (box[0] + box[2]) / 2
            if abs(c - line_px) < margin:
                side = last_side.get(pid)  # inside the dead band: keep the previous side
            else:
                side = "inside" if (c > line_px) != invert else "outside"
            prev = last_side.get(pid)
            crossed = (side and prev and prev != side
                       and now - last_cross.get(pid, 0.0) >= CROSS_COOLDOWN)
            if crossed:
                last_cross[pid] = now
            if crossed and employee:  # role decided at the moment of crossing (majority vote)
                key = "emp_in" if side == "inside" else "emp_out"
                state[key] += 1
                log(f"EMPLOYEE #{pid} {'came in' if side == 'inside' else 'left'}", state)
            elif crossed:
                if side == "inside":
                    state["came_in"] += 1
                    state["in_store"] = max(state["came_in"] - state["left"], 0)
                    stretch.on_came_in(pid)
                    log(f"CUSTOMER #{pid} came in", state)
                else:
                    state["left"] += 1
                    state["in_store"] = max(state["came_in"] - state["left"], 0)
                    log(f"CUSTOMER #{pid} left{stretch.on_left(pid)}", state)
            if side:
                last_side[pid] = side

            color = (0, 140, 255) if employee else (0, 200, 0)
            x1, y1, x2, y2 = map(int, box)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(frame, f"{'EMPLOYEE' if employee else 'CUSTOMER'} #{pid}", (x1, max(y1 - 6, 12)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        for alert in stretch.on_frame(people, front_px, zone_px):
            log(f"ALERT: {alert}")
            alerts.send_alert(alert)

        # overlay
        if axis == "y":
            cv2.line(frame, (0, line_px), (w, line_px), (0, 0, 255), 2)
        else:
            cv2.line(frame, (line_px, 0), (line_px, h), (0, 0, 255), 2)
        if zone_px:
            cv2.rectangle(frame, zone_px[:2], zone_px[2:], (255, 120, 0), 2)
        if front_px:
            cv2.rectangle(frame, front_px[:2], front_px[2:], (255, 255, 0), 1)
        hud = [f"Customers in store: {state['in_store']}", f"Came in: {state['came_in']}",
               f"Left: {state['left']}", f"Employees on floor: {state['employees']}",
               f"Staff in: {state['emp_in']}  Staff out: {state['emp_out']}"] + stretch.hud_lines()
        cv2.rectangle(frame, (0, 0), (360, 18 + 28 * len(hud)), (0, 0, 0), -1)
        for i, t in enumerate(hud):
            cv2.putText(frame, t, (10, 28 + 28 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        if state_export is not None:
            try:
                state_export.write_state(state, people, w, h, log=list(LOG_LINES))
                state_export.set_frame(frame)
            except Exception:
                pass

        if web_ui:
            continue
        cv2.imshow(WIN_VIDEO, frame)
        cv2.imshow(WIN_LOG, render_log_panel(state))
        key = cv2.waitKey(1) & 0xFF
        if key == ord("s"):
            alerts.summarize_session("events.log")
        if key == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()
    alerts.summarize_session("events.log")


if __name__ == "__main__":
    main()
