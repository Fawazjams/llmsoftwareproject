"""Live state feed for the 3D model (Arpit). main.py calls write_state(...) every frame.

Writes live_state.json (cwd) at most 5x/sec, and if STATE_HTTP_PORT is set, serves
GET /state with CORS so a browser (three.js) page can poll it. Never raises.
"""
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PATH = "live_state.json"
MIN_GAP = 0.2  # seconds -> max 5 writes/sec

_last_write = 0.0
_latest = b"{}"
_lock = threading.Lock()
_server_started = False


def _door_y():
    try:
        return float((os.getenv("DOOR_Y_FRAC") or "0.5").split("#")[0].strip())
    except ValueError:
        return 0.5


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?")[0] != "/state":
            self.send_response(404)
            self.end_headers()
            return
        with _lock:
            body = _latest
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep the console clean for the event log
        pass


def _start_server():
    global _server_started
    if _server_started:
        return
    _server_started = True
    port = (os.getenv("STATE_HTTP_PORT") or "").split("#")[0].strip()
    if not port.isdigit():
        return
    try:
        srv = ThreadingHTTPServer(("0.0.0.0", int(port)), _Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        print(f"[state] serving http://localhost:{port}/state", flush=True)
    except Exception as e:
        print(f"[state] HTTP server failed: {e}", flush=True)


def write_state(state, people, w, h):
    """state: counters dict; people: [(pid, (x1,y1,x2,y2), is_employee)]; w,h: frame size."""
    global _last_write, _latest
    try:
        _start_server()
        now = time.time()
        if now - _last_write < MIN_GAP or not w or not h:
            return
        _last_write = now
        data = {
            "t": now,
            "counts": {k: int(state.get(k, 0)) for k in ("in_store", "came_in", "left", "employees")},
            "people": [
                {"id": int(pid), "role": "employee" if emp else "customer",
                 "x": round((b[0] + b[2]) / 2 / w, 4), "y": round(b[3] / h, 4),
                 "w": round((b[2] - b[0]) / w, 4), "h": round((b[3] - b[1]) / h, 4)}
                for pid, b, emp in people
            ],
            "door_y": _door_y(),
        }
        body = json.dumps(data).encode()
        with _lock:
            _latest = body
        tmp = PATH + ".tmp"
        with open(tmp, "wb") as f:
            f.write(body)
        try:
            os.replace(tmp, PATH)
        except PermissionError:  # Windows: reader has the file open; skip this tick
            pass
    except Exception as e:
        print(f"[state] write failed: {e}", flush=True)
