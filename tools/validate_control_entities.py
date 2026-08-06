#!/usr/bin/env python3
"""Validate runtime control entities and options-flow compatibility."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "h3x_predictive_dispatch"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def literal_assignments(source: str) -> dict[str, object]:
    """Return top-level literal assignments from a Python source string."""
    tree = ast.parse(source)
    values: dict[str, object] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        try:
            values[node.targets[0].id] = ast.literal_eval(node.value)
        except (ValueError, SyntaxError):
            continue
    return values


def main() -> None:
    const_source = read(INTEGRATION / "const.py")
    config_flow_source = read(INTEGRATION / "config_flow.py")
    init_source = read(INTEGRATION / "__init__.py")
    coordinator_source = read(INTEGRATION / "coordinator.py")
    optimizer_source = read(INTEGRATION / "optimizer.py")
    sensor_source = read(INTEGRATION / "sensor.py")

    repository_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in ROOT.rglob("*")
        if path.is_file()
        and ".git" not in path.parts
        and "__pycache__" not in path.parts
        and path.suffix.lower() in {".py", ".json", ".md", ".yaml", ".yml"}
    ).lower()
    for retired_reference in (
        "ds" + "mr",
        "currently" + "_delivered",
        "connect" + "_energy_meter",
    ):
        if retired_reference in repository_text:
            raise AssertionError(
                f"retired meter reference remains: {retired_reference}"
            )

    for platform in ("Platform.NUMBER", "Platform.SELECT", "Platform.SWITCH"):
        if platform not in const_source:
            raise AssertionError(f"{platform} missing from PLATFORMS")

    for filename in ("number.py", "select.py", "switch.py"):
        path = INTEGRATION / filename
        if not path.exists():
            raise AssertionError(f"missing {filename}")
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    if "return H3XPredictiveDispatchOptionsFlow()" not in config_flow_source:
        raise AssertionError("options flow must use Home Assistant-managed config_entry")
    if "self.config_entry = config_entry" in config_flow_source:
        raise AssertionError("options flow must not assign self.config_entry")
    if "_apply_profile_when_changed" not in config_flow_source:
        raise AssertionError("options flow must apply changed strategy profiles")
    if "add_update_listener(async_options_updated)" not in init_source:
        raise AssertionError("options updates must refresh in place")
    if "async_reload_entry" in init_source:
        raise AssertionError("options changes should not force a full reload")

    for token in (
        "CONF_STRATEGY_PROFILE",
        "STRATEGY_PROFILE_SETTINGS",
        "async_apply_strategy_profile",
        "async_set_option",
        "async_options_updated",
        "terminal_soc_mode",
        "strategy_profile",
        "discharge_power_mode",
        "discharge_spread_price_tolerance",
        "discharge_spread_max_hours",
        "grid_import_power_entity",
        "grid_import_measurement_source",
        "grid_import_average_source",
        "grid_import_trend_w_per_min",
        "shelly_total_power_entity",
        "shelly_phase_a_power_entity",
        "shelly_phase_b_power_entity",
        "shelly_phase_c_power_entity",
        "solar_power_entity",
        "pv_orientation",
        "pv_panel_count",
        "pv_panel_wp",
        "pv_inverter_limit_w",
        "battery_module_count",
        "battery_module_count_entity",
        "battery_system_capacity_entity",
        "battery_usable_capacity_entity",
        "battery_system_capacity_kwh",
        "battery_usable_capacity_kwh",
        "battery_usable_depth_of_discharge",
        "battery_capacity_warning",
        "battery_capacity_unconfirmed",
        "max_charge_c_rate",
        "max_discharge_c_rate",
        "_power_state_w",
        "_energy_state_kwh",
        "_price_rows_from_response",
        "_ensure_capacity_attributes",
        "_battery_capacity_attributes",
        "_run_predictive_optimizer",
        "_battery_configuration",
        "_home_load_power_w",
        "_solar_forecast_for_slots",
        "_async_refresh_grid_import_trend",
        "_async_refresh_solcast_forecast",
    ):
        if token not in coordinator_source and token not in const_source:
            raise AssertionError(f"{token} missing from control wiring")

    for token in ("_net_cost", "_risk_adjusted_grid_cost", "_grid_feasible"):
        if token not in optimizer_source:
            raise AssertionError(f"{token} missing from optimizer wiring")

    if 'key="reason"' not in sensor_source:
        raise AssertionError("decision reason sensor is missing")
    if 'key="control_enabled"' not in read(INTEGRATION / "switch.py"):
        raise AssertionError("automatic control switch is missing")
    if 'key="ev_discharge_block"' not in read(INTEGRATION / "switch.py"):
        raise AssertionError("EV discharge-block switch is missing")
    if "CONF_BATTERY_CAPACITY_KWH: 20.0" in const_source:
        raise AssertionError("old 20 kWh scaffold capacity must not be the default")
    if "FORCE_H3_MODULE_CAPACITY_KWH = 5.12" not in const_source:
        raise AssertionError("Force H3 module capacity constant is missing")
    if "FORCE_H3_USABLE_DOD = 0.95" not in const_source:
        raise AssertionError("Force H3 usable depth-of-discharge constant is missing")
    if "FORCE_H3_SYSTEM_CAPACITY_KWH" not in const_source:
        raise AssertionError("Force H3 system capacity table is missing")
    if "FORCE_H3_USABLE_CAPACITY_KWH" not in const_source:
        raise AssertionError("Force H3 usable capacity table is missing")
    assignments = literal_assignments(const_source)
    system_capacity = assignments["FORCE_H3_SYSTEM_CAPACITY_KWH"]
    usable_capacity = assignments["FORCE_H3_USABLE_CAPACITY_KWH"]
    usable_dod = float(assignments["FORCE_H3_USABLE_DOD"])
    expected_modules = set(range(2, 8))
    if set(system_capacity) != expected_modules:
        raise AssertionError("system capacity table must cover 2-7 modules")
    if set(usable_capacity) != expected_modules:
        raise AssertionError("usable capacity table must cover 2-7 modules")
    if usable_dod != 0.95:
        raise AssertionError("usable DoD must match the Force H3 datasheet")
    for modules in expected_modules:
        theoretical = round(float(system_capacity[modules]) * usable_dod, 2)
        actual = float(usable_capacity[modules])
        deviation = abs(actual - theoretical) / theoretical * 100
        if deviation > 5.0:
            raise AssertionError(
                f"usable capacity for {modules} modules differs by {deviation:.2f}%"
            )
    if '"version": "0.2.10"' not in read(INTEGRATION / "manifest.json"):
        raise AssertionError("manifest version must be 0.2.10")
    if "CONF_CONTROL_ENABLED: False" not in const_source:
        raise AssertionError("standalone coexistence build must default control to off")
    if "configured and configured.lower() != \"auto\"" not in coordinator_source:
        raise AssertionError("stale Nord Pool config entries must fall back to auto")
    if "\"get_prices_for_date\"" not in coordinator_source:
        raise AssertionError("Nord Pool price fetch must fall back to hourly prices")
    if "{CONF_NORDPOOL_CONFIG_ENTRY: entry.entry_id}" in config_flow_source:
        raise AssertionError("setup defaults must not persist a volatile Nord Pool entry id")
    if "VERSION = 7" not in config_flow_source:
        raise AssertionError("config flow version must migrate obsolete sensor settings")
    if "CONFIG_ENTRY_VERSION = 7" not in init_source:
        raise AssertionError("config entry version must migrate Shelly grid monitoring")
    if "_migrate_dashboard_entity_ids(hass, entry)" not in init_source:
        raise AssertionError("stable dashboard entity IDs must be migrated")
    if 'self.entity_id = f"sensor.{object_id}"' not in sensor_source:
        raise AssertionError("new dashboard sensors must request their stable entity IDs")
    if 'DEFAULT_GRID_IMPORT_POWER_ENTITY = ""' not in const_source:
        raise AssertionError("grid monitoring must not default to a retired meter")
    if "_grid_import_measurement" not in coordinator_source:
        raise AssertionError("Shelly grid source resolver is missing")
    if "self._grid_connection_limit_w()" not in coordinator_source:
        raise AssertionError("selected grid rating must constrain dispatch")
    if "limits = [economic_limit, self._battery_circuit_limit_w()]" not in coordinator_source:
        raise AssertionError("battery circuit rating must cap charge and discharge")
    if "infer_grid_connection_rating" not in init_source:
        raise AssertionError("legacy watt limits must migrate to a rating selection")
    if "autodetect_shelly_total_active_power" not in coordinator_source:
        raise AssertionError("entity-registry Shelly discovery is missing")
    if "autodetect_sma_pv_power" not in coordinator_source:
        raise AssertionError("entity-registry SMA PV discovery is missing")
    if "SelectSelectorConfig(options=list(EMS_MODE_OPTIONS))" not in config_flow_source:
        raise AssertionError("EMS mode settings must use dropdown selectors")
    if "EntitySelectorConfig(domain=\"select\")" not in config_flow_source:
        raise AssertionError("EMS mode entity must use an entity selector")
    if "forecast_index = 1 if len(future_slots) > 1 else None" not in coordinator_source:
        raise AssertionError("forecast power sensors must represent the next slot")
    for stable_attribute in (
        "economic_grid_charge_power_w",
        "live_solar_surplus_power_w",
        "forecast_power_slot_start",
        "grid_net_power_w",
    ):
        if stable_attribute not in sensor_source:
            raise AssertionError(
                f"stable dashboard attribute is missing: {stable_attribute}"
            )
    for sensor_key in (
        "economic_grid_charge_power",
        "live_solar_surplus_power",
        "grid_net_power",
        "grid_import_power",
        "grid_import_average_power",
        "grid_import_trend",
        "grid_charge_headroom",
        "ev_charger_power",
        "battery_supported_load_power",
        "ev_discharge_status",
    ):
        if f'key="{sensor_key}"' not in sensor_source:
            raise AssertionError(f"dashboard sensor is missing: {sensor_key}")
    if "_normalize_resolution(user_input)" not in config_flow_source:
        raise AssertionError("config flow must normalize the submitted resolution")
    if "async_migrate_entry" not in init_source:
        raise AssertionError("version 1 entries need a resolution migration")
    if "data[CONF_RESOLUTION] = resolution" not in init_source:
        raise AssertionError("migration must persist the configured resolution")
    if "data.pop(CONF_GRID_IMPORT_AVERAGE_POWER_ENTITY, None)" not in init_source:
        raise AssertionError("migration must remove the obsolete average sensor")
    if "CONF_GRID_IMPORT_AVERAGE_POWER_ENTITY" in config_flow_source:
        raise AssertionError("external average power must not appear in config flow")
    if "_configured_resolution_minutes" not in coordinator_source:
        raise AssertionError("coordinator must expose configured resolution fallback")
    if 'key="discharge_power_mode"' not in read(INTEGRATION / "select.py"):
        raise AssertionError("discharge power mode select is missing")
    if 'key="pv_orientation"' not in read(INTEGRATION / "select.py"):
        raise AssertionError("PV orientation select is missing")
    if 'key="solar_forecast_source"' not in read(INTEGRATION / "select.py"):
        raise AssertionError("solar forecast source select is missing")
    for token in ('key="grid_connection_rating"', 'key="battery_circuit_rating"'):
        if token not in read(INTEGRATION / "select.py"):
            raise AssertionError(f"electrical rating select is missing: {token}")
    number_source = read(INTEGRATION / "number.py")
    for token in (
        "battery_module_count",
        "discharge_spread_price_tolerance",
        "discharge_spread_max_hours",
        "max_charge_c_rate",
        "max_discharge_c_rate",
        "pv_panel_count",
        "pv_panel_wp",
        "pv_inverter_limit",
        "solcast_update_interval",
        "grid_import_limit",
        "grid_export_limit",
        "battery_circuit_limit",
    ):
        if token not in number_source:
            raise AssertionError(f"{token} number control is missing")
    for token in (
        'key="battery_system_capacity"',
        'key="battery_usable_capacity"',
        'key="target_c_rate"',
        'key="next_charge_slot"',
        'key="next_discharge_slot"',
        'key="periodic_full_charge_slot"',
        'key="price_trend"',
        'key="home_load_power"',
        'key="solar_power"',
        'key="grid_net_power"',
        'key="forecast_load_power"',
        'key="forecast_solar_power"',
        'key="planned_grid_charge_energy"',
        'key="planned_solar_charge_energy"',
        'key="planned_self_consumption_energy"',
        'key="planned_battery_export_energy"',
        'key="grid_import_power"',
        'key="grid_import_average_power"',
        'key="grid_import_trend"',
        'key="grid_charge_headroom"',
        'key="grid_diagnostics_status"',
        'key="grid_connection_capacity"',
        'key="battery_circuit_capacity"',
        'key="ev_charger_power"',
        'key="battery_supported_load_power"',
        'key="ev_discharge_status"',
    ):
        if token not in sensor_source:
            raise AssertionError(f"{token} sensor is missing")
    for token in (
        "_finalize_decision_diagnostics",
        "_attach_plan_summaries",
        "_price_trend_slots",
        "_price_trend_attributes",
    ):
        if token not in coordinator_source:
            raise AssertionError(f"{token} coordinator helper is missing")

    for token in (
        "CONF_BLOCK_DISCHARGE_WHILE_EV_CHARGING",
        "ev_discharge_block_active",
        "battery_supported_load_power_w",
        "discharge_allowed=not",
    ):
        if token not in coordinator_source and token not in const_source:
            raise AssertionError(f"EV discharge protection is missing: {token}")
    if "settings.discharge_allowed and slot.discharge_allowed" not in optimizer_source:
        raise AssertionError("optimizer must enforce per-slot EV discharge protection")


if __name__ == "__main__":
    main()
