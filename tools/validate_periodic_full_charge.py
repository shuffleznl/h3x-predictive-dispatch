#!/usr/bin/env python3
"""Validate the periodic full-charge feature wiring."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "h3x_predictive_dispatch"

PERIODIC_KEYS = (
    "periodic_full_charge_enabled",
    "periodic_full_charge_interval_days",
    "periodic_full_charge_target_soc",
    "periodic_full_charge_threshold_soc",
)

PERIODIC_CONSTANTS = (
    "CONF_PERIODIC_FULL_CHARGE_ENABLED",
    "CONF_PERIODIC_FULL_CHARGE_INTERVAL_DAYS",
    "CONF_PERIODIC_FULL_CHARGE_TARGET_SOC",
    "CONF_PERIODIC_FULL_CHARGE_THRESHOLD_SOC",
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def main() -> None:
    const_source = read(INTEGRATION / "const.py")
    config_source = read(INTEGRATION / "config_flow.py")
    coordinator_source = read(INTEGRATION / "coordinator.py")
    sensor_source = read(INTEGRATION / "sensor.py")
    strings = json.loads((INTEGRATION / "strings.json").read_text(encoding="utf-8"))
    translations = json.loads(
        (INTEGRATION / "translations" / "en.json").read_text(encoding="utf-8")
    )

    for key, constant in zip(PERIODIC_KEYS, PERIODIC_CONSTANTS, strict=True):
        if key not in const_source:
            raise AssertionError(f"{key} missing from constants")
        if constant not in config_source:
            raise AssertionError(f"{constant} missing from config flow")
        if key not in sensor_source:
            raise AssertionError(f"{key} missing from decision attributes")
        if key not in strings["config"]["step"]["user"]["data"]:
            raise AssertionError(f"{key} missing from strings setup form")
        if key not in strings["options"]["step"]["init"]["data"]:
            raise AssertionError(f"{key} missing from strings options form")
        if key not in translations["config"]["step"]["user"]["data"]:
            raise AssertionError(f"{key} missing from translations setup form")
        if key not in translations["options"]["step"]["init"]["data"]:
            raise AssertionError(f"{key} missing from translations options form")

    required_tokens = (
        "Store(",
        "LAST_FULL_CHARGE_KEY",
        "_async_record_full_charge_if_reached",
        "_periodic_full_charge_state",
        "periodic_full_charge_due=force_full_charge",
        "periodic_full_charge_target_soc",
    )
    for token in required_tokens:
        if token not in coordinator_source:
            raise AssertionError(f"{token} missing from coordinator")

    forbidden_tokens = (
        'periodic_full_charge["due"]',
        'periodic_full_charge["target_soc"]',
    )
    for token in forbidden_tokens:
        if token in coordinator_source:
            raise AssertionError(f"coordinator still uses internal key {token}")

    if "full_charge_threshold_above_target" not in config_source:
        raise AssertionError("full charge threshold validation is missing")
    if "full_charge_threshold_above_target" not in strings["config"]["error"]:
        raise AssertionError("full charge threshold error text is missing")


if __name__ == "__main__":
    main()
