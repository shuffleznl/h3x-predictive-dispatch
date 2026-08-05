#!/usr/bin/env python3
"""Validate the standalone predictive dashboard namespace and controls."""

from __future__ import annotations

import ast
import json
import re
import unicodedata
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboards" / "h3x-predictive-dispatch.yaml"
PACKAGED_DASHBOARD = (
    ROOT
    / "custom_components"
    / "h3x_predictive_dispatch"
    / "dashboards"
    / "h3x-predictive-dispatch.yaml"
)
INTEGRATION = ROOT / "custom_components" / "h3x_predictive_dispatch"
DEVICE_NAME = "Pylontech H3X Predictive Dispatch"


def _slugify(value: str) -> str:
    """Approximate Home Assistant's ASCII entity object-ID slugging."""
    normalized = unicodedata.normalize("NFKD", value).encode(
        "ascii", "ignore"
    ).decode()
    return re.sub(r"[^a-z0-9]+", "_", normalized.lower()).strip("_")


def _literal_keyword(call: ast.Call, key: str) -> str | None:
    """Return a string literal keyword from an entity-description call."""
    for keyword in call.keywords:
        if keyword.arg != key:
            continue
        try:
            value = ast.literal_eval(keyword.value)
        except (ValueError, SyntaxError):
            return None
        return value if isinstance(value, str) else None
    return None


def _expected_predictive_entities() -> set[str]:
    """Derive default entity IDs from descriptions and English translations."""
    strings = json.loads((INTEGRATION / "strings.json").read_text(encoding="utf-8"))
    translations = strings["entity"]
    const_tree = ast.parse((INTEGRATION / "const.py").read_text(encoding="utf-8"))
    stable_object_ids: dict[str, str] = {}
    for node in const_tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name)
            and target.id == "DASHBOARD_ENTITY_OBJECT_IDS"
            for target in node.targets
        ):
            continue
        stable_object_ids = ast.literal_eval(node.value)
        break
    expected: set[str] = set()
    for platform in ("sensor", "select", "number", "switch"):
        tree = ast.parse(
            (INTEGRATION / f"{platform}.py").read_text(encoding="utf-8")
        )
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            translation_key = _literal_keyword(node, "translation_key")
            fallback_name = _literal_keyword(node, "name")
            if translation_key is None or fallback_name is None:
                continue
            contract_key = f"{platform}.{_literal_keyword(node, 'key')}"
            object_id = stable_object_ids.get(contract_key)
            if object_id is None:
                translated = translations.get(platform, {}).get(
                    translation_key, {}
                ).get("name", fallback_name)
                object_id = _slugify(f"{DEVICE_NAME} {translated}")
            expected.add(f"{platform}.{object_id}")
    return expected


def _dashboard_entity_ids(value: object) -> set[str]:
    """Recursively collect entity IDs from parsed Lovelace YAML."""
    if isinstance(value, list):
        result: set[str] = set()
        for item in value:
            result.update(_dashboard_entity_ids(item))
        return result
    if not isinstance(value, dict):
        return set()

    result = set()
    entity_id = value.get("entity")
    if isinstance(entity_id, str):
        result.add(entity_id)
    for child in value.values():
        result.update(_dashboard_entity_ids(child))
    return result


def main() -> None:
    """Reject cross-domain entity collisions and missing predictive controls."""
    source = DASHBOARD.read_text(encoding="utf-8")
    dashboard = yaml.safe_load(source)
    if not isinstance(dashboard, dict) or not isinstance(
        dashboard.get("views"), list
    ):
        raise TypeError("dashboard YAML must contain a views list")
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
        "sensor.pylontech_h3x_predictive_dispatch_forecast_load_power",
        "sensor.pylontech_h3x_predictive_dispatch_forecast_solar_power",
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
        "Active or next charge",
        "Price assumptions",
    )
    for token in required:
        if token not in source:
            raise AssertionError(f"dashboard missing {token!r}")
    if "pylontech_h3x_energy_arbitrage" in source:
        raise AssertionError("dashboard still references the conflicting legacy domain")

    dashboard_entities = {
        entity_id
        for entity_id in _dashboard_entity_ids(dashboard)
        if re.fullmatch(
            r"(?:sensor|select|number|switch)\."
            r"pylontech_h3x_predictive_dispatch_[a-z0-9_]+",
            entity_id,
        )
    }
    unknown_entities = dashboard_entities - _expected_predictive_entities()
    if unknown_entities:
        raise AssertionError(
            "dashboard references entities not created by the integration: "
            f"{sorted(unknown_entities)}"
        )
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

    planned_actions = source.split("heading: Planned actions", 1)[1].split(
        "entity: sensor.pylontech_h3x_predictive_dispatch_planned_charge_energy",
        1,
    )[0]
    if "type: attribute" in planned_actions:
        raise AssertionError(
            "planned action rows must use their own entities for correct more-info navigation"
        )


if __name__ == "__main__":
    main()
