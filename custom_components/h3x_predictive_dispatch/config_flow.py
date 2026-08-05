"""Config flow for Pylontech H3X energy arbitrage."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_ACTION_START_COST,
    CONF_AREA,
    CONF_BATTERY_CAPACITY_KWH,
    CONF_BATTERY_MODULE_COUNT,
    CONF_BATTERY_MODULE_COUNT_ENTITY,
    CONF_BATTERY_SYSTEM_CAPACITY_ENTITY,
    CONF_BATTERY_USABLE_CAPACITY_ENTITY,
    CONF_BATTERY_USABLE_CAPACITY_KWH,
    CONF_BMS_TEMP_ENTITY,
    CONF_BUY_COST_ADDER,
    CONF_CHARGE_LIMIT_SOC_ENTITY,
    CONF_CONTINUOUS_POWER_W,
    CONF_CONTROL_ENABLED,
    CONF_CURRENCY,
    CONF_CYCLE_COST,
    CONF_DIRECTION_CHANGE_COST,
    CONF_DISCHARGE_LIMIT_SOC_ENTITY,
    CONF_DISCHARGE_POWER_MODE,
    CONF_DISCHARGE_SPREAD_MAX_HOURS,
    CONF_DISCHARGE_SPREAD_PRICE_TOLERANCE,
    CONF_DUTCH_TARIFF_ENABLED,
    CONF_EMS_MODE_ENTITY,
    CONF_ENABLE_PEAK_POWER,
    CONF_ENERGY_TAX_PER_KWH,
    CONF_EV_CHARGING_THRESHOLD_W,
    CONF_EV_FORECAST_MODE,
    CONF_EV_POWER_ENTITY,
    CONF_FORECAST_RISK_PERCENTILE,
    CONF_GRID_EXPORT_LIMIT_W,
    CONF_GRID_IMPORT_LIMIT_W,
    CONF_GRID_IMPORT_POWER_ENTITY,
    CONF_HORIZON_HOURS,
    CONF_IDLE_EMS_MODE,
    CONF_INVERTER_FULL_SCALE_POWER_W,
    CONF_LOAD_FORECAST_MODE,
    CONF_LOAD_HISTORY_DAYS,
    CONF_LOAD_POWER_ENTITY,
    CONF_MAX_BMS_TEMP_C,
    CONF_MAX_CHARGE_C_RATE,
    CONF_MAX_DISCHARGE_C_RATE,
    CONF_MAX_SOC,
    CONF_MIN_ACTION_DURATION_MINUTES,
    CONF_MIN_ACTIVE_POWER_W,
    CONF_MIN_CHARGE_TEMP_C,
    CONF_MIN_PROFIT_MARGIN,
    CONF_MIN_SOC,
    CONF_NORDPOOL_CONFIG_ENTRY,
    CONF_PEAK_EXTRA_MARGIN,
    CONF_PEAK_POWER_W,
    CONF_PERIODIC_FULL_CHARGE_ENABLED,
    CONF_PERIODIC_FULL_CHARGE_INTERVAL_DAYS,
    CONF_PERIODIC_FULL_CHARGE_TARGET_SOC,
    CONF_PERIODIC_FULL_CHARGE_THRESHOLD_SOC,
    CONF_POWER_REF_ENTITY,
    CONF_PV_INVERTER_LIMIT_W,
    CONF_PV_ORIENTATION,
    CONF_PV_PANEL_COUNT,
    CONF_PV_PANEL_WP,
    CONF_RESERVE_SOC,
    CONF_RESOLUTION,
    CONF_ROUND_TRIP_EFFICIENCY,
    CONF_SELL_COST_ADDER,
    CONF_SHELLY_PHASE_A_POWER_ENTITY,
    CONF_SHELLY_PHASE_B_POWER_ENTITY,
    CONF_SHELLY_PHASE_C_POWER_ENTITY,
    CONF_SHELLY_TOTAL_POWER_ENTITY,
    CONF_SOC_ENTITY,
    CONF_SOLAR_FORECAST_SOURCE,
    CONF_SOLAR_POWER_ENTITY,
    CONF_SOLCAST_API_KEY,
    CONF_SOLCAST_RESOURCE_ID,
    CONF_SOLCAST_UPDATE_INTERVAL_HOURS,
    CONF_STRATEGY_PROFILE,
    CONF_SUPPLIER_BUY_MARKUP,
    CONF_SUPPLIER_SELL_MARKDOWN,
    CONF_TERMINAL_SOC_MODE,
    CONF_UPDATE_INTERVAL_MINUTES,
    CONF_USER_EMS_MODE,
    CONF_VAT_PERCENT,
    CURRENCIES,
    DEFAULT_STRATEGY_PROFILE,
    DEFAULTS,
    DISCHARGE_POWER_MODES,
    DOMAIN,
    EMS_MODE_OPTIONS,
    EV_FORECAST_MODES,
    FORCE_H3_MAX_MODULES,
    FORCE_H3_MIN_MODULES,
    FORCE_H3_SYSTEM_CAPACITY_KWH,
    FORCE_H3_USABLE_CAPACITY_KWH,
    FORCE_H3_USABLE_DOD,
    LOAD_FORECAST_MODES,
    NORDPOOL_AREAS,
    NORDPOOL_CONF_AREAS,
    NORDPOOL_CONF_CURRENCY,
    NORDPOOL_DOMAIN,
    PV_ORIENTATIONS,
    RESOLUTIONS,
    SOLAR_FORECAST_SOURCES,
    STRATEGY_PROFILE_SETTINGS,
    STRATEGY_PROFILES,
    TERMINAL_SOC_MODES,
)
from .meter import (
    autodetect_shelly_total_active_power,
    autodetect_sma_pv_power,
    entity_has_numeric_state,
)


class H3XPredictiveDispatchConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 6

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial setup step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            user_input = _normalize_resolution(user_input)
            user_input = _apply_module_count_settings(user_input)
            user_input = _apply_profile_when_changed(user_input)
            errors = _validate_user_input(user_input)
            if not errors:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="Pylontech H3X Predictive Dispatch",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_schema(self.hass, user_input),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return H3XPredictiveDispatchOptionsFlow()


class H3XPredictiveDispatchOptionsFlow(config_entries.OptionsFlow):
    """Handle options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage options."""
        current = {**self.config_entry.data, **self.config_entry.options}
        errors: dict[str, str] = {}

        if user_input is not None:
            user_input = _normalize_resolution(user_input)
            user_input = _apply_module_count_settings(user_input)
            user_input = _apply_profile_when_changed(user_input, current)
            errors = _validate_user_input(user_input)
            if not errors:
                return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=_schema(self.hass, user_input or current),
            errors=errors,
        )


def _schema(
    hass: HomeAssistant,
    values: dict[str, Any] | None = None,
) -> vol.Schema:
    """Build a setup/options schema."""
    data = {**DEFAULTS, **_autodetected_defaults(hass)}
    if values:
        data.update(values)
    data = _replace_unavailable_autodetected_entities(hass, data)
    data = _normalize_resolution(data)
    data = _apply_module_count_settings(data)

    return vol.Schema(
        {
            vol.Optional(
                CONF_NORDPOOL_CONFIG_ENTRY,
                default=data[CONF_NORDPOOL_CONFIG_ENTRY],
            ): str,
            vol.Optional(CONF_AREA, default=data[CONF_AREA]): vol.In(NORDPOOL_AREAS),
            vol.Optional(CONF_CURRENCY, default=data[CONF_CURRENCY]): vol.In(CURRENCIES),
            vol.Optional(CONF_RESOLUTION, default=data[CONF_RESOLUTION]): vol.All(
                vol.Coerce(int), vol.In(RESOLUTIONS)
            ),
            vol.Optional(
                CONF_CONTROL_ENABLED, default=data[CONF_CONTROL_ENABLED]
            ): bool,
            vol.Optional(
                CONF_STRATEGY_PROFILE, default=data[CONF_STRATEGY_PROFILE]
            ): vol.In(STRATEGY_PROFILES),
            vol.Optional(
                CONF_LOAD_FORECAST_MODE, default=data[CONF_LOAD_FORECAST_MODE]
            ): vol.In(LOAD_FORECAST_MODES),
            vol.Optional(
                CONF_LOAD_HISTORY_DAYS, default=data[CONF_LOAD_HISTORY_DAYS]
            ): vol.All(vol.Coerce(float), vol.Range(min=2.0, max=90.0)),
            vol.Optional(
                CONF_EV_FORECAST_MODE, default=data[CONF_EV_FORECAST_MODE]
            ): vol.In(EV_FORECAST_MODES),
            vol.Optional(
                CONF_EV_POWER_ENTITY, default=data[CONF_EV_POWER_ENTITY]
            ): str,
            vol.Optional(
                CONF_EV_CHARGING_THRESHOLD_W,
                default=data[CONF_EV_CHARGING_THRESHOLD_W],
            ): vol.All(vol.Coerce(float), vol.Range(min=500.0, max=22000.0)),
            vol.Optional(
                CONF_EMS_MODE_ENTITY, default=data[CONF_EMS_MODE_ENTITY]
            ): EntitySelector(EntitySelectorConfig(domain="select")),
            vol.Optional(
                CONF_POWER_REF_ENTITY, default=data[CONF_POWER_REF_ENTITY]
            ): str,
            vol.Optional(CONF_SOC_ENTITY, default=data[CONF_SOC_ENTITY]): str,
            vol.Optional(
                CONF_LOAD_POWER_ENTITY, default=data[CONF_LOAD_POWER_ENTITY]
            ): str,
            vol.Optional(
                CONF_SHELLY_TOTAL_POWER_ENTITY,
                default=data[CONF_SHELLY_TOTAL_POWER_ENTITY],
            ): str,
            vol.Optional(
                CONF_SHELLY_PHASE_A_POWER_ENTITY,
                default=data[CONF_SHELLY_PHASE_A_POWER_ENTITY],
            ): str,
            vol.Optional(
                CONF_SHELLY_PHASE_B_POWER_ENTITY,
                default=data[CONF_SHELLY_PHASE_B_POWER_ENTITY],
            ): str,
            vol.Optional(
                CONF_SHELLY_PHASE_C_POWER_ENTITY,
                default=data[CONF_SHELLY_PHASE_C_POWER_ENTITY],
            ): str,
            vol.Optional(
                CONF_GRID_IMPORT_POWER_ENTITY,
                default=data[CONF_GRID_IMPORT_POWER_ENTITY],
            ): EntitySelector(
                EntitySelectorConfig(domain="sensor", device_class="power")
            ),
            vol.Optional(
                CONF_SOLAR_POWER_ENTITY, default=data[CONF_SOLAR_POWER_ENTITY]
            ): str,
            vol.Optional(
                CONF_SOLAR_FORECAST_SOURCE,
                default=data[CONF_SOLAR_FORECAST_SOURCE],
            ): vol.In(SOLAR_FORECAST_SOURCES),
            vol.Optional(
                CONF_SOLCAST_API_KEY,
                default=data[CONF_SOLCAST_API_KEY],
            ): TextSelector(
                TextSelectorConfig(
                    type=TextSelectorType.PASSWORD,
                    autocomplete="current-password",
                )
            ),
            vol.Optional(
                CONF_SOLCAST_RESOURCE_ID,
                default=data[CONF_SOLCAST_RESOURCE_ID],
            ): str,
            vol.Optional(
                CONF_SOLCAST_UPDATE_INTERVAL_HOURS,
                default=data[CONF_SOLCAST_UPDATE_INTERVAL_HOURS],
            ): vol.All(vol.Coerce(float), vol.Range(min=3.0, max=24.0)),
            vol.Optional(
                CONF_PV_ORIENTATION, default=data[CONF_PV_ORIENTATION]
            ): vol.In(PV_ORIENTATIONS),
            vol.Optional(
                CONF_PV_PANEL_COUNT, default=data[CONF_PV_PANEL_COUNT]
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=200.0)),
            vol.Optional(CONF_PV_PANEL_WP, default=data[CONF_PV_PANEL_WP]): vol.All(
                vol.Coerce(float), vol.Range(min=0.0, max=1500.0)
            ),
            vol.Optional(
                CONF_PV_INVERTER_LIMIT_W,
                default=data[CONF_PV_INVERTER_LIMIT_W],
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=50000.0)),
            vol.Optional(
                CONF_BATTERY_MODULE_COUNT_ENTITY,
                default=data[CONF_BATTERY_MODULE_COUNT_ENTITY],
            ): str,
            vol.Optional(
                CONF_BATTERY_SYSTEM_CAPACITY_ENTITY,
                default=data[CONF_BATTERY_SYSTEM_CAPACITY_ENTITY],
            ): str,
            vol.Optional(
                CONF_BATTERY_USABLE_CAPACITY_ENTITY,
                default=data[CONF_BATTERY_USABLE_CAPACITY_ENTITY],
            ): str,
            vol.Optional(
                CONF_BMS_TEMP_ENTITY, default=data[CONF_BMS_TEMP_ENTITY]
            ): str,
            vol.Optional(
                CONF_CHARGE_LIMIT_SOC_ENTITY,
                default=data[CONF_CHARGE_LIMIT_SOC_ENTITY],
            ): str,
            vol.Optional(
                CONF_DISCHARGE_LIMIT_SOC_ENTITY,
                default=data[CONF_DISCHARGE_LIMIT_SOC_ENTITY],
            ): str,
            vol.Optional(
                CONF_BATTERY_MODULE_COUNT,
                default=data[CONF_BATTERY_MODULE_COUNT],
            ): vol.All(
                vol.Coerce(float),
                vol.Range(min=FORCE_H3_MIN_MODULES, max=FORCE_H3_MAX_MODULES),
            ),
            vol.Optional(
                CONF_BATTERY_CAPACITY_KWH,
                default=data[CONF_BATTERY_CAPACITY_KWH],
            ): vol.All(
                vol.Coerce(float),
                vol.Range(
                    min=min(FORCE_H3_SYSTEM_CAPACITY_KWH.values()),
                    max=max(FORCE_H3_SYSTEM_CAPACITY_KWH.values()),
                ),
            ),
            vol.Optional(
                CONF_BATTERY_USABLE_CAPACITY_KWH,
                default=data[CONF_BATTERY_USABLE_CAPACITY_KWH],
            ): vol.All(
                vol.Coerce(float),
                vol.Range(
                    min=min(FORCE_H3_USABLE_CAPACITY_KWH.values()),
                    max=max(FORCE_H3_USABLE_CAPACITY_KWH.values()),
                ),
            ),
            vol.Optional(CONF_MIN_SOC, default=data[CONF_MIN_SOC]): vol.All(
                vol.Coerce(float), vol.Range(min=0.0, max=95.0)
            ),
            vol.Optional(CONF_RESERVE_SOC, default=data[CONF_RESERVE_SOC]): vol.All(
                vol.Coerce(float), vol.Range(min=0.0, max=95.0)
            ),
            vol.Optional(CONF_MAX_SOC, default=data[CONF_MAX_SOC]): vol.All(
                vol.Coerce(float), vol.Range(min=5.0, max=100.0)
            ),
            vol.Optional(
                CONF_TERMINAL_SOC_MODE, default=data[CONF_TERMINAL_SOC_MODE]
            ): vol.In(TERMINAL_SOC_MODES),
            vol.Optional(
                CONF_PERIODIC_FULL_CHARGE_ENABLED,
                default=data[CONF_PERIODIC_FULL_CHARGE_ENABLED],
            ): bool,
            vol.Optional(
                CONF_PERIODIC_FULL_CHARGE_INTERVAL_DAYS,
                default=data[CONF_PERIODIC_FULL_CHARGE_INTERVAL_DAYS],
            ): vol.All(vol.Coerce(float), vol.Range(min=1.0, max=90.0)),
            vol.Optional(
                CONF_PERIODIC_FULL_CHARGE_TARGET_SOC,
                default=data[CONF_PERIODIC_FULL_CHARGE_TARGET_SOC],
            ): vol.All(vol.Coerce(float), vol.Range(min=95.0, max=100.0)),
            vol.Optional(
                CONF_PERIODIC_FULL_CHARGE_THRESHOLD_SOC,
                default=data[CONF_PERIODIC_FULL_CHARGE_THRESHOLD_SOC],
            ): vol.All(vol.Coerce(float), vol.Range(min=90.0, max=100.0)),
            vol.Optional(
                CONF_ROUND_TRIP_EFFICIENCY,
                default=data[CONF_ROUND_TRIP_EFFICIENCY],
            ): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=1.0)),
            vol.Optional(CONF_CYCLE_COST, default=data[CONF_CYCLE_COST]): vol.All(
                vol.Coerce(float), vol.Range(min=0.0, max=1.0)
            ),
            vol.Optional(
                CONF_MIN_PROFIT_MARGIN, default=data[CONF_MIN_PROFIT_MARGIN]
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                CONF_BUY_COST_ADDER, default=data[CONF_BUY_COST_ADDER]
            ): vol.All(vol.Coerce(float), vol.Range(min=-1.0, max=1.0)),
            vol.Optional(
                CONF_SELL_COST_ADDER, default=data[CONF_SELL_COST_ADDER]
            ): vol.All(vol.Coerce(float), vol.Range(min=-1.0, max=1.0)),
            vol.Optional(
                CONF_DUTCH_TARIFF_ENABLED,
                default=data[CONF_DUTCH_TARIFF_ENABLED],
            ): bool,
            vol.Optional(
                CONF_VAT_PERCENT, default=data[CONF_VAT_PERCENT]
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=100.0)),
            vol.Optional(
                CONF_ENERGY_TAX_PER_KWH,
                default=data[CONF_ENERGY_TAX_PER_KWH],
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                CONF_SUPPLIER_BUY_MARKUP,
                default=data[CONF_SUPPLIER_BUY_MARKUP],
            ): vol.All(vol.Coerce(float), vol.Range(min=-1.0, max=1.0)),
            vol.Optional(
                CONF_SUPPLIER_SELL_MARKDOWN,
                default=data[CONF_SUPPLIER_SELL_MARKDOWN],
            ): vol.All(vol.Coerce(float), vol.Range(min=-1.0, max=1.0)),
            vol.Optional(
                CONF_CONTINUOUS_POWER_W, default=data[CONF_CONTINUOUS_POWER_W]
            ): vol.All(vol.Coerce(float), vol.Range(min=100.0, max=50000.0)),
            vol.Optional(CONF_PEAK_POWER_W, default=data[CONF_PEAK_POWER_W]): vol.All(
                vol.Coerce(float), vol.Range(min=100.0, max=50000.0)
            ),
            vol.Optional(
                CONF_ENABLE_PEAK_POWER, default=data[CONF_ENABLE_PEAK_POWER]
            ): bool,
            vol.Optional(
                CONF_PEAK_EXTRA_MARGIN, default=data[CONF_PEAK_EXTRA_MARGIN]
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                CONF_MAX_CHARGE_C_RATE, default=data[CONF_MAX_CHARGE_C_RATE]
            ): vol.All(vol.Coerce(float), vol.Range(min=0.05, max=0.5)),
            vol.Optional(
                CONF_MAX_DISCHARGE_C_RATE,
                default=data[CONF_MAX_DISCHARGE_C_RATE],
            ): vol.All(vol.Coerce(float), vol.Range(min=0.05, max=0.5)),
            vol.Optional(
                CONF_INVERTER_FULL_SCALE_POWER_W,
                default=data[CONF_INVERTER_FULL_SCALE_POWER_W],
            ): vol.All(vol.Coerce(float), vol.Range(min=100.0, max=50000.0)),
            vol.Optional(
                CONF_MIN_ACTIVE_POWER_W, default=data[CONF_MIN_ACTIVE_POWER_W]
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=50000.0)),
            vol.Optional(
                CONF_GRID_IMPORT_LIMIT_W, default=data[CONF_GRID_IMPORT_LIMIT_W]
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=100000.0)),
            vol.Optional(
                CONF_GRID_EXPORT_LIMIT_W, default=data[CONF_GRID_EXPORT_LIMIT_W]
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=100000.0)),
            vol.Optional(
                CONF_DISCHARGE_POWER_MODE,
                default=data[CONF_DISCHARGE_POWER_MODE],
            ): vol.In(DISCHARGE_POWER_MODES),
            vol.Optional(
                CONF_DISCHARGE_SPREAD_PRICE_TOLERANCE,
                default=data[CONF_DISCHARGE_SPREAD_PRICE_TOLERANCE],
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=50.0)),
            vol.Optional(
                CONF_DISCHARGE_SPREAD_MAX_HOURS,
                default=data[CONF_DISCHARGE_SPREAD_MAX_HOURS],
            ): vol.All(vol.Coerce(float), vol.Range(min=0.25, max=12.0)),
            vol.Optional(
                CONF_MIN_ACTION_DURATION_MINUTES,
                default=data[CONF_MIN_ACTION_DURATION_MINUTES],
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=240.0)),
            vol.Optional(
                CONF_ACTION_START_COST, default=data[CONF_ACTION_START_COST]
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=5.0)),
            vol.Optional(
                CONF_DIRECTION_CHANGE_COST,
                default=data[CONF_DIRECTION_CHANGE_COST],
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=5.0)),
            vol.Optional(
                CONF_FORECAST_RISK_PERCENTILE,
                default=data[CONF_FORECAST_RISK_PERCENTILE],
            ): vol.All(vol.Coerce(float), vol.Range(min=50.0, max=90.0)),
            vol.Optional(
                CONF_HORIZON_HOURS, default=data[CONF_HORIZON_HOURS]
            ): vol.All(vol.Coerce(float), vol.Range(min=2.0, max=72.0)),
            vol.Optional(
                CONF_UPDATE_INTERVAL_MINUTES,
                default=data[CONF_UPDATE_INTERVAL_MINUTES],
            ): vol.All(vol.Coerce(float), vol.Range(min=1.0, max=60.0)),
            vol.Optional(
                CONF_USER_EMS_MODE, default=data[CONF_USER_EMS_MODE]
            ): SelectSelector(
                SelectSelectorConfig(options=list(EMS_MODE_OPTIONS))
            ),
            vol.Optional(
                CONF_IDLE_EMS_MODE, default=data[CONF_IDLE_EMS_MODE]
            ): SelectSelector(
                SelectSelectorConfig(options=list(EMS_MODE_OPTIONS))
            ),
            vol.Optional(
                CONF_MIN_CHARGE_TEMP_C, default=data[CONF_MIN_CHARGE_TEMP_C]
            ): vol.All(vol.Coerce(float), vol.Range(min=-20.0, max=30.0)),
            vol.Optional(
                CONF_MAX_BMS_TEMP_C, default=data[CONF_MAX_BMS_TEMP_C]
            ): vol.All(vol.Coerce(float), vol.Range(min=20.0, max=70.0)),
        }
    )


def _autodetected_defaults(hass: HomeAssistant) -> dict[str, Any]:
    """Return defaults from Nord Pool, Shelly and SMA when available."""
    defaults: dict[str, Any] = {}
    entries = hass.config_entries.async_entries(NORDPOOL_DOMAIN)
    if entries:
        entry = entries[0]
        areas = entry.data.get(NORDPOOL_CONF_AREAS)
        if isinstance(areas, list) and areas:
            defaults[CONF_AREA] = str(areas[0]).upper()
        currency = entry.data.get(NORDPOOL_CONF_CURRENCY)
        if currency:
            defaults[CONF_CURRENCY] = str(currency).upper()

    shelly_grid_entity = autodetect_shelly_total_active_power(hass)
    if shelly_grid_entity:
        defaults[CONF_GRID_IMPORT_POWER_ENTITY] = shelly_grid_entity
    sma_pv_entity = autodetect_sma_pv_power(hass)
    if sma_pv_entity:
        defaults[CONF_SOLAR_POWER_ENTITY] = sma_pv_entity
    return defaults


def _replace_unavailable_autodetected_entities(
    hass: HomeAssistant,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Replace stale meter/inverter selections shown by the config flow."""
    updated = dict(data)
    detected_grid = autodetect_shelly_total_active_power(hass)
    configured_grid = str(updated.get(CONF_GRID_IMPORT_POWER_ENTITY) or "").strip()
    if detected_grid and not entity_has_numeric_state(hass, configured_grid):
        updated[CONF_GRID_IMPORT_POWER_ENTITY] = detected_grid

    detected_solar = autodetect_sma_pv_power(hass)
    configured_solar = str(updated.get(CONF_SOLAR_POWER_ENTITY) or "").strip()
    if detected_solar and not entity_has_numeric_state(hass, configured_solar):
        updated[CONF_SOLAR_POWER_ENTITY] = detected_solar
    return updated


def _apply_profile_when_changed(
    data: dict[str, Any],
    current: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply preset values when the submitted strategy profile changed."""
    profile = str(data.get(CONF_STRATEGY_PROFILE, DEFAULT_STRATEGY_PROFILE))
    previous = (
        DEFAULT_STRATEGY_PROFILE
        if current is None
        else str(current.get(CONF_STRATEGY_PROFILE, DEFAULT_STRATEGY_PROFILE))
    )
    if profile in STRATEGY_PROFILE_SETTINGS and profile != previous:
        updated = dict(data)
        updated.update(STRATEGY_PROFILE_SETTINGS[profile])
        return updated
    return data


def _normalize_resolution(data: dict[str, Any]) -> dict[str, Any]:
    """Keep the configured Nord Pool resolution as a supported integer."""
    updated = dict(data)
    try:
        resolution = int(updated.get(CONF_RESOLUTION, DEFAULTS[CONF_RESOLUTION]))
    except (TypeError, ValueError):
        resolution = int(DEFAULTS[CONF_RESOLUTION])
    updated[CONF_RESOLUTION] = (
        resolution if resolution in RESOLUTIONS else int(DEFAULTS[CONF_RESOLUTION])
    )
    return updated


def _apply_module_count_settings(data: dict[str, Any]) -> dict[str, Any]:
    """Derive datasheet Force H3 capacities from the configured module count."""
    updated = dict(data)
    if CONF_BATTERY_MODULE_COUNT in updated:
        modules = round(float(updated[CONF_BATTERY_MODULE_COUNT]))
        modules = min(max(modules, FORCE_H3_MIN_MODULES), FORCE_H3_MAX_MODULES)
        updated[CONF_BATTERY_MODULE_COUNT] = float(modules)
        updated[CONF_BATTERY_CAPACITY_KWH] = FORCE_H3_SYSTEM_CAPACITY_KWH[modules]
        updated[CONF_BATTERY_USABLE_CAPACITY_KWH] = FORCE_H3_USABLE_CAPACITY_KWH[
            modules
        ]
    return updated


def _validate_user_input(data: dict[str, Any]) -> dict[str, str]:
    """Validate cross-field constraints."""
    errors: dict[str, str] = {}
    min_soc = float(data[CONF_MIN_SOC])
    reserve_soc = float(data[CONF_RESERVE_SOC])
    max_soc = float(data[CONF_MAX_SOC])
    continuous = float(data[CONF_CONTINUOUS_POWER_W])
    peak = float(data[CONF_PEAK_POWER_W])
    full_scale = float(data[CONF_INVERTER_FULL_SCALE_POWER_W])
    full_charge_target = float(data[CONF_PERIODIC_FULL_CHARGE_TARGET_SOC])
    full_charge_threshold = float(data[CONF_PERIODIC_FULL_CHARGE_THRESHOLD_SOC])
    module_count = round(float(data[CONF_BATTERY_MODULE_COUNT]))
    capacity_kwh = float(data[CONF_BATTERY_CAPACITY_KWH])
    usable_capacity_kwh = float(data[CONF_BATTERY_USABLE_CAPACITY_KWH])
    expected_capacity = FORCE_H3_SYSTEM_CAPACITY_KWH[module_count]
    expected_usable_capacity = FORCE_H3_USABLE_CAPACITY_KWH[module_count]
    theoretical_usable = round(expected_capacity * FORCE_H3_USABLE_DOD, 2)

    if (
        data.get(CONF_SOLAR_FORECAST_SOURCE) == "solcast"
        and not str(data.get(CONF_SOLCAST_API_KEY) or "").strip()
    ):
        errors[CONF_SOLCAST_API_KEY] = "solcast_api_key_required"

    if max(min_soc, reserve_soc) >= max_soc:
        errors[CONF_MAX_SOC] = "soc_range"
    if abs(capacity_kwh - expected_capacity) > 0.02:
        errors[CONF_BATTERY_CAPACITY_KWH] = "capacity_module_mismatch"
    if abs(usable_capacity_kwh - expected_usable_capacity) > 0.02:
        errors[CONF_BATTERY_USABLE_CAPACITY_KWH] = "usable_capacity_module_mismatch"
    elif (
        abs(usable_capacity_kwh - theoretical_usable) / theoretical_usable * 100
        > 5.0
    ):
        errors[CONF_BATTERY_USABLE_CAPACITY_KWH] = "usable_capacity_dod_mismatch"
    if full_charge_threshold > full_charge_target:
        errors[CONF_PERIODIC_FULL_CHARGE_THRESHOLD_SOC] = (
            "full_charge_threshold_above_target"
        )
    if peak < continuous:
        errors[CONF_PEAK_POWER_W] = "peak_below_continuous"
    if full_scale < peak:
        errors[CONF_INVERTER_FULL_SCALE_POWER_W] = "full_scale_below_peak"

    return errors
