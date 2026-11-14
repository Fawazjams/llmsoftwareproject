# Demo: In-N-Out (30 seconds)

## 1. Script, second by second
| Time | Who | What |
|---|---|---|
| 0–4 s | Jamshed (talking) | **Problem:** "Restaurant owners already have cameras, but nobody watches them. We count customers and staff live." |
| 4–8 s | Apron teammate | Stands behind the counter in the black apron and is boxed **EMPLOYEE** (orange). Point at *Employees on floor: 1* |
| 8–14 s | Customer teammate | Walks in across the red door line. **Came in** and **Customers in store** go up, and the log line prints |
| 14–20 s | Customer teammate | Walks back out. **Left** goes up, and the log shows `(stayed Xs)` |
| 20–26 s | Arpit | Shows the SMS alert on his phone, or the 3D view if it's ready. Fallback: Jamshed presses **s** and Claude prints the session summary |
| 26–30 s | Jamshed (talking) | **Next:** "Next, we'd hook this into LLMSoftware's WhatsApp alerts and POS data across every camera in the store." |

Jamshed drives the laptop the whole time. Keep the window maximized.

## 2. Pre-demo checklist
`.env` on the demo laptop:
```
CAMERA=1                         # Logitech
DOOR_Y_FRAC=0.5                  # move until the red line sits across the doorway
INSIDE_IS_BELOW=1                # flip to 0 if in/out count backwards
COUNTER_ZONE=0.6,0.0,1.0,0.4     # behind the counter (example: top-right); feet here = employee
COUNTER_FRONT_ZONE=0.4,0.4,0.8,0.7  # where customers wait (example)
COUNTER_WAIT_SECONDS=20          # so the wait alert fires during the demo
TWILIO_FROM=+1...  ALERT_TO=+1...  # needed for the SMS
```
- [ ] `python main.py`: the window opens. Maximize it.
- [ ] Walk in and out once. Counts change the right way (if not, flip `INSIDE_IS_BELOW`)
- [ ] The apron wearer shows as EMPLOYEE
- [ ] Press **s** once to confirm the Claude summary prints
- [ ] Record the 30 s backup: **Win+Alt+R** to start/stop (Xbox Game Bar). It saves to `Videos\Captures`
- [ ] Phone unlocked on the SMS thread

## 3. Likely judge questions
1. **Why not send every frame to an LLM?** YOLOv8n runs locally and free at full frame rate. Claude only sees the *unsure* torso crops (once per person, capped at 40 calls), so the cost stays at a few cents per shift.
2. **Privacy?** No face recognition. Staff vs customer is decided by apron or position only. We send Claude only the chest-to-waist crop, never the face. No video is saved.
3. **False positives?** A majority vote over 15 frames stops labels flickering, a 2 s grace period stops a brief tracker dropout from resetting a wait, a crossing counts only once someone is seen on both sides, and SMS alerts are limited to 1 per 30 s so owners don't mute them.
4. **How does it fit LLMSoftware?** It's the people-count layer of Surveillance.ai. The `send_alert` hook goes straight to their WhatsApp alerts, and the event log feeds the end-of-day summary and POS data (traffic vs sales).
5. **Scaling to many cameras?** One lightweight process per camera (the detector is 6 MB and runs on CPU) sends events to a central service. The LLM is only called on edge cases, so cost grows with uncertain events, not with how many cameras there are.

## 4. Submission checklist (by the deadline)
- [ ] Repo **public**, or shared with **support@llmsoftware.com**: `gh repo edit Fawazjams/llmsoftwareproject --visibility public --accept-visibility-change-consequences`
- [ ] No keys in git (`.env` is gitignored, check with `git log -p | grep -i "sk-ant\|AC[0-9a-f]\{32\}"`)
- [ ] 30-second screen recording of the live counters
- [ ] Team sheet:

| Name | UTD email | Internship / Full-time |
|---|---|---|
| Jamshed Nazar | | |
| Nandhan Alahari | | |
| Lokesh Reddy Penugonda | | |
| Arpit Khavate | | |
