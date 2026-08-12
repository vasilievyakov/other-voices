# Consent-before-record + detector hardening

Date: 2026-08-12
Status: approved

## Problem

1. The daemon auto-starts capture on call detection. Capture opens the default
   input (Bose QC45 Bluetooth mic), which drops the headphones from A2DP to HFP
   — audio dies for the user mid-music. It happens again on capture stop.
2. The Google Meet detector counts any Chrome/Arc helper with >=2 UDP
   connections to distinct remote IPs. Chrome's QUIC traffic (HTTP/3, UDP:443)
   to ordinary Google services triggers false "calls" — log for 2026-08-12
   shows three 26-30s phantom sessions within 12 minutes.

## Decisions (user-approved)

- Ask before recording via a native `osascript` `display dialog` — zero
  dependencies, impossible to miss.
- Timeout (60s) or "Нет" → do NOT record. Never touch the mic without explicit
  consent. No re-prompt for the same ongoing call.
- Call ends while the dialog is up → dismiss the dialog, record nothing.
- Detector: exclude UDP remote port 443 (QUIC) from the browser-helper count;
  require 2 consecutive positive checks (debounce) before reporting a call.
- Out of scope for this pass: pinning capture input to a non-Bluetooth mic,
  Screen Recording TCC re-grant (manual step).

## Design

### src/consent.py (new)

- `ConsentPrompt(app_name, timeout=CONSENT_TIMEOUT)` — spawns a non-blocking
  `osascript` dialog via `subprocess.Popen`: buttons «Нет» / «Записать»,
  default «Записать», `giving up after <timeout>`.
  - `poll()` → `None` while pending; `"record"` if «Записать» clicked;
    `"decline"` on «Нет», timeout (`gave up:true`), or any osascript error.
    Hung osascript is killed after `timeout + 10s` → `"decline"`.
  - `cancel()` → kills the dialog process.
- `ConsentGate(prompt_factory=ConsentPrompt)` — per-tick state machine used by
  the daemon loop. `tick(in_call, app_name, recording) -> bool` returns True
  exactly when recording should start:
  - not in call → cancel pending prompt, clear denied flag, False
  - recording already / denied for this call → False
  - in call, no prompt yet → spawn prompt, False
  - prompt answered "record" → True (once); "decline" → set denied flag

### src/daemon.py

Main loop keeps its shape; the `in_call and not recorder.is_recording` branch
delegates to `ConsentGate.tick()`. Recording start (Ollama health check,
notify, `recorder.start`, `write_status`) moves behind the granted consent.
`status.json` stays "idle" while the prompt is pending — the Swift app is not
touched.

### src/detector.py

- `_has_udp_connections(..., exclude_ports=frozenset())` — browser-helper path
  passes `{443}`; native apps (Teams/Discord/Telegram/FaceTime) are unchanged.
- `CallDetector(confirmations=N)` — raw positive result must repeat N
  consecutive `check()` calls (same app) before being reported. A negative
  check resets the counter; an app switch restarts it. Default 1 preserves
  existing behavior; the daemon passes `DETECTION_CONFIRMATIONS`.

### src/config.py

- `CONSENT_TIMEOUT = 60`
- `DETECTION_CONFIRMATIONS = 2`

## Known tradeoffs

- The beginning of a consented call is not recorded (consent-first by design).
- Meet on networks that relay media over UDP:443 will no longer be detected;
  normal networks use UDP 19305+ and are unaffected.
- An unattended real call is skipped after the 60s timeout.

## Testing

- Detector: QUIC-only traffic ignored, high-port WebRTC still detected,
  mixed below-threshold, debounce (N consecutive, reset on gap, app switch).
- ConsentPrompt: stdout parsing (record/decline/gave-up/error), cancel kills,
  hung-process kill; subprocess mocked.
- ConsentGate: full flow — prompt on call, no re-prompt after decline until
  call end, cancel on call end, single True on grant.
