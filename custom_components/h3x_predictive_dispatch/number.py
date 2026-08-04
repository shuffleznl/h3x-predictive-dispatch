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
    CONF_ACTION_START_COST,
    CONF_BATTERY_MODULE_COUNT,
    CONF_DIRECTION_CHANGE_COST,
    CONF_DISCHARGE_SPREAD_MAX_HOURS,
    CONF_DISCHARGE_SPREAD_PRICE_TOLERANCE,
    CONF_ENERGY_TAX_PER_KWH,
    CONF_EV_CHARGING_THRESHOLD_W,
    CONF_FORECAST_RISK_PERCENTILE,
    CONF_GRID_EXPORT_LIMIT_W,
    CONF_GRID_IMPORT_LIMIT_W,
    CONF_LOAD_HISTORY_DAYS,
    CONF_MAX_CHARGE_C_RATE,
    CONF_MAX_DISCHARGE_C_RATE,
    CONF_MIN_ACTION_DURATION_MINUTES,
    CONF_PERIODIC_FULL_CHARGE_INTERVAL_DAYS,
    CONF_PERIODIC_FULL_CHARGE_TARGET_SOC,
    CONF_PERIODIC_FULL_CHARGE_THRESHOLD_SOC,
    CONF_PV_INVERTER_LIMIT_W,
    CONF_PV_PANEL_COUNT,
    CONF_PV_PANEL_WP,
    CONF_SOLCAST_UPDATE_INTERVAL_HOURS,
    CONF_SUPPLIER_BUY_MARKUP,
    CONF_SUPPLIER_SELL_MARKDOWN,
    CONF_VAT_PERCENT,
    DOMAIN,
    FORCE_H3_MAX_MODULES,
    FORCE_H3_MIN_MODULES,
)
from .coordinator import H3XPredictiveDispatchCoordinator


@dataclass(frozen=True, kw_only=True)
class H3XPredictiveDispatchNumberDescription(NumberEntityDescription):
    """Describe an arbitrage number control."""

    option_key: str


NUMBERS: tuple[H3XPredictiveDispatchNumberDescription, ...] = (
    H3XPredictiveDispatchNumberDescription(
        key="load_history_days",
        translation_key="load_history_days",
        name="Load history window",
        icon="mdi:history",
        native_min_value=2.0,
        native_max_value=90.0,
        native_step=1.0,
        native_unit_of_measurement=UnitOfTime.DAYS,
        option_key=CONF_LOAD_HISTORY_DAYS,
    ),
    H3XPredictiveDispatchNumberDescription(
        key="solcast_update_interval",
        translation_key="solcast_update_interval",
        name="Solcast refresh interval",
        icon="mdi:cloud-sync",
        native_min_value=3.0,
        native_max_value=24.0,
        native_step=1.0,
        native_unit_of_measurement=UnitOfTime.HOURS,
        option_key=CONF_SOLCAST_UPDATE_INTERVAL_HOURS,
    ),
    H3XPredictiveDispatchNumberDescription(
        key="ev_charging_threshold",
        translation_key="ev_charging_threshold",
        name="EV detection threshold",
        icon="mdi:ev-station",
        native_min_value=500.0,
        native_max_value=22000.0,
        native_step=100.0,
        native_unit_of_measurement=UnitOfPower.WATT,
        option_key=CONF_EV_CHARGING_THRESHOLD_W,
    ),
    H3XPredictiveDispatchNumberDescription(
        key="grid_import_limit",
        translation_key="grid_import_limit",
        name="Grid import limit",
        icon="mdi:transmission-tower-import",
        native_min_value=0.0,
        native_max_value=50000.0,
        native_step=100.0,
        native_unit_of_measurement=UnitOfPower.WATT,
        option_key=CONF_GRID_IMPORT_LIMIT_W,
    ),
    H3XPredictiveDispatchNumberDescription(
        key="grid_export_limit",
        translation_key="grid_export_limit",
        name="Grid export limit",
        icon="mdi:transmission-tower-export",
        native_min_value=0.0,
        native_max_value=50000.0,
        native_step=100.0,
        native_unit_of_measurement=UnitOfPower.WATT,
        option_key=CONF_GRID_EXPORT_LIMIT_W,
    ),
    H3XPredictiveDispatchNumberDescription(
        key="forecast_risk_percentile",
        translation_key="forecast_risk_percentile",
        name="Forecast risk percentile",
        icon="mdi:chart-bell-curve-cumulative",
        native_min_value=50.0,
        native_max_value=90.0,
        native_step=5.0,
        native_unit_of_measurement=PERCENTAGE,
        option_key=CONF_FORECAST_RISK_PERCENTILE,
    ),
    H3XPredictiveDispatchNumberDescription(
        key="minimum_action_duration",
        translation_key="minimum_action_duration",
        name="Minimum action duration",
        icon="mdi:timer-lock",
        native_min_value=0.0,
        native_max_value=240.0,
        native_step=15.0,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        option_key=CONF_MIN_ACTION_DURATION_MINUTES,
    ),
    H3XPredictiveDispatchNumberDescription(
        key="action_start_cost",
        translation_key="action_start_cost",
        name="Action start penalty",
        icon="mdi:cash-clock",
        native_min_value=0.0,
        native_max_value=5.0,
        native_step=0.005,
        option_key=CONF_ACTION_START_COST,
    ),
    H3XPredictiveDispatchNumberDescription(
        key="direction_change_cost",
        translation_key="direction_change_cost",
        name="Direction change penalty",
        icon="mdi:swap-horizontal-bold",
        native_min_value=0.0,
        native_max_value=5.0,
        native_step=0.005,
        option_key=CONF_DIRECTION_CHANGE_COST,
    ),
    H3XPredictiveDispatchNumberDescription(
        key="vat_percent",
        translation_key="vat_percent",
        name="VAT",
        icon="mdi:percent",
        native_min_value=0.0,
        native_max_value=100.0,
        native_step=0.1,
        native_unit_of_measurement=PERCENTAGE,
        option_key=CONF_VAT_PERCENT,
    ),
    H3XPredictiveDispatchNumberDescription(
        key="energy_tax_per_kwh",
        translation_key="energy_tax_per_kwh",
        name="Energy tax per kWh",
        icon="mdi:bank",
        native_min_value=0.0,
        native_max_value=1.0,
        native_step=0.00001,
        option_key=CONF_ENERGY_TAX_PER_KWH,
    ),
    H3XPredictiveDispatchNumberDescription(
        key="supplier_buy_markup",
        translation_key="supplier_buy_markup",
        name="Supplier import markup",
        icon="mdi:transmission-tower-import",
        native_min_value=-1.0,
        native_max_value=1.0,
        native_step=0.0001,
        option_key=CONF_SUPPLIER_BUY_MARKUP,
    ),
    H3XPredictiveDispatchNumberDescription(
        key="supplier_sell_markdown",
        translation_key="supplier_sell_markdown",
        name="Supplier export deduction",
        icon="mdi:transmission-tower-export",
        native_min_value=-1.0,
        native_max_value=1.0,
        native_step=0.0001,
        option_key=CONF_SUPPLIER_SELL_MARKDOWN,
    ),
    H3XPredictiveDispatchNumberDescription(
        key="battery_module_count",
        translation_key="battery_module_count",
        name="Battery module count",
        icon="mdi:battery-sync",
        native_min_value=float(FORCE_H3_MIN_MODULES),
        native_max_value=float(FORCE_H3_MAX_MODULES),
        native_step=1.0,
        option_key=CONF_BATTERY_MODULE_COUNT,
    ),
    H3XPredictiveDispatchNumberDescription(
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
    H3XPredictiveDispatchNumberDescription(
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
    H3XPredictiveDispatchNumberDescription(
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
    H3XPredictiveDispatchNumberDescription(
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
    H3XPredictiveDispatchNumberDescription(
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
    H3XPredictiveDispatchNumberDescription(
        key="max_charge_c_rate",
        translation_key="max_charge_c_rate",
        name="Maximum charge C-rate",
        icon="mdi:battery-arrow-up",
        native_min_value=0.05,
        native_max_value=0.5,
        native_step=0.01,
        option_key=CONF_MAX_CHARGE_C_RATE,
    ),
    H3XPredictiveDispatchNumberDescription(
        key="max_discharge_c_rate",
        translation_key="max_discharge_c_rate",
        name="Maximum discharge C-rate",
        icon="mdi:battery-arrow-down",
        native_min_value=0.05,
        native_max_value=0.5,
        native_step=0.01,
        option_key=CONF_MAX_DISCHARGE_C_RATE,
    ),
    H3XPredictiveDispatchNumberDescription(
        key="pv_panel_count",
        translation_key="pv_panel_count",
        name="PV panel count",
        icon="mdi:solar-panel-large",
        native_min_value=0.0,
        native_max_value=200.0,
        native_step=1.0,
        option_key=CONF_PV_PANEL_COUNT,
    ),
    H3XPredictiveDispatchNumberDescription(
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
    H3XPredictiveDispatchNumberDescription(
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
    coordinator: H3XPredictiveDispatchCoordinator = entry.runtime_data
    async_add_entities(
        H3XPredictiveDispatchNumber(coordinator, entry, description)
        for description in NUMBERS
    )


class H3XPredictiveDispatchNumber(CoordinatorEntity[H3XPredictiveDispatchCoordinator], NumberEntity):
    """A runtime number control for the arbitrage optimizer."""

    entity_description: H3XPredictiveDispatchNumberDescription
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: H3XPredictiveDispatchCoordinator,
        entry: ConfigEntry,
        description: H3XPredictiveDispatchNumberDescription,
    ) -> None:
        """Initialize the number control."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Pylontech H3X Predictive Dispatch",
            "manufacturer": "Local",
            "model": "Predictive Energy Optimizer",
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
