"""Tests for src.transcriber — mock subprocess.run.

Enterprise coverage: merge branches, transcribe pipeline, edge cases.
"""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.transcriber import Transcriber


def _wav_bytes(size=100):
    """Create bytes larger than WAV header (44 bytes)."""
    return b"\x00" * size


def _empty_wav_bytes():
    """Create bytes exactly at WAV header size (should be treated as empty)."""
    return b"\x00" * 44


@pytest.fixture
def transcriber():
    return Transcriber()


@pytest.fixture
def session_both(tmp_path):
    """Session dir with both system.wav and mic.wav."""
    d = tmp_path / "session"
    d.mkdir()
    (d / "system.wav").write_bytes(_wav_bytes())
    (d / "mic.wav").write_bytes(_wav_bytes())
    return d


@pytest.fixture
def session_system_only(tmp_path):
    """Session dir with only system.wav."""
    d = tmp_path / "session"
    d.mkdir()
    (d / "system.wav").write_bytes(_wav_bytes())
    return d


@pytest.fixture
def session_mic_only(tmp_path):
    """Session dir with only mic.wav."""
    d = tmp_path / "session"
    d.mkdir()
    (d / "mic.wav").write_bytes(_wav_bytes())
    return d


@pytest.fixture
def session_empty(tmp_path):
    """Session dir with no audio files."""
    d = tmp_path / "session"
    d.mkdir()
    return d


@pytest.fixture
def session_empty_wavs(tmp_path):
    """Session dir with WAVs at exactly header size (44 bytes = empty)."""
    d = tmp_path / "session"
    d.mkdir()
    (d / "system.wav").write_bytes(_empty_wav_bytes())
    (d / "mic.wav").write_bytes(_empty_wav_bytes())
    return d


# =============================================================================
# Merge Audio (8 tests)
# =============================================================================


class TestMergeAudio:
    def test_merge_both_files(self, transcriber, session_both, tmp_path):
        """system.wav + mic.wav → ffmpeg amix command."""
        output = str(tmp_path / "combined.wav")
        with patch("src.transcriber.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = transcriber.merge_audio(
                str(session_both / "system.wav"),
                str(session_both / "mic.wav"),
                output,
            )
        assert result is True
        cmd = mock_run.call_args[0][0]
        assert "amix" in " ".join(str(c) for c in cmd)

    def test_merge_system_only(self, transcriber, session_system_only, tmp_path):
        """mic absent → single-input conversion (no amix)."""
        output = str(tmp_path / "combined.wav")
        with patch("src.transcriber.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = transcriber.merge_audio(
                str(session_system_only / "system.wav"),
                str(session_system_only / "mic.wav"),
                output,
            )
        assert result is True
        cmd = " ".join(str(c) for c in mock_run.call_args[0][0])
        assert "amix" not in cmd

    def test_merge_mic_only(self, transcriber, session_mic_only, tmp_path):
        """system absent → single-input conversion from mic."""
        output = str(tmp_path / "combined.wav")
        with patch("src.transcriber.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = transcriber.merge_audio(
                str(session_mic_only / "system.wav"),
                str(session_mic_only / "mic.wav"),
                output,
            )
        assert result is True
        cmd = " ".join(str(c) for c in mock_run.call_args[0][0])
        assert "amix" not in cmd
        assert "mic.wav" in cmd

    def test_merge_no_files(self, transcriber, session_empty, tmp_path):
        """No audio files → False."""
        output = str(tmp_path / "combined.wav")
        result = transcriber.merge_audio(
            str(session_empty / "system.wav"),
            str(session_empty / "mic.wav"),
            output,
        )
        assert result is False

    def test_merge_empty_wavs(self, transcriber, session_empty_wavs, tmp_path):
        """WAVs at exactly 44 bytes (header only) treated as empty → False."""
        output = str(tmp_path / "combined.wav")
        result = transcriber.merge_audio(
            str(session_empty_wavs / "system.wav"),
            str(session_empty_wavs / "mic.wav"),
            output,
        )
        assert result is False

    def test_merge_ffmpeg_failure(self, transcriber, session_both, tmp_path):
        """ffmpeg returns non-zero → False."""
        output = str(tmp_path / "combined.wav")
        with patch("src.transcriber.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="ffmpeg error")
            result = transcriber.merge_audio(
                str(session_both / "system.wav"),
                str(session_both / "mic.wav"),
                output,
            )
        assert result is False

    def test_merge_output_format(self, transcriber, session_both, tmp_path):
        """ffmpeg command includes 16kHz mono PCM output settings."""
        output = str(tmp_path / "combined.wav")
        with patch("src.transcriber.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            transcriber.merge_audio(
                str(session_both / "system.wav"),
                str(session_both / "mic.wav"),
                output,
            )
        cmd = " ".join(str(c) for c in mock_run.call_args[0][0])
        assert "16000" in cmd
        assert "pcm_s16le" in cmd

    def test_merge_uses_capture_output(self, transcriber, session_both, tmp_path):
        """ffmpeg is called with capture_output=True."""
        output = str(tmp_path / "combined.wav")
        with patch("src.transcriber.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            transcriber.merge_audio(
                str(session_both / "system.wav"),
                str(session_both / "mic.wav"),
                output,
            )
        kwargs = mock_run.call_args[1]
        assert kwargs.get("capture_output") is True


# =============================================================================
# Transcribe Pipeline (5 tests)
# =============================================================================


class TestTranscribe:
    @patch("src.transcriber.subprocess.run")
    def test_transcribe_json_success(self, mock_run, transcriber, session_both):
        """merge → whisper → .json → dict with text and segments returned."""
        import json as _json

        def run_side_effect(cmd, **kwargs):
            result = MagicMock(returncode=0, stderr="")
            cmd_str = " ".join(str(c) for c in cmd)
            if "mlx_whisper" in cmd_str:
                for i, arg in enumerate(cmd):
                    if str(arg) == "--output-dir" and i + 1 < len(cmd):
                        out_dir = Path(cmd[i + 1])
                        whisper_output = {
                            "text": "Привет, это тестовый транскрипт",
                            "segments": [
                                {"start": 0.0, "end": 2.5, "text": "Привет"},
                                {
                                    "start": 2.5,
                                    "end": 5.0,
                                    "text": "это тестовый транскрипт",
                                },
                            ],
                        }
                        (out_dir / "combined.json").write_text(
                            _json.dumps(whisper_output, ensure_ascii=False)
                        )
                        break
            return result

        mock_run.side_effect = run_side_effect
        result = transcriber.transcribe(str(session_both))

        assert isinstance(result, dict)
        assert "тестовый транскрипт" in result["text"]
        assert len(result["segments"]) == 2
        assert result["segments"][0]["start"] == 0.0
        assert result["segments"][0]["text"] == "Привет"
        assert (session_both / "transcript.txt").exists()

    @patch("src.transcriber.subprocess.run")
    def test_transcribe_json_saves_text(self, mock_run, transcriber, session_both):
        """JSON transcription saves plain text as transcript.txt."""
        import json as _json

        def run_side_effect(cmd, **kwargs):
            result = MagicMock(returncode=0, stderr="")
            cmd_str = " ".join(str(c) for c in cmd)
            if "mlx_whisper" in cmd_str:
                for i, arg in enumerate(cmd):
                    if str(arg) == "--output-dir" and i + 1 < len(cmd):
                        out_dir = Path(cmd[i + 1])
                        whisper_output = {
                            "text": "Saved text from JSON",
                            "segments": [
                                {
                                    "start": 0.0,
                                    "end": 1.0,
                                    "text": "Saved text from JSON",
                                }
                            ],
                        }
                        (out_dir / "combined.json").write_text(
                            _json.dumps(whisper_output, ensure_ascii=False)
                        )
                        break
            return result

        mock_run.side_effect = run_side_effect
        transcriber.transcribe(str(session_both))

        saved = (session_both / "transcript.txt").read_text()
        assert saved == "Saved text from JSON"

    @patch("src.transcriber.subprocess.run")
    def test_transcribe_txt_fallback(self, mock_run, transcriber, session_both):
        """Falls back to .txt when no JSON output."""

        def run_side_effect(cmd, **kwargs):
            result = MagicMock(returncode=0, stderr="")
            cmd_str = " ".join(str(c) for c in cmd)
            if "mlx_whisper" in cmd_str:
                for i, arg in enumerate(cmd):
                    if str(arg) == "--output-dir" and i + 1 < len(cmd):
                        out_dir = Path(cmd[i + 1])
                        (out_dir / "combined.txt").write_text("Fallback text only")
                        break
            return result

        mock_run.side_effect = run_side_effect
        result = transcriber.transcribe(str(session_both))

        assert isinstance(result, str)
        assert "Fallback text only" in result
        assert (session_both / "transcript.txt").exists()

    @patch("src.transcriber.subprocess.run")
    def test_transcribe_merge_failure(self, mock_run, transcriber, session_both):
        """ffmpeg fails → None returned."""
        mock_run.return_value = MagicMock(returncode=1, stderr="ffmpeg error")
        result = transcriber.transcribe(str(session_both))
        assert result is None

    @patch("src.transcriber.subprocess.run")
    def test_transcribe_whisper_failure(self, mock_run, transcriber, session_both):
        """Whisper fails (returncode != 0) → None."""
        call_count = [0]

        def run_side_effect(cmd, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return MagicMock(returncode=0, stderr="")  # ffmpeg OK
            return MagicMock(returncode=1, stderr="whisper error")  # whisper fails

        mock_run.side_effect = run_side_effect
        result = transcriber.transcribe(str(session_both))
        assert result is None

    @patch("src.transcriber.subprocess.run")
    def test_transcribe_fallback_glob(self, mock_run, transcriber, session_both):
        """If combined.txt doesn't exist, falls back to glob(*.txt)."""

        def run_side_effect(cmd, **kwargs):
            result = MagicMock(returncode=0, stderr="")
            cmd_str = " ".join(str(c) for c in cmd)
            if "mlx_whisper" in cmd_str:
                for i, arg in enumerate(cmd):
                    if str(arg) == "--output-dir" and i + 1 < len(cmd):
                        out_dir = Path(cmd[i + 1])
                        # Write with alternate name (not combined.txt)
                        (out_dir / "output.txt").write_text("Fallback transcript")
                        break
            return result

        mock_run.side_effect = run_side_effect
        result = transcriber.transcribe(str(session_both))
        assert result is not None
        assert "Fallback transcript" in result


# =============================================================================
# Transcriber Edge Cases (4 tests)
# =============================================================================


class TestTranscriberEdgeCases:
    def test_merge_nonexistent_paths(self, transcriber, tmp_path):
        """Paths that don't exist at all → False."""
        result = transcriber.merge_audio(
            str(tmp_path / "nonexistent_sys.wav"),
            str(tmp_path / "nonexistent_mic.wav"),
            str(tmp_path / "output.wav"),
        )
        assert result is False

    @patch("src.transcriber.subprocess.run")
    def test_transcribe_no_output_produced(self, mock_run, transcriber, session_both):
        """Whisper succeeds but produces no output files → None."""

        def run_side_effect(cmd, **kwargs):
            # Both commands succeed but whisper doesn't create output
            return MagicMock(returncode=0, stderr="")

        mock_run.side_effect = run_side_effect
        result = transcriber.transcribe(str(session_both))
        assert result is None

    @patch("src.transcriber.subprocess.run")
    def test_transcribe_empty_session_dir(self, mock_run, transcriber, session_empty):
        """Empty session dir → merge fails → None."""
        result = transcriber.transcribe(str(session_empty))
        assert result is None
        mock_run.assert_not_called()  # merge_audio returns False before subprocess

    @patch("src.transcriber.subprocess.run")
    def test_whisper_model_in_command(self, mock_run, transcriber, session_both):
        """Whisper command includes model, language, and json output format."""
        import json as _json

        def run_side_effect(cmd, **kwargs):
            result = MagicMock(returncode=0, stderr="")
            cmd_str = " ".join(str(c) for c in cmd)
            if "mlx_whisper" in cmd_str:
                for i, arg in enumerate(cmd):
                    if str(arg) == "--output-dir" and i + 1 < len(cmd):
                        out_dir = Path(cmd[i + 1])
                        (out_dir / "combined.json").write_text(
                            _json.dumps({"text": "Test", "segments": []})
                        )
                        break
            return result

        mock_run.side_effect = run_side_effect
        transcriber.transcribe(str(session_both))

        # Find the whisper call
        for call in mock_run.call_args_list:
            cmd_str = " ".join(str(c) for c in call[0][0])
            if "mlx_whisper" in cmd_str:
                assert "--model" in cmd_str
                assert "--language" in cmd_str
                assert "--output-format" in cmd_str
                assert "json" in cmd_str
                break

    @patch("src.transcriber.subprocess.run")
    def test_transcribe_json_fallback_on_bad_json(
        self, mock_run, transcriber, session_both
    ):
        """If JSON file is malformed, falls back to txt."""

        def run_side_effect(cmd, **kwargs):
            result = MagicMock(returncode=0, stderr="")
            cmd_str = " ".join(str(c) for c in cmd)
            if "mlx_whisper" in cmd_str:
                for i, arg in enumerate(cmd):
                    if str(arg) == "--output-dir" and i + 1 < len(cmd):
                        out_dir = Path(cmd[i + 1])
                        (out_dir / "combined.json").write_text("not valid json{{{")
                        (out_dir / "combined.txt").write_text("Fallback from bad json")
                        break
            return result

        mock_run.side_effect = run_side_effect
        result = transcriber.transcribe(str(session_both))

        assert isinstance(result, str)
        assert "Fallback from bad json" in result


# =============================================================================
# Diarization wiring in transcribe_separate
# =============================================================================


class TestMergeByTimestampSpeakers:
    def test_system_segments_keep_diarized_speaker(self, transcriber):
        """_merge_by_timestamp honours a per-segment speaker on system segments."""
        me = [{"start": 1.0, "end": 2.0, "text": "hi"}]
        others = [
            {"start": 0.0, "end": 1.0, "text": "a", "speaker": "SPEAKER_1"},
            {"start": 2.0, "end": 3.0, "text": "b", "speaker": "SPEAKER_2"},
        ]
        merged = transcriber._merge_by_timestamp(me, others)
        by_text = {m["text"]: m["speaker"] for m in merged}
        assert by_text["hi"] == "SPEAKER_ME"
        assert by_text["a"] == "SPEAKER_1"
        assert by_text["b"] == "SPEAKER_2"

    def test_system_segments_default_to_other(self, transcriber):
        """Without a speaker key, system segments fall back to SPEAKER_OTHER."""
        others = [{"start": 0.0, "end": 1.0, "text": "a"}]
        merged = transcriber._merge_by_timestamp([], others)
        assert merged[0]["speaker"] == "SPEAKER_OTHER"


class TestTranscribeSeparateDiarization:
    def _fake_whisper(self, mic_segs, sys_segs):
        """Return a _run_whisper stub keyed on the audio file name."""

        def _run(audio_path, output_dir):
            return mic_segs if "mic.wav" in str(audio_path) else sys_segs

        return _run

    def test_diarization_labels_propagate(self, transcriber, session_both):
        """diarize() output (SPEAKER_1/2) flows into merged segments and text."""
        mic_segs = [{"start": 5.0, "end": 6.0, "text": "me"}]
        sys_segs = [
            {"start": 0.0, "end": 2.0, "text": "one"},
            {"start": 2.0, "end": 4.0, "text": "two"},
        ]

        def fake_diarize(wav_path, segments, **kwargs):
            labels = ["SPEAKER_1", "SPEAKER_2"]
            return [{**s, "speaker": labels[i]} for i, s in enumerate(segments)]

        with (
            patch.object(
                transcriber,
                "_run_whisper",
                side_effect=self._fake_whisper(mic_segs, sys_segs),
            ),
            patch("src.transcriber.diarizer.diarize", side_effect=fake_diarize),
        ):
            result = transcriber.transcribe_separate(str(session_both))

        speakers = {s["speaker"] for s in result["segments"]}
        assert speakers == {"SPEAKER_ME", "SPEAKER_1", "SPEAKER_2"}
        assert "SPEAKER_1: one" in result["text"]
        assert "SPEAKER_2: two" in result["text"]

    def test_diarization_fallback_to_other(self, transcriber, session_both):
        """If diarize returns SPEAKER_OTHER, merged output uses SPEAKER_OTHER."""
        mic_segs = [{"start": 5.0, "end": 6.0, "text": "me"}]
        sys_segs = [{"start": 0.0, "end": 2.0, "text": "one"}]

        def fake_diarize(wav_path, segments, **kwargs):
            return [{**s, "speaker": "SPEAKER_OTHER"} for s in segments]

        with (
            patch.object(
                transcriber,
                "_run_whisper",
                side_effect=self._fake_whisper(mic_segs, sys_segs),
            ),
            patch("src.transcriber.diarizer.diarize", side_effect=fake_diarize),
        ):
            result = transcriber.transcribe_separate(str(session_both))

        speakers = {s["speaker"] for s in result["segments"]}
        assert speakers == {"SPEAKER_ME", "SPEAKER_OTHER"}

    def test_diarize_called_only_for_system(self, transcriber, session_mic_only):
        """Mic-only session: diarize is never called; output unchanged (SPEAKER_ME)."""
        mic_segs = [{"start": 0.0, "end": 1.0, "text": "solo"}]

        with (
            patch.object(
                transcriber,
                "_run_whisper",
                side_effect=self._fake_whisper(mic_segs, []),
            ),
            patch("src.transcriber.diarizer.diarize") as mock_diar,
        ):
            result = transcriber.transcribe_separate(str(session_mic_only))

        mock_diar.assert_not_called()
        assert {s["speaker"] for s in result["segments"]} == {"SPEAKER_ME"}


# =============================================================================
# Night build A: merge fragmented same-speaker turns (IE-expert spec)
# =============================================================================

from src.transcriber import Transcriber


class TestMergeTurns:
    def _seg(self, start, end, text, speaker="SPEAKER_ME"):
        return {"start": start, "end": end, "text": text, "speaker": speaker}

    def test_fragmented_promise_merges_into_one_turn(self):
        segs = [
            self._seg(10.0, 11.2, "я тогда"),
            self._seg(11.5, 12.8, "пришлю договор"),
            self._seg(13.0, 14.1, "в пятницу"),
        ]
        out = Transcriber._merge_turns(segs)
        assert len(out) == 1
        assert out[0]["text"] == "я тогда пришлю договор в пятницу"
        assert out[0]["start"] == 10.0
        assert out[0]["end"] == 14.1

    def test_long_pause_splits_turns(self):
        segs = [
            self._seg(10.0, 11.0, "первая мысль"),
            self._seg(14.0, 15.0, "вторая мысль"),
        ]
        out = Transcriber._merge_turns(segs)
        assert len(out) == 2

    def test_speaker_change_never_merges(self):
        segs = [
            self._seg(10.0, 11.0, "вопрос", "SPEAKER_1"),
            self._seg(11.2, 12.0, "ответ", "SPEAKER_ME"),
        ]
        out = Transcriber._merge_turns(segs)
        assert len(out) == 2

    def test_word_cap_limits_turn(self):
        segs = [
            self._seg(10.0 + i, 10.5 + i, "слово " * 15) for i in range(5)
        ]
        out = Transcriber._merge_turns(segs)
        assert len(out) >= 2
        assert all(len(t["text"].split()) <= 45 for t in out)
