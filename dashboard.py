"""One-page live dashboard for Surveillance.ai.

Run alongside main.py:  python dashboard.py   then open http://localhost:8000
Reads events.log only (no video, no faces), so it never touches the camera loop.
"""
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).parent
LOG = ROOT / "events.log"
PAGE = ROOT / "dashboard" / "index.html"
PORT = int(os.getenv("DASHBOARD_PORT", "8000"))

COUNTS = re.compile(r"In store: (\d+) \| Came in: (\d+) \| Left: (\d+) \| Employees: (\d+)")


def read_state():
    lines = LOG.read_text(encoding="utf-8", errors="ignore").splitlines() if LOG.exists() else []
    state = {"in_store": 0, "came_in": 0, "left": 0, "employees": 0}
    for line in reversed(lines):
        m = COUNTS.search(line)
        if m:
            state = dict(zip(state, map(int, m.groups())))
            break
    alerts = [l for l in lines if "ALERT" in l][-5:]
    return {**state, "log": lines[-40:], "alerts": alerts}


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
    print(f"Surveillance.ai dashboard on http://localhost:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
