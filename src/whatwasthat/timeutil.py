"""시간대 유틸리티.

모든 내부 계산은 UTC epoch로, 사용자 노출은 KST로 처리합니다.
naive datetime은 UTC로 간주하여 머신 의존성을 제거합니다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9), name="KST")
UTC = timezone.utc


def ensure_utc(dt: datetime | None) -> datetime | None:
    """naive datetime은 UTC로 간주하고, aware datetime은 UTC로 변환한다."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def to_kst(dt: datetime | None) -> datetime | None:
    """어떤 timezone이든 KST aware datetime으로 변환한다."""
    utc_dt = ensure_utc(dt)
    if utc_dt is None:
        return None
    return utc_dt.astimezone(KST)


def to_epoch(dt: datetime | None) -> int:
    """머신 독립 epoch를 반환한다. naive datetime은 UTC로 간주한다."""
    utc_dt = ensure_utc(dt)
    if utc_dt is None:
        return 0
    return int(utc_dt.timestamp())


def kst_day_bounds(date_str: str) -> tuple[int, int]:
    """KST 날짜 문자열을 UTC epoch 범위로 변환한다."""
    try:
        day_start = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=KST)
    except ValueError as e:
        raise ValueError(
            f"Invalid date format (expected YYYY-MM-DD): {date_str}",
        ) from e

    day_end = day_start + timedelta(days=1)
    return int(day_start.timestamp()), int(day_end.timestamp())


def format_kst(dt: datetime | None, fmt: str = "%Y-%m-%d %H:%M KST") -> str:
    """KST 기준 사람이 읽기 쉬운 문자열로 포맷한다."""
    kst_dt = to_kst(dt)
    if kst_dt is None:
        return ""
    return kst_dt.strftime(fmt)
