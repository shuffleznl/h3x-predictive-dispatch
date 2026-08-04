#!/usr/bin/env python3
"""Validate the standalone predictive dashboard namespace and controls."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboards" / "h3x-predictive-dispatch.yaml"
PACKAGED_DASHBOARD = (
    ROOT
    / "custom_components"
    / "h3x_predictive_dispatch"
    / "dashboards"
    / "h3x-predictive-dispatch.yaml"
)


def main() -> None:
    """Reject cross-domain entity collisions and missing predictive controls."""
    source = DASHBOARD.read_text(encoding="utf-8")
    if not PACKAGED_DASHBOARD.exists():
        raise AssertionError("HACS-packaged predictive dashboard is missing")
    if PACKAGED_DASHBOARD.read_text(encoding="utf-8") != source:
        raise AssertionError("repository and HACS-packaged dashboards differ")
    if "Shelly Pro 3EM grid trend and limits" not in source:
        raise AssertionError("dashboard must identify the Shelly grid source")
    required = (
        "title: H3X Predictive Dispatch",
        "sensor.pylontech_h3x_predictive_dispatch_decision",
        "sensor.pylontech_h3x_predictive_dispatch_baseline_grid_cost",
        "sensor.pylontech_h3x_predictive_dispatch_optimized_grid_cost",
        "select.pylontech_h3x_predictive_dispatch_load_forecast_mode",
        "select.pylontech_h3x_predictive_dispatch_ev_forecast_mode",
        "switch.pylontech_h3x_predictive_dispatch_automatic_control",
        "select.pylontech_h3x_predictive_dispatch_solar_forecast_source",
        "switch.pylontech_h3x_predictive_dispatch_dutch_retail_tariff",
        "number.pylontech_h3x_predictive_dispatch_forecast_risk_percentile",
        "number.pylontech_h3x_predictive_dispatch_minimum_action_duration",
        "type: history-graph",
        "attribute: solcast_fetched_at",
        "sensor.pylontech_h3x_predictive_dispatch_grid_import_power",
        "sensor.pylontech_h3x_predictive_dispatch_grid_import_15_minute_average",
        "sensor.pylontech_h3x_predictive_dispatch_grid_import_trend",
        "sensor.pylontech_h3x_predictive_dispatch_grid_net_power",
        "sensor.pylontech_h3x_predictive_dispatch_grid_charge_headroom",
        "sensor.pylontech_h3x_predictive_dispatch_grid_diagnostics_status",
        "sensor.pylontech_h3x_predictive_dispatch_economic_grid_charge_power",
        "sensor.pylontech_h3x_predictive_dispatch_live_solar_surplus_power",
        "number.pylontech_h3x_predictive_dispatch_grid_import_limit",
        "number.pylontech_h3x_predictive_dispatch_grid_export_limit",
        "attribute: forecast_power_slot_start",
        "attribute: measurement_source",
        "Load forecast, next interval",
        "Solar forecast, next interval",
        "Forecast load over full horizon",
        "Forecast solar over full horizon",
        "Active or next forced charge",
        "Price assumptions",
    )
    for token in required:
        if token not in source:
            raise AssertionError(f"dashboard missing {token!r}")
    if "pylontech_h3x_energy_arbitrage" in source:
        raise AssertionError("dashboard still references the conflicting legacy domain")
    for forbidden in (
        "custom:apexcharts-card",
        "type: markdown",
        "<table",
        "<tr>",
        "attribute: economic_grid_charge_w",
        "attribute: live_surplus_w",
        "attribute: economic_grid_charge_power_w",
        "attribute: live_solar_surplus_power_w",
        "attribute: grid_net_power_w",
        "attribute: grid_import_power_w",
        "attribute: grid_import_average_power_w",
        "attribute: grid_import_trend_w_per_min",
        "attribute: grid_charge_headroom_w",
        "Current-slot load forecast",
        "Current-slot solar forecast",
    ):
        if forbidden in source:
            raise AssertionError(f"dashboard still uses unsupported {forbidden!r}")

    measured_history = source.split(
        "title: Measured home load and SMA PV history", 1
    )[1].split("- type: history-graph", 1)[0]
    if "forecast_load_power" in measured_history or "forecast_solar_power" in measured_history:
        raise AssertionError("rolling forecast snapshots must not be charted as history")


if __name__ == "__main__":
    main()
