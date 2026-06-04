from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any


@dataclass(slots=True)
class TemporalExpression:
    text: str
    normalized_type: str
    range_start: str
    range_end: str
    granularity: str
    calendar: str = "gregorian"
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "normalized_type": self.normalized_type,
            "range_start": self.range_start,
            "range_end": self.range_end,
            "granularity": self.granularity,
            "calendar": self.calendar,
            "confidence": self.confidence,
        }


class TemporalNormalizer:
    """Normalize stable calendar-relative phrases before LLM planning.

    This intentionally handles generic calendar language only. Business-specific
    periods such as fiscal year variants and payment periods should be resolved
    by a fiscal/business-period resolver when the relevant company or API context
    is known.
    """

    _PHRASES: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
        ("today", "calendar_day", "day", ("今天", "今日", "today")),
        ("yesterday", "calendar_day", "day", ("昨天", "昨日", "yesterday")),
        ("tomorrow", "calendar_day", "day", ("明天", "明日", "tomorrow")),
        ("day_after_tomorrow", "calendar_day", "day", ("后天", "後天", "day after tomorrow")),
        (
            "this_week",
            "calendar_week",
            "week",
            ("本周", "这周", "這周", "本星期", "这个星期", "這個星期", "本礼拜", "本禮拜", "this week", "current week"),
        ),
        (
            "last_week",
            "calendar_week",
            "week",
            ("上周", "上週", "上个周", "上個周", "上一周", "上星期", "上个星期", "上個星期", "上礼拜", "上禮拜", "last week", "previous week"),
        ),
        (
            "next_week",
            "calendar_week",
            "week",
            ("下周", "下週", "下个周", "下個周", "下一周", "下星期", "下个星期", "下個星期", "下礼拜", "下禮拜", "next week"),
        ),
        ("this_month", "calendar_month", "month", ("本月", "这个月", "這個月", "当月", "當月", "this month", "current month")),
        ("last_month", "calendar_month", "month", ("上月", "上个月", "上個月", "前一个月", "前一個月", "last month", "previous month")),
        ("next_month", "calendar_month", "month", ("下月", "下个月", "下個月", "next month")),
        ("this_year", "calendar_year", "year", ("今年", "本年", "this year", "current year")),
        ("last_year", "calendar_year", "year", ("去年", "上年", "上一年", "last year", "previous year")),
        ("next_year", "calendar_year", "year", ("明年", "下年", "下一年", "next year")),
    )

    def __init__(self, today: date | None = None) -> None:
        self.today = today or date.today()

    def detect(self, text: str) -> list[dict[str, Any]]:
        request_text = str(text or "")
        if not request_text.strip():
            return []

        matches: list[tuple[int, int, TemporalExpression]] = []
        occupied: list[tuple[int, int]] = []
        for key, normalized_type, granularity, phrases in self._PHRASES:
            for phrase in sorted(phrases, key=len, reverse=True):
                for match in self._iter_phrase_matches(request_text, phrase):
                    start, end = match.span()
                    if any(start < taken_end and end > taken_start for taken_start, taken_end in occupied):
                        continue
                    expression = self._expression_for_key(
                        key=key,
                        matched_text=request_text[start:end],
                        normalized_type=normalized_type,
                        granularity=granularity,
                    )
                    matches.append((start, end, expression))
                    occupied.append((start, end))

        matches.sort(key=lambda item: item[0])
        deduped: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str, str]] = set()
        for _, _, expression in matches:
            payload = expression.to_dict()
            key = (
                payload["text"],
                payload["normalized_type"],
                payload["range_start"],
                payload["range_end"],
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(payload)
        return deduped

    @staticmethod
    def _iter_phrase_matches(text: str, phrase: str):
        if re.fullmatch(r"[A-Za-z][A-Za-z ]*[A-Za-z]", phrase):
            pattern = r"(?<![A-Za-z])" + re.escape(phrase) + r"(?![A-Za-z])"
            yield from re.finditer(pattern, text, flags=re.IGNORECASE)
            return
        yield from re.finditer(re.escape(phrase), text, flags=re.IGNORECASE)

    def _expression_for_key(
        self,
        key: str,
        matched_text: str,
        normalized_type: str,
        granularity: str,
    ) -> TemporalExpression:
        if key == "today":
            start, end = self._day_range(self.today)
        elif key == "yesterday":
            start, end = self._day_range(self.today - timedelta(days=1))
        elif key == "tomorrow":
            start, end = self._day_range(self.today + timedelta(days=1))
        elif key == "day_after_tomorrow":
            start, end = self._day_range(self.today + timedelta(days=2))
        elif key == "this_week":
            start, end = self._week_range(0)
        elif key == "last_week":
            start, end = self._week_range(-1)
        elif key == "next_week":
            start, end = self._week_range(1)
        elif key == "this_month":
            start, end = self._month_range(0)
        elif key == "last_month":
            start, end = self._month_range(-1)
        elif key == "next_month":
            start, end = self._month_range(1)
        elif key == "this_year":
            start, end = self._year_range(0)
        elif key == "last_year":
            start, end = self._year_range(-1)
        elif key == "next_year":
            start, end = self._year_range(1)
        else:
            start, end = self._day_range(self.today)
        return TemporalExpression(
            text=matched_text,
            normalized_type=normalized_type,
            range_start=start,
            range_end=end,
            granularity=granularity,
        )

    @staticmethod
    def _day_range(value: date) -> tuple[str, str]:
        return f"{value.isoformat()}T00:00:00", f"{value.isoformat()}T23:59:59"

    def _week_range(self, offset_weeks: int) -> tuple[str, str]:
        week_start = self.today - timedelta(days=self.today.weekday())
        start = week_start + timedelta(days=7 * offset_weeks)
        end = start + timedelta(days=6)
        return f"{start.isoformat()}T00:00:00", f"{end.isoformat()}T23:59:59"

    def _month_range(self, offset_months: int) -> tuple[str, str]:
        month_index = (self.today.year * 12 + self.today.month - 1) + offset_months
        year = month_index // 12
        month = month_index % 12 + 1
        last_day = calendar.monthrange(year, month)[1]
        return f"{year:04d}-{month:02d}-01T00:00:00", f"{year:04d}-{month:02d}-{last_day:02d}T23:59:59"

    def _year_range(self, offset_years: int) -> tuple[str, str]:
        year = self.today.year + offset_years
        return f"{year:04d}-01-01T00:00:00", f"{year:04d}-12-31T23:59:59"
