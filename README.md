# Other Voices

A macOS app that automatically records, transcribes, and summarizes your calls — Zoom, Meet, Teams, Discord, Telegram, FaceTime. Everything runs locally. No cloud. No subscriptions.

![macOS](https://img.shields.io/badge/macOS-14%2B-blue) ![Python](https://img.shields.io/badge/Python-3.11%2B-yellow) ![Swift](https://img.shields.io/badge/Swift-6.0-orange) ![License](https://img.shields.io/badge/license-MIT-green) ![Tests](https://img.shields.io/badge/tests-395-brightgreen)

<!-- ![Other Voices — three-column call browser](screenshot.png) -->

## Why

Every call you take contains decisions, promises, and context that evaporates within hours. Enterprise tools like Otter.ai or Fireflies send your audio to the cloud, cost $20+/month, and don't work with Telegram or FaceTime.

Other Voices runs entirely on your Mac:

- **Audio capture** via ScreenCaptureKit — records both system audio and your microphone
- **Transcription** via [mlx-whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper) — Whisper Large V3 running on Apple Silicon, no network needed
- **Summarization** via [Ollama](https://ollama.com) — qwen3:14b generates structured summaries locally
- **Storage** in SQLite with FTS5 — full-text search across all your calls

You own your data. It never leaves your machine.

## Features

- **Set it and forget it** — daemon runs at login via launchd, detects calls automatically, records, transcribes, and summarizes without any interaction
- **6 call platforms** — Zoom, Google Meet, Microsoft Teams, Discord, Telegram, FaceTime. Detection uses process inspection + UDP connection analysis
- **6 summary templates** — Default, Sales Call, 1-on-1, Standup, Interview, Brainstorm. Each produces a structured JSON summary tailored to the meeting type
- **Entity extraction** — people and companies mentioned in calls are extracted automatically and searchable across your entire history
- **Timestamp citations** — transcripts include `[M:SS]` markers, summaries cite specific moments. Click a timestamp to jump to that point in the audio
- **User notes** — add your own notes to any call; they're used as steering signals during re-summarization
- **Native macOS app** — SwiftUI three-column browser with live daemon status, audio playback, full-text search, and template picker
- **CLI for power users** — search, list, show, action items, entities — all from the terminal

## How It Works

```
          ┌─────────────┐
          │   Daemon     │  polls every 3s
          │  (Python)    │
          └──────┬───────┘
                 │ call detected?
                 ▼
          ┌─────────────┐
          │   Recorder   │  spawns audio-capture binary
          │   (Swift)    │  → system.wav + mic.wav (16 kHz, mono)
          └──────┬───────┘
                 │ call ended
                 ▼
          ┌─────────────┐
          │ Transcriber  │  ffmpeg merge → mlx_whisper
          │  (Python)    │  → JSON {text, segments[{start, end, text}]}
          └──────┬───────┘
                 │
                 ▼
          ┌─────────────┐
          │ Summarizer   │  template → prompt → Ollama
          │  (Python)    │  → structured JSON + entities
          └──────┬───────┘
                 │
                 ▼
          ┌─────────────┐
          │  Database    │  SQLite + FTS5
          │              │  calls, entities
          └──────┬───────┘
                 │
          ┌──────┴───────┐
          │              │
          ▼              ▼
   ┌───────────┐  ┌───────────┐
   │ SwiftUI   │  │   CLI     │
   │   App     │  │ (Python)  │
   └───────────┘  └───────────┘
```

## Call Detection

Each platform requires a different detection strategy:

| Platform | Strategy | How it works |
|----------|----------|-------------|
| **Zoom** | Process-only | `CptHost` process exists only during active calls |
| **Google Meet** | Browser + UDP | Chrome/Arc/Chromium helper with 2+ WebRTC UDP connections |
| **Microsoft Teams** | Process + UDP | Teams process with 2+ distinct remote UDP endpoints |
| **Discord** | Process + UDP | Discord process with 2+ distinct remote UDP endpoints |
| **Telegram** | Process + UDP | Telegram process with 2+ distinct remote UDP endpoints |
| **FaceTime** | Process + UDP | FaceTime process with 2+ distinct remote UDP endpoints |

## Install

Requires macOS 14 (Sonoma) or later. Apple Silicon recommended (for mlx-whisper).

### Prerequisites

```bash
# Ollama — local LLM runtime
brew install ollama
ollama serve &    # start in background
ollama pull qwen3:14b

# mlx-whisper — local transcription
pipx install mlx-whisper

# ffmpeg — audio processing
brew install ffmpeg
```

### Setup

```bash
git clone https://github.com/vasilievyakov/other-voices.git ~/call-recorder
cd ~/call-recorder
bash setup.sh
```

Setup script will:
1. Create Python venv, install `psutil`
2. Compile Swift audio-capture binary from source
3. Pull Ollama model if needed
4. Install launchd agent (auto-start at login)
5. Verify mlx-whisper installation

### Permissions

Go to **System Settings → Privacy & Security** and grant your terminal app:
- **Screen Recording** — required to capture system audio
- **Microphone** — required to capture your voice

### Start

```bash
# Via launchd (recommended — auto-restarts on crash):
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.user.call-recorder.plist

# Or manually for testing:
cd ~/call-recorder && .venv/bin/python3 -m src.daemon
```

### Build the SwiftUI app

```bash
cd ~/call-recorder/app
swift build
open .build/debug/OtherVoices  # or: swift run
```

## Usage

### CLI

```bash
cd ~/call-recorder

# List recent calls
.venv/bin/python3 cli.py list

# Full-text search
.venv/bin/python3 cli.py search "архитектура"

# Search by person or company
.venv/bin/python3 cli.py search --person "Vasya"
.venv/bin/python3 cli.py search --company "Acme"

# Show call details
.venv/bin/python3 cli.py show 20260220_143000

# Action items from last 7 days
.venv/bin/python3 cli.py actions

# List all extracted people and companies
.venv/bin/python3 cli.py entities
```

### Summary Templates

Choose the right template for each meeting type:

| Template | Sections | Best for |
|----------|----------|----------|
| **Default** | Summary, Key Points, Decisions, Action Items, Participants | General calls |
| **Sales Call** | Summary, Objections, Budget Signals, Decision Makers, Next Steps | Sales / client calls |
| **1-on-1** | Summary, Feedback, Blockers, Goals, Mood | Manager/report meetings |
| **Standup** | Summary, Done Yesterday, Doing Today, Blockers | Daily standups |
| **Interview** | Summary, Strengths, Concerns, Culture Fit, Recommendation | Candidate debriefs |
| **Brainstorm** | Summary, Ideas, Feasibility, Next Steps | Creative sessions |

Re-summarize any call with a different template from the SwiftUI app or CLI:

```bash
.venv/bin/python3 resummarize.py --session 20260220_143000 --template sales_call
```

## Privacy

- **Reads:** microphone input, system audio output (during calls only)
- **Writes:** WAV files, SQLite database — all in `~/call-recorder/data/`
- **Transmits:** nothing. All ML inference runs locally via mlx-whisper and Ollama
- **No telemetry. No analytics. No cloud.**

Your call recordings, transcripts, and summaries never leave your machine.

## Project Structure

```
call-recorder/
├── src/                          # Python daemon (10 modules, ~1,600 lines)
│   ├── daemon.py                 # Main event loop: detect → record → process
│   ├── detector.py               # Call detection via psutil + UDP inspection
│   ├── recorder.py               # Manages audio-capture subprocess
│   ├── transcriber.py            # ffmpeg merge + mlx_whisper
│   ├── summarizer.py             # Ollama-based structured summarization
│   ├── templates.py              # 6 templates + bilingual prompt builder
│   ├── chunking.py               # Map-reduce chunking for long transcripts
│   ├── database.py               # SQLite + FTS5 (calls, entities)
│   └── config.py                 # Paths, models, detection parameters
│
├── app/                          # SwiftUI macOS app (~3,000 lines)
│   ├── Sources/
│   │   ├── Models/               # Call, Entity, Template, DaemonStatus, etc.
│   │   ├── Services/             # CallStore, SQLiteDatabase, AudioPlayer
│   │   ├── Views/                # Sidebar, CallList, Detail, Notes
│   │   └── App/                  # Entry point
│   └── Tests/CallTests.swift     # 137 Swift tests
│
├── swift/AudioCapture.swift      # ScreenCaptureKit audio capture (330 lines)
├── cli.py                        # CLI interface (5 commands)
├── tests/                        # 258 Python tests
├── setup.sh                      # One-command installation
└── launchd/                      # macOS launch agent config
```

<details>
<summary><strong>Database Schema</strong></summary>

```sql
-- Calls with full-text search
CREATE TABLE calls (
    session_id TEXT PRIMARY KEY,
    app_name TEXT,
    started_at TEXT,
    ended_at TEXT,
    duration_seconds REAL,
    system_wav_path TEXT,
    mic_wav_path TEXT,
    transcript TEXT,
    summary_json TEXT,
    template_name TEXT DEFAULT 'default',
    notes TEXT,
    transcript_segments TEXT     -- JSON [{start, end, text}, ...]
);

CREATE VIRTUAL TABLE calls_fts USING fts5(
    session_id, app_name, transcript, summary_json
);

-- Extracted entities (people and companies)
CREATE TABLE entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    type TEXT CHECK(type IN ('person','company')),
    session_id TEXT REFERENCES calls(session_id) ON DELETE CASCADE,
    UNIQUE(name, type, session_id)
);

-- Chat history (per-call and global)
CREATE TABLE chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT REFERENCES calls(session_id),
    role TEXT CHECK(role IN ('user','assistant')),
    content TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    scope TEXT DEFAULT 'call' CHECK(scope IN ('call','global'))
);
```

</details>

<details>
<summary><strong>Configuration</strong></summary>

All defaults in `src/config.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| `POLL_INTERVAL` | 3s | How often to check for active calls |
| `MIN_CALL_DURATION` | 30s | Ignore calls shorter than this |
| `WHISPER_MODEL` | `mlx-community/whisper-large-v3-mlx` | Transcription model |
| `WHISPER_LANGUAGE` | `ru` | Default transcription language |
| `OLLAMA_MODEL` | `qwen3:14b` | Summarization model |
| `OLLAMA_URL` | `http://localhost:11434/api/generate` | Ollama endpoint |

Override via environment variables or edit `src/config.py` directly.

</details>

## Tests

```bash
# Python (258 tests)
cd ~/call-recorder && .venv/bin/python3 -m pytest tests/ -v

# Swift (137 tests)
cd ~/call-recorder/app && swift build && .build/debug/OtherVoicesTests
```

Test suite covers: detection logic, audio recording lifecycle, transcription (JSON + fallback), summarization, all 6 templates, chunked processing, database CRUD + FTS5, entity extraction, CLI commands, daemon event loop, and Swift models/services.

## Requirements

| Component | Purpose | Size |
|-----------|---------|------|
| [Ollama](https://ollama.com) | Local LLM runtime | ~500 MB |
| [qwen3:14b](https://ollama.com/library/qwen3:14b) | Summarization model | ~9 GB |
| [mlx-whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper) | Transcription | ~3 GB (model auto-downloads) |
| [ffmpeg](https://ffmpeg.org) | Audio merging | ~80 MB |
| Python 3.11+ | Daemon runtime | system |
| Xcode Command Line Tools | Swift compiler | system |

Total disk: ~8 GB (mostly ML models). RAM: ~6 GB during transcription + summarization.

## License

MIT License. See [LICENSE](LICENSE) for details.
