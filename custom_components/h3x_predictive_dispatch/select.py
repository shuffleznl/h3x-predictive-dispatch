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
    CONF_BATTERY_CIRCUIT_RATING,
    CONF_DISCHARGE_POWER_MODE,
    CONF_EV_FORECAST_MODE,
    CONF_GRID_CONNECTION_RATING,
    CONF_LOAD_FORECAST_MODE,
    CONF_PV_ORIENTATION,
    CONF_SOLAR_FORECAST_SOURCE,
    CONF_STRATEGY_PROFILE,
    CONF_TERMINAL_SOC_MODE,
    DASHBOARD_ENTITY_OBJECT_IDS,
    DISCHARGE_POWER_MODES,
    DOMAIN,
    EV_FORECAST_MODES,
    LOAD_FORECAST_MODES,
    PV_ORIENTATIONS,
    SOLAR_FORECAST_SOURCES,
    STRATEGY_PROFILES,
    TERMINAL_SOC_MODES,
)
from .coordinator import H3XPredictiveDispatchCoordinator
from .electrical import (
    BATTERY_CIRCUIT_RATINGS,
    GRID_CONNECTION_RATINGS,
    rating_power_w,
)


@dataclass(frozen=True, kw_only=True)
class H3XPredictiveDispatchSelectDescription(SelectEntityDescription):
    """Describe an arbitrage select control."""

    option_key: str
    options: tuple[str, ...]


SELECTS: tuple[H3XPredictiveDispatchSelectDescription, ...] = (
    H3XPredictiveDispatchSelectDescription(
        key="grid_connection_rating",
        translation_key="grid_connection_rating",
        name="Grid connection rating",
        icon="mdi:transmission-tower",
        option_key=CONF_GRID_CONNECTION_RATING,
        options=GRID_CONNECTION_RATINGS,
    ),
    H3XPredictiveDispatchSelectDescription(
        key="battery_circuit_rating",
        translation_key="battery_circuit_rating",
        name="Battery circuit rating",
        icon="mdi:fuse",
        option_key=CONF_BATTERY_CIRCUIT_RATING,
        options=BATTERY_CIRCUIT_RATINGS,
    ),
    H3XPredictiveDispatchSelectDescription(
        key="load_forecast_mode",
        translation_key="load_forecast_mode",
        name="Load forecast mode",
        icon="mdi:home-analytics",
        option_key=CONF_LOAD_FORECAST_MODE,
        options=LOAD_FORECAST_MODES,
    ),
    H3XPredictiveDispatchSelectDescription(
        key="ev_forecast_mode",
        translation_key="ev_forecast_mode",
        name="EV forecast mode",
        icon="mdi:car-electric",
        option_key=CONF_EV_FORECAST_MODE,
        options=EV_FORECAST_MODES,
    ),
    H3XPredictiveDispatchSelectDescription(
        key="strategy_profile",
        translation_key="strategy_profile",
        name="Strategy profile",
        icon="mdi:tune-variant",
        option_key=CONF_STRATEGY_PROFILE,
        options=STRATEGY_PROFILES,
    ),
    H3XPredictiveDispatchSelectDescription(
        key="terminal_soc_mode",
        translation_key="terminal_soc_mode",
        name="End-of-horizon SOC",
        icon="mdi:battery-clock",
        option_key=CONF_TERMINAL_SOC_MODE,
        options=TERMINAL_SOC_MODES,
    ),
    H3XPredictiveDispatchSelectDescription(
        key="discharge_power_mode",
        translation_key="discharge_power_mode",
        name="Discharge power mode",
        icon="mdi:transmission-tower-export",
        option_key=CONF_DISCHARGE_POWER_MODE,
        options=DISCHARGE_POWER_MODES,
    ),
    H3XPredictiveDispatchSelectDescription(
        key="pv_orientation",
        translation_key="pv_orientation",
        name="PV orientation",
        icon="mdi:compass",
        option_key=CONF_PV_ORIENTATION,
        options=PV_ORIENTATIONS,
    ),
    H3XPredictiveDispatchSelectDescription(
        key="solar_forecast_source",
        translation_key="solar_forecast_source",
        name="Solar forecast source",
        icon="mdi:weather-partly-cloudy",
        option_key=CONF_SOLAR_FORECAST_SOURCE,
        options=SOLAR_FORECAST_SOURCES,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up select controls from a config entry."""
    coordinator: H3XPredictiveDispatchCoordinator = entry.runtime_data
    async_add_entities(
        H3XPredictiveDispatchSelect(coordinator, entry, description)
        for description in SELECTS
    )


class H3XPredictiveDispatchSelect(CoordinatorEntity[H3XPredictiveDispatchCoordinator], SelectEntity):
    """A runtime select control for the arbitrage optimizer."""

    entity_description: H3XPredictiveDispatchSelectDescription
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: H3XPredictiveDispatchCoordinator,
        entry: ConfigEntry,
        description: H3XPredictiveDispatchSelectDescription,
    ) -> None:
        """Initialize the select control."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_options = list(description.options)
        contract_key = f"select.{description.key}"
        if object_id := DASHBOARD_ENTITY_OBJECT_IDS.get(contract_key):
            self.entity_id = f"select.{object_id}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Pylontech H3X Predictive Dispatch",
            "manufacturer": "Local",
            "model": "Predictive Energy Optimizer",
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
            profiles = {
                "conservative": "25% reserve, 85% max SOC, 0.35C, 60-minute runs, high forecast protection, no peak power",
                "typical": "20% reserve, 90% max SOC, 0.5C charge / 0.45C discharge, 30-minute runs, balanced margins",
                "spread": "20% reserve, 90% max SOC, 0.4C charge / 0.3C discharge, 45-minute runs, spread across up to 5 hours",
                "aggressive": "15% reserve, 100% max SOC, 0.5C, 15-minute runs, no extra profit margin or periodic-full-charge constraint",
                "custom": "manual settings differ from a built-in profile",
            }
            active = self.current_option or "custom"
            return {
                "active_profile_description": profiles.get(active, profiles["custom"]),
                **profiles,
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
        if self.entity_description.option_key == CONF_SOLAR_FORECAST_SOURCE:
            return {
                "auto": "use Solcast when configured, otherwise use the local panel model",
                "solcast": "use Solcast and retain the last valid cache during API outages",
                "panel_model": "use the local orientation and daylight model without cloud forecasts",
            }
        if self.entity_description.option_key in {
            CONF_GRID_CONNECTION_RATING,
            CONF_BATTERY_CIRCUIT_RATING,
        }:
            return {
                rating: (
                    f"{rating_power_w(rating) / 1000:.2f} kW nominal at 230 V per phase"
                    if rating_power_w(rating) is not None
                    else "use the corresponding custom watt limit"
                )
                for rating in self.entity_description.options
            }
        return {}
