#!/usr/bin/env python3
"""Validate Shelly grid-meter discovery without a Home Assistant install."""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT / "custom_components" / "h3x_predictive_dispatch" / "meter.py"
)


@dataclass
class FakeState:
    """Minimal Home Assistant State replacement."""

    entity_id: str
    attributes: dict[str, str]


class FakeRegistry:
    """Minimal entity registry replacement."""

    def __init__(self, entries: dict[str, object]) -> None:
        self._entries = entries

    def async_get(self, entity_id: str) -> object | None:
        return self._entries.get(entity_id)


class FakeStates:
    """Minimal state machine replacement."""

    def __init__(self, states: list[FakeState]) -> None:
        self._states = states

    def async_all(self, domain: str) -> list[FakeState]:
        assert domain == "sensor"
        return self._states


def load_meter_module() -> ModuleType:
    """Load meter.py with the Home Assistant imports stubbed."""
    homeassistant = ModuleType("homeassistant")
    core = ModuleType("homeassistant.core")
    helpers = ModuleType("homeassistant.helpers")
    entity_registry = ModuleType("homeassistant.helpers.entity_registry")
    core.HomeAssistant = object
    entity_registry.async_get = lambda hass: hass.registry
    helpers.entity_registry = entity_registry
    sys.modules.update(
        {
            "homeassistant": homeassistant,
            "homeassistant.core": core,
            "homeassistant.helpers": helpers,
            "homeassistant.helpers.entity_registry": entity_registry,
        }
    )
    spec = importlib.util.spec_from_file_location("meter_under_test", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def hass_with(entries: dict[str, object], states: list[FakeState]) -> object:
    """Return a fake Home Assistant object."""
    return SimpleNamespace(registry=FakeRegistry(entries), states=FakeStates(states))


def main() -> None:
    """Exercise renamed, ambiguous, and unrelated power sensors."""
    module = load_meter_module()
    renamed = FakeState(
        "sensor.grid_connection",
        {"device_class": "power", "friendly_name": "Grid connection"},
    )
    renamed_entry = SimpleNamespace(
        platform="shelly",
        unique_id="abc-em:0-total_act_power",
        original_name="Total active power",
    )
    hass = hass_with({renamed.entity_id: renamed_entry}, [renamed])
    assert (
        module.autodetect_shelly_total_active_power(hass)
        == "sensor.grid_connection"
    )

    second = FakeState(
        "sensor.garage_grid",
        {"device_class": "power", "friendly_name": "Garage grid"},
    )
    second_entry = SimpleNamespace(
        platform="shelly",
        unique_id="def-em:0-total_act_power",
        original_name="Total active power",
    )
    ambiguous = hass_with(
        {renamed.entity_id: renamed_entry, second.entity_id: second_entry},
        [renamed, second],
    )
    assert module.autodetect_shelly_total_active_power(ambiguous) == ""

    unrelated = FakeState(
        "sensor.total_active_power",
        {"device_class": "power", "friendly_name": "Total active power"},
    )
    unrelated_entry = SimpleNamespace(
        platform="modbus",
        unique_id="total_act_power",
        original_name="Total active power",
    )
    other = hass_with({unrelated.entity_id: unrelated_entry}, [unrelated])
    assert module.autodetect_shelly_total_active_power(other) == ""


if __name__ == "__main__":
    main()
