"""Live web dashboard + state feed. main.py calls set_frame(frame) and write_state(...) every frame.

If STATE_HTTP_PORT is set (e.g. 8765), serves:
  GET /          -> dashboard.html (video, live log, counters, Arpit's 3D view)
  GET /video     -> MJPEG stream of the annotated camera frames
  GET /state     -> JSON: counts, people (0..1 coords), log lines  (CORS on, for three.js)
  GET /summary   -> asks Claude for the session summary (alerts.summarize_session)
Also writes live_state.json (cwd) at most 5x/sec. Never raises.
"""
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2

PATH = "live_state.json"
MIN_GAP = 0.2        # state: max 5 updates/sec
FRAME_GAP = 1 / 15   # video: max 15 fps to the browser
HERE = os.path.dirname(os.path.abspath(__file__))

_last_write = 0.0
_last_frame = 0.0
_latest = b"{}"
_jpeg = None
_lock = threading.Lock()
_frame_cv = threading.Condition()
_server_started = False


def _door_y():
    try:
        return float((os.getenv("DOOR_Y_FRAC") or "0.5").split("#")[0].strip())
    except ValueError:
        return 0.5


class _Handler(BaseHTTPRequestHandler):
    def _send(self, body, ctype):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        try:
            if path == "/state":
                with _lock:
                    body = _latest
                self._send(body, "application/json")
            elif path in ("/", "/index.html"):
                with open(os.path.join(HERE, "dashboard.html"), "rb") as f:
                    self._send(f.read(), "text/html; charset=utf-8")
            elif path == "/frame.jpg":
                with _frame_cv:
                    jpg = _jpeg
                if jpg is None:
                    self.send_response(503)
                    self.end_headers()
                else:
                    self._send(jpg, "image/jpeg")
            elif path == "/summary":
                import alerts
                threading.Thread(target=alerts.summarize_session, args=("events.log",), daemon=True).start()
                self._send(b'{"ok": true}', "application/json")
            elif path == "/video":
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                while True:
                    with _frame_cv:
                        _frame_cv.wait(timeout=1.0)
                        jpg = _jpeg
                    if jpg is None:
                        continue
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                     + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n")
            else:
                self.send_response(404)
                self.end_headers()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # browser tab closed
        except Exception as e:
            print(f"[web] {path} failed: {e}", flush=True)

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
        srv.daemon_threads = True
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        print(f"[web] dashboard at http://localhost:{port}", flush=True)
    except Exception as e:
        print(f"[web] HTTP server failed: {e}", flush=True)


def set_frame(frame):
    """Publish the annotated frame to /video (JPEG, throttled)."""
    global _jpeg, _last_frame
    try:
        _start_server()
        now = time.time()
        if now - _last_frame < FRAME_GAP:
            return
        _last_frame = now
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if ok:
            with _frame_cv:
                _jpeg = buf.tobytes()
                _frame_cv.notify_all()
    except Exception as e:
        print(f"[web] frame failed: {e}", flush=True)


def write_state(state, people, w, h, log=None):
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
            "counts": {k: int(state.get(k, 0))
                       for k in ("in_store", "came_in", "left", "employees", "emp_in", "emp_out")},
            "people": [
                {"id": int(pid), "role": "employee" if emp else "customer",
                 "x": round((b[0] + b[2]) / 2 / w, 4), "y": round(b[3] / h, 4),
                 "w": round((b[2] - b[0]) / w, 4), "h": round((b[3] - b[1]) / h, 4)}
                for pid, b, emp in people
            ],
            "door_y": _door_y(),
            "log": list(log or []),
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
