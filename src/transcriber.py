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

    def _run_whisper(self, audio_path: str, output_dir: str) -> list[dict] | None:
        """Run mlx_whisper on a single audio file.

        Returns list of segment dicts [{"start", "end", "text"}, ...] or None on failure.
        """
        cmd = [
            str(MLX_WHISPER_BIN),
            audio_path,
            "--model",
            WHISPER_MODEL,
            "--language",
            WHISPER_LANGUAGE,
            "--output-dir",
            output_dir,
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
            log.error(f"mlx_whisper failed for {audio_path}: {result.stderr}")
            return None

        # Find the JSON output file
        audio_stem = Path(audio_path).stem
        json_file = Path(output_dir) / f"{audio_stem}.json"
        if not json_file.exists():
            json_files = list(Path(output_dir).glob("*.json"))
            if json_files:
                json_file = json_files[0]

        if not json_file.exists():
            log.error(f"No JSON output produced for {audio_path}")
            return None

        try:
            whisper_data = json.loads(json_file.read_text(encoding="utf-8"))
            segments = []
            for seg in whisper_data.get("segments", []):
                segments.append(
                    {
                        "start": seg.get("start", 0.0),
                        "end": seg.get("end", 0.0),
                        "text": seg.get("text", "").strip(),
                    }
                )
            return segments
        except (json.JSONDecodeError, KeyError) as e:
            log.warning(f"Failed to parse JSON transcript for {audio_path}: {e}")
            return None

    @staticmethod
    def _merge_by_timestamp(
        segments_me: list[dict], segments_others: list[dict]
    ) -> list[dict]:
        """Merge two transcript segment lists by start time."""
        all_segments = [
            {
                "start": s["start"],
                "end": s["end"],
                "text": s["text"],
                "speaker": "SPEAKER_ME",
            }
            for s in segments_me
        ] + [
            {
                "start": s["start"],
                "end": s["end"],
                "text": s["text"],
                "speaker": "SPEAKER_OTHER",
            }
            for s in segments_others
        ]
        return sorted(all_segments, key=lambda x: x["start"])

    @staticmethod
    def _format_speaker_text(merged_segments: list[dict]) -> str:
        """Build unified text from merged segments with speaker labels and timestamps."""
        lines = []
        for seg in merged_segments:
            minutes = int(seg["start"]) // 60
            seconds = int(seg["start"]) % 60
            lines.append(f"[{minutes}:{seconds:02d}] {seg['speaker']}: {seg['text']}")
        return "\n".join(lines)

    def transcribe_separate(self, session_dir: str) -> dict | None:
        """Transcribe mic and system audio separately, then merge by timestamp.

        Returns:
            dict with keys:
            - "text": full merged transcript text with speaker labels
            - "segments": list of {"start", "end", "text", "speaker"}
              where speaker is "SPEAKER_ME" or "SPEAKER_OTHER"
            - "transcript_me": segments from mic only
            - "transcript_others": segments from system only
            Or None on failure.
        """
        session_path = Path(session_dir)
        mic_wav = session_path / "mic.wav"
        system_wav = session_path / "system.wav"

        mic_exists = mic_wav.exists() and mic_wav.stat().st_size > 44
        sys_exists = system_wav.exists() and system_wav.stat().st_size > 44

        if not mic_exists and not sys_exists:
            log.error("No audio files found for separate transcription")
            return None

        segments_me: list[dict] = []
        segments_others: list[dict] = []

        # Transcribe mic (SPEAKER_ME)
        if mic_exists:
            with tempfile.TemporaryDirectory() as tmp_dir:
                log.info("Running mlx_whisper on mic.wav...")
                result = self._run_whisper(str(mic_wav), tmp_dir)
                if result is not None:
                    segments_me = result
                else:
                    log.warning("Mic transcription failed, continuing with system only")

        # Transcribe system (SPEAKER_OTHER)
        if sys_exists:
            with tempfile.TemporaryDirectory() as tmp_dir:
                log.info("Running mlx_whisper on system.wav...")
                result = self._run_whisper(str(system_wav), tmp_dir)
                if result is not None:
                    segments_others = result
                else:
                    log.warning("System transcription failed, continuing with mic only")

        # Check that at least one transcription succeeded
        if not segments_me and not segments_others:
            log.error("Both mic and system transcriptions failed")
            return None

        # Merge by timestamp
        merged = self._merge_by_timestamp(segments_me, segments_others)

        # Build unified text with speaker labels
        full_text = self._format_speaker_text(merged)

        # Save transcript
        if full_text:
            transcript_path = session_path / "transcript.txt"
            transcript_path.write_text(full_text, encoding="utf-8")
            log.info(
                f"Separate transcript: {len(full_text)} chars, "
                f"{len(segments_me)} mic + {len(segments_others)} system segments"
            )

        return {
            "text": full_text,
            "segments": merged,
            "transcript_me": segments_me,
            "transcript_others": segments_others,
        }
