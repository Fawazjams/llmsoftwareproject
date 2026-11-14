# In-N-Out: Who's Coming, Who's Leaving

**LLMSoftware x UT Dallas Hackathon, Challenge 1 (Surveillance.ai: Who's Coming, Who's Leaving).** A restaurant's camera already sees everything, but nobody watches it. In-N-Out turns a live camera into live answers: how many customers are in the store, who came in, who left, and how many staff are on the floor.

## What it does (mapped to the challenge)

| Requirement | How we do it |
|---|---|
| Connect to the live camera | OpenCV reads the Logitech webcam (`CAMERA=1`), a stream URL, or `nest_backup.mp4`, and reconnects automatically if the feed drops |
| Detect + track every person with a stable ID | YOLOv8n person detection + ByteTrack tracking |
| Label Employee vs Customer | Black-apron color check on the torso, **or** feet inside the counter zone. When the color check is unsure, **Claude vision** checks a torso-only crop, once per person, in a background thread (the answer is cached) |
| Count customers in / out | A door line across the frame. A customer crossing it changes *Came in* / *Left*. Employees are never counted |
| Show it live | Labeled boxes (`CUSTOMER #7` / `EMPLOYEE #2`) + 4 counters: *Customers in store, Came in, Left, Employees on floor* |
| Log line for every event | Printed to the console and appended to `events.log` |

### Stretch goals (both done)
- **Dwell time:** each exit is logged with how long the customer stayed; the overlay shows the average stay.
- **Counter-wait alert:** a customer at the counter for 2 min with **no employee** behind it triggers an alert. Claude rewrites it into an owner-friendly SMS, and **Twilio** texts the owner.
- **Bonus:** pressing `s` (or quitting) has Claude write a short end-of-session summary for the owner: traffic, peak, average stay, staff coverage.

### Example log
```
[02:41:05 PM] CUSTOMER #7 came in              | In store: 4 | Came in: 9 | Left: 5 | Employees: 2
[02:42:18 PM] CUSTOMER #3 left (stayed 6m12s)  | In store: 3 | Came in: 9 | Left: 6 | Employees: 2
[02:43:50 PM] ALERT: customer #5 waiting at counter 2m00s, no employee present
[02:43:51 PM] AI-verified: EMPLOYEE (apron)
```

## Architecture

```
webcam ─► YOLOv8n + ByteTrack ─► employee.py (color + Claude vision) ─► door-line counter ─► live overlay + events.log
                                                                     └► stretch.py (dwell, counter wait) ─► alerts.py (Claude text + Twilio SMS)
```

| Module | Owner | Role |
|---|---|---|
| `main.py` | Jamshed | Camera, tracking, door counting, overlay, log, wiring |
| `employee.py` | Nandhan | Employee vs customer: apron color + counter zone + Claude vision |
| `stretch.py` | Lokesh | Dwell time + 2-min counter-wait alert |
| `alerts.py` | Arpit | Claude-written alerts, Twilio SMS, end-of-session summary |

A 3D visualization of the store is in progress (Arpit).

## Run it

```
pip install -r requirements.txt
cp .env.example .env      # fill in the keys below
python main.py            # q = quit, s = AI session summary
```
First run downloads `yolov8n.pt` (~6 MB). Tune the employee thresholds live with `python employee.py`.

### `.env` settings
| Variable | Meaning |
|---|---|
| `CAMERA` | Webcam index (`1` = Logitech, `0` = built-in) or a stream URL / video file |
| `DOOR_Y_FRAC` | Door line height as a fraction of the frame (e.g. `0.5`) |
| `INSIDE_IS_BELOW` | `1` if "inside the store" is below the line in the image |
| `COUNTER_ZONE` | Behind the counter (anyone here = employee), `x1,y1,x2,y2` as fractions |
| `COUNTER_FRONT_ZONE` | Where customers wait at the counter, same format |
| `COUNTER_WAIT_SECONDS` | Wait before the counter alert (`120`; `20` for demos) |
| `APRON_SHARE`, `BLACK_V_MAX` | Apron color thresholds (share of black torso pixels, HSV brightness ceiling) |
| `APRON_AI_LOW`, `APRON_AI_HIGH` | "Unsure" band that triggers a Claude vision check |
| `EMPLOYEE_AI`, `EMPLOYEE_AI_MODEL`, `EMPLOYEE_AI_MAX_CALLS` | Turn the vision check on/off, model, per-session call cap |
| `ANTHROPIC_API_KEY` | Claude (alerts, summaries, vision check) |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM`, `ALERT_TO` | SMS alerts to the owner |

## Privacy
- **No face recognition.** Staff and customers are told apart by apron or position only.
- Only a **chest-to-waist crop** (no face) is ever sent to the AI.
- **No video is saved.** Only text events go to `events.log`.

## Keys
All keys live in `.env`, which is gitignored (`.env*` except `.env.example`). No keys are in the code or the git history.

## What's next
Per-hour traffic and staffing reports sent to the owner, plus POS integration so the system can flag a "register opened, no sale" event.
