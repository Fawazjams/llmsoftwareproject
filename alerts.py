"""OWNER: Arpit (issue #4). Twilio SMS + Claude-written alerts and summary.

main.py already calls these functions. Keep the signatures.
Rules: keys come from .env only; never block or crash the video loop (use a thread).
"""
import os
import threading
import time

MODEL = "claude-haiku-5-5"
SMS_MIN_GAP = 30.0
_last_sms = 0.0
_lock = threading.Lock()


def _claude(prompt: str, max_tokens: int) -> str | None:
    try:
        import anthropic
        r = anthropic.Anthropic(timeout=8.0).messages.create(
            model=MODEL, max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}])
        text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text").strip()
        return text.encode("ascii", "ignore").decode().strip() or None
    except Exception as e:
        print(f"[alerts] Claude failed: {type(e).__name__}: {str(e)[:100]}")
        return None


def _push(body: str) -> None:
    """Custom-text phone notification via ntfy (free, no account). Phone: ntfy app, subscribe to NTFY_TOPIC."""
    topic = (os.getenv("NTFY_TOPIC") or "").split("#")[0].strip()
    if not topic:
        return
    try:
        import urllib.request
        req = urllib.request.Request(f"https://ntfy.sh/{topic}", data=body.encode("utf-8"), method="POST",
                                     headers={"Title": "In-N-Out alert", "Priority": "urgent", "Tags": "rotating_light"})
        urllib.request.urlopen(req, timeout=5).read()
        print(f"[PUSH sent] {body}")
    except Exception as e:
        print(f"[alerts] push failed: {type(e).__name__}: {str(e)[:80]}")


def _sms(body: str, force: bool = False) -> None:
    global _last_sms
    _push(body)
    frm, to = os.getenv("TWILIO_FROM", "").strip(), os.getenv("ALERT_TO", "").strip()
    if not frm or not to:
        print(f"[SMS skipped: no number] {body}")
        return
    with _lock:
        if not force and time.time() - _last_sms < SMS_MIN_GAP:
            print(f"[SMS rate-limited] {body}")
            return
        _last_sms = time.time()
    try:
        from twilio.rest import Client
        client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
    except Exception as e:
        print(f"[alerts] Twilio client failed: {e}")
        return
    if os.getenv("ALERT_MODE", "auto").split("#")[0].strip() != "call":
        try:
            client.messages.create(body=body[:1500], from_=frm, to=to)
            print(f"[SMS sent] {body}")
            return
        except Exception as e:
            print(f"[alerts] SMS blocked ({str(e)[:60]}), calling instead")
    # Spoken alert: Twilio's hosted Twimlet reads CALL_SCRIPT aloud (works on trial accounts, which
    # block inline TwiML). On a trial, the callee hears Twilio's trial notice first and presses any key.
    try:
        import urllib.parse
        script = os.getenv("CALL_SCRIPT", "").split("#")[0].strip() or (
            "In N Out alert. A customer is waiting and no employee is on the floor. "
            "Please go help them now. Again: a customer is waiting with no employee on the floor.")
        url = "https://twimlets.com/message?" + urllib.parse.urlencode({"Message[0]": script})
        client.calls.create(to=to, from_=frm, url=url)
        print(f"[CALL placed to employee] {body}")
    except Exception as e:
        print(f"[alerts] Twilio call failed: {type(e).__name__}: {str(e)[:100]} | {body}")


def _alert_worker(text: str) -> None:
    try:
        msg = _claude(
            "Rewrite this restaurant camera event as ONE short SMS line for the owner "
            f"(max 20 words, plain text, no emoji, no quotes):\n{text}", 1024) or text
        _sms(f"In-N-Out: {msg}")
    except Exception as e:
        print(f"[alerts] send_alert error: {e}")


def send_alert(text: str) -> None:
    """Non-blocking: Claude rewrites the event, then Twilio SMS to ALERT_TO (1 per 30 s)."""
    try:
        threading.Thread(target=_alert_worker, args=(text,), daemon=True).start()
    except Exception as e:
        print(f"[alerts] could not start thread: {e}")


def _summary_worker(log_path: str) -> None:
    try:
        if not os.path.exists(log_path):
            print(f"[alerts] no {log_path} yet, nothing to summarize")
            return
        with open(log_path, encoding="utf-8") as f:
            lines = f.read().splitlines()[-300:]
        if not lines:
            print("[alerts] log is empty, nothing to summarize")
            return
        summary = _claude(
            "You are In-N-Out reporting to a restaurant owner. From this event log, write a "
            "3-4 line plain-text summary: total customers in/out, peak customers in store, staff "
            "coverage (employees on floor), and any alerts. Be concrete, no markdown.\n\n"
            + "\n".join(lines), 1024)
        if not summary:
            summary = f"{len(lines)} events logged (AI summary unavailable). Last: {lines[-1]}"
        print("\n=== Session summary ===\n" + summary + "\n=======================")
        _sms(f"In-N-Out summary:\n{summary}", force=True)
    except Exception as e:
        print(f"[alerts] summarize_session error: {e}")


def summarize_session(log_path: str = "events.log") -> None:
    """Claude summary of the session log; printed and SMS'd. Blocks at most ~10 s."""
    try:
        t = threading.Thread(target=_summary_worker, args=(log_path,), daemon=True)
        t.start()
        t.join(timeout=10)
    except Exception as e:
        print(f"[alerts] summarize_session error: {e}")
