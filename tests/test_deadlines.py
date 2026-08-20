"""Tests for src.deadlines — raw Russian deadline phrase -> concrete date.

Anchor: CALL = Wednesday 2026-08-12. All relative arithmetic counts from it.
The parametrized corpora include every deadline form actually observed in
data/calls.db commitment texts and eval reports («завтра», «сегодня»,
«в понедельник», «в среду», «в воскресенье», «в пятницу», «на этой неделе»,
«на следующей неделе», «через неделю проведем.», «через полчаса.»,
«сегодня-завтра», «не указано»).
"""

from datetime import date

import pytest

from src.deadlines import parse_deadline

CALL = date(2026, 8, 12)  # Wednesday


# --- honest emptiness -------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        "когда получится",
        "позже",
        "на днях",
        "не указано",  # real value from eval reports
        "как можно скорее",
        "в сентябре",  # month without day — underdetermined
        "скоро",
    ],
)
def test_no_deadline_returns_none(raw):
    assert parse_deadline(raw, CALL) is None


# --- today ------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "сегодня",
        "сейчас",
        "прямо сейчас",
        "сегодня вечером",
        "до конца дня",
        "в течение дня",
        "через полчаса.",  # real form from calls.db
        "через час",
        "через 2 часа",
        "через 40 минут",
    ],
)
def test_today(raw):
    assert parse_deadline(raw, CALL) == CALL


# --- tomorrow and the day after ---------------------------------------------


def test_tomorrow():
    assert parse_deadline("завтра", CALL) == date(2026, 8, 13)


def test_tomorrow_with_tail():
    assert parse_deadline("завтра утром", CALL) == date(2026, 8, 14 - 1)


def test_day_after_tomorrow():
    assert parse_deadline("послезавтра", CALL) == date(2026, 8, 14)


def test_segodnya_zavtra_range_takes_upper_bound():
    # real form from calls.db: «я сейчас сегодня-завтра пришлю»
    assert parse_deadline("сегодня-завтра", CALL) == date(2026, 8, 13)


def test_zavtra_inside_poslezavtra_not_matched_alone():
    # «послезавтра» must never parse as «завтра»
    assert parse_deadline("послезавтра", CALL) != date(2026, 8, 13)


# --- через N ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("через день", date(2026, 8, 13)),
        ("через два дня", date(2026, 8, 14)),
        ("через 3 дня", date(2026, 8, 15)),
        ("через 5 дней", date(2026, 8, 17)),
        ("через неделю", date(2026, 8, 19)),
        ("через неделю проведем.", date(2026, 8, 19)),  # real form from calls.db
        ("через две недели", date(2026, 8, 26)),
        ("через 3 недели", date(2026, 9, 2)),
        ("через месяц", date(2026, 9, 12)),
        ("через 2 месяца", date(2026, 10, 12)),
    ],
)
def test_cherez_arithmetic(raw, expected):
    assert parse_deadline(raw, CALL) == expected


def test_cherez_month_clamps_to_month_end():
    assert parse_deadline("через месяц", date(2026, 1, 31)) == date(2026, 2, 28)


# --- в течение --------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("в течение недели", date(2026, 8, 19)),
        ("в течение двух недель", date(2026, 8, 26)),
        ("в течение трех дней", date(2026, 8, 15)),
        ("в течение месяца", date(2026, 9, 12)),
    ],
)
def test_v_techenie(raw, expected):
    assert parse_deadline(raw, CALL) == expected


# --- weekdays (call on Wednesday 2026-08-12) --------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("в понедельник", date(2026, 8, 17)),
        ("в понедельник утром", date(2026, 8, 17)),
        ("к понедельнику", date(2026, 8, 17)),
        ("во вторник", date(2026, 8, 18)),
        ("в среду", date(2026, 8, 12)),  # call day itself
        ("к среде", date(2026, 8, 12)),
        ("в четверг", date(2026, 8, 13)),
        ("до четверга", date(2026, 8, 13)),
        ("в пятницу", date(2026, 8, 14)),
        ("до пятницы", date(2026, 8, 14)),
        ("к пятнице", date(2026, 8, 14)),
        ("в субботу", date(2026, 8, 15)),
        ("в воскресенье", date(2026, 8, 16)),
    ],
)
def test_weekdays(raw, expected):
    assert parse_deadline(raw, CALL) == expected


def test_weekday_stem_needs_real_case_ending():
    # «средство» must not attest «среда» — no \w-tails
    assert parse_deadline("средство", CALL) is None


def test_weekday_case_insensitive():
    assert parse_deadline("В Пятницу", CALL) == date(2026, 8, 14)


# --- weeks ------------------------------------------------------------------


def test_next_week_is_next_monday():
    assert parse_deadline("на следующей неделе", CALL) == date(2026, 8, 17)


def test_next_week_from_monday_is_the_following_monday():
    assert parse_deadline("на следующей неделе", date(2026, 8, 17)) == date(2026, 8, 24)


def test_this_week_is_friday_when_ahead():
    assert parse_deadline("на этой неделе", CALL) == date(2026, 8, 14)


def test_this_week_on_friday_is_friday():
    assert parse_deadline("на этой неделе", date(2026, 8, 14)) == date(2026, 8, 14)


def test_this_week_on_saturday_is_none():
    assert parse_deadline("на этой неделе", date(2026, 8, 15)) is None


def test_end_of_week_is_sunday():
    assert parse_deadline("до конца недели", CALL) == date(2026, 8, 16)


def test_end_of_month():
    assert parse_deadline("до конца месяца", CALL) == date(2026, 8, 31)


def test_end_of_month_february():
    assert parse_deadline("до конца месяца", date(2026, 2, 10)) == date(2026, 2, 28)


# --- explicit dates ---------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("15 сентября", date(2026, 9, 15)),
        ("до 15 сентября", date(2026, 9, 15)),
        ("к 15 сентября", date(2026, 9, 15)),
        ("15 Сентября", date(2026, 9, 15)),
        ("15 августа", date(2026, 8, 15)),  # still ahead this year
        ("12 августа", date(2026, 8, 12)),  # call day itself
        ("10 августа", date(2027, 8, 10)),  # already passed -> next year
        ("1 января", date(2027, 1, 1)),
        ("15.09", date(2026, 9, 15)),
        ("15.09.2026", date(2026, 9, 15)),
        ("15.09.2025", date(2025, 9, 15)),  # explicit year wins even in the past
        ("10.08", date(2027, 8, 10)),  # already passed -> next year
    ],
)
def test_explicit_dates(raw, expected):
    assert parse_deadline(raw, CALL) == expected


@pytest.mark.parametrize("raw", ["32.13", "31.02", "0.05", "29.02"])
def test_invalid_explicit_dates(raw):
    # 29.02 is invalid both in the call year and the next -> honest None
    assert parse_deadline(raw, CALL) is None


# --- normalization ----------------------------------------------------------


def test_surrounding_whitespace_and_case():
    assert parse_deadline("  ЗАВТРА  ", CALL) == date(2026, 8, 13)


def test_yo_normalized():
    # transcripts may spell «в течение» with stray ё; ё->е must not break parsing
    assert parse_deadline("в течениё недели", CALL) == date(2026, 8, 19)


def test_multiple_spaces():
    assert parse_deadline("через   две   недели", CALL) == date(2026, 8, 26)
