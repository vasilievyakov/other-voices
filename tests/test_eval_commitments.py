"""Tests for scripts.eval_commitments — funnel decomposition, regression
scoring against the owner-curated set, precision block.

The funnel attributes every golden label to the stage where it died:
stage1 (no candidate covers it), stage2 (no LLM yes-vote on a covering
candidate), stage3 (no verified extracted item matches). No live Ollama:
conftest stubs _call_llm, tests inject explicit llm stubs.
"""

from scripts.eval_commitments import (
    build_funnel,
    eval_funnel,
    precision_block,
    regression_check,
)


def _yes(quote: str, text: str) -> dict:
    return {
        "is_commitment": True,
        "confidence": "high",
        "committer": "SPEAKER_ME",
        "recipient": "SPEAKER_01",
        "text": text,
        "deadline": "",
        "quote": quote,
    }


_NO = {"is_commitment": False, "committer": "", "text": "", "quote": ""}


class TestFunnel:
    # Three known fates: label 1 has no stage-1 candidate (no commissive
    # pattern), label 2 gets a candidate but only no-votes, label 3 survives
    # end to end.
    TRANSCRIPT = "\n".join(
        [
            "[01:00] SPEAKER_ME: отчет для клиента надо передать позже",
            "[02:00] SPEAKER_01: хорошо, спасибо",
            "[03:00] SPEAKER_ME: я пришлю договор завтра",
            "[04:00] SPEAKER_01: отлично, жду",
            "[05:00] SPEAKER_ME: я скину презентацию сегодня",
            "[06:00] SPEAKER_01: буду ждать",
        ]
    )
    LABELS = [
        {"ts": "01:00", "text": "передать отчет клиенту", "committer": "SPEAKER_ME"},
        {"ts": "03:00", "text": "прислать договор", "committer": "SPEAKER_ME"},
        {"ts": "05:00", "text": "скинуть презентацию", "committer": "SPEAKER_ME"},
    ]

    @staticmethod
    def _stub(prompt, temperature=0.25, schema=None):
        # "презентацию" occurs only in the candidate that must survive;
        # keying on it avoids collisions with the static prompt text.
        if "презентацию" in prompt:
            return _yes("я скину презентацию сегодня", "скинуть презентацию сегодня")
        return dict(_NO)

    def test_known_fates_land_in_the_right_stages(self):
        extracted, funnel = eval_funnel(self.TRANSCRIPT, self.LABELS, llm=self._stub)
        assert funnel["labels"] == 3
        assert funnel["stage1_coverage"] == {
            "count": 2,
            "covered": ["прислать договор", "скинуть презентацию"],
        }
        assert funnel["stage2_survival"] == {
            "count": 1,
            "survived": ["скинуть презентацию"],
        }
        assert funnel["stage3_survival"] == {
            "count": 1,
            "survived": ["скинуть презентацию"],
        }
        assert funnel["lost"] == [
            {"label": "передать отчет клиенту", "ts": "01:00", "stage": "stage1"},
            {"label": "прислать договор", "ts": "03:00", "stage": "stage2"},
        ]

    def test_extraction_result_is_the_real_pipeline_output(self):
        extracted, _ = eval_funnel(self.TRANSCRIPT, self.LABELS, llm=self._stub)
        assert len(extracted) == 1
        assert extracted[0]["quote"] == "я скину презентацию сегодня"
        assert extracted[0]["verified"] == "exact"

    def test_failed_verification_is_a_stage3_death(self):
        transcript = (
            "[01:00] SPEAKER_ME: я пришлю смету по проекту\n[02:00] SPEAKER_01: спасибо"
        )
        labels = [{"ts": "01:00", "text": "прислать смету"}]

        def stub(prompt, temperature=0.25, schema=None):
            return _yes("фиолетовый носорог играет на трубе", "пришлет смету")

        extracted, funnel = eval_funnel(transcript, labels, llm=stub)
        # the item is kept (visibility over silent drops) but marked failed
        assert len(extracted) == 1
        assert extracted[0]["verified"] == "failed"
        assert funnel["stage1_coverage"]["count"] == 1
        assert funnel["stage2_survival"]["count"] == 1
        assert funnel["stage3_survival"] == {"count": 0, "survived": []}
        assert funnel["lost"] == [
            {"label": "прислать смету", "ts": "01:00", "stage": "stage3"}
        ]

    def test_default_llm_is_conftest_stub_no_live_ollama(self):
        # conftest patches commitments2._call_llm to return None: every vote
        # is a no-vote, so covered labels die at stage 2 and nothing crashes.
        extracted, funnel = eval_funnel(self.TRANSCRIPT, self.LABELS)
        assert extracted == []
        stages = {item["label"]: item["stage"] for item in funnel["lost"]}
        assert stages == {
            "передать отчет клиенту": "stage1",
            "прислать договор": "stage2",
            "скинуть презентацию": "stage2",
        }

    def test_build_funnel_with_no_candidates(self):
        funnel = build_funnel(self.LABELS, [], [], [])
        assert funnel["stage1_coverage"] == {"count": 0, "covered": []}
        assert [item["stage"] for item in funnel["lost"]] == ["stage1"] * 3


class TestRegressionCheck:
    ROWS = [
        {
            "id": 1,
            "session_id": "s1",
            "text": "Пришлю смету",
            "verbatim_quote": "я пришлю смету завтра",
            "direction": "outgoing",
            "uncertain": 0,
            "status": "open",
            "resolved_at": None,
        },
        {
            "id": 2,
            "session_id": "s1",
            "text": "Скину презентацию",
            "verbatim_quote": "скину презентацию",
            "direction": "outgoing",
            "uncertain": 0,
            "status": "open",
            "resolved_at": None,
        },
        {
            "id": 3,
            "session_id": "s1",
            "text": "Возможно созвонимся",
            "verbatim_quote": "возможно созвонимся",
            "direction": "outgoing",
            "uncertain": 1,
            "status": "dismissed",
            "resolved_at": "2026-08-15T00:00:00",
        },
        {
            "id": 4,
            "session_id": "s2",
            "text": "Отправлю запись",
            "verbatim_quote": "отправлю запись",
            "direction": "outgoing",
            "uncertain": 0,
            "status": "dismissed",
            "resolved_at": "2026-08-15T00:00:00",
        },
        {
            "id": 5,
            "session_id": "s3",
            "text": "Согласую бюджет",
            "verbatim_quote": "согласую бюджет",
            "direction": "outgoing",
            "uncertain": 0,
            "status": "open",
            "resolved_at": None,
        },
    ]
    EXTRACTED = {
        "s1": [
            {"what": "пришлет смету", "quote": "я пришлю смету завтра"},
            {"what": "созвонимся", "quote": "возможно созвонимся"},
        ],
        "s2": [],
    }

    def test_rates_and_named_regressions(self):
        result = regression_check(self.ROWS, self.EXTRACTED)
        # s3 never ran — its row must not be judged
        assert result["rows_total"] == 5
        assert result["rows_evaluated"] == 4
        # open: id 1 kept, id 2 lost
        assert result["open_total"] == 2
        assert result["open_kept"] == 1
        assert result["kept_open_rate"] == 0.5
        # dismissed: id 3 reproduced (bad), id 4 stayed dead (good)
        assert result["dismissed_total"] == 2
        assert result["dismissed_reproduced"] == 1
        assert result["reproduced_dismissed_rate"] == 0.5
        kinds = {(r["id"], r["kind"]) for r in result["regressions"]}
        assert kinds == {(2, "open_lost"), (3, "dismissed_reproduced")}

    def test_regressions_carry_session_and_text(self):
        result = regression_check(self.ROWS, self.EXTRACTED)
        by_id = {r["id"]: r for r in result["regressions"]}
        assert by_id[2]["session_id"] == "s1"
        assert by_id[2]["text"] == "Скину презентацию"

    def test_empty_denominators_yield_none_rates(self):
        result = regression_check(self.ROWS, {})
        assert result["rows_evaluated"] == 0
        assert result["kept_open_rate"] is None
        assert result["reproduced_dismissed_rate"] is None
        assert result["regressions"] == []


def _populate_for_precision(db):
    db.insert_call(
        session_id="sess_p",
        app_name="Zoom",
        started_at="2026-08-10T10:00:00",
        ended_at="2026-08-10T10:10:00",
        duration_seconds=600.0,
        system_wav_path=None,
        mic_wav_path=None,
        transcript="т",
        summary=None,
    )
    db.insert_commitments(
        "sess_p",
        [
            {
                "type": "outgoing",
                "who": "SPEAKER_ME",
                "what": "Пришлю смету",
                "quote": "пришлю смету",
            },
            {
                "type": "outgoing",
                "who": "SPEAKER_ME",
                "what": "Скину презентацию",
                "quote": "скину презентацию",
            },
            {
                "type": "incoming",
                "who": "SPEAKER_1",
                "what": "Подготовит договор",
                "quote": "подготовлю договор",
            },
            {
                "type": "outgoing",
                "who": "SPEAKER_ME",
                "what": "Созвонимся в четверг",
                "quote": "созвонимся в четверг",
            },
        ],
    )
    return db


def _audit_md(verdicts: dict[int, str]) -> str:
    blocks = []
    for n, (row_id, mark) in enumerate(sorted(verdicts.items()), 1):
        blocks.append(
            f"## {n} <!-- id:{row_id} session:sess_p status:open -->\n"
            f"Цитата: «ц»\nТекст: т\nДата звонка: 2026-08-10\nВердикт: {mark}\n"
        )
    return "\n".join(blocks)


class TestPrecisionBlock:
    def test_scores_marked_synthetic_sheet(self, tmp_db, tmp_path):
        db = _populate_for_precision(tmp_db)
        audit = tmp_path / "audit.md"
        audit.write_text(_audit_md({1: "+", 2: "-", 3: "+", 4: "_"}), encoding="utf-8")
        block = precision_block(audit_path=audit, db_path=db.db_path)
        assert block["precision"] == round(2 / 3, 3)
        assert block["marked"] == 3
        assert block["unmarked"] == 1

    def test_missing_sheet_is_awaiting_owner_labels(self, tmp_db, tmp_path):
        db = _populate_for_precision(tmp_db)
        block = precision_block(audit_path=tmp_path / "missing.md", db_path=db.db_path)
        assert block == {"precision": None, "note": "awaiting owner labels"}

    def test_unmarked_sheet_is_awaiting_owner_labels(self, tmp_db, tmp_path):
        db = _populate_for_precision(tmp_db)
        audit = tmp_path / "audit.md"
        audit.write_text(_audit_md({1: "_", 2: "_", 3: "_", 4: "_"}), encoding="utf-8")
        block = precision_block(audit_path=audit, db_path=db.db_path)
        assert block["precision"] is None
        assert block["note"] == "awaiting owner labels"
