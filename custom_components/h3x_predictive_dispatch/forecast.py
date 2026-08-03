"""Robust local load and EV forecasting for quarter-hour dispatch."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from statistics import median
from typing import Protocol


class TimeSlot(Protocol):
    """Minimum interface required from a market slot."""

    start: datetime
    end: datetime


@dataclass(frozen=True, slots=True)
class PowerObservation:
    """One historical average-power observation."""

    timestamp: datetime
    load_w: float
    ev_w: float | None = None


@dataclass(frozen=True, slots=True)
class ForecastBand:
    """Probabilistic power forecast for one interval."""

    p10_w: float
    p50_w: float
    p90_w: float
    samples: int
    confidence: float
    ev_w: float = 0.0


@dataclass(frozen=True, slots=True)
class ForecastMetrics:
    """Diagnostics for a fitted historical forecast."""

    observations: int
    days_covered: int
    mae_w: float | None
    bias_w: float | None
    ev_sessions: int
    source: str


@dataclass(frozen=True, slots=True)
class LoadForecast:
    """Forecast result and quality metadata."""

    bands: list[ForecastBand]
    metrics: ForecastMetrics


def _percentile(values: list[float], percentile: float) -> float:
    """Return a linearly interpolated percentile without external packages."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = min(max(percentile, 0.0), 100.0) / 100 * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _slot_index(timestamp: datetime) -> int:
    """Return the local quarter-hour index for a timestamp."""
    return timestamp.hour * 4 + timestamp.minute // 15


def _day_class(timestamp: datetime) -> int:
    """Separate weekdays and weekends while retaining weekday proximity."""
    return 1 if timestamp.weekday() >= 5 else 0


class HistoricalLoadForecaster:
    """Recency-weighted robust ensemble with optional EV separation.

    The forecaster intentionally uses transparent local statistics instead of a
    black-box model. Heat pumps, hot-water cycles and occupancy peaks are learned
    through weekday/weekend and quarter-hour seasonality. Extreme observations
    are retained in the uncertainty band but have limited influence on p50.
    """

    def __init__(
        self,
        observations: Iterable[PowerObservation],
        *,
        ev_mode: str = "detect",
        ev_threshold_w: float = 2800.0,
    ) -> None:
        self._observations = sorted(observations, key=lambda row: row.timestamp)
        self._ev_mode = ev_mode
        self._ev_threshold_w = max(ev_threshold_w, 500.0)
        self._residuals: list[float] = []
        self._ev_sessions = 0

    def forecast(
        self,
        slots: list[TimeSlot],
        *,
        current_load_w: float | None,
        current_ev_w: float | None = None,
    ) -> LoadForecast:
        """Forecast slots and expose confidence/error diagnostics."""
        if not slots:
            return LoadForecast([], self._metrics("historical_empty"))
        if len(self._observations) < 96:
            fallback = max(current_load_w or 0.0, 0.0)
            bands = [ForecastBand(fallback, fallback, fallback, 0, 0.0) for _ in slots]
            return LoadForecast(bands, self._metrics("live_flat_insufficient_history"))

        cleaned = self._separate_ev_load()
        latest = self._observations[-1].timestamp
        buckets: dict[tuple[int, int], list[tuple[float, float]]] = {}
        broad: dict[int, list[tuple[float, float]]] = {}
        for timestamp, base_w, _ev_w in cleaned:
            age_days = max((latest - timestamp).total_seconds() / 86400, 0.0)
            recency = math.exp(-age_days / 14.0)
            key = (_day_class(timestamp), _slot_index(timestamp))
            buckets.setdefault(key, []).append((base_w, recency))
            broad.setdefault(_slot_index(timestamp), []).append((base_w, recency * 0.55))

        raw_bands: list[ForecastBand] = []
        for slot in slots:
            midpoint = slot.start + (slot.end - slot.start) / 2
            exact = buckets.get((_day_class(midpoint), _slot_index(midpoint)), [])
            candidates = exact if len(exact) >= 3 else exact + broad.get(_slot_index(midpoint), [])
            values = self._weighted_expand(candidates)
            if not values:
                values = [max(current_load_w or 0.0, 0.0)]
            ev_w = self._expected_ev_power(midpoint, cleaned, current_ev_w)
            p10 = _percentile(values, 10) + ev_w
            p50 = _percentile(values, 50) + ev_w
            p90 = _percentile(values, 90) + ev_w
            confidence = min(len(exact) / 10.0, 1.0)
            raw_bands.append(
                ForecastBand(
                    p10_w=max(p10, 0.0),
                    p50_w=max(p50, 0.0),
                    p90_w=max(p90, p50, 0.0),
                    samples=len(exact),
                    confidence=confidence,
                    ev_w=max(ev_w, 0.0),
                )
            )

        bands = self._apply_live_residual(raw_bands, current_load_w)
        self._calculate_backtest_residuals(cleaned)
        return LoadForecast(bands, self._metrics("historical_robust_ensemble"))

    @staticmethod
    def _weighted_expand(values: list[tuple[float, float]]) -> list[float]:
        """Approximate weighted quantiles with a bounded deterministic expansion."""
        expanded: list[float] = []
        for value, weight in values:
            copies = max(1, min(round(weight * 10), 10))
            expanded.extend([max(value, 0.0)] * copies)
        return expanded

    def _separate_ev_load(self) -> list[tuple[datetime, float, float]]:
        """Separate explicit or detected EV power from normal household demand."""
        rows: list[tuple[datetime, float, float]] = []
        active = False
        sessions = 0
        recent_base: list[float] = []
        for observation in self._observations:
            load_w = max(observation.load_w, 0.0)
            if self._ev_mode == "off":
                ev_w = 0.0
            elif self._ev_mode == "sensor" and observation.ev_w is not None:
                ev_w = min(max(observation.ev_w, 0.0), load_w)
            else:
                baseline = median(recent_base[-32:]) if recent_base else min(load_w, 800.0)
                excess = max(load_w - baseline, 0.0)
                ev_w = excess if excess >= self._ev_threshold_w else 0.0
            is_active = ev_w >= self._ev_threshold_w
            if is_active and not active:
                sessions += 1
            active = is_active
            base_w = max(load_w - ev_w, 0.0)
            recent_base.append(base_w)
            rows.append((observation.timestamp, base_w, ev_w))
        self._ev_sessions = sessions
        return rows

    def _expected_ev_power(
        self,
        target: datetime,
        rows: list[tuple[datetime, float, float]],
        current_ev_w: float | None,
    ) -> float:
        """Return probability-weighted EV power for the target quarter."""
        if self._ev_mode == "off":
            return 0.0
        if current_ev_w is not None and target.date() == datetime.now(target.tzinfo).date():
            delta_h = (target - datetime.now(target.tzinfo)).total_seconds() / 3600
            if -0.25 <= delta_h <= 1.0 and current_ev_w >= self._ev_threshold_w:
                return max(current_ev_w, 0.0)
        matching_days: set[object] = set()
        active_values: list[float] = []
        for timestamp, _base_w, ev_w in rows:
            if _day_class(timestamp) != _day_class(target):
                continue
            if _slot_index(timestamp) != _slot_index(target):
                continue
            matching_days.add(timestamp.date())
            if ev_w >= self._ev_threshold_w:
                active_values.append(ev_w)
        possible_days = max(len({row[0].date() for row in rows if _day_class(row[0]) == _day_class(target)}), 1)
        probability = min(len(matching_days) / possible_days, 1.0)
        active_power = median(active_values) if active_values else 0.0
        return active_power * probability

    @staticmethod
    def _apply_live_residual(
        bands: list[ForecastBand], current_load_w: float | None
    ) -> list[ForecastBand]:
        """Blend the current deviation out over two hours."""
        if not bands or current_load_w is None:
            return bands
        residual = current_load_w - bands[0].p50_w
        corrected: list[ForecastBand] = []
        for index, band in enumerate(bands):
            gain = max(1.0 - index / 8.0, 0.0) * 0.75
            adjustment = residual * gain
            corrected.append(
                ForecastBand(
                    p10_w=max(band.p10_w + adjustment, 0.0),
                    p50_w=max(band.p50_w + adjustment, 0.0),
                    p90_w=max(band.p90_w + adjustment, 0.0),
                    samples=band.samples,
                    confidence=band.confidence,
                    ev_w=band.ev_w,
                )
            )
        return corrected

    def _calculate_backtest_residuals(
        self, rows: list[tuple[datetime, float, float]]
    ) -> None:
        """Compute a cheap leave-recent-day-out forecast score."""
        if len(rows) < 7 * 24:
            return
        cutoff = rows[-1][0].date()
        training = [row for row in rows if row[0].date() != cutoff]
        test = [row for row in rows if row[0].date() == cutoff]
        by_slot: dict[tuple[int, int], list[float]] = {}
        for timestamp, base_w, ev_w in training:
            by_slot.setdefault((_day_class(timestamp), _slot_index(timestamp)), []).append(base_w + ev_w)
        self._residuals = []
        for timestamp, base_w, ev_w in test:
            values = by_slot.get((_day_class(timestamp), _slot_index(timestamp)), [])
            if values:
                self._residuals.append(base_w + ev_w - median(values))

    def _metrics(self, source: str) -> ForecastMetrics:
        """Build forecast quality metadata."""
        dates = {row.timestamp.date() for row in self._observations}
        mae = (
            sum(abs(value) for value in self._residuals) / len(self._residuals)
            if self._residuals
            else None
        )
        bias = (
            sum(self._residuals) / len(self._residuals)
            if self._residuals
            else None
        )
        return ForecastMetrics(
            observations=len(self._observations),
            days_covered=len(dates),
            mae_w=mae,
            bias_w=bias,
            ev_sessions=self._ev_sessions,
            source=source,
        )


def select_risk_forecast(band: ForecastBand, percentile: float) -> float:
    """Interpolate p50..p90 according to the configured risk percentile."""
    percentile = min(max(percentile, 50.0), 90.0)
    fraction = (percentile - 50.0) / 40.0
    return band.p50_w + (band.p90_w - band.p50_w) * fraction
