# AGENTS.md: read this first

Hackathon: **LLMSoftware x UTD, Challenge 1 "Surveillance.ai: Who's Coming, Who's Leaving"**.
**Hard deadline: code pushed by 3:50 PM. The team submits at 4:00.** Small, working, merged beats ambitious.

## ⚠️ JUDGE'S REQUIREMENTS (said live at the event, highest priority)
1. **Anyone in an apron = EMPLOYEE. Everyone else = CUSTOMER.**
2. **Customers going out and coming in** must be counted.
3. **Employees coming in and employees going out** must ALSO be counted (done in main.py:
   `EMPLOYEE #3 came in` / `EMPLOYEE #3 left` log lines, "Staff came in / Staff left" counters).
The demo and the demo script must show all of these on screen. See issue #7.

## Live dashboard (one screen)
`python main.py` serves everything at **http://localhost:8765**: counters on top, camera top-left,
event log top-right, 3D view bottom-center (`?three=<url of the three.js page>`). Set `WEB_UI=0` in
`.env` to get the old OpenCV windows back.

## The challenge (judges score against this)
Live camera (Logitech webcam, `CAMERA=1`). Detect and track every person with a stable ID, label each one
**Employee** (black LLMSoftware apron, OR standing behind the counter) or **Customer**, count customers
**coming in / leaving** across a door line, and show it live: labeled boxes + 4 counters (*Customers in
store, Came in, Left, Employees on floor*) + a log line per event.
Stretch: how long each customer stayed; an alert when a customer waits at the counter 2 min with no employee present.

Scoring: It works 30 · Real-world usefulness 25 · Use of AI 20 · Engineering quality 15 · Stretch/polish 10.

## Who owns what (one file each, so there are no merge conflicts)
| Person | GitHub | File | Issue |
|---|---|---|---|
| Jamshed | @Fawazjams | `main.py`, `.env` tuning, merges, submission | #1 |
| Nandhan | @nandhanalahari | `employee.py` | #2 |
| Lokesh | @notlokii | `stretch.py` | #3 |
| Arpit | @ArpitKhavate | `alerts.py` | #4 |

**Only edit your own file.** `main.py` already calls every function in `employee.py`, `stretch.py` and
`alerts.py`. Keep those function signatures exactly as they are. If you need a change in `main.py`,
comment on issue #1 instead of editing it.

## Workflow
1. `git clone https://github.com/Fawazjams/llmsoftwareproject && cd llmsoftwareproject`
2. `pip install -r requirements.txt`, then `cp .env.example .env` and fill in the keys (ask the team; never commit them)
3. `git checkout -b <yourname>`, do the work, and make sure `python main.py` still runs
4. Push the branch and open a PR that says `Closes #N`. Jamshed merges it.
5. Small PRs early (by 3:15) beat one big PR at 3:50.

## Hard rules (judges check these)
- **No keys in code.** Read everything from `.env` (gitignored). A key in the repo costs points.
- **No face recognition.** Tell staff from customers by apron or position only. Don't save video.
- Never crash or block the video loop: wrap network calls (Claude, Twilio) in try/except and a thread.
- AI provider: Claude (`anthropic` SDK, key `ANTHROPIC_API_KEY`). Use `claude-haiku-5-5` for speed.

## Interfaces (already wired in main.py)
- `employee.is_employee(frame, box, counter_zone_px) -> bool`
- `stretch.on_came_in(pid)`, `stretch.on_left(pid) -> str` (log suffix),
  `stretch.on_frame(people, counter_front_px, counter_zone_px) -> list[str]` (alerts),
  `stretch.hud_lines() -> list[str]`
  where `people = [(pid, (x1,y1,x2,y2), is_employee), ...]`
- `alerts.send_alert(text)` (non-blocking), `alerts.summarize_session(log_path)`

## 3D model feed (for Arpit)
`state_export.write_state(state, people, w, h)` runs every frame and publishes the live scene (max 5x/sec):
- **File:** `live_state.json` in the folder `main.py` runs from (gitignored)
- **HTTP:** set `STATE_HTTP_PORT=8765` in `.env` → `GET http://localhost:8765/state` (CORS enabled)

```json
{"t": 1763150000.1,
 "counts": {"in_store": 3, "came_in": 9, "left": 6, "employees": 2},
 "people": [{"id": 7, "role": "customer", "x": 0.42, "y": 0.81, "w": 0.12, "h": 0.55}],
 "door_y": 0.5}
```
`x` = box center, `y` = feet (bottom of box), `w`/`h` = box size; all are fractions 0..1 of the frame.

```js
setInterval(async () => {
  const s = await (await fetch("http://localhost:8765/state")).json();
  s.people.forEach(p => placeAvatar(p.id, p.x, p.y, p.role)); // your three.js code
  updateCounters(s.counts);
}, 200);
```
