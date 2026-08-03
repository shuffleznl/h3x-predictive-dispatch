"""Number controls for Pylontech H3X energy arbitrage."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfPower, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_BATTERY_MODULE_COUNT,
    CONF_DISCHARGE_SPREAD_MAX_HOURS,
    CONF_DISCHARGE_SPREAD_PRICE_TOLERANCE,
    CONF_MAX_CHARGE_C_RATE,
    CONF_MAX_DISCHARGE_C_RATE,
    CONF_PV_INVERTER_LIMIT_W,
    CONF_PV_PANEL_COUNT,
    CONF_PV_PANEL_WP,
    FORCE_H3_MAX_MODULES,
    FORCE_H3_MIN_MODULES,
    CONF_PERIODIC_FULL_CHARGE_INTERVAL_DAYS,
    CONF_PERIODIC_FULL_CHARGE_TARGET_SOC,
    CONF_PERIODIC_FULL_CHARGE_THRESHOLD_SOC,
    DOMAIN,
)
from .coordinator import H3XArbitrageCoordinator


@dataclass(frozen=True, kw_only=True)
class H3XArbitrageNumberDescription(NumberEntityDescription):
    """Describe an arbitrage number control."""

    option_key: str


NUMBERS: tuple[H3XArbitrageNumberDescription, ...] = (
    H3XArbitrageNumberDescription(
        key="battery_module_count",
        translation_key="battery_module_count",
        name="Battery module count",
        icon="mdi:battery-sync",
        native_min_value=float(FORCE_H3_MIN_MODULES),
        native_max_value=float(FORCE_H3_MAX_MODULES),
        native_step=1.0,
        option_key=CONF_BATTERY_MODULE_COUNT,
    ),
    H3XArbitrageNumberDescription(
        key="periodic_full_charge_interval_days",
        translation_key="periodic_full_charge_interval_days",
        name="Periodic full-charge interval",
        icon="mdi:calendar-clock",
        native_min_value=1.0,
        native_max_value=90.0,
        native_step=1.0,
        native_unit_of_measurement=UnitOfTime.DAYS,
        option_key=CONF_PERIODIC_FULL_CHARGE_INTERVAL_DAYS,
    ),
    H3XArbitrageNumberDescription(
        key="periodic_full_charge_target_soc",
        translation_key="periodic_full_charge_target_soc",
        name="Periodic full-charge target SOC",
        icon="mdi:battery-charging-100",
        native_min_value=95.0,
        native_max_value=100.0,
        native_step=1.0,
        native_unit_of_measurement=PERCENTAGE,
        option_key=CONF_PERIODIC_FULL_CHARGE_TARGET_SOC,
    ),
    H3XArbitrageNumberDescription(
        key="periodic_full_charge_threshold_soc",
        translation_key="periodic_full_charge_threshold_soc",
        name="Periodic full-charge threshold SOC",
        icon="mdi:battery-check",
        native_min_value=90.0,
        native_max_value=100.0,
        native_step=1.0,
        native_unit_of_measurement=PERCENTAGE,
        option_key=CONF_PERIODIC_FULL_CHARGE_THRESHOLD_SOC,
    ),
    H3XArbitrageNumberDescription(
        key="discharge_spread_price_tolerance",
        translation_key="discharge_spread_price_tolerance",
        name="Discharge spread price tolerance",
        icon="mdi:chart-bell-curve",
        native_min_value=0.0,
        native_max_value=50.0,
        native_step=1.0,
        native_unit_of_measurement=PERCENTAGE,
        option_key=CONF_DISCHARGE_SPREAD_PRICE_TOLERANCE,
    ),
    H3XArbitrageNumberDescription(
        key="discharge_spread_max_hours",
        translation_key="discharge_spread_max_hours",
        name="Discharge spread maximum window",
        icon="mdi:timeline-clock",
        native_min_value=0.25,
        native_max_value=12.0,
        native_step=0.25,
        native_unit_of_measurement=UnitOfTime.HOURS,
        option_key=CONF_DISCHARGE_SPREAD_MAX_HOURS,
    ),
    H3XArbitrageNumberDescription(
        key="max_charge_c_rate",
        translation_key="max_charge_c_rate",
        name="Maximum charge C-rate",
        icon="mdi:battery-arrow-up",
        native_min_value=0.05,
        native_max_value=0.5,
        native_step=0.01,
        option_key=CONF_MAX_CHARGE_C_RATE,
    ),
    H3XArbitrageNumberDescription(
        key="max_discharge_c_rate",
        translation_key="max_discharge_c_rate",
        name="Maximum discharge C-rate",
        icon="mdi:battery-arrow-down",
        native_min_value=0.05,
        native_max_value=0.5,
        native_step=0.01,
        option_key=CONF_MAX_DISCHARGE_C_RATE,
    ),
    H3XArbitrageNumberDescription(
        key="pv_panel_count",
        translation_key="pv_panel_count",
        name="PV panel count",
        icon="mdi:solar-panel-large",
        native_min_value=0.0,
        native_max_value=200.0,
        native_step=1.0,
        option_key=CONF_PV_PANEL_COUNT,
    ),
    H3XArbitrageNumberDescription(
        key="pv_panel_wp",
        translation_key="pv_panel_wp",
        name="PV panel Wp rating",
        icon="mdi:solar-power",
        native_min_value=0.0,
        native_max_value=1500.0,
        native_step=5.0,
        native_unit_of_measurement=UnitOfPower.WATT,
        option_key=CONF_PV_PANEL_WP,
    ),
    H3XArbitrageNumberDescription(
        key="pv_inverter_limit",
        translation_key="pv_inverter_limit",
        name="PV inverter limit",
        icon="mdi:current-ac",
        native_min_value=0.0,
        native_max_value=50000.0,
        native_step=50.0,
        native_unit_of_measurement=UnitOfPower.WATT,
        option_key=CONF_PV_INVERTER_LIMIT_W,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up number controls from a config entry."""
    coordinator: H3XArbitrageCoordinator = entry.runtime_data
    async_add_entities(
        H3XArbitrageNumber(coordinator, entry, description)
        for description in NUMBERS
    )


class H3XArbitrageNumber(CoordinatorEntity[H3XArbitrageCoordinator], NumberEntity):
    """A runtime number control for the arbitrage optimizer."""

    entity_description: H3XArbitrageNumberDescription
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: H3XArbitrageCoordinator,
        entry: ConfigEntry,
        description: H3XArbitrageNumberDescription,
    ) -> None:
        """Initialize the number control."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Pylontech H3X Energy Arbitrage",
            "manufacturer": "Local",
            "model": "Nord Pool Optimizer",
        }

    @property
    def native_value(self) -> float | None:
        """Return the current option value."""
        return float(self.coordinator._option(self.entity_description.option_key))

    async def async_set_native_value(self, value: float) -> None:
        """Update the number option."""
        await self.coordinator.async_set_option(
            self.entity_description.option_key,
            float(value),
        )
        self.async_write_ha_state()
