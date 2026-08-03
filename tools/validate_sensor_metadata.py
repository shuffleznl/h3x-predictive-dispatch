#!/usr/bin/env python3
"""Validate Home Assistant sensor metadata for recorder/statistics compatibility."""

from __future__ import annotations

import ast
from pathlib import Path


SENSOR_PATH = Path("custom_components/h3x_predictive_dispatch/sensor.py")


def keyword_name(node: ast.keyword) -> str:
    if node.arg is None:
        raise AssertionError("unexpected **kwargs in sensor description")
    return node.arg


def dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{dotted_name(node.value)}.{node.attr}"
    return ast.unparse(node)


def main() -> None:
    tree = ast.parse(SENSOR_PATH.read_text(), filename=str(SENSOR_PATH))
    source = ast.unparse(tree)

    if "_unrecorded_attributes = UNRECORDED_PLAN_ATTRIBUTES" not in source:
        raise AssertionError("large chart arrays must be excluded from recorder")
    if "native_unit_of_measurement='currency'" in source:
        raise AssertionError("literal currency placeholder must not be used")
    if "native_unit_of_measurement='currency/kWh'" in source:
        raise AssertionError("literal currency/kWh placeholder must not be used")
    if "def native_unit_of_measurement" not in source:
        raise AssertionError("currency units must be resolved dynamically")
    if "UnitOfTime.MINUTES" not in source:
        raise AssertionError("price resolution must use the Home Assistant minute unit")

    descriptions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and dotted_name(node.func).endswith("H3XPredictiveDispatchSensorDescription")
    ]
    if not descriptions:
        raise AssertionError("no sensor descriptions found")

    for description in descriptions:
        kwargs = {keyword_name(keyword): keyword.value for keyword in description.keywords}
        key_node = kwargs.get("key")
        key = ast.literal_eval(key_node) if key_node is not None else None
        device_class = kwargs.get("device_class")
        state_class = kwargs.get("state_class")
        if key in {"first_slot_value", "estimated_savings", "estimated_savings_today"}:
            if (
                device_class is None
                or dotted_name(device_class) != "SensorDeviceClass.MONETARY"
            ):
                raise AssertionError(f"{key} must use the monetary device class")
            if "native_unit_of_measurement" in kwargs:
                raise AssertionError(f"{key} must use the dynamic currency unit")
            if state_class is not None:
                raise AssertionError(f"{key} is a plan estimate, not statistics")
        if key == "current_price":
            if "native_unit_of_measurement" in kwargs:
                raise AssertionError("current_price must use the dynamic price unit")
            if state_class is not None:
                raise AssertionError("current_price must not use placeholder statistics")
        if key == "resolution_minutes":
            unit = kwargs.get("native_unit_of_measurement")
            if unit is None or dotted_name(unit) != "UnitOfTime.MINUTES":
                raise AssertionError("resolution_minutes must use UnitOfTime.MINUTES")
            if (
                device_class is None
                or dotted_name(device_class) != "SensorDeviceClass.DURATION"
            ):
                raise AssertionError("resolution_minutes must use duration device class")
        if key == "price_plan":
            if "native_unit_of_measurement" in kwargs:
                raise AssertionError("price_plan must be unitless to avoid LTS warnings")
            if state_class is not None:
                raise AssertionError("price_plan must not create long-term statistics")
        if (
            device_class is not None
            and dotted_name(device_class) == "SensorDeviceClass.ENERGY"
            and state_class is not None
            and dotted_name(state_class) == "SensorStateClass.MEASUREMENT"
        ):
            raise AssertionError(
                f"{key} uses energy device class with invalid measurement state class"
            )

    decision = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_decision_attributes"
    )
    decision_source = ast.unparse(decision)
    for token in (
        "price_slots",
        "today_slots",
        "tomorrow_slots",
        "dispatch_plan",
    ):
        if token in decision_source:
            raise AssertionError(f"decision sensor must not expose {token}")

    for token in (
        "price_trend",
        "load_forecast",
        "solar_forecast",
        "planned_charge_slots",
        "planned_discharge_slots",
    ):
        if token not in source:
            raise AssertionError(f"{token} must be excluded from recorder attributes")


if __name__ == "__main__":
    main()
