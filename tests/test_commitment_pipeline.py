"""End-to-end integration tests for the commitment extraction pipeline.

Tests the FULL flow:
    mic.wav -> whisper -> SPEAKER_ME
    system.wav -> whisper -> SPEAKER_OTHER
    merge by timestamp -> resolve_speakers (Ollama)
    extract_commitments (Karpathy -> Murati -> empty list)
    save to SQLite commitments table

Focus: cross-module integration (speaker_resolver + commitment_extractor + database),
daemon.process_recording flow, retry chain, chunking, deduplication, graceful degradation.
"""

import json
from unittest.mock import patch, MagicMock

import pytest

from src.commitment_extractor import extract_commitments
from src.database import Database
from src.daemon import process_recording
from src.speaker_resolver import resolve_speakers, format_transcript_for_prompt


# =============================================================================
# Shared fixtures & helpers
# =============================================================================


def _mock_ollama_response(content: str, thinking: str = ""):
    """Create a mock urlopen response matching Ollama /api/chat format."""
    body = json.dumps(
        {
            "message": {
                "role": "assistant",
                "content": content,
                "thinking": thinking,
            },
        }
    ).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


# --- Realistic Russian transcript with clear commitments ---

REALISTIC_SEGMENTS = [
    {
        "start": 0.0,
        "end": 3.5,
        "text": "Добрый день, это Алексей из отдела продаж.",
        "speaker": "SPEAKER_ME",
    },
    {
        "start": 4.0,
        "end": 7.0,
        "text": "Здравствуйте, Алексей! Это Елена Викторовна, рада вас слышать.",
        "speaker": "SPEAKER_OTHER",
    },
    {
        "start": 8.0,
        "end": 15.0,
        "text": "Елена Викторовна, я звоню по поводу нашего контракта. Хотел обсудить сроки и условия.",
        "speaker": "SPEAKER_ME",
    },
    {
        "start": 16.0,
        "end": 22.0,
        "text": "Да, конечно. Я уже подготовила черновик. Могу отправить вам сегодня.",
        "speaker": "SPEAKER_OTHER",
    },
    {
        "start": 23.0,
        "end": 30.0,
        "text": "Отлично. Я отправлю отчёт к пятнице, как мы договаривались на прошлой неделе.",
        "speaker": "SPEAKER_ME",
    },
    {
        "start": 31.0,
        "end": 38.0,
        "text": "Хорошо. А я пришлю вам финальную версию контракта завтра до конца дня.",
        "speaker": "SPEAKER_OTHER",
    },
    {
        "start": 39.0,
        "end": 44.0,
        "text": "Договорились. Также мне нужно согласовать бюджет с руководством до среды.",
        "speaker": "SPEAKER_ME",
    },
    {
        "start": 45.0,
        "end": 50.0,
        "text": "Понятно. Тогда я подготовлю презентацию для вашего руководства к четвергу.",
        "speaker": "SPEAKER_OTHER",
    },
    {
        "start": 51.0,
        "end": 55.0,
        "text": "Спасибо, Елена Викторовна. До связи!",
        "speaker": "SPEAKER_ME",
    },
    {
        "start": 55.5,
        "end": 58.0,
        "text": "До свидания, Алексей!",
        "speaker": "SPEAKER_OTHER",
    },
]

SPEAKER_MAP_RESOLVED = {
    "SPEAKER_ME": {"confirmed": True, "source": "mic_channel"},
    "SPEAKER_OTHER": {
        "name": "Елена Викторовна",
        "confidence": 0.95,
        "source": "self_introduction",
        "evidence": "Это Елена Викторовна, рада вас слышать.",
    },
}

SPEAKER_RESOLUTION_OLLAMA_RESPONSE = json.dumps(
    {
        "speaker_map": SPEAKER_MAP_RESOLVED,
        "resolution_notes": "SPEAKER_OTHER identified via self-introduction.",
    }
)

# --- Karpathy-format commitments (prompt 3) ---

KARPATHY_COMMITMENTS_RESPONSE = json.dumps(
    {
        "commitments": [
            {
                "id": 1,
                "type": "outgoing",
                "who": "SPEAKER_ME",
                "who_name": None,
                "to_whom": "SPEAKER_OTHER",
                "to_whom_name": "Елена Викторовна",
                "what": "Отправить отчёт",
                "deadline": "к пятнице",
                "quote": "Я отправлю отчёт к пятнице, как мы договаривались",
                "timestamp": "00:00:23",
                "uncertain": False,
            },
            {
                "id": 2,
                "type": "incoming",
                "who": "SPEAKER_OTHER",
                "who_name": "Елена Викторовна",
                "to_whom": "SPEAKER_ME",
                "to_whom_name": None,
                "what": "Прислать финальную версию контракта",
                "deadline": "завтра до конца дня",
                "quote": "Я пришлю вам финальную версию контракта завтра до конца дня",
                "timestamp": "00:00:31",
                "uncertain": False,
            },
            {
                "id": 3,
                "type": "outgoing",
                "who": "SPEAKER_ME",
                "who_name": None,
                "to_whom": "SPEAKER_OTHER",
                "to_whom_name": "Елена Викторовна",
                "what": "Согласовать бюджет с руководством",
                "deadline": "до среды",
                "quote": "Мне нужно согласовать бюджет с руководством до среды",
                "timestamp": "00:00:39",
                "uncertain": False,
            },
            {
                "id": 4,
                "type": "incoming",
                "who": "SPEAKER_OTHER",
                "who_name": "Елена Викторовна",
                "to_whom": "SPEAKER_ME",
                "to_whom_name": None,
                "what": "Подготовить презентацию для руководства",
                "deadline": "к четвергу",
                "quote": "Я подготовлю презентацию для вашего руководства к четвергу",
                "timestamp": "00:00:45",
                "uncertain": False,
            },
        ]
    }
)

# --- Murati-format commitments (prompt 1, used as fallback) ---

MURATI_COMMITMENTS_RESPONSE = json.dumps(
    {
        "commitments": [
            {
                "id": 1,
                "direction": "outgoing",
                "committer_label": "SPEAKER_ME",
                "committer_name": None,
                "recipient_label": "SPEAKER_OTHER",
                "recipient_name": "Елена Викторовна",
                "commitment_text": "Отправить отчёт",
                "verbatim_quote": "Я отправлю отчёт к пятнице",
                "timestamp": "00:00:23",
                "deadline_raw": "к пятнице",
                "deadline_type": "relative_week",
                "commitment_confidence": 0.95,
                "conditional": False,
                "condition_text": None,
            },
            {
                "id": 2,
                "direction": "incoming",
                "committer_label": "SPEAKER_OTHER",
                "committer_name": "Елена Викторовна",
                "recipient_label": "SPEAKER_ME",
                "recipient_name": None,
                "commitment_text": "Прислать финальную версию контракта",
                "verbatim_quote": "Я пришлю вам финальную версию контракта завтра до конца дня",
                "timestamp": "00:00:31",
                "deadline_raw": "завтра до конца дня",
                "deadline_type": "relative_day",
                "commitment_confidence": 0.92,
                "conditional": False,
                "condition_text": None,
            },
        ],
        "extraction_notes": "",
    }
)


@pytest.fixture
def pipeline_db(tmp_path):
    """Clean database on a temp path for pipeline tests."""
    return Database(db_path=tmp_path / "pipeline_test.db")


@pytest.fixture
def pipeline_session(tmp_path):
    """Session dict as returned by recorder.stop(), for pipeline integration."""
    session_dir = tmp_path / "20260220_150000"
    session_dir.mkdir()
    return {
        "session_id": "20260220_150000",
        "app_name": "Zoom",
        "started_at": "2026-02-20T15:00:00",
        "ended_at": "2026-02-20T15:58:00",
        "duration_seconds": 3480.0,
        "session_dir": str(session_dir),
        "system_wav": str(session_dir / "system.wav"),
        "mic_wav": str(session_dir / "mic.wav"),
    }


def _make_separate_result(segments=None, text=None):
    """Build a transcribe_separate() return value from segments."""
    if segments is None:
        segments = REALISTIC_SEGMENTS
    if text is None:
        text = " ".join(seg["text"] for seg in segments)
    return {
        "text": text,
        "segments": segments,
        "transcript_me": [s for s in segments if s["speaker"] == "SPEAKER_ME"],
        "transcript_others": [s for s in segments if s["speaker"] != "SPEAKER_ME"],
    }


# =============================================================================
# 1. Full end-to-end pipeline: segments -> speakers -> commitments -> SQLite
# =============================================================================


class TestFullPipeline:
    """Integration across resolve_speakers + format_transcript + extract_commitments + DB.

    These tests mock urllib.request.urlopen with side_effect to serve
    sequential Ollama responses: first for speaker resolution, then for
    commitment extraction.
    """

    @patch("src.speaker_resolver.urllib.request.urlopen")
    def test_segments_to_commitments_in_sqlite(self, mock_urlopen, pipeline_db):
        """Full flow: segments -> resolve_speakers -> format_transcript ->
        extract_commitments -> insert_commitments -> verify in SQLite."""
        session_id = "e2e_full_001"

        # Step 1: Insert a parent call record (required for FK)
        pipeline_db.insert_call(
            session_id=session_id,
            app_name="Zoom",
            started_at="2026-02-20T15:00:00",
            ended_at="2026-02-20T15:58:00",
            duration_seconds=3480.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript="placeholder",
            summary=None,
        )

        # Step 2: Speaker resolution (first urlopen call)
        mock_urlopen.return_value = _mock_ollama_response(
            SPEAKER_RESOLUTION_OLLAMA_RESPONSE
        )
        speaker_map = resolve_speakers(REALISTIC_SEGMENTS)

        assert speaker_map["SPEAKER_ME"]["confirmed"] is True
        assert speaker_map["SPEAKER_OTHER"]["name"] == "Елена Викторовна"
        assert speaker_map["SPEAKER_OTHER"]["confidence"] == 0.95

        # Step 3: Format transcript with resolved names
        resolved_transcript = format_transcript_for_prompt(
            REALISTIC_SEGMENTS, speaker_map
        )
        assert "SPEAKER_OTHER (Елена Викторовна, conf=0.95)" in resolved_transcript
        assert "Я отправлю отчёт к пятнице" in resolved_transcript

        # Step 4: Extract commitments (Karpathy succeeds on first attempt)
        # Switch the mock for the commitment extractor calls
        with patch("src.commitment_extractor.urllib.request.urlopen") as mock_ext:
            mock_ext.return_value = _mock_ollama_response(KARPATHY_COMMITMENTS_RESPONSE)
            commitments_data = extract_commitments(
                resolved_transcript, speaker_map, "2026-02-20"
            )

        assert len(commitments_data["commitments"]) == 4

        # Step 5: Save to database
        pipeline_db.insert_commitments(session_id, commitments_data["commitments"])

        # Step 6: Verify in SQLite
        rows = pipeline_db.get_commitments(session_id)
        assert len(rows) == 4

        # Verify outgoing commitment fields
        outgoing = [r for r in rows if r["direction"] == "outgoing"]
        assert len(outgoing) == 2

        report_commitment = next(r for r in outgoing if "отчёт" in r["text"])
        assert report_commitment["who_label"] == "SPEAKER_ME"
        assert report_commitment["to_name"] == "Елена Викторовна"
        assert report_commitment["deadline_raw"] == "к пятнице"
        assert report_commitment["status"] == "open"
        assert report_commitment["uncertain"] == 0

        # Verify incoming commitment fields
        incoming = [r for r in rows if r["direction"] == "incoming"]
        assert len(incoming) == 2

        contract_commitment = next(r for r in incoming if "контракт" in r["text"])
        assert contract_commitment["who_label"] == "SPEAKER_OTHER"
        assert contract_commitment["who_name"] == "Елена Викторовна"
        assert contract_commitment["deadline_raw"] == "завтра до конца дня"
        assert contract_commitment["status"] == "open"

    @patch("src.speaker_resolver.urllib.request.urlopen")
    def test_commitment_counts_after_pipeline(self, mock_urlopen, pipeline_db):
        """After pipeline, get_commitment_counts returns correct outgoing/incoming."""
        session_id = "e2e_counts_001"
        pipeline_db.insert_call(
            session_id=session_id,
            app_name="Google Meet",
            started_at="2026-02-20T16:00:00",
            ended_at="2026-02-20T16:45:00",
            duration_seconds=2700.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript="placeholder",
            summary=None,
        )

        mock_urlopen.return_value = _mock_ollama_response(
            SPEAKER_RESOLUTION_OLLAMA_RESPONSE
        )
        speaker_map = resolve_speakers(REALISTIC_SEGMENTS)

        resolved_transcript = format_transcript_for_prompt(
            REALISTIC_SEGMENTS, speaker_map
        )

        with patch("src.commitment_extractor.urllib.request.urlopen") as mock_ext:
            mock_ext.return_value = _mock_ollama_response(KARPATHY_COMMITMENTS_RESPONSE)
            commitments_data = extract_commitments(
                resolved_transcript, speaker_map, "2026-02-20"
            )
        pipeline_db.insert_commitments(session_id, commitments_data["commitments"])

        counts = pipeline_db.get_commitment_counts()
        assert counts["outgoing"] == 2
        assert counts["incoming"] == 2

    @patch("src.speaker_resolver.urllib.request.urlopen")
    def test_open_commitments_query_after_pipeline(self, mock_urlopen, pipeline_db):
        """get_open_commitments returns commitments with call metadata."""
        session_id = "e2e_open_001"
        pipeline_db.insert_call(
            session_id=session_id,
            app_name="Telegram",
            started_at="2026-02-20T17:00:00",
            ended_at="2026-02-20T17:30:00",
            duration_seconds=1800.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript="placeholder",
            summary=None,
        )

        mock_urlopen.return_value = _mock_ollama_response(
            SPEAKER_RESOLUTION_OLLAMA_RESPONSE
        )
        speaker_map = resolve_speakers(REALISTIC_SEGMENTS)
        resolved_transcript = format_transcript_for_prompt(
            REALISTIC_SEGMENTS, speaker_map
        )

        with patch("src.commitment_extractor.urllib.request.urlopen") as mock_ext:
            mock_ext.return_value = _mock_ollama_response(KARPATHY_COMMITMENTS_RESPONSE)
            commitments_data = extract_commitments(
                resolved_transcript, speaker_map, "2026-02-20"
            )
        pipeline_db.insert_commitments(session_id, commitments_data["commitments"])

        # Query open incoming commitments
        open_incoming = pipeline_db.get_open_commitments(direction="incoming")
        assert len(open_incoming) == 2
        assert all(c["app_name"] == "Telegram" for c in open_incoming)
        assert all(c["started_at"] == "2026-02-20T17:00:00" for c in open_incoming)

        # Mark one as done, verify count drops
        cid = open_incoming[0]["id"]
        pipeline_db.update_commitment_status(cid, "done", "2026-02-21T10:00:00")
        open_incoming_after = pipeline_db.get_open_commitments(direction="incoming")
        assert len(open_incoming_after) == 1


# =============================================================================
# 2. Retry chain: Karpathy fails -> Murati succeeds
# =============================================================================


class TestRetryChain:
    """Test the Karpathy -> Murati fallback within the full pipeline."""

    @patch("src.commitment_extractor.urllib.request.urlopen")
    def test_karpathy_invalid_json_falls_back_to_murati(
        self, mock_urlopen, pipeline_db
    ):
        """Karpathy returns garbage JSON, Murati succeeds -> commitments saved."""
        session_id = "retry_001"
        pipeline_db.insert_call(
            session_id=session_id,
            app_name="Zoom",
            started_at="2026-02-20T10:00:00",
            ended_at="2026-02-20T10:30:00",
            duration_seconds=1800.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript="placeholder",
            summary=None,
        )

        # First call (Karpathy) returns invalid, second (Murati) returns valid
        mock_urlopen.side_effect = [
            _mock_ollama_response("This is not valid JSON at all {{{"),
            _mock_ollama_response(MURATI_COMMITMENTS_RESPONSE),
        ]

        resolved_transcript = format_transcript_for_prompt(
            REALISTIC_SEGMENTS, SPEAKER_MAP_RESOLVED
        )
        commitments_data = extract_commitments(
            resolved_transcript, SPEAKER_MAP_RESOLVED, "2026-02-20"
        )

        # Murati format used -> "direction" field present
        assert len(commitments_data["commitments"]) == 2
        assert commitments_data["commitments"][0]["direction"] == "outgoing"

        # Save to DB and verify normalization from Murati format
        pipeline_db.insert_commitments(session_id, commitments_data["commitments"])
        rows = pipeline_db.get_commitments(session_id)
        assert len(rows) == 2

        outgoing = next(r for r in rows if r["direction"] == "outgoing")
        assert outgoing["who_label"] == "SPEAKER_ME"
        assert outgoing["text"] == "Отправить отчёт"
        assert outgoing["deadline_raw"] == "к пятнице"
        assert outgoing["deadline_type"] == "relative_week"

        incoming = next(r for r in rows if r["direction"] == "incoming")
        assert incoming["who_label"] == "SPEAKER_OTHER"
        assert incoming["who_name"] == "Елена Викторовна"
        assert incoming["text"] == "Прислать финальную версию контракта"
        assert incoming["deadline_raw"] == "завтра до конца дня"
        assert incoming["deadline_type"] == "relative_day"

    @patch("src.commitment_extractor.urllib.request.urlopen")
    def test_both_prompts_fail_returns_empty_list(self, mock_urlopen, pipeline_db):
        """Both Karpathy and Murati produce invalid JSON -> empty commitments, no crash."""
        session_id = "retry_002"
        pipeline_db.insert_call(
            session_id=session_id,
            app_name="Zoom",
            started_at="2026-02-20T10:00:00",
            ended_at="2026-02-20T10:30:00",
            duration_seconds=1800.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript="placeholder",
            summary=None,
        )

        mock_urlopen.return_value = _mock_ollama_response(
            "Sorry, I cannot parse this transcript properly. Here are some thoughts..."
        )

        resolved_transcript = format_transcript_for_prompt(
            REALISTIC_SEGMENTS, SPEAKER_MAP_RESOLVED
        )
        commitments_data = extract_commitments(
            resolved_transcript, SPEAKER_MAP_RESOLVED, "2026-02-20"
        )

        assert commitments_data["commitments"] == []
        assert "extraction_notes" in commitments_data

        # Saving empty list should be a no-op
        pipeline_db.insert_commitments(session_id, commitments_data["commitments"])
        rows = pipeline_db.get_commitments(session_id)
        assert rows == []

    @patch("src.commitment_extractor.urllib.request.urlopen")
    def test_karpathy_returns_think_block_then_valid_json(
        self, mock_urlopen, pipeline_db
    ):
        """Karpathy response has <think> block leaked into content -> still parses."""
        session_id = "retry_003"
        pipeline_db.insert_call(
            session_id=session_id,
            app_name="Zoom",
            started_at="2026-02-20T10:00:00",
            ended_at="2026-02-20T10:30:00",
            duration_seconds=1800.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript="placeholder",
            summary=None,
        )

        response_with_think = (
            "<think>Let me analyze this transcript carefully...</think>\n"
            + KARPATHY_COMMITMENTS_RESPONSE
        )
        mock_urlopen.return_value = _mock_ollama_response(response_with_think)

        resolved_transcript = format_transcript_for_prompt(
            REALISTIC_SEGMENTS, SPEAKER_MAP_RESOLVED
        )
        commitments_data = extract_commitments(
            resolved_transcript, SPEAKER_MAP_RESOLVED, "2026-02-20"
        )

        assert len(commitments_data["commitments"]) == 4

        pipeline_db.insert_commitments(session_id, commitments_data["commitments"])
        rows = pipeline_db.get_commitments(session_id)
        assert len(rows) == 4


# =============================================================================
# 3. Chunking: long transcript splits and deduplicates
# =============================================================================


class TestChunkingPipeline:
    """Test chunking for transcripts >25K chars with deduplication in DB."""

    def _make_long_resolved_transcript(self, chars: int = 60000) -> str:
        """Create a resolved-format transcript longer than CHUNK_MAX_CHARS."""
        line = (
            "[00:01:23] SPEAKER_ME: Это длинная строка транскрипта для тестирования "
            "чанкинга в системе извлечения обязательств.\n"
            "[00:01:30] SPEAKER_OTHER (Елена Викторовна, conf=0.95): Да, согласна, "
            "продолжаем обсуждение.\n"
        )
        repeats = chars // len(line) + 1
        return line * repeats

    @patch("src.commitment_extractor.urllib.request.urlopen")
    def test_long_transcript_chunked_and_saved(self, mock_urlopen, pipeline_db):
        """60K transcript splits into chunks, each extracted, merged, saved to DB."""
        session_id = "chunk_001"
        pipeline_db.insert_call(
            session_id=session_id,
            app_name="Zoom",
            started_at="2026-02-20T10:00:00",
            ended_at="2026-02-20T11:00:00",
            duration_seconds=3600.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript="placeholder",
            summary=None,
        )

        # Each chunk returns unique commitments
        chunk1_resp = json.dumps(
            {
                "commitments": [
                    {
                        "id": 1,
                        "type": "outgoing",
                        "who": "SPEAKER_ME",
                        "who_name": None,
                        "to_whom": "SPEAKER_OTHER",
                        "to_whom_name": "Елена Викторовна",
                        "what": "Подготовить техническое задание",
                        "deadline": "к понедельнику",
                        "quote": "Я подготовлю ТЗ к понедельнику",
                        "timestamp": "00:05:00",
                        "uncertain": False,
                    }
                ]
            }
        )
        chunk2_resp = json.dumps(
            {
                "commitments": [
                    {
                        "id": 1,
                        "type": "incoming",
                        "who": "SPEAKER_OTHER",
                        "who_name": "Елена Викторовна",
                        "to_whom": "SPEAKER_ME",
                        "to_whom_name": None,
                        "what": "Провести ревью кода",
                        "deadline": "до пятницы",
                        "quote": "Я проведу ревью до пятницы",
                        "timestamp": "00:20:00",
                        "uncertain": False,
                    }
                ]
            }
        )
        chunk3_resp = json.dumps(
            {
                "commitments": [
                    {
                        "id": 1,
                        "type": "outgoing",
                        "who": "SPEAKER_ME",
                        "who_name": None,
                        "to_whom": "SPEAKER_OTHER",
                        "to_whom_name": "Елена Викторовна",
                        "what": "Обновить документацию",
                        "deadline": None,
                        "quote": "Я обновлю документацию",
                        "timestamp": "00:40:00",
                        "uncertain": False,
                    }
                ]
            }
        )

        mock_urlopen.side_effect = [
            _mock_ollama_response(chunk1_resp),
            _mock_ollama_response(chunk2_resp),
            _mock_ollama_response(chunk3_resp),
        ]

        transcript = self._make_long_resolved_transcript(60000)
        commitments_data = extract_commitments(
            transcript, SPEAKER_MAP_RESOLVED, "2026-02-20"
        )

        assert "_chunks" in commitments_data
        assert commitments_data["_chunks"] >= 2
        assert len(commitments_data["commitments"]) == 3

        # IDs are sequential after merge
        ids = [c["id"] for c in commitments_data["commitments"]]
        assert ids == [1, 2, 3]

        # Save and verify all 3 in DB
        pipeline_db.insert_commitments(session_id, commitments_data["commitments"])
        rows = pipeline_db.get_commitments(session_id)
        assert len(rows) == 3

        texts = {r["text"] for r in rows}
        assert "Подготовить техническое задание" in texts
        assert "Провести ревью кода" in texts
        assert "Обновить документацию" in texts

    @patch("src.commitment_extractor.urllib.request.urlopen")
    def test_chunking_deduplicates_overlapping_commitments(
        self, mock_urlopen, pipeline_db
    ):
        """Same commitment in overlapping chunks is deduplicated before saving."""
        session_id = "chunk_dedup_001"
        pipeline_db.insert_call(
            session_id=session_id,
            app_name="Zoom",
            started_at="2026-02-20T10:00:00",
            ended_at="2026-02-20T11:00:00",
            duration_seconds=3600.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript="placeholder",
            summary=None,
        )

        # Both chunks return the SAME commitment (from overlapping region)
        identical_commitment = {
            "id": 1,
            "type": "outgoing",
            "who": "SPEAKER_ME",
            "who_name": None,
            "to_whom": "SPEAKER_OTHER",
            "to_whom_name": "Елена Викторовна",
            "what": "Отправить отчёт",
            "deadline": "к пятнице",
            "quote": "Я отправлю отчёт к пятнице",
            "timestamp": "00:23:00",
            "uncertain": False,
        }

        chunk_resp = json.dumps({"commitments": [identical_commitment]})
        # Each chunk call returns the same commitment
        mock_urlopen.return_value = _mock_ollama_response(chunk_resp)

        transcript = self._make_long_resolved_transcript(60000)
        commitments_data = extract_commitments(
            transcript, SPEAKER_MAP_RESOLVED, "2026-02-20"
        )

        # Should be deduplicated to 1
        assert len(commitments_data["commitments"]) == 1

        pipeline_db.insert_commitments(session_id, commitments_data["commitments"])
        rows = pipeline_db.get_commitments(session_id)
        assert len(rows) == 1
        assert rows[0]["text"] == "Отправить отчёт"

    @patch("src.commitment_extractor.urllib.request.urlopen")
    def test_one_chunk_fails_others_succeed(self, mock_urlopen, pipeline_db):
        """If one chunk fails extraction, others still produce commitments."""
        session_id = "chunk_partial_001"
        pipeline_db.insert_call(
            session_id=session_id,
            app_name="Zoom",
            started_at="2026-02-20T10:00:00",
            ended_at="2026-02-20T11:00:00",
            duration_seconds=3600.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript="placeholder",
            summary=None,
        )

        good_resp = json.dumps(
            {
                "commitments": [
                    {
                        "id": 1,
                        "type": "outgoing",
                        "who": "SPEAKER_ME",
                        "who_name": None,
                        "to_whom": "SPEAKER_OTHER",
                        "to_whom_name": None,
                        "what": "Отправить документ",
                        "deadline": "завтра",
                        "quote": "Я отправлю завтра",
                        "timestamp": "00:10:00",
                        "uncertain": False,
                    }
                ]
            }
        )

        # Chunk 1: Karpathy invalid, Murati invalid (both fail -> empty)
        # Chunk 2: Karpathy succeeds
        # Chunk 3: Karpathy succeeds
        mock_urlopen.side_effect = [
            # Chunk 1 — Karpathy fails
            _mock_ollama_response("not json"),
            # Chunk 1 — Murati fails
            _mock_ollama_response("still not json"),
            # Chunk 2 — Karpathy succeeds
            _mock_ollama_response(good_resp),
            # Chunk 3 — Karpathy succeeds (different commitment to avoid dedup)
            _mock_ollama_response(
                json.dumps(
                    {
                        "commitments": [
                            {
                                "id": 1,
                                "type": "incoming",
                                "who": "SPEAKER_OTHER",
                                "who_name": None,
                                "to_whom": "SPEAKER_ME",
                                "to_whom_name": None,
                                "what": "Прислать отзыв",
                                "deadline": "до вечера",
                                "quote": "Пришлю отзыв до вечера",
                                "timestamp": "00:35:00",
                                "uncertain": False,
                            }
                        ]
                    }
                )
            ),
        ]

        transcript = self._make_long_resolved_transcript(60000)
        commitments_data = extract_commitments(
            transcript, SPEAKER_MAP_RESOLVED, "2026-02-20"
        )

        # Chunk 1 produced 0, chunks 2 and 3 produced 1 each
        assert len(commitments_data["commitments"]) == 2

        pipeline_db.insert_commitments(session_id, commitments_data["commitments"])
        rows = pipeline_db.get_commitments(session_id)
        assert len(rows) == 2


# =============================================================================
# 4. Graceful degradation: pipeline never blocks
# =============================================================================


class TestGracefulDegradation:
    """Test that the pipeline always returns rather than hanging or crashing."""

    @patch("src.commitment_extractor.urllib.request.urlopen")
    def test_ollama_unreachable_returns_empty(self, mock_urlopen, pipeline_db):
        """Ollama connection refused -> empty commitments, no exception."""
        from urllib.error import URLError

        mock_urlopen.side_effect = URLError("Connection refused")

        resolved_transcript = format_transcript_for_prompt(
            REALISTIC_SEGMENTS, SPEAKER_MAP_RESOLVED
        )
        commitments_data = extract_commitments(
            resolved_transcript, SPEAKER_MAP_RESOLVED, "2026-02-20"
        )

        assert commitments_data["commitments"] == []
        assert "unavailable" in commitments_data.get("extraction_notes", "").lower()

    @patch("src.commitment_extractor.urllib.request.urlopen")
    def test_ollama_timeout_returns_empty(self, mock_urlopen, pipeline_db):
        """Ollama times out -> empty commitments, no exception."""
        mock_urlopen.side_effect = TimeoutError("Request timed out")

        resolved_transcript = format_transcript_for_prompt(
            REALISTIC_SEGMENTS, SPEAKER_MAP_RESOLVED
        )
        commitments_data = extract_commitments(
            resolved_transcript, SPEAKER_MAP_RESOLVED, "2026-02-20"
        )

        assert commitments_data["commitments"] == []

    def test_empty_transcript_returns_early(self):
        """Empty or very short transcript -> early return without Ollama call."""
        result = extract_commitments("", {})
        assert result["commitments"] == []
        assert "too short" in result.get("extraction_notes", "")

    def test_short_transcript_returns_early(self):
        """Transcript under 50 chars -> early return."""
        result = extract_commitments("hello world", {})
        assert result["commitments"] == []

    @patch("src.speaker_resolver.urllib.request.urlopen")
    def test_speaker_resolution_failure_returns_fallback(self, mock_urlopen):
        """Speaker resolution failure returns minimal fallback map."""
        from urllib.error import URLError

        mock_urlopen.side_effect = URLError("Connection refused")
        speaker_map = resolve_speakers(REALISTIC_SEGMENTS)

        assert "SPEAKER_ME" in speaker_map
        assert speaker_map["SPEAKER_ME"]["confirmed"] is True
        assert len(speaker_map) == 1  # Only the fallback SPEAKER_ME

    def test_insert_commitments_with_empty_list_is_noop(self, pipeline_db):
        """Inserting an empty commitment list does nothing, no errors."""
        pipeline_db.insert_call(
            session_id="noop_001",
            app_name="Zoom",
            started_at="2026-02-20T10:00:00",
            ended_at="2026-02-20T10:30:00",
            duration_seconds=1800.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript="placeholder",
            summary=None,
        )
        pipeline_db.insert_commitments("noop_001", [])
        rows = pipeline_db.get_commitments("noop_001")
        assert rows == []

    def test_insert_commitments_skips_malformed(self, pipeline_db):
        """Malformed commitment dicts (missing required fields) are skipped."""
        pipeline_db.insert_call(
            session_id="malformed_001",
            app_name="Zoom",
            started_at="2026-02-20T10:00:00",
            ended_at="2026-02-20T10:30:00",
            duration_seconds=1800.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript="placeholder",
            summary=None,
        )

        malformed_commitments = [
            {"random_key": "random_value"},  # No recognized format
            {"type": "outgoing", "who": "", "what": "test"},  # Empty who_label
            {"type": "outgoing", "who": "SPEAKER_ME", "what": ""},  # Empty text
            {
                "type": "outgoing",
                "who": "SPEAKER_ME",
                "what": "Valid commitment",
                "to_whom": "SPEAKER_OTHER",
                "deadline": None,
                "quote": "test",
                "timestamp": "00:01:00",
                "uncertain": False,
            },  # This one is valid
        ]

        pipeline_db.insert_commitments("malformed_001", malformed_commitments)
        rows = pipeline_db.get_commitments("malformed_001")
        assert len(rows) == 1
        assert rows[0]["text"] == "Valid commitment"


# =============================================================================
# 5. Full daemon.process_recording() integration with commitments
# =============================================================================


class TestDaemonProcessRecording:
    """Test process_recording() as the ultimate integration point."""

    @patch("src.daemon.notify")
    @patch("src.daemon.write_status")
    @patch("src.daemon.extract_commitments")
    @patch("src.daemon.resolve_speakers")
    def test_process_recording_saves_commitments_to_db(
        self,
        mock_resolve,
        mock_extract,
        mock_status,
        mock_notify,
        pipeline_db,
        pipeline_session,
    ):
        """Full process_recording flow: transcribe -> resolve -> extract -> save commitments."""
        mock_resolve.return_value = SPEAKER_MAP_RESOLVED
        mock_extract.return_value = {
            "commitments": json.loads(KARPATHY_COMMITMENTS_RESPONSE)["commitments"]
        }

        transcriber = MagicMock()
        transcriber.transcribe_separate.return_value = _make_separate_result()
        summarizer = MagicMock()
        summarizer.summarize.return_value = {
            "summary": "Обсудили контракт и дедлайны",
            "key_points": ["Контракт", "Дедлайны"],
            "decisions": [],
            "action_items": [],
            "participants": ["Алексей", "Елена Викторовна"],
        }

        process_recording(pipeline_session, transcriber, summarizer, pipeline_db)

        # Verify commitments are in the database
        session_id = pipeline_session["session_id"]
        rows = pipeline_db.get_commitments(session_id)
        assert len(rows) == 4

        # Verify directions
        directions = {r["direction"] for r in rows}
        assert "outgoing" in directions
        assert "incoming" in directions

        # Verify call record also exists
        call = pipeline_db.get_call(session_id)
        assert call is not None
        assert call["transcript"] is not None
        assert call["summary_json"] is not None

    @patch("src.daemon.notify")
    @patch("src.daemon.write_status")
    @patch("src.daemon.extract_commitments")
    @patch("src.daemon.resolve_speakers")
    def test_process_recording_no_commitments_when_no_separate_transcript(
        self,
        mock_resolve,
        mock_extract,
        mock_status,
        mock_notify,
        pipeline_db,
        pipeline_session,
    ):
        """When transcribe_separate fails -> no speaker resolution, no commitments."""
        transcriber = MagicMock()
        transcriber.transcribe_separate.return_value = None
        transcriber.transcribe.return_value = "Merged fallback transcript"
        summarizer = MagicMock()
        summarizer.summarize.return_value = {
            "summary": "Test",
            "key_points": [],
            "decisions": [],
            "action_items": [],
            "participants": [],
        }

        process_recording(pipeline_session, transcriber, summarizer, pipeline_db)

        mock_resolve.assert_not_called()
        mock_extract.assert_not_called()

        # Call saved without commitments
        session_id = pipeline_session["session_id"]
        rows = pipeline_db.get_commitments(session_id)
        assert rows == []

    @patch("src.daemon.notify")
    @patch("src.daemon.write_status")
    @patch("src.daemon.extract_commitments")
    @patch("src.daemon.resolve_speakers")
    def test_process_recording_empty_commitments_does_not_crash(
        self,
        mock_resolve,
        mock_extract,
        mock_status,
        mock_notify,
        pipeline_db,
        pipeline_session,
    ):
        """extract_commitments returns empty list -> no crash, no DB rows."""
        mock_resolve.return_value = SPEAKER_MAP_RESOLVED
        mock_extract.return_value = {"commitments": []}

        transcriber = MagicMock()
        transcriber.transcribe_separate.return_value = _make_separate_result()
        summarizer = MagicMock()
        summarizer.summarize.return_value = {
            "summary": "Test",
            "key_points": [],
            "decisions": [],
            "action_items": [],
            "participants": [],
        }

        process_recording(pipeline_session, transcriber, summarizer, pipeline_db)

        session_id = pipeline_session["session_id"]
        rows = pipeline_db.get_commitments(session_id)
        assert rows == []

    @patch("src.daemon.notify")
    @patch("src.daemon.write_status")
    @patch("src.daemon.extract_commitments")
    @patch("src.daemon.resolve_speakers")
    def test_process_recording_calls_extract_with_resolved_transcript(
        self,
        mock_resolve,
        mock_extract,
        mock_status,
        mock_notify,
        pipeline_db,
        pipeline_session,
    ):
        """Verify extract_commitments receives resolved transcript, not raw."""
        mock_resolve.return_value = SPEAKER_MAP_RESOLVED
        mock_extract.return_value = {"commitments": []}

        transcriber = MagicMock()
        transcriber.transcribe_separate.return_value = _make_separate_result()
        summarizer = MagicMock()
        summarizer.summarize.return_value = {
            "summary": "Test",
            "key_points": [],
            "decisions": [],
            "action_items": [],
            "participants": [],
        }

        process_recording(pipeline_session, transcriber, summarizer, pipeline_db)

        # extract_commitments should have been called with a string containing resolved names
        mock_extract.assert_called_once()
        call_args = mock_extract.call_args
        transcript_arg = call_args[0][0]  # first positional arg
        # The resolved transcript should contain the speaker name annotation
        assert "Елена Викторовна" in transcript_arg
        assert "conf=0.95" in transcript_arg

        # Speaker map should be the second arg
        speaker_map_arg = call_args[0][1]
        assert speaker_map_arg["SPEAKER_ME"]["confirmed"] is True

        # Call date should be extracted from started_at
        call_date_arg = call_args[0][2]
        assert call_date_arg == "2026-02-20"

    @patch("src.daemon.notify")
    @patch("src.daemon.write_status")
    @patch("src.daemon.extract_commitments")
    @patch("src.daemon.resolve_speakers")
    def test_process_recording_notification_includes_commitment_count(
        self,
        mock_resolve,
        mock_extract,
        mock_status,
        mock_notify,
        pipeline_db,
        pipeline_session,
    ):
        """Final notification includes commitment count."""
        mock_resolve.return_value = SPEAKER_MAP_RESOLVED
        mock_extract.return_value = {
            "commitments": json.loads(KARPATHY_COMMITMENTS_RESPONSE)["commitments"]
        }

        transcriber = MagicMock()
        transcriber.transcribe_separate.return_value = _make_separate_result()
        summarizer = MagicMock()
        summarizer.summarize.return_value = {
            "summary": "Test",
            "key_points": [],
            "decisions": [],
            "action_items": [],
            "participants": [],
        }

        process_recording(pipeline_session, transcriber, summarizer, pipeline_db)

        # Check the final notification contains commitment count
        last_notify_call = mock_notify.call_args_list[-1]
        notification_message = last_notify_call[0][1]
        assert "4 обязательств" in notification_message


# =============================================================================
# 6. DB normalization: Karpathy vs Murati format stored correctly
# =============================================================================


class TestDBNormalization:
    """Test that both Karpathy and Murati commitment formats are normalized correctly."""

    def test_karpathy_format_normalized_to_db(self, pipeline_db):
        """Karpathy format (type/who/what) -> DB columns (direction/who_label/text)."""
        session_id = "norm_karpathy_001"
        pipeline_db.insert_call(
            session_id=session_id,
            app_name="Zoom",
            started_at="2026-02-20T10:00:00",
            ended_at="2026-02-20T10:30:00",
            duration_seconds=1800.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript="placeholder",
            summary=None,
        )

        karpathy_commitments = json.loads(KARPATHY_COMMITMENTS_RESPONSE)["commitments"]
        pipeline_db.insert_commitments(session_id, karpathy_commitments)

        rows = pipeline_db.get_commitments(session_id)
        assert len(rows) == 4

        # Check first outgoing (Karpathy type->direction mapping)
        c1 = rows[0]
        assert c1["direction"] == "outgoing"
        assert c1["who_label"] == "SPEAKER_ME"
        assert c1["who_name"] is None  # Karpathy had null
        assert c1["to_label"] == "SPEAKER_OTHER"
        assert c1["to_name"] == "Елена Викторовна"
        assert c1["text"] == "Отправить отчёт"
        assert (
            c1["verbatim_quote"] == "Я отправлю отчёт к пятнице, как мы договаривались"
        )
        assert c1["timestamp"] == "00:00:23"
        assert c1["deadline_raw"] == "к пятнице"
        assert c1["deadline_type"] is None  # Karpathy doesn't have this field
        assert c1["uncertain"] == 0
        assert c1["status"] == "open"
        assert c1["created_at"] is not None

    def test_murati_format_normalized_to_db(self, pipeline_db):
        """Murati format (direction/committer_label/commitment_text) -> same DB columns."""
        session_id = "norm_murati_001"
        pipeline_db.insert_call(
            session_id=session_id,
            app_name="Zoom",
            started_at="2026-02-20T10:00:00",
            ended_at="2026-02-20T10:30:00",
            duration_seconds=1800.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript="placeholder",
            summary=None,
        )

        murati_commitments = json.loads(MURATI_COMMITMENTS_RESPONSE)["commitments"]
        pipeline_db.insert_commitments(session_id, murati_commitments)

        rows = pipeline_db.get_commitments(session_id)
        assert len(rows) == 2

        c1 = rows[0]
        assert c1["direction"] == "outgoing"
        assert c1["who_label"] == "SPEAKER_ME"
        assert c1["who_name"] is None
        assert c1["to_label"] == "SPEAKER_OTHER"
        assert c1["to_name"] == "Елена Викторовна"
        assert c1["text"] == "Отправить отчёт"
        assert c1["deadline_raw"] == "к пятнице"
        assert c1["deadline_type"] == "relative_week"
        assert c1["uncertain"] == 0  # confidence 0.95 >= 0.8

        c2 = rows[1]
        assert c2["direction"] == "incoming"
        assert c2["who_label"] == "SPEAKER_OTHER"
        assert c2["who_name"] == "Елена Викторовна"
        assert c2["deadline_type"] == "relative_day"

    def test_murati_low_confidence_marked_uncertain(self, pipeline_db):
        """Murati commitment with confidence < 0.8 is marked uncertain=1."""
        session_id = "norm_uncertain_001"
        pipeline_db.insert_call(
            session_id=session_id,
            app_name="Zoom",
            started_at="2026-02-20T10:00:00",
            ended_at="2026-02-20T10:30:00",
            duration_seconds=1800.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript="placeholder",
            summary=None,
        )

        low_confidence_commitment = [
            {
                "id": 1,
                "direction": "outgoing",
                "committer_label": "SPEAKER_ME",
                "committer_name": None,
                "recipient_label": "SPEAKER_OTHER",
                "recipient_name": None,
                "commitment_text": "Постараюсь посмотреть",
                "verbatim_quote": "Постараюсь посмотреть к вечеру",
                "timestamp": "00:10:00",
                "deadline_raw": "к вечеру",
                "deadline_type": "implied_urgent",
                "commitment_confidence": 0.35,
                "conditional": False,
                "condition_text": None,
            }
        ]

        pipeline_db.insert_commitments(session_id, low_confidence_commitment)
        rows = pipeline_db.get_commitments(session_id)
        assert len(rows) == 1
        assert rows[0]["uncertain"] == 1  # confidence 0.35 < 0.8

    def test_murati_conditional_marked_uncertain(self, pipeline_db):
        """Murati commitment with conditional=True is marked uncertain=1."""
        session_id = "norm_conditional_001"
        pipeline_db.insert_call(
            session_id=session_id,
            app_name="Zoom",
            started_at="2026-02-20T10:00:00",
            ended_at="2026-02-20T10:30:00",
            duration_seconds=1800.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript="placeholder",
            summary=None,
        )

        conditional_commitment = [
            {
                "id": 1,
                "direction": "outgoing",
                "committer_label": "SPEAKER_ME",
                "committer_name": None,
                "recipient_label": "SPEAKER_OTHER",
                "recipient_name": None,
                "commitment_text": "Подготовлю отчёт если одобрят бюджет",
                "verbatim_quote": "Если одобрят бюджет, я подготовлю отчёт",
                "timestamp": "00:15:00",
                "deadline_raw": None,
                "deadline_type": "none",
                "commitment_confidence": 0.85,
                "conditional": True,
                "condition_text": "если одобрят бюджет",
            }
        ]

        pipeline_db.insert_commitments(session_id, conditional_commitment)
        rows = pipeline_db.get_commitments(session_id)
        assert len(rows) == 1
        assert rows[0]["uncertain"] == 1  # conditional=True overrides confidence


# =============================================================================
# 7. Multi-call isolation: commitments don't leak between sessions
# =============================================================================


class TestMultiCallIsolation:
    """Commitments from different calls stay isolated in the DB."""

    def test_commitments_isolated_per_session(self, pipeline_db):
        """Commitments from different sessions don't leak."""
        for sid in ("iso_001", "iso_002"):
            pipeline_db.insert_call(
                session_id=sid,
                app_name="Zoom",
                started_at="2026-02-20T10:00:00",
                ended_at="2026-02-20T10:30:00",
                duration_seconds=1800.0,
                system_wav_path=None,
                mic_wav_path=None,
                transcript="placeholder",
                summary=None,
            )

        # Insert different commitments for each session
        pipeline_db.insert_commitments(
            "iso_001",
            [
                {
                    "type": "outgoing",
                    "who": "SPEAKER_ME",
                    "who_name": None,
                    "to_whom": "SPEAKER_OTHER",
                    "to_whom_name": None,
                    "what": "Commitment from call 1",
                    "deadline": None,
                    "quote": "test",
                    "timestamp": "00:01:00",
                    "uncertain": False,
                }
            ],
        )
        pipeline_db.insert_commitments(
            "iso_002",
            [
                {
                    "type": "incoming",
                    "who": "SPEAKER_OTHER",
                    "who_name": "Петр",
                    "to_whom": "SPEAKER_ME",
                    "to_whom_name": None,
                    "what": "Commitment from call 2",
                    "deadline": "завтра",
                    "quote": "test",
                    "timestamp": "00:05:00",
                    "uncertain": False,
                },
                {
                    "type": "outgoing",
                    "who": "SPEAKER_ME",
                    "who_name": None,
                    "to_whom": "SPEAKER_OTHER",
                    "to_whom_name": "Петр",
                    "what": "Another from call 2",
                    "deadline": None,
                    "quote": "test",
                    "timestamp": "00:10:00",
                    "uncertain": False,
                },
            ],
        )

        rows_1 = pipeline_db.get_commitments("iso_001")
        rows_2 = pipeline_db.get_commitments("iso_002")

        assert len(rows_1) == 1
        assert len(rows_2) == 2
        assert rows_1[0]["text"] == "Commitment from call 1"
        assert rows_1[0]["direction"] == "outgoing"
        assert {r["text"] for r in rows_2} == {
            "Commitment from call 2",
            "Another from call 2",
        }

    @patch("src.daemon.notify")
    @patch("src.daemon.write_status")
    @patch("src.daemon.extract_commitments")
    @patch("src.daemon.resolve_speakers")
    def test_two_calls_through_process_recording_isolated(
        self,
        mock_resolve,
        mock_extract,
        mock_status,
        mock_notify,
        pipeline_db,
        tmp_path,
    ):
        """Two calls processed through daemon both save commitments independently."""
        sessions = []
        for i, (sid, app) in enumerate(
            [
                ("multi_001", "Zoom"),
                ("multi_002", "Google Meet"),
            ]
        ):
            d = tmp_path / sid
            d.mkdir()
            sessions.append(
                {
                    "session_id": sid,
                    "app_name": app,
                    "started_at": f"2026-02-20T{10 + i}:00:00",
                    "ended_at": f"2026-02-20T{10 + i}:30:00",
                    "duration_seconds": 1800.0,
                    "session_dir": str(d),
                    "system_wav": str(d / "system.wav"),
                    "mic_wav": str(d / "mic.wav"),
                }
            )

        mock_resolve.return_value = SPEAKER_MAP_RESOLVED
        summarizer = MagicMock()
        summarizer.summarize.return_value = {
            "summary": "Test",
            "key_points": [],
            "decisions": [],
            "action_items": [],
            "participants": [],
        }

        # Call 1 has 2 commitments
        call_1_commitments = [
            {
                "type": "outgoing",
                "who": "SPEAKER_ME",
                "what": "Task A",
                "to_whom": "SPEAKER_OTHER",
                "quote": "test",
                "timestamp": "00:01:00",
                "deadline": None,
                "uncertain": False,
            },
            {
                "type": "incoming",
                "who": "SPEAKER_OTHER",
                "what": "Task B",
                "to_whom": "SPEAKER_ME",
                "quote": "test",
                "timestamp": "00:02:00",
                "deadline": None,
                "uncertain": False,
            },
        ]
        # Call 2 has 1 commitment
        call_2_commitments = [
            {
                "type": "outgoing",
                "who": "SPEAKER_ME",
                "what": "Task C",
                "to_whom": "SPEAKER_OTHER",
                "quote": "test",
                "timestamp": "00:05:00",
                "deadline": "к понедельнику",
                "uncertain": False,
            },
        ]

        transcriber = MagicMock()

        for session, commitments in zip(
            sessions, [call_1_commitments, call_2_commitments]
        ):
            transcriber.transcribe_separate.return_value = _make_separate_result()
            mock_extract.return_value = {"commitments": commitments}
            process_recording(session, transcriber, summarizer, pipeline_db)

        # Verify isolation
        assert len(pipeline_db.get_commitments("multi_001")) == 2
        assert len(pipeline_db.get_commitments("multi_002")) == 1

        # Verify aggregate counts
        counts = pipeline_db.get_commitment_counts()
        assert counts["outgoing"] == 2  # Task A + Task C
        assert counts["incoming"] == 1  # Task B
