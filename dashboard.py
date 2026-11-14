"""One-page live dashboard for Footfall: camera, counters, 3D floor twin, event log.

Run alongside main.py:  python dashboard.py   then open http://localhost:8000
Reads live_state.json (written by state_export.py: positions only, no video) and events.log,
so it never touches the camera loop.
"""
import json
import os
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).parent
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

LOG = ROOT / "events.log"
LIVE = ROOT / "live_state.json"   # written by main.py via state_export.write_state
PAGE = ROOT / "dashboard" / "index.html"
PORT = int(os.getenv("DASHBOARD_PORT", "8000"))
STALE_AFTER = 3.0                 # seconds: older than this means main.py is not running

COUNTS = re.compile(r"In store: (\d+) \| Came in: (\d+) \| Left: (\d+) \| Employees: (\d+)")


def _zone(name):
    """x1,y1,x2,y2 fractions from .env (same format main.py reads), or None."""
    v = (os.getenv(name) or "").split("#")[0].strip()
    try:
        z = [float(x) for x in v.split(",")]
        return z if len(z) == 4 else None
    except ValueError:
        return None


def read_live():
    """Live scene for the 3D view, or None when main.py is not running."""
    try:
        if time.time() - LIVE.stat().st_mtime > STALE_AFTER:
            return None
        s = json.loads(LIVE.read_text(encoding="utf-8"))
        line = s.get("line") or {}
        return {
            "door": line.get("pos", s.get("door_y", 0.5)),
            "inside_below": not line.get("invert", False),
            "counter": _zone("COUNTER_ZONE"), "front": _zone("COUNTER_FRONT_ZONE"),
            **s["counts"],
            # main.py tests the box CENTER against the door line, so place people there
            "people": [{"id": p["id"], "employee": p["role"] == "employee",
                        "x": p["x"], "y": p["y"] - p["h"] / 2} for p in s["people"]],
            "log": s.get("log") or [],
        }
    except (OSError, ValueError, KeyError, TypeError):
        return None


def read_state():
    lines = LOG.read_text(encoding="utf-8", errors="ignore").splitlines() if LOG.exists() else []
    state = {"in_store": 0, "came_in": 0, "left": 0, "employees": 0}
    for line in reversed(lines):
        m = COUNTS.search(line)
        if m:
            state = dict(zip(state, map(int, m.groups())))
            break
    live = read_live()
    if live:
        state = {k: live[k] for k in state}      # live counts beat the last log line
        lines = live.pop("log") or lines
    alerts = [l for l in lines if "ALERT" in l][-5:]
    return {**state, "log": lines[-40:], "alerts": alerts, "live": live}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/state"):
            body, ctype = json.dumps(read_state()).encode(), "application/json"
        elif self.path in ("/", "/index.html"):
            body, ctype = PAGE.read_bytes(), "text/html; charset=utf-8"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print(f"Footfall dashboard on http://localhost:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
