"""Call Recorder — audio merge + mlx_whisper transcription."""

import json
import logging
import subprocess
import tempfile
from pathlib import Path

from .config import (
    FFMPEG_BIN,
    MLX_WHISPER_BIN,
    WHISPER_LANGUAGE,
    WHISPER_MODEL,
)

log = logging.getLogger("call-recorder")


class Transcriber:
    """Merges system + mic audio and runs mlx_whisper."""

    def merge_audio(self, system_wav: str, mic_wav: str, output_path: str) -> bool:
        """Merge system and mic WAV into a single 16kHz mono WAV.

        Uses amix filter to combine both streams.
        Falls back to single file if one is missing/empty.
        """
        sys_exists = Path(system_wav).exists() and Path(system_wav).stat().st_size > 44
        mic_exists = Path(mic_wav).exists() and Path(mic_wav).stat().st_size > 44

        if sys_exists and mic_exists:
            # Merge both
            cmd = [
                FFMPEG_BIN,
                "-y",
                "-i",
                system_wav,
                "-i",
                mic_wav,
                "-filter_complex",
                "amix=inputs=2:duration=longest:dropout_transition=2",
                "-ar",
                "16000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                output_path,
            ]
        elif sys_exists:
            cmd = [
                FFMPEG_BIN,
                "-y",
                "-i",
                system_wav,
                "-ar",
                "16000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                output_path,
            ]
        elif mic_exists:
            cmd = [
                FFMPEG_BIN,
                "-y",
                "-i",
                mic_wav,
                "-ar",
                "16000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                output_path,
            ]
        else:
            log.error("No audio files to merge")
            return False

        log.info(f"Merging audio → {output_path}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            log.error(f"ffmpeg merge failed: {result.stderr}")
            return False
        return True

    def transcribe(self, session_dir: str) -> dict | str | None:
        """Merge audio and transcribe.

        Returns a dict with 'text' and 'segments' if JSON output available,
        or a plain string for backward compat, or None on failure.
        """
        session_path = Path(session_dir)
        system_wav = str(session_path / "system.wav")
        mic_wav = str(session_path / "mic.wav")
        combined_wav = str(session_path / "combined.wav")

        # Step 1: Merge
        if not self.merge_audio(system_wav, mic_wav, combined_wav):
            return None

        # Step 2: Transcribe with mlx_whisper (JSON for segments)
        log.info("Running mlx_whisper...")

        with tempfile.TemporaryDirectory() as tmp_dir:
            cmd = [
                str(MLX_WHISPER_BIN),
                combined_wav,
                "--model",
                WHISPER_MODEL,
                "--language",
                WHISPER_LANGUAGE,
                "--output-dir",
                tmp_dir,
                "--output-format",
                "json",
                "--condition-on-previous-text",
                "False",
                "--hallucination-silence-threshold",
                "2.0",
                "--no-speech-threshold",
                "0.6",
                "--compression-ratio-threshold",
                "2.4",
                "--initial-prompt",
                "Это запись разговора. Говорят несколько человек.",
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                log.error(f"mlx_whisper failed: {result.stderr}")
                return None

            # Try JSON output first (contains segments with timestamps)
            json_file = Path(tmp_dir) / "combined.json"
            if not json_file.exists():
                json_files = list(Path(tmp_dir).glob("*.json"))
                if json_files:
                    json_file = json_files[0]

            if json_file.exists():
                try:
                    whisper_data = json.loads(json_file.read_text(encoding="utf-8"))
                    full_text = whisper_data.get("text", "").strip()
                    segments = []
                    for seg in whisper_data.get("segments", []):
                        segments.append(
                            {
                                "start": seg.get("start", 0.0),
                                "end": seg.get("end", 0.0),
                                "text": seg.get("text", "").strip(),
                            }
                        )

                    # Save text transcript alongside recordings
                    if full_text:
                        transcript_path = session_path / "transcript.txt"
                        transcript_path.write_text(full_text, encoding="utf-8")
                        log.info(
                            f"Transcript: {len(full_text)} chars, {len(segments)} segments"
                        )
                        return {"text": full_text, "segments": segments}
                except (json.JSONDecodeError, KeyError) as e:
                    log.warning(f"Failed to parse JSON transcript: {e}")

            # Fallback: try txt output
            txt_file = Path(tmp_dir) / "combined.txt"
            if not txt_file.exists():
                txt_files = list(Path(tmp_dir).glob("*.txt"))
                if txt_files:
                    txt_file = txt_files[0]
                else:
                    log.error("No transcript file produced")
                    return None

            transcript = txt_file.read_text(encoding="utf-8").strip()

            # Save transcript alongside recordings
            transcript_path = session_path / "transcript.txt"
            transcript_path.write_text(transcript, encoding="utf-8")

            log.info(f"Transcript: {len(transcript)} chars (text only)")
            return transcript
