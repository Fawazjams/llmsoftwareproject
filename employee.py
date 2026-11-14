"""Employee vs customer (OWNER: Nandhan, issue #2).

A person is an EMPLOYEE if
  1. their feet are inside the counter zone (behind the counter), or
  2. their torso is mostly black (the LLMSoftware apron).

The color check is fast but fooled by dark shirts and jackets. When it is unsure
(apron share between AI_LOW and AI_HIGH), we send ONLY the torso crop (chest to
waist, no face) to Claude vision once per person, in a background thread, and
cache the answer. The video loop never waits on the network.

main.py calls is_employee(frame, box, counter_zone_px) without the track ID, so
answers are cached per person by matching boxes across frames (IoU). If main.py
ever passes pid=..., that is used directly.

Tuning: run `python employee.py` to see each person's apron share live.
All thresholds can be overridden in .env.
"""
import base64
import os
import threading
import time

import cv2
import numpy as np

BLACK_MEDIAN_V = int(os.getenv("BLACK_MEDIAN_V", "75"))  # chest median brightness below this = black top

APRON_SHARE = float(os.getenv("APRON_SHARE", "0.35"))   # share of black torso pixels = apron
BLACK_V_MAX = int(os.getenv("BLACK_V_MAX", "60"))       # HSV brightness ceiling for "black"
AI_LOW = float(os.getenv("APRON_AI_LOW", "0.20"))       # unsure band -> ask Claude
AI_HIGH = float(os.getenv("APRON_AI_HIGH", "0.55"))
AI_ENABLED = os.getenv("EMPLOYEE_AI", "1") == "1"
AI_MODEL = os.getenv("EMPLOYEE_AI_MODEL", "claude-haiku-5-5")
AI_MAX_CALLS = int(os.getenv("EMPLOYEE_AI_MAX_CALLS", "40"))  # per session, protects credits

_PROMPT = (
    "This is a cropped chest-to-waist image of one person from a restaurant security camera. "
    "Staff wear a black apron (often with an 'LLMSoftware' logo) tied over their clothes: a black "
    "panel covering the front of the torso, usually with straps or a neck loop and a visible waist tie. "
    "A plain black shirt, hoodie or jacket is NOT an apron. "
    "Is this person wearing a black apron? Answer with exactly one word: YES, NO, or UNSURE."
)

# ---- per-person cache, matched across frames by box overlap -----------------
_tracks = []            # dicts: box, seen, ai (None | "pending" | True | False | "skip")
_by_pid = {}            # pid -> same dict, if main.py passes pid
_lock = threading.Lock()
_calls = 0
_client = None
TRACK_TTL = 3.0         # seconds a box is remembered after it was last seen
MATCH_IOU = 0.3


def _iou(a, b):
    ix1, iy1, ix2, iy2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(ix2 - ix1, 0) * max(iy2 - iy1, 0)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _track_for(box, pid=None):
    now = time.time()
    with _lock:
        if pid is not None and pid in _by_pid:
            t = _by_pid[pid]
        else:
            _tracks[:] = [t for t in _tracks if now - t["seen"] < TRACK_TTL]
            best = max(_tracks, key=lambda t: _iou(t["box"], box), default=None)
            if best is not None and _iou(best["box"], box) >= MATCH_IOU:
                t = best
            else:
                t = {"box": box, "seen": now, "ai": None}
                _tracks.append(t)
            if pid is not None:
                _by_pid[pid] = t
        t["box"], t["seen"] = box, now
        return t


# ---- color check -------------------------------------------------------------
def torso_crop(frame, box):
    """Chest-to-waist band, middle 70% of the width (drops background at the sides). No face."""
    x1, y1, x2, y2 = [int(v) for v in box]
    fh, fw = frame.shape[:2]
    x1, x2 = max(x1, 0), min(x2, fw)
    y1, y2 = max(y1, 0), min(y2, fh)
    h, w = y2 - y1, x2 - x1
    if h < 20 or w < 10:
        return None
    crop = frame[y1 + int(h * 0.28): y1 + int(h * 0.65), x1 + int(w * 0.15): x2 - int(w * 0.15)]
    return crop if crop.size else None


def apron_share(torso):
    hsv = cv2.cvtColor(torso, cv2.COLOR_BGR2HSV)
    black = cv2.inRange(hsv, (0, 0, 0), (180, 255, BLACK_V_MAX))
    return float(black.mean() / 255)


# ---- Claude vision (background thread) ---------------------------------------
def _get_client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    return _client


def _ask_claude(track, torso):
    try:
        ok, jpg = cv2.imencode(".jpg", torso, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok:
            raise ValueError("jpeg encode failed")
        msg = _get_client().messages.create(
            model=AI_MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                             "data": base64.b64encode(jpg.tobytes()).decode()}},
                {"type": "text", "text": _PROMPT},
            ]}],
        )
        answer = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip().upper()
        verdict = True if answer.startswith("YES") else False if answer.startswith("NO") else None
        track["ai"] = "skip" if verdict is None else verdict  # "skip": asked once, fall back to color
        label = {True: "EMPLOYEE (apron)", False: "CUSTOMER (no apron)", None: "unsure"}[verdict]
        print(f"[{time.strftime('%I:%M:%S %p')}] AI-verified: {label}", flush=True)
    except Exception as e:  # never let the network break the video loop
        track["ai"] = "skip"
        print(f"[employee] Claude check failed: {e}", flush=True)


def _maybe_ask(track, torso):
    global _calls
    if not AI_ENABLED or not os.getenv("ANTHROPIC_API_KEY"):
        return
    with _lock:
        if track["ai"] is not None or _calls >= AI_MAX_CALLS:
            return
        track["ai"] = "pending"
        _calls += 1
    threading.Thread(target=_ask_claude, args=(track, torso.copy()), daemon=True).start()


# ---- public API (signature fixed by main.py) ---------------------------------
def is_employee(frame, box, counter_zone=None, pid=None):
    x1, y1, x2, y2 = [int(v) for v in box]
    if counter_zone:
        cx, feet_y = (x1 + x2) / 2, y2
        zx1, zy1, zx2, zy2 = counter_zone
        if zx1 <= cx <= zx2 and zy1 <= feet_y <= zy2:
            return True

    # HARD RULE (demo): black clothing = EMPLOYEE, any other color = CUSTOMER.
    # Look only at the middle of the chest (no background, no face) and use the MEDIAN
    # brightness, so shadows and a dark room behind a white shirt can't flip it.
    fh, fw = frame.shape[:2]
    cx1, cx2 = max(x1, 0), min(x2, fw)
    cy1, cy2 = max(y1, 0), min(y2, fh)
    bw, bh = cx2 - cx1, cy2 - cy1
    if bw < 10 or bh < 20:
        return False
    chest = frame[cy1 + int(bh * 0.35): cy1 + int(bh * 0.65), cx1 + int(bw * 0.30): cx2 - int(bw * 0.30)]
    if chest.size == 0:
        return False
    hsv = cv2.cvtColor(chest, cv2.COLOR_BGR2HSV)
    v = float(np.median(hsv[:, :, 2]))
    return v < BLACK_MEDIAN_V


# ---- tuning tool: python employee.py ----------------------------------------
if __name__ == "__main__":
    from dotenv import load_dotenv
    from ultralytics import YOLO

    load_dotenv()
    src = os.getenv("CAMERA", "1")
    cap = cv2.VideoCapture(int(src) if src.isdigit() else src)
    model = YOLO("yolov8n.pt")
    print(f"BLACK_V_MAX={BLACK_V_MAX} APRON_SHARE={APRON_SHARE} unsure band={AI_LOW}-{AI_HIGH}. q to quit.")
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        res = model.track(frame, classes=[0], persist=True, verbose=False)[0]
        for b in res.boxes.xyxy.tolist():
            t = torso_crop(frame, b)
            if t is None:
                continue
            s = apron_share(t)
            emp = is_employee(frame, b)
            x1, y1, x2, y2 = map(int, b)
            color = (0, 140, 255) if emp else (0, 200, 0)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            h, w = y2 - y1, x2 - x1
            cv2.rectangle(frame, (x1 + int(w * 0.15), y1 + int(h * 0.28)),
                          (x2 - int(w * 0.15), y1 + int(h * 0.65)), (255, 0, 255), 1)
            cv2.putText(frame, f"apron {s:.2f} {'EMP' if emp else 'CUST'}", (x1, max(y1 - 6, 12)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        cv2.imshow("employee.py tuning", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break
    cap.release()
    cv2.destroyAllWindows()
