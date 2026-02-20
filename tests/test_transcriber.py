"""Tests for src.transcriber — mock subprocess.run."""

from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

from src.transcriber import Transcriber


def _wav_header_bytes(size=100):
    """Create minimal bytes larger than WAV header (44 bytes)."""
    return b"\x00" * size


@pytest.fixture
def transcriber():
    return Transcriber()


@pytest.fixture
def session_with_both(tmp_path):
    """Session dir with both system.wav and mic.wav."""
    d = tmp_path / "session"
    d.mkdir()
    (d / "system.wav").write_bytes(_wav_header_bytes())
    (d / "mic.wav").write_bytes(_wav_header_bytes())
    return d


@pytest.fixture
def session_system_only(tmp_path):
    """Session dir with only system.wav."""
    d = tmp_path / "session"
    d.mkdir()
    (d / "system.wav").write_bytes(_wav_header_bytes())
    return d


@pytest.fixture
def session_empty(tmp_path):
    """Session dir with no audio files."""
    d = tmp_path / "session"
    d.mkdir()
    return d


import pytest


class TestMergeAudio:
    def test_merge_both_files(self, transcriber, session_with_both, tmp_path):
        """system.wav + mic.wav → ffmpeg amix command."""
        output = str(tmp_path / "combined.wav")
        with patch("src.transcriber.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = transcriber.merge_audio(
                str(session_with_both / "system.wav"),
                str(session_with_both / "mic.wav"),
                output,
            )
        assert result is True
        cmd = mock_run.call_args[0][0]
        assert "amix" in " ".join(cmd)

    def test_merge_system_only(self, transcriber, session_system_only, tmp_path):
        """mic absent → single-input conversion."""
        output = str(tmp_path / "combined.wav")
        with patch("src.transcriber.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = transcriber.merge_audio(
                str(session_system_only / "system.wav"),
                str(session_system_only / "mic.wav"),
                output,
            )
        assert result is True
        cmd = mock_run.call_args[0][0]
        assert "amix" not in " ".join(cmd)

    def test_merge_no_files(self, transcriber, session_empty, tmp_path):
        """No audio files → False."""
        output = str(tmp_path / "combined.wav")
        result = transcriber.merge_audio(
            str(session_empty / "system.wav"),
            str(session_empty / "mic.wav"),
            output,
        )
        assert result is False


class TestTranscribe:
    @patch("src.transcriber.subprocess.run")
    def test_transcribe_success(self, mock_run, transcriber, session_with_both):
        """merge → whisper → .txt → transcript text."""

        # ffmpeg merge succeeds
        # mlx_whisper succeeds and creates a txt file
        def run_side_effect(cmd, **kwargs):
            result = MagicMock(returncode=0, stderr="")
            # When mlx_whisper runs, create the output txt in its --output-dir
            if "mlx_whisper" in str(cmd[0]) or "mlx_whisper" in " ".join(
                str(c) for c in cmd
            ):
                # Find --output-dir in cmd
                for i, arg in enumerate(cmd):
                    if str(arg) == "--output-dir" and i + 1 < len(cmd):
                        out_dir = Path(cmd[i + 1])
                        (out_dir / "combined.txt").write_text(
                            "Привет, это тестовый транскрипт"
                        )
                        break
            return result

        mock_run.side_effect = run_side_effect
        result = transcriber.transcribe(str(session_with_both))

        assert result is not None
        assert "тестовый транскрипт" in result
        # transcript.txt should be saved alongside recordings
        assert (session_with_both / "transcript.txt").exists()

    @patch("src.transcriber.subprocess.run")
    def test_transcribe_merge_failure(self, mock_run, transcriber, session_with_both):
        """ffmpeg fails → None."""
        mock_run.return_value = MagicMock(returncode=1, stderr="ffmpeg error")
        result = transcriber.transcribe(str(session_with_both))
        assert result is None
