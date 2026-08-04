"""Solcast forecast parsing and price-slot alignment."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from .forecast import ForecastBand


class TimeSlot(Protocol):
    """Minimum slot interface required for forecast alignment."""

    start: datetime
    end: datetime


@dataclass(frozen=True, slots=True)
class SolcastInterval:
    """One normalized Solcast AC-power forecast interval."""

    start: datetime
    end: datetime
    p10_w: float
    p50_w: float
    p90_w: float

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-safe cache representation."""
        data = asdict(self)
        data["start"] = self.start.isoformat()
        data["end"] = self.end.isoformat()
        return data


def parse_solcast_forecasts(payload: Any) -> list[SolcastInterval]:
    """Parse hobbyist and current rooftop-PV Solcast response shapes."""
    if not isinstance(payload, dict):
        return []
    rows = payload.get("forecasts")
    if not isinstance(rows, list):
        return []

    intervals: list[SolcastInterval] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        end = _datetime(row.get("period_end") or row.get("end"))
        if end is None:
            continue
        start = _datetime(row.get("period_start") or row.get("start"))
        if start is None:
            start = end - _duration(row.get("period"))
        if start >= end:
            continue

        p50_kw = _number(row, "pv_estimate", "pv_power_rooftop")
        if p50_kw is None:
            continue
        p10_kw = _number(
            row,
            "pv_estimate10",
            "pv_power_rooftop10",
            default=p50_kw * 0.8,
        )
        p90_kw = _number(
            row,
            "pv_estimate90",
            "pv_power_rooftop90",
            default=p50_kw * 1.2,
        )
        p10_w = max(float(p10_kw) * 1000, 0.0)
        p50_w = max(float(p50_kw) * 1000, 0.0)
        p90_w = max(float(p90_kw) * 1000, p50_w)
        intervals.append(
            SolcastInterval(
                start=start,
                end=end,
                p10_w=min(p10_w, p50_w),
                p50_w=p50_w,
                p90_w=p90_w,
            )
        )
    return sorted(intervals, key=lambda item: item.start)


def restore_solcast_forecasts(rows: Any) -> list[SolcastInterval]:
    """Restore validated forecast intervals from persisted state."""
    if not isinstance(rows, list):
        return []
    restored: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        p50_kw = _cached_watts_to_kw(row.get("p50_w"))
        p10_kw = _cached_watts_to_kw(row.get("p10_w"))
        p90_kw = _cached_watts_to_kw(row.get("p90_w"))
        if p50_kw is None or p10_kw is None or p90_kw is None:
            continue
        restored.append(
            {
                "period_start": row.get("start"),
                "period_end": row.get("end"),
                "period": "PT30M",
                "pv_power_rooftop": p50_kw,
                "pv_power_rooftop10": p10_kw,
                "pv_power_rooftop90": p90_kw,
            }
        )
    payload = {"forecasts": restored}
    return parse_solcast_forecasts(payload)


def align_solcast_forecasts(
    intervals: list[SolcastInterval],
    slots: list[TimeSlot],
) -> list[ForecastBand | None]:
    """Overlap-weight Solcast intervals into arbitrary market slots."""
    aligned: list[ForecastBand | None] = []
    for slot in slots:
        duration = max((slot.end - slot.start).total_seconds(), 0.0)
        if duration <= 0:
            aligned.append(None)
            continue
        totals = [0.0, 0.0, 0.0]
        covered = 0.0
        samples = 0
        for interval in intervals:
            overlap_start = max(slot.start, interval.start)
            overlap_end = min(slot.end, interval.end)
            overlap = max((overlap_end - overlap_start).total_seconds(), 0.0)
            if overlap <= 0:
                continue
            totals[0] += interval.p10_w * overlap
            totals[1] += interval.p50_w * overlap
            totals[2] += interval.p90_w * overlap
            covered += overlap
            samples += 1
        if covered <= 0:
            aligned.append(None)
            continue
        coverage = min(covered / duration, 1.0)
        aligned.append(
            ForecastBand(
                p10_w=totals[0] / covered,
                p50_w=totals[1] / covered,
                p90_w=totals[2] / covered,
                samples=samples,
                confidence=round(0.9 * coverage, 3),
            )
        )
    return aligned


def _number(
    row: dict[str, Any],
    *keys: str,
    default: float | None = None,
) -> float | None:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return default


def _cached_watts_to_kw(value: Any) -> float | None:
    try:
        return float(value) / 1000
    except (TypeError, ValueError):
        return None


def _datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _duration(value: Any) -> timedelta:
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?", str(value or "PT30M"))
    if not match:
        return timedelta(minutes=30)
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    duration = timedelta(hours=hours, minutes=minutes)
    return duration if duration.total_seconds() > 0 else timedelta(minutes=30)
