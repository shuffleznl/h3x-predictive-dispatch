#!/usr/bin/env python3
"""Validate PV/load self-consumption optimizer wiring."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "h3x_energy_arbitrage"


def read(path: Path) -> str:
    """Read a UTF-8 source file."""
    return path.read_text(encoding="utf-8")


def main() -> None:
    """Run static wiring checks."""
    const_source = read(INTEGRATION / "const.py")
    config_source = read(INTEGRATION / "config_flow.py")
    coordinator_source = read(INTEGRATION / "coordinator.py")
    forecast_source = read(INTEGRATION / "forecast.py")
    optimizer_source = read(INTEGRATION / "optimizer.py")
    sensor_source = read(INTEGRATION / "sensor.py")
    number_source = read(INTEGRATION / "number.py")
    select_source = read(INTEGRATION / "select.py")

    for path in INTEGRATION.glob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    for token in (
        "CONF_SHELLY_TOTAL_POWER_ENTITY",
        "CONF_SHELLY_PHASE_A_POWER_ENTITY",
        "CONF_SHELLY_PHASE_B_POWER_ENTITY",
        "CONF_SHELLY_PHASE_C_POWER_ENTITY",
        "CONF_SOLAR_POWER_ENTITY",
        "CONF_PV_ORIENTATION",
        "CONF_PV_PANEL_COUNT",
        "CONF_PV_PANEL_WP",
        "CONF_PV_INVERTER_LIMIT_W",
        "PV_ORIENTATIONS",
    ):
        if token not in const_source:
            raise AssertionError(f"{token} missing from constants")
        if token not in config_source and token != "PV_ORIENTATIONS":
            raise AssertionError(f"{token} missing from config flow")

    for token in (
        "_home_load_power_w",
        "_forecast_load",
        "_solar_forecast_for_slots",
        "_solar_forecast_bands",
        "_solar_power_model_w",
        "_daylight_hours",
        "_solar_noon_hour",
        "_run_predictive_optimizer",
        "_grid_charge_headroom_w",
        "solar surplus forecast",
    ):
        if token not in coordinator_source:
            raise AssertionError(f"{token} missing from coordinator wiring")

    for token in (
        "_risk_adjusted_grid_cost",
        "_grid_feasible",
        "baseline_cost",
        "estimated_savings",
        "grid_charge_kwh",
        "solar_charge_kwh",
        "self_consumption_kwh",
        "battery_export_kwh",
    ):
        if token not in optimizer_source:
            raise AssertionError(f"{token} missing from predictive optimizer")

    for token in ("HistoricalLoadForecaster", "ev_sessions", "p10_w", "p90_w"):
        if token not in forecast_source:
            raise AssertionError(f"{token} missing from load forecast")

    for token in (
        "load_forecast",
        "solar_forecast",
        "planned_grid_charge_energy",
        "planned_solar_charge_energy",
        "planned_self_consumption_energy",
        "planned_battery_export_energy",
        "forecast_load_energy",
        "forecast_solar_energy",
    ):
        if token not in sensor_source:
            raise AssertionError(f"{token} missing from sensor wiring")

    for token in ("pv_panel_count", "pv_panel_wp", "pv_inverter_limit"):
        if token not in number_source:
            raise AssertionError(f"{token} missing from number controls")
    if "pv_orientation" not in select_source:
        raise AssertionError("pv_orientation select is missing")


if __name__ == "__main__":
    main()
