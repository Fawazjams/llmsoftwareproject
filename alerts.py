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


def _sms(body: str, force: bool = False) -> None:
    global _last_sms
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
    # Trial accounts can only use Twilio's predefined voice template: the owner's phone rings.
    try:
        client.calls.create(to=to, from_=frm, url=os.getenv(
            "TWILIO_CALL_URL", "https://webhooks.twilio.com/v1/Voice/Template/voice_speech_recognition"))
        print(f"[CALL placed to owner] {body}")
    except Exception as e:
        print(f"[alerts] Twilio call failed: {type(e).__name__}: {str(e)[:100]} | {body}")


def _alert_worker(text: str) -> None:
    try:
        msg = _claude(
            "Rewrite this restaurant camera event as ONE short SMS line for the owner "
            f"(max 20 words, plain text, no emoji, no quotes):\n{text}", 1024) or text
        _sms(f"Surveillance.ai: {msg}")
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
            "You are Surveillance.ai reporting to a restaurant owner. From this event log, write a "
            "3-4 line plain-text summary: total customers in/out, peak customers in store, staff "
            "coverage (employees on floor), and any alerts. Be concrete, no markdown.\n\n"
            + "\n".join(lines), 1024)
        if not summary:
            summary = f"{len(lines)} events logged (AI summary unavailable). Last: {lines[-1]}"
        print("\n=== Session summary ===\n" + summary + "\n=======================")
        _sms(f"Surveillance.ai summary:\n{summary}", force=True)
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
