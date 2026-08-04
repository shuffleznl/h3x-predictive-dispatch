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
        "sensor.pylontech_h3x_predictive_dispatch_grid_net_power",
        "sensor.pylontech_h3x_predictive_dispatch_grid_import_15_minute_average",
        "sensor.pylontech_h3x_predictive_dispatch_grid_import_trend",
        "sensor.pylontech_h3x_predictive_dispatch_grid_charge_headroom",
        "sensor.pylontech_h3x_predictive_dispatch_grid_diagnostics_status",
        "number.pylontech_h3x_predictive_dispatch_grid_import_limit",
        "number.pylontech_h3x_predictive_dispatch_grid_export_limit",
        "attribute: economic_grid_charge_w",
        "Active or next forced charge",
        "Price assumptions",
    )
    for token in required:
        if token not in source:
            raise AssertionError(f"dashboard missing {token!r}")
    if "pylontech_h3x_energy_arbitrage" in source:
        raise AssertionError("dashboard still references the conflicting legacy domain")
    for forbidden in ("custom:apexcharts-card", "type: markdown", "<table", "<tr>"):
        if forbidden in source:
            raise AssertionError(f"dashboard still uses unsupported {forbidden!r}")


if __name__ == "__main__":
    main()
