"""Shelly Pro 3EM entity discovery helpers."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er


def autodetect_shelly_total_active_power(hass: HomeAssistant) -> str:
    """Return an unambiguous Shelly total active-power sensor entity ID."""
    registry = er.async_get(hass)
    strong_candidates: set[str] = set()
    named_candidates: set[str] = set()

    for state in hass.states.async_all("sensor"):
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
