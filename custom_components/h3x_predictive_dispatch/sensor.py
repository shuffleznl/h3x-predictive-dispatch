"""Sensors for Pylontech H3X energy arbitrage."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfPower, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_CURRENCY,
    DEFAULT_CURRENCY,
    DOMAIN,
    NORDPOOL_CONF_CURRENCY,
    NORDPOOL_DOMAIN,
)
from .coordinator import H3XPredictiveDispatchCoordinator

MONETARY_SENSOR_KEYS = frozenset(
    {
        "first_slot_value",
        "estimated_savings",
        "estimated_savings_today",
        "baseline_grid_cost",
        "optimized_grid_cost",
        "modeled_cycle_cost",
        "modeled_transition_cost",
    }
)

UNRECORDED_PLAN_ATTRIBUTES = frozenset(
    {
        "dispatch_plan",
        "price_slots",
        "price_trend",
        "load_forecast",
        "solar_forecast",
        "planned_charge_slots",
        "planned_discharge_slots",
        "today_slots",
        "tomorrow_slots",
    }
)


@dataclass(frozen=True, kw_only=True)
class H3XPredictiveDispatchSensorDescription(SensorEntityDescription):
    """Describe an arbitrage sensor."""

    value_fn: Callable[[dict[str, Any]], Any]
    extra_fn: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None


def _decision_attributes(data: dict[str, Any]) -> dict[str, Any]:
    """Return rich diagnostics for the decision sensor."""
    raw_attributes = dict(data.get("attributes") or {})
    attributes = {
        key: raw_attributes.get(key)
        for key in (
            "area",
            "currency",
            "min_soc",
            "max_soc",
            "capacity_kwh",
            "capacity_basis",
            "battery_system_capacity_kwh",
            "battery_usable_capacity_kwh",
            "battery_usable_depth_of_discharge",
            "battery_module_count",
            "battery_module_capacity_kwh",
            "battery_capacity_source",
            "battery_capacity_warning",
            "max_charge_c_rate",
            "max_discharge_c_rate",
            "max_charge_c_rate_power_w",
            "max_discharge_c_rate_power_w",
            "target_c_rate",
            "temperature_guard",
            "control_enabled",
            "strategy_profile",
            "terminal_soc_mode",
            "discharge_power_mode",
            "discharge_spread_price_tolerance_pct",
            "discharge_spread_max_hours",
            "discharge_spread_reason",
            "discharge_spread_price_floor",
            "discharge_spread_slots",
            "discharge_spread_window_hours",
            "discharge_spread_energy_kwh",
            "target_power_before_shaping_w",
            "target_power_before_grid_limit_w",
            "grid_import_limit_w",
            "grid_export_limit_w",
            "load_power_entity",
            "home_load_power_source",
            "shelly_total_power_entity",
            "shelly_phase_a_power_entity",
            "shelly_phase_b_power_entity",
            "shelly_phase_c_power_entity",
            "grid_import_power_entity",
            "grid_import_average_source",
            "grid_import_trend_w_per_min",
            "grid_import_trend_samples",
            "solar_power_entity",
            "solar_forecast_source",
            "solar_forecast_scale",
            "solcast_fetched_at",
            "solcast_interval_count",
            "solcast_status",
            "solcast_error",
            "load_forecast_source",
            "load_forecast_observations",
            "load_forecast_days",
            "load_forecast_mae_w",
            "load_forecast_bias_w",
            "ev_forecast_mode",
            "ev_sessions_detected",
            "pv_orientation",
            "pv_panel_count",
            "pv_panel_wp",
            "pv_peak_power_w",
            "pv_inverter_limit_w",
            "nordpool_resolution_minutes",
            "price_fetch_errors",
            "price_trend_direction",
            "price_trend_delta_next",
            "price_trend_price",
            "next_charge_slot",
            "next_discharge_slot",
            "periodic_full_charge_slot",
            "normal_max_soc",
            "periodic_full_charge_enabled",
            "periodic_full_charge_due",
            "periodic_full_charge_target_soc",
            "periodic_full_charge_threshold_soc",
            "periodic_full_charge_interval_days",
            "periodic_full_charge_last_at",
            "periodic_full_charge_next_due_at",
            "optimizer",
            "optimizer_diagnostics",
            "baseline_grid_cost",
            "optimized_grid_cost",
            "modeled_cycle_cost",
            "modeled_transition_cost",
            "equivalent_full_cycles",
            "dutch_tariff_enabled",
            "vat_percent",
            "energy_tax_per_kwh",
            "supplier_buy_markup_per_kwh",
            "supplier_sell_markdown_per_kwh",
        )
    }
    attributes.update(
        {
            "reason": data.get("reason"),
            "current_price": data.get("current_price"),
            "target_power_w": data.get("target_power_w"),
            "target_power_percent": data.get("target_power_percent"),
            "soc": data.get("soc"),
            "load_power_w": data.get("load_power_w"),
            "solar_power_w": data.get("solar_power_w"),
            "forecast_load_power_w": data.get("forecast_load_power_w"),
            "forecast_solar_power_w": data.get("forecast_solar_power_w"),
            "grid_import_power_w": data.get("grid_import_power_w"),
            "grid_import_average_power_w": data.get(
                "grid_import_average_power_w"
            ),
            "grid_charge_headroom_w": data.get("grid_charge_headroom_w"),
            "bms_temperature_c": data.get("bms_temperature_c"),
            "resolution_minutes": data.get("resolution_minutes"),
            "slots_available": data.get("slots_available"),
            "next_slot_start": data.get("next_slot_start"),
            "next_slot_end": data.get("next_slot_end"),
            "estimated_first_slot_value": data.get("estimated_first_slot_value"),
            "estimated_plan_value": data.get("estimated_plan_value"),
            "estimated_today_value": data.get("estimated_today_value"),
            "planned_charge_kwh": data.get("planned_charge_kwh"),
            "planned_discharge_kwh": data.get("planned_discharge_kwh"),
            "planned_grid_charge_kwh": data.get("planned_grid_charge_kwh"),
            "planned_solar_charge_kwh": data.get("planned_solar_charge_kwh"),
            "planned_self_consumption_kwh": data.get(
                "planned_self_consumption_kwh"
            ),
            "planned_grid_export_kwh": data.get("planned_grid_export_kwh"),
            "forecast_load_kwh": data.get("forecast_load_kwh"),
            "forecast_solar_kwh": data.get("forecast_solar_kwh"),
            "applied": data.get("applied"),
            "apply_error": data.get("apply_error"),
            "updated_at": data.get("updated_at"),
        }
    )
    return attributes


def _price_plan_attributes(data: dict[str, Any]) -> dict[str, Any]:
    """Return price and dispatch arrays for dashboard charts."""
    attributes = dict(data.get("attributes") or {})
    return {
        "area": attributes.get("area"),
        "currency": attributes.get("currency"),
        "resolution_minutes": data.get("resolution_minutes"),
        "updated_at": data.get("updated_at"),
        "price_trend_direction": attributes.get("price_trend_direction"),
        "price_trend_delta_next": attributes.get("price_trend_delta_next"),
        "price_slots": attributes.get("price_slots", []),
        "price_trend": attributes.get("price_trend", []),
        "load_forecast": attributes.get("load_forecast", []),
        "solar_forecast": attributes.get("solar_forecast", []),
        "dispatch_plan": attributes.get("dispatch_plan", []),
    }


def _attribute(data: dict[str, Any], key: str) -> Any:
    """Return an attribute from the coordinator data payload."""
    return (data.get("attributes") or {}).get(key)


def _slot_state(data: dict[str, Any], key: str) -> str:
    """Return a stable sensor state for a planned slot attribute."""
    slot = _attribute(data, key)
    if isinstance(slot, dict):
        if slot.get("state") == "active":
            return "active"
        start = slot.get("start")
        if start:
            return str(start)
        return str(slot.get("state") or "none")
    return "none"


def _slot_attributes(data: dict[str, Any], key: str) -> dict[str, Any]:
    """Return all details for a planned slot sensor."""
    slot = _attribute(data, key)
    return dict(slot) if isinstance(slot, dict) else {"state": "none"}


def _periodic_full_charge_slot_state(data: dict[str, Any]) -> str:
    """Return a stable state for the periodic full-charge slot."""
    slot = _attribute(data, "periodic_full_charge_slot")
    if isinstance(slot, dict):
        start = slot.get("start")
        if start:
            return str(start)
        return str(slot.get("state") or "unknown")
    return "unknown"


def _price_trend_attributes(data: dict[str, Any]) -> dict[str, Any]:
    """Return concise current trend diagnostics."""
    return {
        "price_trend_delta_next": _attribute(data, "price_trend_delta_next"),
        "price_trend_price": _attribute(data, "price_trend_price"),
    }


SENSORS: tuple[H3XPredictiveDispatchSensorDescription, ...] = (
    H3XPredictiveDispatchSensorDescription(
        key="decision",
        translation_key="decision",
        name="Decision",
        icon="mdi:battery-sync",
        value_fn=lambda data: data.get("action"),
        extra_fn=_decision_attributes,
    ),
    H3XPredictiveDispatchSensorDescription(
        key="target_power",
        translation_key="target_power",
        name="Target power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("target_power_w"),
    ),
    H3XPredictiveDispatchSensorDescription(
        key="target_power_percent",
        translation_key="target_power_percent",
        name="Target power percent",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("target_power_percent"),
    ),
    H3XPredictiveDispatchSensorDescription(
        key="battery_system_capacity",
        translation_key="battery_system_capacity",
        name="Battery system capacity",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery-high",
        value_fn=lambda data: (data.get("attributes") or {}).get(
            "battery_system_capacity_kwh"
        ),
    ),
    H3XPredictiveDispatchSensorDescription(
        key="battery_usable_capacity",
        translation_key="battery_usable_capacity",
        name="Battery usable capacity",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery-check",
        value_fn=lambda data: (data.get("attributes") or {}).get(
            "battery_usable_capacity_kwh"
        ),
    ),
    H3XPredictiveDispatchSensorDescription(
        key="target_c_rate",
        translation_key="target_c_rate",
        name="Target C-rate",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:speedometer",
        value_fn=lambda data: (data.get("attributes") or {}).get("target_c_rate"),
    ),
    H3XPredictiveDispatchSensorDescription(
        key="home_load_power",
        translation_key="home_load_power",
        name="Home load power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:home-lightning-bolt",
        value_fn=lambda data: data.get("load_power_w"),
    ),
    H3XPredictiveDispatchSensorDescription(
        key="solar_power",
        translation_key="solar_power",
        name="Solar power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:solar-power",
        value_fn=lambda data: data.get("solar_power_w"),
    ),
    H3XPredictiveDispatchSensorDescription(
        key="forecast_load_power",
        translation_key="forecast_load_power",
        name="Forecast load power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:home-analytics",
        value_fn=lambda data: data.get("forecast_load_power_w"),
    ),
    H3XPredictiveDispatchSensorDescription(
        key="forecast_solar_power",
        translation_key="forecast_solar_power",
        name="Forecast solar power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:weather-sunny",
        value_fn=lambda data: data.get("forecast_solar_power_w"),
    ),
    H3XPredictiveDispatchSensorDescription(
        key="next_charge_slot",
        translation_key="next_charge_slot",
        name="Next charge slot",
        icon="mdi:battery-clock",
        value_fn=lambda data: _slot_state(data, "next_charge_slot"),
        extra_fn=lambda data: _slot_attributes(data, "next_charge_slot"),
    ),
    H3XPredictiveDispatchSensorDescription(
        key="next_discharge_slot",
        translation_key="next_discharge_slot",
        name="Next discharge slot",
        icon="mdi:battery-clock-outline",
        value_fn=lambda data: _slot_state(data, "next_discharge_slot"),
        extra_fn=lambda data: _slot_attributes(data, "next_discharge_slot"),
    ),
    H3XPredictiveDispatchSensorDescription(
        key="periodic_full_charge_slot",
        translation_key="periodic_full_charge_slot",
        name="Periodic full-charge slot",
        icon="mdi:battery-charging-100",
        value_fn=_periodic_full_charge_slot_state,
        extra_fn=lambda data: _slot_attributes(data, "periodic_full_charge_slot"),
    ),
    H3XPredictiveDispatchSensorDescription(
        key="current_price",
        translation_key="current_price",
        name="Current price",
        value_fn=lambda data: data.get("current_price"),
    ),
    H3XPredictiveDispatchSensorDescription(
        key="price_trend",
        translation_key="price_trend",
        name="Price trend",
        icon="mdi:trending-up",
        value_fn=lambda data: _attribute(data, "price_trend_direction"),
        extra_fn=_price_trend_attributes,
    ),
    H3XPredictiveDispatchSensorDescription(
        key="reason",
        translation_key="reason",
        name="Decision reason",
        icon="mdi:text-search",
        value_fn=lambda data: data.get("reason"),
    ),
    H3XPredictiveDispatchSensorDescription(
        key="first_slot_value",
        translation_key="first_slot_value",
        name="First slot value",
        device_class=SensorDeviceClass.MONETARY,
        value_fn=lambda data: data.get("estimated_first_slot_value"),
    ),
    H3XPredictiveDispatchSensorDescription(
        key="estimated_savings",
        translation_key="estimated_savings",
        name="Estimated savings",
        device_class=SensorDeviceClass.MONETARY,
        icon="mdi:cash-multiple",
        value_fn=lambda data: data.get("estimated_plan_value"),
    ),
    H3XPredictiveDispatchSensorDescription(
        key="estimated_savings_today",
        translation_key="estimated_savings_today",
        name="Estimated savings today",
        device_class=SensorDeviceClass.MONETARY,
        icon="mdi:cash-clock",
        value_fn=lambda data: data.get("estimated_today_value"),
    ),
    H3XPredictiveDispatchSensorDescription(
        key="baseline_grid_cost",
        translation_key="baseline_grid_cost",
        name="Baseline grid cost",
        device_class=SensorDeviceClass.MONETARY,
        icon="mdi:cash-remove",
        value_fn=lambda data: _attribute(data, "baseline_grid_cost"),
    ),
    H3XPredictiveDispatchSensorDescription(
        key="optimized_grid_cost",
        translation_key="optimized_grid_cost",
        name="Optimized grid cost",
        device_class=SensorDeviceClass.MONETARY,
        icon="mdi:cash-check",
        value_fn=lambda data: _attribute(data, "optimized_grid_cost"),
    ),
    H3XPredictiveDispatchSensorDescription(
        key="modeled_cycle_cost",
        translation_key="modeled_cycle_cost",
        name="Modeled cycle cost",
        device_class=SensorDeviceClass.MONETARY,
        icon="mdi:battery-heart-variant",
        value_fn=lambda data: _attribute(data, "modeled_cycle_cost"),
    ),
    H3XPredictiveDispatchSensorDescription(
        key="modeled_transition_cost",
        translation_key="modeled_transition_cost",
        name="Modeled transition cost",
        device_class=SensorDeviceClass.MONETARY,
        icon="mdi:swap-horizontal",
        value_fn=lambda data: _attribute(data, "modeled_transition_cost"),
    ),
    H3XPredictiveDispatchSensorDescription(
        key="forecast_accuracy",
        translation_key="forecast_accuracy",
        name="Load forecast MAE",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:target",
        value_fn=lambda data: _attribute(data, "load_forecast_mae_w"),
    ),
    H3XPredictiveDispatchSensorDescription(
        key="equivalent_full_cycles",
        translation_key="equivalent_full_cycles",
        name="Planned equivalent full cycles",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery-sync",
        value_fn=lambda data: _attribute(data, "equivalent_full_cycles"),
    ),
    H3XPredictiveDispatchSensorDescription(
        key="planned_charge_energy",
        translation_key="planned_charge_energy",
        name="Planned charge energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        icon="mdi:battery-plus",
        value_fn=lambda data: data.get("planned_charge_kwh"),
    ),
    H3XPredictiveDispatchSensorDescription(
        key="planned_discharge_energy",
        translation_key="planned_discharge_energy",
        name="Planned discharge energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        icon="mdi:battery-minus",
        value_fn=lambda data: data.get("planned_discharge_kwh"),
    ),
    H3XPredictiveDispatchSensorDescription(
        key="planned_grid_charge_energy",
        translation_key="planned_grid_charge_energy",
        name="Planned grid charge energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        icon="mdi:transmission-tower-import",
        value_fn=lambda data: data.get("planned_grid_charge_kwh"),
    ),
    H3XPredictiveDispatchSensorDescription(
        key="planned_solar_charge_energy",
        translation_key="planned_solar_charge_energy",
        name="Planned solar charge energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        icon="mdi:solar-power-variant",
        value_fn=lambda data: data.get("planned_solar_charge_kwh"),
    ),
    H3XPredictiveDispatchSensorDescription(
        key="planned_self_consumption_energy",
        translation_key="planned_self_consumption_energy",
        name="Planned self-consumption energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        icon="mdi:home-battery",
        value_fn=lambda data: data.get("planned_self_consumption_kwh"),
    ),
    H3XPredictiveDispatchSensorDescription(
        key="planned_battery_export_energy",
        translation_key="planned_battery_export_energy",
        name="Planned battery export energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        icon="mdi:transmission-tower-export",
        value_fn=lambda data: data.get("planned_grid_export_kwh"),
    ),
    H3XPredictiveDispatchSensorDescription(
        key="forecast_load_energy",
        translation_key="forecast_load_energy",
        name="Forecast load energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        icon="mdi:home-analytics",
        value_fn=lambda data: data.get("forecast_load_kwh"),
    ),
    H3XPredictiveDispatchSensorDescription(
        key="forecast_solar_energy",
        translation_key="forecast_solar_energy",
        name="Forecast solar energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        icon="mdi:solar-power",
        value_fn=lambda data: data.get("forecast_solar_kwh"),
    ),
    H3XPredictiveDispatchSensorDescription(
        key="price_plan",
        translation_key="price_plan",
        name="Price plan",
        icon="mdi:chart-timeline-variant",
        value_fn=lambda data: data.get("current_price"),
        extra_fn=_price_plan_attributes,
    ),
    H3XPredictiveDispatchSensorDescription(
        key="resolution_minutes",
        translation_key="resolution_minutes",
        name="Price resolution",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("resolution_minutes"),
    ),
    H3XPredictiveDispatchSensorDescription(
        key="slots_available",
        translation_key="slots_available",
        name="Price slots available",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("slots_available"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors from a config entry."""
    coordinator: H3XPredictiveDispatchCoordinator = entry.runtime_data
    async_add_entities(
        H3XPredictiveDispatchSensor(coordinator, entry, description) for description in SENSORS
    )


class H3XPredictiveDispatchSensor(CoordinatorEntity[H3XPredictiveDispatchCoordinator], SensorEntity):
    """A diagnostic sensor for the arbitrage controller."""

    _unrecorded_attributes = UNRECORDED_PLAN_ATTRIBUTES
    entity_description: H3XPredictiveDispatchSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: H3XPredictiveDispatchCoordinator,
        entry: ConfigEntry,
        description: H3XPredictiveDispatchSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Pylontech H3X Predictive Dispatch",
            "manufacturer": "Local",
            "model": "Predictive Energy Optimizer",
        }

    @property
    def native_value(self) -> Any:
        """Return the sensor state."""
        return self.entity_description.value_fn(self.coordinator.data or {})

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return dynamic units for price and monetary plan sensors."""
        if self.entity_description.key == "current_price":
            return f"{self._currency_code()}/{UnitOfEnergy.KILO_WATT_HOUR}"
        if self.entity_description.key in MONETARY_SENSOR_KEYS:
            return self._currency_code()
        return self.entity_description.native_unit_of_measurement

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return optional attributes."""
        if self.entity_description.extra_fn is None:
            return None
        return self.entity_description.extra_fn(self.coordinator.data or {})

    def _currency_code(self) -> str:
        """Return the active ISO 4217 currency code."""
        data = self.coordinator.data or {}
        attributes = dict(data.get("attributes") or {})
        currency = str(attributes.get("currency") or "").strip().upper()
        if currency and currency != DEFAULT_CURRENCY.upper():
            return currency

        configured = str(
            self._entry.options.get(
                CONF_CURRENCY,
                self._entry.data.get(CONF_CURRENCY, DEFAULT_CURRENCY),
            )
        ).strip().upper()
        if configured and configured != DEFAULT_CURRENCY.upper():
            return configured

        for entry in self.coordinator.hass.config_entries.async_entries(
            NORDPOOL_DOMAIN
        ):
            currency = str(entry.data.get(NORDPOOL_CONF_CURRENCY) or "").strip().upper()
            if currency:
                return currency

        return "EUR"
