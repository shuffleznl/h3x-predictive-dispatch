#!/usr/bin/env python3
"""Validate the official Pylontech backend contract (legacy CLI name retained)."""

import ast
import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components/h3x_predictive_dispatch"


def main():
    manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))
    assert "pylontech_fh3x" in manifest["after_dependencies"]
    assert "pylontech_h3x_bridge" not in manifest["after_dependencies"]
    spec = importlib.util.spec_from_file_location(
        "official_contract", INTEGRATION / "backend.py"
    )
    backend = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(backend)
    assert backend.OFFICIAL_DOMAIN == "pylontech_fh3x"
    assert (
        backend.OFFICIAL_KEYS["power_ref_entity"] == "charge_discharge_power_reference"
    )
    assert (
        backend.OFFICIAL_KEYS["discharge_limit_soc_entity"] == "eps_limit_soc_on_grid"
    )
    assert backend.OFFICIAL_KEYS["battery_system_capacity_entity"] == "battery_capacity"
    assert "battery_usable_capacity_entity" not in backend.OFFICIAL_KEYS
    const = (INTEGRATION / "const.py").read_text(encoding="utf-8")
    for node in ast.parse(const).body:
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id
            in {
                "DEFAULT_EMS_MODE_ENTITY",
                "DEFAULT_POWER_REF_ENTITY",
                "DEFAULT_SOC_ENTITY",
            }
        ):
            assert ast.literal_eval(node.value) == "", (
                "hardware entity IDs must be discovered"
            )
    assert 'CONF_IDLE_EMS_MODE: "user"' in const
    assert 'CONF_USER_EMS_MODE: "user"' in const
    coordinator = (INTEGRATION / "coordinator.py").read_text(encoding="utf-8")
    assert 'return -percent if action == "charge" else percent' in coordinator
    assert 'hass.data.get("pylontech_h3x_bridge"' not in coordinator
    dashboard = (ROOT / "dashboards/h3x-predictive-dispatch.yaml").read_text(
        encoding="utf-8"
    )
    assert dashboard == (
        INTEGRATION / "dashboards/h3x-predictive-dispatch.yaml"
    ).read_text(encoding="utf-8")
    assert "pylontech_h3x_bridge" not in dashboard
    assert "force_charge" not in dashboard
    assert "readback_raw" not in dashboard
    entities = set(
        re.findall(r"(?:sensor|number|select)\.fh3x15khy3peu_[a-z0-9_]+", dashboard)
    )
    assert entities == {
        "select.fh3x15khy3peu_ems_mode",
        "number.fh3x15khy3peu_charge_discharge_power_reference",
        "number.fh3x15khy3peu_charge_limit_soc",
        "number.fh3x15khy3peu_on_grid_eps_reserve_soc",
        "sensor.fh3x15khy3peu_battery_level",
        "sensor.fh3x15khy3peu_battery_power",
        "sensor.fh3x15khy3peu_battery_current",
        "sensor.fh3x15khy3peu_bms_temperature",
        "sensor.fh3x15khy3peu_bms_module_count",
        "sensor.fh3x15khy3peu_battery_capacity",
    }
    print("official backend and dashboard contract validated")


if __name__ == "__main__":
    main()
