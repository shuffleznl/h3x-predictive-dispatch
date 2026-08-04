"""Power-meter and inverter entity discovery helpers."""

from __future__ import annotations

import math

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

UNAVAILABLE_STATES = {"", "unknown", "unavailable", "none"}


def entity_has_numeric_state(hass: HomeAssistant, entity_id: str) -> bool:
    """Return whether an entity currently exposes a finite numeric state."""
    state = hass.states.get(entity_id)
    return _state_is_numeric(state)


def _state_is_numeric(state: object | None) -> bool:
    """Return whether a state-like object contains a finite number."""
    if state is None:
        return False
    value = getattr(state, "state", None)
    if str(value).strip().lower() in UNAVAILABLE_STATES:
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def autodetect_shelly_total_active_power(hass: HomeAssistant) -> str:
    """Return an unambiguous Shelly total active-power sensor entity ID."""
    registry = er.async_get(hass)
    strong_candidates: set[str] = set()
    named_candidates: set[str] = set()

    for state in hass.states.async_all("sensor"):
        if not _state_is_numeric(state):
            continue
        attributes = state.attributes or {}
        if str(attributes.get("device_class") or "").lower() != "power":
            continue

        registry_entry = registry.async_get(state.entity_id)
        platform = str(getattr(registry_entry, "platform", "") or "").lower()
        unique_id = str(getattr(registry_entry, "unique_id", "") or "").lower()
        original_name = str(
            getattr(registry_entry, "original_name", "") or ""
        ).lower()
        identity = " ".join(
            (
                state.entity_id,
                str(attributes.get("friendly_name") or ""),
                original_name,
                unique_id,
            )
        ).lower()

        if platform == "shelly" and "total_act_power" in unique_id:
            strong_candidates.add(state.entity_id)
            continue
        if (
            (platform == "shelly" or "shelly" in identity)
            and (
                "total_act_power" in identity
                or all(token in identity for token in ("total", "active", "power"))
            )
        ):
            named_candidates.add(state.entity_id)

    candidates = strong_candidates or named_candidates
    return next(iter(candidates)) if len(candidates) == 1 else ""


def autodetect_sma_pv_power(hass: HomeAssistant) -> str:
    """Return an unambiguous SMA AC-side PV power sensor entity ID."""
    registry = er.async_get(hass)
    strong_candidates: set[str] = set()
    named_candidates: set[str] = set()

    for state in hass.states.async_all("sensor"):
        if not _state_is_numeric(state):
            continue
        attributes = state.attributes or {}
        if str(attributes.get("device_class") or "").lower() != "power":
            continue

        registry_entry = registry.async_get(state.entity_id)
        platform = str(getattr(registry_entry, "platform", "") or "").lower()
        unique_id = str(getattr(registry_entry, "unique_id", "") or "").lower()
        original_name = str(
            getattr(registry_entry, "original_name", "") or ""
        ).lower()
        identity = " ".join(
            (
                state.entity_id,
                str(attributes.get("friendly_name") or ""),
                original_name,
                unique_id,
            )
        ).lower()

        if platform == "sma" and (
            unique_id.endswith(("_pv_power", "-pv_power"))
            or unique_id == "pv_power"
        ):
            strong_candidates.add(state.entity_id)
            continue
        if platform == "sma" and (
            "pv_power" in identity or "pv power" in identity
        ):
            named_candidates.add(state.entity_id)

    candidates = strong_candidates or named_candidates
    return next(iter(candidates)) if len(candidates) == 1 else ""
