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
    def test_transcribe_success(self, mock_run, transcriber, session_both):
        """merge → whisper → .txt → transcript text returned."""

        def run_side_effect(cmd, **kwargs):
            result = MagicMock(returncode=0, stderr="")
            cmd_str = " ".join(str(c) for c in cmd)
            if "mlx_whisper" in cmd_str:
                for i, arg in enumerate(cmd):
                    if str(arg) == "--output-dir" and i + 1 < len(cmd):
                        out_dir = Path(cmd[i + 1])
                        (out_dir / "combined.txt").write_text(
                            "Привет, это тестовый транскрипт"
                        )
                        break
            return result

        mock_run.side_effect = run_side_effect
        result = transcriber.transcribe(str(session_both))

        assert result is not None
        assert "тестовый транскрипт" in result
        assert (session_both / "transcript.txt").exists()

    @patch("src.transcriber.subprocess.run")
    def test_transcribe_saves_to_file(self, mock_run, transcriber, session_both):
        """Transcript is saved as transcript.txt in session dir."""

        def run_side_effect(cmd, **kwargs):
            result = MagicMock(returncode=0, stderr="")
            cmd_str = " ".join(str(c) for c in cmd)
            if "mlx_whisper" in cmd_str:
                for i, arg in enumerate(cmd):
                    if str(arg) == "--output-dir" and i + 1 < len(cmd):
                        out_dir = Path(cmd[i + 1])
                        (out_dir / "combined.txt").write_text("Saved text")
                        break
            return result

        mock_run.side_effect = run_side_effect
        transcriber.transcribe(str(session_both))

        saved = (session_both / "transcript.txt").read_text()
        assert saved == "Saved text"

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
    def test_transcribe_no_txt_produced(self, mock_run, transcriber, session_both):
        """Whisper succeeds but produces no .txt file → None."""

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
        """Whisper command includes model and language settings."""

        def run_side_effect(cmd, **kwargs):
            result = MagicMock(returncode=0, stderr="")
            cmd_str = " ".join(str(c) for c in cmd)
            if "mlx_whisper" in cmd_str:
                for i, arg in enumerate(cmd):
                    if str(arg) == "--output-dir" and i + 1 < len(cmd):
                        out_dir = Path(cmd[i + 1])
                        (out_dir / "combined.txt").write_text("Test")
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
                break
