# Detection v2 — physical call signal

Date: 2026-08-19
Status: approved by board backlog item 10; implementing

## Problem

Detection rests on per-app heuristics: a Zoom-only process name and UDP
connection counting that (a) fired on QUIC browsing noise for months,
(b) died for Meet when the noise was filtered, (c) was never verified live
for Teams/Discord (zero real calls in DB). Board verdict: replace the
heuristic pile with one physical signal, verified for all platforms at once.

## Signal stack (2026 standard, per market research)

1. **Who holds the microphone** — CoreAudio per-process API (macOS 14.4+):
   `kAudioHardwarePropertyProcessObjectList` + per-process
   `kAudioProcessPropertyIsRunningInput` + PID. The OS-level truth behind the
   orange mic indicator. One-shot reads each poll — reliable on Tahoe 26
   (listeners there are flaky, reads are not).
2. **Camera running** — CMIO `kCMIODevicePropertyDeviceIsRunningSomewhere`
   over camera devices. Status read, no extra TCC.
3. **WebRTC power assertion** — Chrome holds a `NoIdleSleepAssertion` named
   "WebRTC has active PeerConnections" during a call; survives mute (the
   sticky keep-alive). Read via `pmset -g assertions` from Python.

## Components

### swift/CallSignal.swift → bin/call-signal

One-shot CLI, prints JSON to stdout and exits:

```json
{"mic_processes": [{"pid": 123, "name": "zoom.us"}], "camera_on": true}
```

No TCC required: both APIs are status reads. Built by setup.sh next to
audio-capture (`swiftc swift/CallSignal.swift -o bin/call-signal`).

### src/detector.py — SignalProbe + decision rules

`SignalProbe.probe()` runs bin/call-signal (timeout 3s) and
`pmset -g assertions`; returns `{"mic_apps": [...], "camera_on": bool,
"webrtc_assertion": bool}` or None when the helper is missing/broken.

Decision (inside `_raw_check`, before UDP heuristics):

- `audio-capture` (our own recorder) is excluded from mic holders — else the
  recorder detects itself forever (superwhisper's documented bug).
- Zoom: CptHost process check stays first (cheapest, proven).
- Native apps: known call app (zoom.us, Microsoft Teams, Discord, Telegram,
  FaceTime) holds the mic → call. Unknown mic holders (dictation tools,
  voice notes) map to nothing — no false positives by construction.
- Browser (Chrome/Arc/Chromium family): call = WebRTC assertion present,
  OR browser holds mic AND camera is on. Assertion alone is enough — it is
  the mute-proof signal; Meet solo rooms hold mic+assertion too.
- Probe returned None → legacy UDP heuristics (fallback, unchanged).
- Debounce (2 consecutive checks) and the consent dialog stay as gates.

## Known tradeoffs

- Native apps that release the mic on mute may drop detection mid-call;
  Zoom is covered by CptHost, browsers by the assertion. Accepted for now.
- Helper spawn each poll (~30-60 ms) — acceptable at 3 s cadence.
- Camera signal is global (not per-app) — used only as an AND-condition for
  browsers, never alone.

## Verification

- Unit: mapping rules with mocked probe output (all branches).
- Live: run bin/call-signal while bin/audio-capture records for 2 s — the
  helper must list audio-capture as a mic holder; verify exclusion rule.
- Live: real Meet/Zoom call — owner's manual step (backlog).
