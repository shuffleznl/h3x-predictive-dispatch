"""Electrical connection and circuit-rating helpers."""

from __future__ import annotations

import re

NOMINAL_PHASE_VOLTAGE_V = 230.0
CUSTOM_RATING = "custom"

# Includes common legacy and modern residential service ratings across Europe.
GRID_CONNECTION_RATINGS = (
    "1x25 A",
    "1x35 A",
    "1x40 A",
    "1x63 A",
    "3x16 A",
    "3x20 A",
    "3x25 A",
    "3x32 A",
    "3x35 A",
    "3x40 A",
    "3x50 A",
    "3x63 A",
    "3x80 A",
    CUSTOM_RATING,
)

# The H3X is three-phase, so its dedicated circuit choices are three-phase.
BATTERY_CIRCUIT_RATINGS = (
    "3x10 A",
    "3x13 A",
    "3x16 A",
    "3x20 A",
    "3x25 A",
    "3x32 A",
    "3x40 A",
    CUSTOM_RATING,
)

DEFAULT_GRID_CONNECTION_RATING = "3x25 A"
DEFAULT_BATTERY_CIRCUIT_RATING = "3x20 A"

_RATING_PATTERN = re.compile(r"^(?P<phases>[13])x(?P<amps>\d+) A$")


def rating_power_w(rating: str) -> float | None:
    """Return nominal aggregate real power at unity power factor."""
    match = _RATING_PATTERN.fullmatch(rating)
    if match is None:
        return None
    return (
        float(match.group("phases"))
        * NOMINAL_PHASE_VOLTAGE_V
        * float(match.group("amps"))
    )


def effective_rating_limit_w(rating: str, custom_limit_w: float) -> float:
    """Resolve a selected standard rating or its custom watt fallback."""
    rated_power = rating_power_w(rating)
    return rated_power if rated_power is not None else max(custom_limit_w, 0.0)


def infer_grid_connection_rating(limit_w: float) -> str:
    """Infer a standard selection from a legacy aggregate watt limit."""
    if limit_w <= 0:
        return CUSTOM_RATING
    candidates = {
        rating: rating_power_w(rating)
        for rating in GRID_CONNECTION_RATINGS
        if rating != CUSTOM_RATING
    }
    closest = min(
        candidates,
        key=lambda rating: abs((candidates[rating] or 0.0) - limit_w),
    )
    closest_power = candidates[closest] or 0.0
    if abs(closest_power - limit_w) / limit_w <= 0.05:
        return closest
    return CUSTOM_RATING
