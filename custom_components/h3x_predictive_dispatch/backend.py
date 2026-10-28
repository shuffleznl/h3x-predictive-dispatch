"""Bind economic dispatch to the official integration's registered entities."""

from __future__ import annotations

OFFICIAL_DOMAIN = "pylontech_fh3x"
REFERENCE_KEY = "charge_discharge_power_reference"
OFFICIAL_KEYS = {
    "ems_mode_entity": "ems_mode",
    "power_ref_entity": REFERENCE_KEY,
    "soc_entity": "battery_soc",
    "battery_power_entity": "battery_power",
    "inverter_rated_power_entity": "parallel_pcs_rated_power",
    "load_power_entity": "load_power",
    "battery_module_count_entity": "bms_module_count",
    "battery_system_capacity_entity": "battery_capacity",
    "bms_temperature_entity": "bms_temperature",
    "charge_limit_soc_entity": "charge_limit_soc",
    "discharge_limit_soc_entity": "eps_limit_soc_on_grid",
}
LEGACY_DOMAINS = {"pylontech_h3x_bridge", "force_h3x_bridge"}


def field(entry, key):
    return entry.get(key) if isinstance(entry, dict) else getattr(entry, key, None)


def official_bindings(entries, settings):
    """Resolve exact unique IDs for one device; preserve explicit other backends."""
    entries = list(entries)
    by_id = {field(entry, "entity_id"): entry for entry in entries}
    configured_ref = str(settings.get("power_ref_entity") or "")
    selected = by_id.get(configured_ref)
    if (
        configured_ref
        and selected is None
        and not any(f".{domain}_" in configured_ref for domain in LEGACY_DOMAINS)
    ):
        return {}
    if selected and field(selected, "platform") not in LEGACY_DOMAINS | {
        OFFICIAL_DOMAIN
    }:
        return {}
    candidates = [
        entry
        for entry in entries
        if field(entry, "platform") == OFFICIAL_DOMAIN
        and str(field(entry, "unique_id")).endswith("_" + REFERENCE_KEY)
        and str(field(entry, "entity_id")).startswith("number.")
    ]
    if selected and field(selected, "platform") == OFFICIAL_DOMAIN:
        candidates = [
            entry
            for entry in candidates
            if field(entry, "config_entry_id") == field(selected, "config_entry_id")
        ]
    if len(candidates) != 1:
        return {}
    reference = candidates[0]
    prefix = str(field(reference, "unique_id")).removesuffix("_" + REFERENCE_KEY) + "_"
    device = {
        str(field(entry, "unique_id"))[len(prefix) :]: field(entry, "entity_id")
        for entry in entries
        if field(entry, "platform") == OFFICIAL_DOMAIN
        and field(entry, "config_entry_id") == field(reference, "config_entry_id")
        and str(field(entry, "unique_id")).startswith(prefix)
    }

    def replaceable(option):
        entity_id = str(settings.get(option) or "")
        existing = by_id.get(entity_id)
        if not entity_id:
            return True
        if existing is not None:
            return field(existing, "platform") in LEGACY_DOMAINS
        return any(f".{domain}_" in entity_id for domain in LEGACY_DOMAINS)

    updates = {}
    for option, key in OFFICIAL_KEYS.items():
        if (
            key in device
            and replaceable(option)
            and settings.get(option) != device[key]
        ):
            updates[option] = device[key]
    if replaceable("battery_usable_capacity_entity") and settings.get(
        "battery_usable_capacity_entity"
    ):
        # Official battery_capacity is nominal; usable energy remains a derived value.
        updates["battery_usable_capacity_entity"] = ""
    for option in ("user_ems_mode", "idle_ems_mode"):
        if settings.get(option) in {None, "", "User mode", "Self-Consumption"}:
            updates[option] = "user"
    return updates


def resolve_ems_option(requested, available):
    """Match actual select options, including stored legacy translated labels."""

    def canonical(value):
        normalized = "".join(
            character for character in str(value).lower() if character.isalnum()
        )
        return normalized.removesuffix("mode")

    if requested in available:
        return requested
    matches = [value for value in available if canonical(value) == canonical(requested)]
    if len(matches) != 1:
        raise ValueError(
            f"EMS option {requested!r} is not supported by the selected device"
        )
    return matches[0]
