#!/usr/bin/env python3
"""Validate the Predictive Dispatch contract with H3X Bridge."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "h3x_predictive_dispatch"
BRIDGE_DOMAIN = "pylontech_h3x_bridge"
MIN_BRIDGE_VERSION = (0, 3, 9)

DEFAULT_ENTITY_CONTRACT = {
    "DEFAULT_EMS_MODE_ENTITY": "select.pylontech_h3x_bridge_ems_mode",
    "DEFAULT_POWER_REF_ENTITY": (
        "number.pylontech_h3x_bridge_charge_discharge_power_ref"
    ),
    "DEFAULT_SOC_ENTITY": "sensor.pylontech_h3x_bridge_battery_soc",
    "DEFAULT_LOAD_POWER_ENTITY": "sensor.pylontech_h3x_bridge_load_power",
    "DEFAULT_BATTERY_MODULE_COUNT_ENTITY": (
        "sensor.pylontech_h3x_bridge_battery_module_count"
    ),
    "DEFAULT_BATTERY_SYSTEM_CAPACITY_ENTITY": (
        "sensor.pylontech_h3x_bridge_battery_system_capacity"
    ),
    "DEFAULT_BATTERY_USABLE_CAPACITY_ENTITY": (
        "sensor.pylontech_h3x_bridge_battery_usable_capacity"
    ),
    "DEFAULT_BMS_TEMP_ENTITY": "sensor.pylontech_h3x_bridge_bms_temperature",
    "DEFAULT_CHARGE_LIMIT_SOC_ENTITY": (
        "number.pylontech_h3x_bridge_charge_limit_soc"
    ),
    "DEFAULT_DISCHARGE_LIMIT_SOC_ENTITY": (
        "number.pylontech_h3x_bridge_discharge_limit_soc_eps"
    ),
}

DASHBOARD_BRIDGE_ENTITIES = {
    "sensor.pylontech_h3x_bridge_battery_power",
    "sensor.pylontech_h3x_bridge_battery_soc",
    "select.pylontech_h3x_bridge_ems_mode",
    "number.pylontech_h3x_bridge_charge_discharge_power_ref",
    "number.pylontech_h3x_bridge_charge_limit_soc",
    "number.pylontech_h3x_bridge_discharge_limit_soc_eps",
}


def read(path: Path) -> str:
    """Read one UTF-8 file."""
    return path.read_text(encoding="utf-8")


def literal_assignments(source: str) -> dict[str, object]:
    """Return literal top-level assignments from Python source."""
    tree = ast.parse(source)
    values: dict[str, object] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        try:
            values[target.id] = ast.literal_eval(node.value)
        except (SyntaxError, ValueError):
            continue
    return values


def version_tuple(value: str) -> tuple[int, ...]:
    """Convert a dotted release version to an integer tuple."""
    return tuple(int(part) for part in value.split("."))


def require_tokens(source: str, tokens: tuple[str, ...], label: str) -> None:
    """Require every contract token in a source file."""
    for token in tokens:
        if token not in source:
            raise AssertionError(f"{label} missing {token!r}")


def validate_predictive_contract() -> None:
    """Validate the standalone contract encoded by Predictive Dispatch."""
    manifest = json.loads(read(INTEGRATION / "manifest.json"))
    if BRIDGE_DOMAIN not in manifest.get("after_dependencies", []):
        raise AssertionError("predictive manifest must load after H3X Bridge")

    const_source = read(INTEGRATION / "const.py")
    assignments = literal_assignments(const_source)
    for name, expected in DEFAULT_ENTITY_CONTRACT.items():
        if assignments.get(name) != expected:
            raise AssertionError(f"{name} must remain {expected!r}")

    coordinator = read(INTEGRATION / "coordinator.py")
    require_tokens(
        const_source,
        (
            'CONF_IDLE_EMS_MODE: "Self-Consumption"',
            'CONF_USER_EMS_MODE: "User mode"',
        ),
        "predictive bridge defaults",
    )
    require_tokens(
        coordinator,
        (
            'return -percent if action == "charge" else percent',
            '"number",\n            "set_value"',
            '"select",\n            "select_option"',
        ),
        "predictive bridge control",
    )

    dashboard = read(ROOT / "dashboards" / "h3x-predictive-dispatch.yaml")
    packaged = read(INTEGRATION / "dashboards" / "h3x-predictive-dispatch.yaml")
    if dashboard != packaged:
        raise AssertionError("repository and packaged predictive dashboards differ")
    referenced = set(
        re.findall(
            r"(?:sensor|number|select)\.pylontech_h3x_bridge_[a-z0-9_]+",
            dashboard,
        )
    )
    if referenced != DASHBOARD_BRIDGE_ENTITIES:
        raise AssertionError(
            "predictive dashboard bridge entities changed: "
            f"expected {sorted(DASHBOARD_BRIDGE_ENTITIES)}, got {sorted(referenced)}"
        )

    readme = read(ROOT / "README.md")
    require_tokens(
        readme,
        (
            "H3X Bridge `0.3.9` or newer",
            "https://github.com/shuffleznl/h3x-bridge",
        ),
        "predictive README",
    )


def validate_local_bridge() -> None:
    """Validate the sibling bridge checkout when it is available locally."""
    bridge = ROOT.parent / "custom_components" / BRIDGE_DOMAIN
    if not bridge.exists():
        print("sibling H3X Bridge checkout not present; static contract validated")
        return

    manifest = json.loads(read(bridge / "manifest.json"))
    if manifest.get("domain") != BRIDGE_DOMAIN:
        raise AssertionError("sibling bridge has an incompatible domain")
    if version_tuple(str(manifest.get("version", "0"))) < MIN_BRIDGE_VERSION:
        raise AssertionError("sibling bridge must be version 0.3.9 or newer")

    require_tokens(
        read(bridge / "number.py"),
        (
            'key="charge_discharge_power"',
            "native_min_value=-100.0",
            "native_max_value=100.0",
            "native_step=1",
            "scale=0.1",
            "force_user_mode_for_nonzero=True",
            'key="charge_limit_soc"',
            'key="discharge_limit_soc"',
        ),
        "bridge number platform",
    )
    require_tokens(
        read(bridge / "select.py"),
        (
            'key="ems_mode"',
            '"0": "Self-Consumption"',
            '"4": "User mode"',
        ),
        "bridge select platform",
    )
    require_tokens(
        read(bridge / "sensor.py"),
        tuple(
            f'key="{key}"'
            for key in (
                "battery_power",
                "battery_soc",
                "load_power",
                "battery_module_count",
                "battery_system_capacity",
                "battery_usable_capacity",
                "bms_temperature",
            )
        ),
        "bridge sensor platform",
    )


def main() -> None:
    """Run static and optional cross-repository checks."""
    validate_predictive_contract()
    validate_local_bridge()


if __name__ == "__main__":
    main()
