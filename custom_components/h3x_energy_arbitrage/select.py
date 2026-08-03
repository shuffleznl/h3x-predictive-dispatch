"""Select controls for Pylontech H3X energy arbitrage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_DISCHARGE_POWER_MODE,
    CONF_EV_FORECAST_MODE,
    CONF_LOAD_FORECAST_MODE,
    CONF_PV_ORIENTATION,
    CONF_STRATEGY_PROFILE,
    CONF_TERMINAL_SOC_MODE,
    DISCHARGE_POWER_MODES,
    DOMAIN,
    EV_FORECAST_MODES,
    LOAD_FORECAST_MODES,
    PV_ORIENTATIONS,
    STRATEGY_PROFILES,
    TERMINAL_SOC_MODES,
)
from .coordinator import H3XArbitrageCoordinator


@dataclass(frozen=True, kw_only=True)
class H3XArbitrageSelectDescription(SelectEntityDescription):
    """Describe an arbitrage select control."""

    option_key: str
    options: tuple[str, ...]


SELECTS: tuple[H3XArbitrageSelectDescription, ...] = (
    H3XArbitrageSelectDescription(
        key="load_forecast_mode",
        translation_key="load_forecast_mode",
        name="Load forecast mode",
        icon="mdi:home-analytics",
        option_key=CONF_LOAD_FORECAST_MODE,
        options=LOAD_FORECAST_MODES,
    ),
    H3XArbitrageSelectDescription(
        key="ev_forecast_mode",
        translation_key="ev_forecast_mode",
        name="EV forecast mode",
        icon="mdi:car-electric",
        option_key=CONF_EV_FORECAST_MODE,
        options=EV_FORECAST_MODES,
    ),
    H3XArbitrageSelectDescription(
        key="strategy_profile",
        translation_key="strategy_profile",
        name="Strategy profile",
        icon="mdi:tune-variant",
        option_key=CONF_STRATEGY_PROFILE,
        options=STRATEGY_PROFILES,
    ),
    H3XArbitrageSelectDescription(
        key="terminal_soc_mode",
        translation_key="terminal_soc_mode",
        name="End-of-horizon SOC",
        icon="mdi:battery-clock",
        option_key=CONF_TERMINAL_SOC_MODE,
        options=TERMINAL_SOC_MODES,
    ),
    H3XArbitrageSelectDescription(
        key="discharge_power_mode",
        translation_key="discharge_power_mode",
        name="Discharge power mode",
        icon="mdi:transmission-tower-export",
        option_key=CONF_DISCHARGE_POWER_MODE,
        options=DISCHARGE_POWER_MODES,
    ),
    H3XArbitrageSelectDescription(
        key="pv_orientation",
        translation_key="pv_orientation",
        name="PV orientation",
        icon="mdi:compass",
        option_key=CONF_PV_ORIENTATION,
        options=PV_ORIENTATIONS,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up select controls from a config entry."""
    coordinator: H3XArbitrageCoordinator = entry.runtime_data
    async_add_entities(
        H3XArbitrageSelect(coordinator, entry, description)
        for description in SELECTS
    )


class H3XArbitrageSelect(CoordinatorEntity[H3XArbitrageCoordinator], SelectEntity):
    """A runtime select control for the arbitrage optimizer."""

    entity_description: H3XArbitrageSelectDescription
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: H3XArbitrageCoordinator,
        entry: ConfigEntry,
        description: H3XArbitrageSelectDescription,
    ) -> None:
        """Initialize the select control."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_options = list(description.options)
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Pylontech H3X Energy Arbitrage",
            "manufacturer": "Local",
            "model": "Nord Pool Optimizer",
        }

    @property
    def current_option(self) -> str | None:
        """Return the selected option."""
        return str(self.coordinator._option(self.entity_description.option_key))

    async def async_select_option(self, option: str) -> None:
        """Update the selected optimizer option."""
        if option not in self.entity_description.options:
            raise ValueError(f"Unsupported option {option}")
        if self.entity_description.option_key == CONF_STRATEGY_PROFILE:
            await self.coordinator.async_apply_strategy_profile(option)
        else:
            await self.coordinator.async_set_option(
                self.entity_description.option_key,
                option,
            )
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return profile details for the strategy selector."""
        if self.entity_description.option_key == CONF_STRATEGY_PROFILE:
            return {
                "conservative": "preserve SOC, weekly full charge, higher profit margin, spread discharge, no peak power",
                "typical": "balanced default profile with spread discharge",
                "spread": "lower C-rate and longer action windows across economically similar slots",
                "aggressive": "reserve-only horizon, no periodic full-charge constraint, 100% max SOC, max-economic discharge, lowest extra margin",
                "custom": "manual settings differ from a built-in profile",
            }
        if self.entity_description.option_key == CONF_DISCHARGE_POWER_MODE:
            return {
                "spread": "spread export across nearby expensive slots when prices are close enough",
                "max_economic": "use the optimizer's highest economic target power",
            }
        if self.entity_description.option_key == CONF_PV_ORIENTATION:
            return {
                "N": "north-facing plane, low default yield in the northern hemisphere",
                "NE": "north-east-facing plane, morning biased",
                "E": "east-facing plane, morning biased",
                "SE": "south-east-facing plane, late-morning biased",
                "S": "south-facing plane, midday biased",
                "SW": "south-west-facing plane, afternoon biased",
                "W": "west-facing plane, afternoon biased",
                "NW": "north-west-facing plane, late-afternoon biased",
            }
        return {}
