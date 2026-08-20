"""Deadline parsing — raw Russian deadline phrase -> concrete date.

Pure deterministic code: no LLM, no network, no guessing. A phrase that does
not carry a computable deadline («когда получится», «на днях», «не указано»)
honestly yields None. All arithmetic counts from call_date — the date of the
call the phrase was spoken on.

Morphology follows src.evaluation._name_present: a weekday or month counts as
present when its stem appears with a real Russian case ending («к пятнице»,
«15 сентября»). Arbitrary \\w-tails are not accepted — «средство» must not
attest «среда».
"""

import calendar
import datetime
import re

# --- morphology -------------------------------------------------------------

# Weekday stems with explicit case-ending alternations. Consonant-final
# nominative stems (понедельник) take an optional ending; vowel/soft stems
# (сред-, пятниц-) require one — the bare stem is not a word.
_WEEKDAYS: list[tuple[int, str]] = [
    (0, r"понедельник(?:а|у|е|ом)?"),
    (1, r"вторник(?:а|у|е|ом)?"),
    (2, r"сред(?:а|у|ы|е|ой)"),
    (3, r"четверг(?:а|у|е|ом)?"),
    (4, r"пятниц(?:а|у|ы|е|ей)"),
    (5, r"суббот(?:а|у|ы|е|ой)"),
    (6, r"воскресень(?:е|я|ю|ем)"),
]

_MONTHS: list[tuple[int, str]] = [
    (1, r"январ(?:ь|я|е|ю)"),
    (2, r"феврал(?:ь|я|е|ю)"),
    (3, r"март(?:а|е|у)?"),
    (4, r"апрел(?:ь|я|е|ю)"),
    (5, r"ма(?:й|я|е|ю)"),
    (6, r"июн(?:ь|я|е|ю)"),
    (7, r"июл(?:ь|я|е|ю)"),
    (8, r"август(?:а|е|у)?"),
    (9, r"сентябр(?:ь|я|е|ю)"),
    (10, r"октябр(?:ь|я|е|ю)"),
    (11, r"ноябр(?:ь|я|е|ю)"),
    (12, r"декабр(?:ь|я|е|ю)"),
]

# Spoken numerals in the forms «через …» / «в течение …» actually take
# (nominative/accusative and genitive). Text is ё-normalized before lookup.
_NUMBER_WORDS = {
    "один": 1,
    "одну": 1,
    "одного": 1,
    "одной": 1,
    "два": 2,
    "две": 2,
    "двух": 2,
    "пару": 2,
    "пары": 2,
    "три": 3,
    "трех": 3,
    "четыре": 4,
    "четырех": 4,
    "пять": 5,
    "пяти": 5,
    "шесть": 6,
    "шести": 6,
    "семь": 7,
    "семи": 7,
    "восемь": 8,
    "восьми": 8,
    "девять": 9,
    "девяти": 9,
    "десять": 10,
    "десяти": 10,
}

# --- phrase patterns --------------------------------------------------------

_TOMORROW = re.compile(r"(?<!\w)завтра(?!\w)")
_AFTER_TOMORROW = re.compile(r"(?<!\w)послезавтра(?!\w)")
_TODAY = re.compile(r"(?<!\w)(?:сегодня|сейчас)(?!\w)")

_END_OF_DAY = re.compile(r"(?<!\w)до конца дня(?!\w)")
_END_OF_WEEK = re.compile(r"(?<!\w)до конца недели(?!\w)")
_END_OF_MONTH = re.compile(r"(?<!\w)до конца месяца(?!\w)")

# «через …» and «в течение …»: optional count (digits or a spoken numeral),
# then a unit in its real spoken forms. Sub-day units resolve to call_date.
_IN_PHRASE = re.compile(
    r"(?<!\w)(через|в течение)"
    r"(?: (\d{1,3}|[а-я]+))?"
    r" (полчаса|час(?:а|ов)?|минут(?:у|ы)?|день|дня|дней|"
    r"недел(?:ю|и|ь|е|я)|месяц(?:а|ев)?)(?!\w)"
)
_HOUR_UNITS = ("полчаса", "час", "часа", "часов", "минут", "минуту", "минуты")
_DAY_UNITS = ("день", "дня", "дней")

_NEXT_WEEK = re.compile(r"(?<!\w)следующ(?:ей|ую|ая|ий|ем) недел(?:е|ю|и|я)(?!\w)")
_THIS_WEEK = re.compile(r"(?<!\w)эт(?:ой|у|а) недел(?:е|ю|и|я)(?!\w)")

_NUMERIC_DATE = re.compile(r"(?<![\w.])(\d{1,2})[./](\d{1,2})(?:[./](\d{4}))?(?!\d)")

_MONTH_DATES = [
    (num, re.compile(rf"(?<!\w)(\d{{1,2}}) {pattern}(?!\w)"))
    for num, pattern in _MONTHS
]
_WEEKDAY_RES = [
    (num, re.compile(rf"(?<!\w){pattern}(?!\w)")) for num, pattern in _WEEKDAYS
]

# --- date arithmetic --------------------------------------------------------


def _add_months(d: datetime.date, n: int) -> datetime.date:
    month_index = d.month - 1 + n
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return datetime.date(year, month, day)


def _nearest_future(
    day: int, month: int, call_date: datetime.date
) -> datetime.date | None:
    """The next occurrence of day.month on or after call_date, else None."""
    for year in (call_date.year, call_date.year + 1):
        try:
            candidate = datetime.date(year, month, day)
        except ValueError:
            continue
        if candidate >= call_date:
            return candidate
    return None


def _parse_count(token: str | None) -> int | None:
    """Count for «через N …»: absent -> 1, unknown numeral -> None."""
    if token is None:
        return 1
    if token.isdigit():
        return int(token)
    return _NUMBER_WORDS.get(token)


def _in_phrase(m: re.Match, call_date: datetime.date) -> datetime.date | None:
    introducer, count_token, unit = m.group(1), m.group(2), m.group(3)
    if unit in _HOUR_UNITS:
        return call_date  # sub-day horizon: due the same day
    count = _parse_count(count_token)
    if count is None:
        return None
    if unit in _DAY_UNITS:
        # «в течение дня» = by the end of today; «через день» = a day later.
        if introducer == "в течение" and count_token is None:
            return call_date
        return call_date + datetime.timedelta(days=count)
    if unit.startswith("недел"):
        return call_date + datetime.timedelta(weeks=count)
    return _add_months(call_date, count)


# --- public entry -----------------------------------------------------------


def parse_deadline(raw: str | None, call_date: datetime.date) -> datetime.date | None:
    """Turn a raw Russian deadline phrase into a concrete date.

    Returns None for empty input and for phrases that carry no computable
    deadline. Never guesses.
    """
    if raw is None:
        return None
    text = re.sub(r"\s+", " ", raw.lower().replace("ё", "е")).strip()
    if not text:
        return None

    monday = call_date - datetime.timedelta(days=call_date.weekday())

    if _AFTER_TOMORROW.search(text):
        return call_date + datetime.timedelta(days=2)
    if _TOMORROW.search(text):
        return call_date + datetime.timedelta(days=1)
    if _TODAY.search(text) or _END_OF_DAY.search(text):
        return call_date
    if _END_OF_WEEK.search(text):
        return monday + datetime.timedelta(days=6)
    if _END_OF_MONTH.search(text):
        last = calendar.monthrange(call_date.year, call_date.month)[1]
        return call_date.replace(day=last)

    m = _IN_PHRASE.search(text)
    if m:
        return _in_phrase(m, call_date)

    if _NEXT_WEEK.search(text):
        return monday + datetime.timedelta(days=7)
    if _THIS_WEEK.search(text):
        friday = monday + datetime.timedelta(days=4)
        return friday if friday >= call_date else None

    m = _NUMERIC_DATE.search(text)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        if m.group(3):
            try:
                return datetime.date(int(m.group(3)), month, day)
            except ValueError:
                return None
        return _nearest_future(day, month, call_date)

    for month_num, pattern in _MONTH_DATES:
        m = pattern.search(text)
        if m:
            return _nearest_future(int(m.group(1)), month_num, call_date)

    for weekday_num, pattern in _WEEKDAY_RES:
        if pattern.search(text):
            days_ahead = (weekday_num - call_date.weekday()) % 7
            return call_date + datetime.timedelta(days=days_ahead)

    return None
