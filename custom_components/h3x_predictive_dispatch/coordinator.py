"""Coordinator and optimizer for Pylontech H3X energy arbitrage."""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from aiohttp import ClientError
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

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
    DEFAULT_RESOLUTION,
    DEFAULTS,
    DOMAIN,
    FORCE_H3_MAX_MODULES,
    FORCE_H3_MIN_MODULES,
    FORCE_H3_MODULE_CAPACITY_KWH,
    FORCE_H3_SYSTEM_CAPACITY_KWH,
    FORCE_H3_USABLE_CAPACITY_KWH,
    FORCE_H3_USABLE_DOD,
    NORDPOOL_CONF_AREAS,
    NORDPOOL_CONF_CURRENCY,
    NORDPOOL_DOMAIN,
    PV_ORIENTATIONS,
    RESOLUTIONS,
    STRATEGY_PROFILE_SETTINGS,
)
from .forecast import (
    ForecastBand,
    HistoricalLoadForecaster,
    LoadForecast,
    PowerObservation,
)
from .history import RecorderHistoryLoader
from .optimizer import (
    OptimizerSettings,
    OptimizerSlot,
    PredictiveDispatchOptimizer,
    live_solar_charge_target_w,
)
from .solcast import (
    SolcastInterval,
    align_solcast_forecasts,
    parse_solcast_forecasts,
    restore_solcast_forecasts,
)
from .tariff import TariffSettings, retail_price

LOGGER = logging.getLogger(__name__)
STORAGE_VERSION = 1
LAST_FULL_CHARGE_KEY = "last_periodic_full_charge_at"
FULL_CHARGE_SCHEDULE_STARTED_KEY = "periodic_full_charge_schedule_started_at"
SOLCAST_CACHE_KEY = "solcast_forecast"
SOLCAST_FETCHED_AT_KEY = "solcast_fetched_at"
BATTERY_CAPACITY_ISSUE_ID = "battery_capacity_unconfirmed"
PV_ORIENTATION_PROFILE: dict[str, tuple[float, float]] = {
    "N": (0.20, 0.0),
    "NE": (0.45, -4.0),
    "E": (0.70, -3.0),
    "SE": (0.90, -1.5),
    "S": (1.00, 0.0),
    "SW": (0.90, 1.5),
    "W": (0.70, 3.0),
    "NW": (0.45, 4.0),
}


@dataclass(slots=True)
class PriceSlot:
    """One Nord Pool price interval."""

    start: datetime
    end: datetime
    price: float

    @property
    def duration_hours(self) -> float:
        """Return the full slot duration in hours."""
        return max((self.end - self.start).total_seconds() / 3600, 0.0)


@dataclass(slots=True)
class BatteryConfiguration:
    """Resolved Force H3 battery stack configuration."""

    module_count: int
    system_capacity_kwh: float
    usable_capacity_kwh: float
    source: str
    warning: str | None = None


@dataclass(slots=True)
class Decision:
    """Computed control decision."""

    action: str = "idle"
    reason: str = "waiting"
    current_price: float | None = None
    target_power_w: float = 0.0
    target_power_percent: float = 0.0
    soc: float | None = None
    load_power_w: float | None = None
    solar_power_w: float | None = None
    forecast_load_power_w: float | None = None
    forecast_solar_power_w: float | None = None
    grid_import_power_w: float | None = None
    grid_import_average_power_w: float | None = None
    grid_charge_headroom_w: float | None = None
    bms_temperature_c: float | None = None
    resolution_minutes: int | None = None
    slots_available: int = 0
    next_slot_start: str | None = None
    next_slot_end: str | None = None
    estimated_first_slot_value: float = 0.0
    estimated_plan_value: float = 0.0
    estimated_today_value: float = 0.0
    planned_charge_kwh: float = 0.0
    planned_discharge_kwh: float = 0.0
    planned_grid_charge_kwh: float = 0.0
    planned_solar_charge_kwh: float = 0.0
    planned_self_consumption_kwh: float = 0.0
    planned_grid_export_kwh: float = 0.0
    forecast_load_kwh: float = 0.0
    forecast_solar_kwh: float = 0.0
    applied: bool = False
    apply_error: str | None = None
    updated_at: str = field(default_factory=lambda: dt_util.utcnow().isoformat())
    attributes: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-safe dictionary for sensors."""
        data = asdict(self)
        data["target_power_w"] = round(self.target_power_w, 1)
        data["target_power_percent"] = round(self.target_power_percent, 1)
        data["estimated_first_slot_value"] = round(self.estimated_first_slot_value, 4)
        data["estimated_plan_value"] = round(self.estimated_plan_value, 4)
        data["estimated_today_value"] = round(self.estimated_today_value, 4)
        data["planned_charge_kwh"] = round(self.planned_charge_kwh, 3)
        data["planned_discharge_kwh"] = round(self.planned_discharge_kwh, 3)
        data["planned_grid_charge_kwh"] = round(self.planned_grid_charge_kwh, 3)
        data["planned_solar_charge_kwh"] = round(self.planned_solar_charge_kwh, 3)
        data["planned_self_consumption_kwh"] = round(
            self.planned_self_consumption_kwh, 3
        )
        data["planned_grid_export_kwh"] = round(self.planned_grid_export_kwh, 3)
        data["forecast_load_kwh"] = round(self.forecast_load_kwh, 3)
        data["forecast_solar_kwh"] = round(self.forecast_solar_kwh, 3)
        if self.load_power_w is not None:
            data["load_power_w"] = round(self.load_power_w, 1)
        if self.solar_power_w is not None:
            data["solar_power_w"] = round(self.solar_power_w, 1)
        if self.forecast_load_power_w is not None:
            data["forecast_load_power_w"] = round(self.forecast_load_power_w, 1)
        if self.forecast_solar_power_w is not None:
            data["forecast_solar_power_w"] = round(self.forecast_solar_power_w, 1)
        if self.grid_import_power_w is not None:
            data["grid_import_power_w"] = round(self.grid_import_power_w, 1)
        if self.grid_import_average_power_w is not None:
            data["grid_import_average_power_w"] = round(
                self.grid_import_average_power_w, 1
            )
        if self.grid_charge_headroom_w is not None:
            data["grid_charge_headroom_w"] = round(self.grid_charge_headroom_w, 1)
        return data


class H3XPredictiveDispatchCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch prices, optimize dispatch, and apply H3X controls."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.entry = entry
        update_minutes = float(self._option(CONF_UPDATE_INTERVAL_MINUTES))
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(minutes=max(update_minutes, 1.0)),
        )
        self._last_power_percent: float | None = None
        self._last_ems_mode: str | None = None
        self._last_applied_action: str | None = None
        self._last_action_changed_at: datetime | None = None
        self._last_target_power_w: float = 0.0
        self._store = Store(
            hass,
            STORAGE_VERSION,
            f"{DOMAIN}_{entry.entry_id}_state",
        )
        self._state_loaded = False
        self._last_full_charge_at: datetime | None = None
        self._full_charge_schedule_started_at: datetime | None = None
        self._last_price_fetch_errors: list[str] = []
        self._history_loader = RecorderHistoryLoader(hass)
        self._historical_observations = []
        self._history_loaded_at: datetime | None = None
        self._load_forecast_result: LoadForecast | None = None
        self._predictive_optimizer = PredictiveDispatchOptimizer()
        self._grid_import_average_power_w: float | None = None
        self._grid_import_trend_w_per_min: float | None = None
        self._grid_import_sample_count = 0
        self._solcast_forecast: list[SolcastInterval] = []
        self._solcast_fetched_at: datetime | None = None
        self._solcast_last_attempt_at: datetime | None = None
        self._solcast_error: str | None = None

    def _option(self, key: str) -> Any:
        """Return an option value with a default fallback."""
        if key in self.entry.options:
            return self.entry.options[key]
        return self.entry.data.get(key, DEFAULTS[key])

    async def async_options_updated(self) -> None:
        """Apply updated options without reloading entities."""
        update_minutes = float(self._option(CONF_UPDATE_INTERVAL_MINUTES))
        self.update_interval = timedelta(minutes=max(update_minutes, 1.0))
        await self.async_request_refresh()

    async def async_set_option(self, key: str, value: Any) -> None:
        """Persist one option and refresh the optimizer."""
        options = {**self.entry.options, key: value}
        self._normalize_mutable_options(options)
        if key != CONF_STRATEGY_PROFILE:
            options[CONF_STRATEGY_PROFILE] = "custom"
        self.hass.config_entries.async_update_entry(self.entry, options=options)
        await self.async_options_updated()

    async def async_apply_strategy_profile(self, profile: str) -> None:
        """Apply a strategy profile to optimizer options."""
        options = {**self.entry.options, CONF_STRATEGY_PROFILE: profile}
        options.update(STRATEGY_PROFILE_SETTINGS.get(profile, {}))
        self._normalize_mutable_options(options)
        self.hass.config_entries.async_update_entry(self.entry, options=options)
        await self.async_options_updated()

    def _normalize_mutable_options(self, options: dict[str, Any]) -> None:
        """Keep runtime control options inside valid cross-field ranges."""
        target_soc = float(
            options.get(
                CONF_PERIODIC_FULL_CHARGE_TARGET_SOC,
                self._option(CONF_PERIODIC_FULL_CHARGE_TARGET_SOC),
            )
        )
        threshold_soc = float(
            options.get(
                CONF_PERIODIC_FULL_CHARGE_THRESHOLD_SOC,
                self._option(CONF_PERIODIC_FULL_CHARGE_THRESHOLD_SOC),
            )
        )
        if threshold_soc > target_soc:
            options[CONF_PERIODIC_FULL_CHARGE_THRESHOLD_SOC] = target_soc
        if CONF_BATTERY_MODULE_COUNT in options:
            modules = self._clamp_module_count(options[CONF_BATTERY_MODULE_COUNT])
            options[CONF_BATTERY_MODULE_COUNT] = float(modules)
            options[CONF_BATTERY_CAPACITY_KWH] = self._system_capacity_for_modules(
                modules
            )
            options[CONF_BATTERY_USABLE_CAPACITY_KWH] = (
                self._usable_capacity_for_modules(modules)
            )
        for key in (CONF_MAX_CHARGE_C_RATE, CONF_MAX_DISCHARGE_C_RATE):
            if key in options:
                options[key] = min(max(float(options[key]), 0.05), 0.5)
        if CONF_DISCHARGE_SPREAD_PRICE_TOLERANCE in options:
            options[CONF_DISCHARGE_SPREAD_PRICE_TOLERANCE] = min(
                max(float(options[CONF_DISCHARGE_SPREAD_PRICE_TOLERANCE]), 0.0),
                50.0,
            )
        if CONF_DISCHARGE_SPREAD_MAX_HOURS in options:
            options[CONF_DISCHARGE_SPREAD_MAX_HOURS] = min(
                max(float(options[CONF_DISCHARGE_SPREAD_MAX_HOURS]), 0.25),
                12.0,
            )
        if CONF_PV_ORIENTATION in options:
            orientation = str(options[CONF_PV_ORIENTATION]).upper()
            options[CONF_PV_ORIENTATION] = (
                orientation if orientation in PV_ORIENTATIONS else "S"
            )
        if CONF_PV_PANEL_COUNT in options:
            options[CONF_PV_PANEL_COUNT] = min(
                max(float(options[CONF_PV_PANEL_COUNT]), 0.0),
                200.0,
            )
        if CONF_PV_PANEL_WP in options:
            options[CONF_PV_PANEL_WP] = min(
                max(float(options[CONF_PV_PANEL_WP]), 0.0),
                1500.0,
            )
        if CONF_PV_INVERTER_LIMIT_W in options:
            options[CONF_PV_INVERTER_LIMIT_W] = min(
                max(float(options[CONF_PV_INVERTER_LIMIT_W]), 0.0),
                50000.0,
            )

    async def _async_update_data(self) -> dict[str, Any]:
        """Update price data, compute the decision, and apply controls."""
        try:
            await self._async_load_state()
            current_soc = self._state_float(str(self._option(CONF_SOC_ENTITY)))
            if current_soc is not None:
                await self._async_record_full_charge_if_reached(current_soc)
            slots = await self._fetch_price_slots()
            await self._async_refresh_history()
            await self._async_refresh_grid_import_trend()
            await self._async_refresh_solcast_forecast()
            decision = self._compute_decision(slots)
        except Exception as err:  # pylint: disable=broad-except
            LOGGER.exception("Failed to compute arbitrage decision")
            decision = Decision(
                action="failsafe",
                reason=str(err),
                resolution_minutes=self._configured_resolution_minutes(),
            )

        self._finalize_decision_diagnostics(decision)
        self._update_battery_capacity_issue(decision)

        if bool(self._option(CONF_CONTROL_ENABLED)):
            await self._apply_decision(decision)
        else:
            decision.reason = f"{decision.reason}; control disabled"

        return decision.as_dict()

    async def async_shutdown(self) -> None:
        """Shut down coordinator resources."""
        return

    async def _async_refresh_history(self) -> None:
        """Refresh Recorder training data at most once per hour."""
        if str(self._option(CONF_LOAD_FORECAST_MODE)) != "historical":
            self._historical_observations = []
            return
        now = dt_util.utcnow()
        if (
            self._history_loaded_at is not None
            and now - self._history_loaded_at < timedelta(hours=1)
        ):
            return
        load_entity = str(self._option(CONF_SHELLY_TOTAL_POWER_ENTITY)).strip()
        if not load_entity:
            load_entity = str(self._option(CONF_LOAD_POWER_ENTITY)).strip()
        ev_entity = str(self._option(CONF_EV_POWER_ENTITY)).strip()
        self._historical_observations = (
            await self._history_loader.async_load_power_history(
                load_entity,
                days=int(float(self._option(CONF_LOAD_HISTORY_DAYS))),
                ev_entity_id=ev_entity or None,
            )
        )
        self._history_loaded_at = now

    async def _async_refresh_grid_import_trend(self) -> None:
        """Derive recent grid import average and slope from Recorder history."""
        entity_id = str(self._option(CONF_GRID_IMPORT_POWER_ENTITY)).strip()
        samples = await self._history_loader.async_load_recent_power_samples(
            entity_id,
            minutes=15,
        )
        current = self._power_state_w(entity_id)
        now = dt_util.now()
        if current is not None:
            samples.append(
                PowerObservation(timestamp=now, load_w=max(current, 0.0))
            )
        if not samples:
            self._grid_import_average_power_w = None
            self._grid_import_trend_w_per_min = None
            self._grid_import_sample_count = 0
            return

        deduplicated: dict[datetime, float] = {
            row.timestamp: row.load_w for row in samples
        }
        ordered = sorted(deduplicated.items())
        values = [value for _timestamp, value in ordered]
        self._grid_import_average_power_w = sum(values) / len(values)
        self._grid_import_sample_count = len(values)
        if len(ordered) < 2:
            self._grid_import_trend_w_per_min = 0.0
            return

        origin = ordered[0][0]
        x_values = [
            (timestamp - origin).total_seconds() / 60 for timestamp, _value in ordered
        ]
        x_mean = sum(x_values) / len(x_values)
        y_mean = sum(values) / len(values)
        denominator = sum((value - x_mean) ** 2 for value in x_values)
        self._grid_import_trend_w_per_min = (
            sum(
                (x_value - x_mean) * (y_value - y_mean)
                for x_value, y_value in zip(x_values, values, strict=True)
            )
            / denominator
            if denominator > 0
            else 0.0
        )

    async def _async_refresh_solcast_forecast(self) -> None:
        """Refresh the cached Solcast forecast without exceeding hobbyist quotas."""
        source = str(self._option(CONF_SOLAR_FORECAST_SOURCE))
        api_key = str(self._option(CONF_SOLCAST_API_KEY)).strip()
        if source == "panel_model" or not api_key:
            self._solcast_error = None if source == "panel_model" else "not_configured"
            return

        now = dt_util.utcnow()
        refresh_hours = float(self._option(CONF_SOLCAST_UPDATE_INTERVAL_HOURS))
        cache_valid = any(row.end > now for row in self._solcast_forecast)
        if (
            cache_valid
            and self._solcast_fetched_at is not None
            and now - self._solcast_fetched_at < timedelta(hours=refresh_hours)
        ):
            return
        if (
            self._solcast_last_attempt_at is not None
            and now - self._solcast_last_attempt_at < timedelta(hours=1)
        ):
            return
        self._solcast_last_attempt_at = now

        resource_id = str(self._option(CONF_SOLCAST_RESOURCE_ID)).strip()
        headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
        if resource_id:
            url = f"https://api.solcast.com.au/rooftop_sites/{resource_id}/forecasts"
            params: dict[str, Any] = {"format": "json"}
        else:
            url = "https://api.solcast.com.au/data/forecast/rooftop_pv_power"
            panel_kw = (
                float(self._option(CONF_PV_PANEL_COUNT))
                * float(self._option(CONF_PV_PANEL_WP))
                / 1000
            )
            inverter_kw = float(self._option(CONF_PV_INVERTER_LIMIT_W)) / 1000
            params = {
                "latitude": float(getattr(self.hass.config, "latitude", 0.0)),
                "longitude": float(getattr(self.hass.config, "longitude", 0.0)),
                "hours": max(int(float(self._option(CONF_HORIZON_HOURS))), 24),
                "period": f"PT{self._configured_resolution_minutes()}M",
                "output_parameters": (
                    "pv_power_rooftop,pv_power_rooftop10,pv_power_rooftop90"
                ),
                "capacity": max(panel_kw, inverter_kw, 0.1),
                "azimuth": self._solcast_azimuth(),
                "format": "json",
            }

        try:
            session = async_get_clientsession(self.hass)
            async with asyncio.timeout(30):
                async with session.get(url, params=params, headers=headers) as response:
                    response.raise_for_status()
                    payload = await response.json(content_type=None)
            forecasts = parse_solcast_forecasts(payload)
            if not forecasts:
                raise ValueError("Solcast returned no usable forecast intervals")
        except (ClientError, TimeoutError, TypeError, ValueError) as err:
            self._solcast_error = f"{type(err).__name__}: {err}"
            LOGGER.warning("Unable to refresh Solcast forecast: %s", self._solcast_error)
            return

        self._solcast_forecast = forecasts
        self._solcast_fetched_at = now
        self._solcast_error = None
        await self._async_save_state()

    def _solcast_azimuth(self) -> int:
        """Map compass orientation to Solcast's north-based azimuth."""
        return {
            "N": 0,
            "NE": -45,
            "E": -90,
            "SE": -135,
            "S": 180,
            "SW": 135,
            "W": 90,
            "NW": 45,
        }.get(str(self._option(CONF_PV_ORIENTATION)).upper(), 180)

    def _solcast_status(self) -> str:
        """Return a stable, user-facing Solcast acquisition state."""
        source = str(self._option(CONF_SOLAR_FORECAST_SOURCE))
        if source == "panel_model":
            return "panel_model_selected"
        if not str(self._option(CONF_SOLCAST_API_KEY)).strip():
            return "not_configured"
        if self._solcast_error and self._solcast_forecast:
            return "cached_after_error"
        if self._solcast_error:
            return "error"
        if self._solcast_forecast:
            return "ready"
        return "waiting_for_first_forecast"

    async def _async_load_state(self) -> None:
        """Load persisted optimizer state."""
        if self._state_loaded:
            return
        stored = await self._store.async_load()
        timestamp = (stored or {}).get(LAST_FULL_CHARGE_KEY)
        if timestamp:
            parsed = dt_util.parse_datetime(str(timestamp))
            if parsed is not None:
                self._last_full_charge_at = dt_util.as_utc(parsed)
        schedule_started = (stored or {}).get(FULL_CHARGE_SCHEDULE_STARTED_KEY)
        if schedule_started:
            parsed = dt_util.parse_datetime(str(schedule_started))
            if parsed is not None:
                self._full_charge_schedule_started_at = dt_util.as_utc(parsed)
        if self._full_charge_schedule_started_at is None:
            self._full_charge_schedule_started_at = dt_util.utcnow()

        fetched_at = (stored or {}).get(SOLCAST_FETCHED_AT_KEY)
        if fetched_at:
            parsed = dt_util.parse_datetime(str(fetched_at))
            if parsed is not None:
                self._solcast_fetched_at = dt_util.as_utc(parsed)
        self._solcast_forecast = restore_solcast_forecasts(
            (stored or {}).get(SOLCAST_CACHE_KEY)
        )
        self._state_loaded = True
        await self._async_save_state()

    async def _async_save_state(self) -> None:
        """Persist periodic-charge scheduling and the Solcast cache together."""
        await self._store.async_save(
            {
                LAST_FULL_CHARGE_KEY: (
                    self._last_full_charge_at.isoformat()
                    if self._last_full_charge_at is not None
                    else None
                ),
                FULL_CHARGE_SCHEDULE_STARTED_KEY: (
                    self._full_charge_schedule_started_at.isoformat()
                    if self._full_charge_schedule_started_at is not None
                    else None
                ),
                SOLCAST_FETCHED_AT_KEY: (
                    self._solcast_fetched_at.isoformat()
                    if self._solcast_fetched_at is not None
                    else None
                ),
                SOLCAST_CACHE_KEY: [row.as_dict() for row in self._solcast_forecast],
            }
        )

    async def _async_record_full_charge_if_reached(self, soc: float) -> None:
        """Persist the timestamp when the pack reaches the full-charge threshold."""
        if not bool(self._option(CONF_PERIODIC_FULL_CHARGE_ENABLED)):
            return
        threshold = float(self._option(CONF_PERIODIC_FULL_CHARGE_THRESHOLD_SOC))
        if soc < threshold:
            return

        now = dt_util.utcnow()
        if (
            self._last_full_charge_at is not None
            and now - self._last_full_charge_at < timedelta(hours=12)
        ):
            return

        self._last_full_charge_at = now
        await self._async_save_state()

    async def _fetch_price_slots(self) -> list[PriceSlot]:
        """Fetch today and tomorrow price slots from Home Assistant Nord Pool."""
        entry_id = self._resolve_nordpool_entry_id()
        area = self._resolve_area()
        currency = self._resolve_currency()
        resolution = self._configured_resolution_minutes()
        self._last_price_fetch_errors = []

        today = dt_util.now().date()
        responses: list[Any] = []
        for day in (today, today + timedelta(days=1)):
            response = await self._call_nordpool(
                entry_id,
                area,
                currency,
                resolution,
                day,
                "get_price_indices_for_date",
            )
            rows = self._price_rows_from_response(response, area)
            if not rows:
                response = await self._call_nordpool(
                    entry_id,
                    area,
                    currency,
                    resolution,
                    day,
                    "get_prices_for_date",
                )
                rows = self._price_rows_from_response(response, area)
            responses.extend(rows)

        slots: dict[tuple[str, str], PriceSlot] = {}
        now = dt_util.utcnow()
        horizon_end = now + timedelta(hours=float(self._option(CONF_HORIZON_HOURS)))

        for row in responses:
            if isinstance(row, dict):
                start_raw = row.get("start")
                end_raw = row.get("end")
                price_raw = row.get("price")
            else:
                start_raw = getattr(row, "start", None)
                end_raw = getattr(row, "end", None)
                price_raw = getattr(row, "price", None)
            if start_raw is None or end_raw is None or price_raw is None:
                continue

            start = dt_util.parse_datetime(str(start_raw))
            end = dt_util.parse_datetime(str(end_raw))
            if start is None or end is None:
                continue
            start = dt_util.as_utc(start)
            end = dt_util.as_utc(end)
            if end <= now or start >= horizon_end:
                continue
            key = (start.isoformat(), end.isoformat())
            slots[key] = PriceSlot(start=start, end=end, price=float(price_raw) / 1000)

        return sorted(slots.values(), key=lambda slot: slot.start)

    async def _call_nordpool(
        self,
        entry_id: str,
        area: str,
        currency: str,
        resolution: int,
        day: date,
        service_name: str,
    ) -> dict[str, Any]:
        """Call the Nord Pool service and return its response."""
        payload: dict[str, Any] = {
            "config_entry": entry_id,
            "date": day.isoformat(),
            "areas": area,
            "currency": currency,
        }
        if service_name == "get_price_indices_for_date":
            payload["resolution"] = resolution

        try:
            response = await self.hass.services.async_call(
                NORDPOOL_DOMAIN,
                service_name,
                payload,
                blocking=True,
                return_response=True,
            )
        except HomeAssistantError as err:
            message = f"{service_name} failed for {day.isoformat()}: {err}"
            self._last_price_fetch_errors.append(message)
            LOGGER.debug("Nord Pool price fetch failed: %s", message)
            return {area: []}

        if not isinstance(response, dict):
            return {area: []}
        return response

    def _price_rows_from_response(
        self,
        response: dict[str, Any],
        area: str,
    ) -> list[Any]:
        """Extract a market-area price row list from Nord Pool action output."""
        if not isinstance(response, dict):
            return []
        area_upper = area.upper()
        for key, value in response.items():
            if str(key).upper() == area_upper and isinstance(value, list):
                return value
        for nested_key in ("data", "prices", "values"):
            nested = response.get(nested_key)
            if isinstance(nested, dict):
                rows = self._price_rows_from_response(nested, area)
                if rows:
                    return rows
            if isinstance(nested, list):
                return nested
        list_values = [value for value in response.values() if isinstance(value, list)]
        if len(list_values) == 1:
            return list_values[0]
        return []

    def _resolve_nordpool_entry_id(self) -> str:
        """Resolve the configured or first available Nord Pool config entry."""
        configured = str(self._option(CONF_NORDPOOL_CONFIG_ENTRY)).strip()
        entries = self.hass.config_entries.async_entries(NORDPOOL_DOMAIN)
        if configured and configured.lower() != "auto":
            if any(entry.entry_id == configured for entry in entries):
                return configured
            LOGGER.warning(
                "Configured Nord Pool config entry %s no longer exists; using auto",
                configured,
            )
        if entries:
            return entries[0].entry_id
        raise RuntimeError("Nord Pool integration is not configured")

    def _resolve_area(self) -> str:
        """Resolve the configured Nord Pool area."""
        configured = str(self._option(CONF_AREA)).strip().upper()
        if configured and configured != "AUTO":
            return configured
        entries = self.hass.config_entries.async_entries(NORDPOOL_DOMAIN)
        for entry in entries:
            areas = entry.data.get(NORDPOOL_CONF_AREAS)
            if isinstance(areas, list) and areas:
                return str(areas[0]).upper()
        raise RuntimeError("Nord Pool area is not configured")

    def _resolve_currency(self) -> str:
        """Resolve the configured Nord Pool currency."""
        configured = str(self._option(CONF_CURRENCY)).strip().upper()
        if configured and configured != "AUTO":
            return configured
        entries = self.hass.config_entries.async_entries(NORDPOOL_DOMAIN)
        for entry in entries:
            currency = entry.data.get(NORDPOOL_CONF_CURRENCY)
            if currency:
                return str(currency).upper()
        return "EUR"

    def _compute_decision(self, slots: list[PriceSlot]) -> Decision:
        """Compute the current best charge/discharge action."""
        now = dt_util.utcnow()
        future_slots = [slot for slot in slots if slot.end > now]
        if not future_slots:
            return Decision(action="failsafe", reason="no current or future price slots")

        soc = self._state_float(str(self._option(CONF_SOC_ENTITY)))
        if soc is None:
            return Decision(action="failsafe", reason="battery SOC entity unavailable")

        battery_config = self._battery_configuration()
        usable_capacity_kwh = battery_config.usable_capacity_kwh
        capacity_kwh = usable_capacity_kwh
        min_soc = max(float(self._option(CONF_MIN_SOC)), 0.0)
        reserve_soc = max(float(self._option(CONF_RESERVE_SOC)), min_soc)
        normal_max_soc = min(
            max(float(self._option(CONF_MAX_SOC)), reserve_soc + 1.0), 100.0
        )
        periodic_full_charge = self._periodic_full_charge_state(soc)

        bms_temp = self._state_float(str(self._option(CONF_BMS_TEMP_ENTITY)))
        charge_allowed, discharge_allowed, temp_reason = self._temperature_permissions(
            bms_temp
        )

        force_full_charge = (
            periodic_full_charge["periodic_full_charge_due"] and charge_allowed
        )
        max_soc = normal_max_soc
        if force_full_charge:
            max_soc = max(
                max_soc,
                periodic_full_charge["periodic_full_charge_target_soc"],
            )

        floor_soc = min(reserve_soc, max_soc - 1.0)
        min_energy = capacity_kwh * floor_soc / 100
        max_energy = capacity_kwh * max_soc / 100
        current_energy = min(max(capacity_kwh * soc / 100, min_energy), max_energy)
        terminal_energy = (
            max_energy
            if force_full_charge
            else self._terminal_energy(current_energy, min_energy, max_energy)
        )

        interval_minutes = self._infer_resolution_minutes(future_slots)
        optimization_slots = list(future_slots)
        if optimization_slots[0].start < now:
            current = optimization_slots[0]
            optimization_slots[0] = PriceSlot(
                start=now,
                end=current.end,
                price=current.price,
            )
        load_power_w, load_source = self._home_load_power_w()
        solar_power_w = self._positive_power_state_w(
            str(self._option(CONF_SOLAR_POWER_ENTITY)).strip()
        )
        load_forecast = self._forecast_load(optimization_slots, load_power_w)
        self._load_forecast_result = load_forecast
        load_forecast_w = [band.p50_w for band in load_forecast.bands]
        solar_forecast, solar_forecast_source, solar_forecast_scale = (
            self._solar_forecast_for_slots(optimization_slots, solar_power_w)
        )
        solar_forecast_w = [band.p50_w for band in solar_forecast]
        decision = self._run_predictive_optimizer(
            future_slots=optimization_slots,
            current_energy=current_energy,
            min_energy=min_energy,
            max_energy=max_energy,
            terminal_energy=terminal_energy,
            charge_allowed=charge_allowed,
            discharge_allowed=discharge_allowed,
            usable_capacity_kwh=usable_capacity_kwh,
            periodic_full_charge_due=force_full_charge,
            load_forecast=load_forecast,
            solar_forecast=solar_forecast,
            current_load_power_w=load_power_w,
            current_solar_power_w=solar_power_w,
        )

        current_slot = future_slots[0]
        decision.soc = soc
        decision.current_price = retail_price(
            current_slot.price, self._tariff_settings()
        ).buy
        decision.bms_temperature_c = bms_temp
        decision.resolution_minutes = interval_minutes
        decision.slots_available = len(future_slots)
        decision.next_slot_start = current_slot.start.isoformat()
        decision.next_slot_end = current_slot.end.isoformat()
        decision.load_power_w = load_power_w
        decision.solar_power_w = solar_power_w
        decision.forecast_load_power_w = load_forecast_w[0] if load_forecast_w else None
        decision.forecast_solar_power_w = (
            solar_forecast_w[0] if solar_forecast_w else None
        )
        decision.grid_import_power_w = self._power_state_w(
            str(self._option(CONF_GRID_IMPORT_POWER_ENTITY))
        )
        decision.grid_import_average_power_w = self._grid_import_average_power_w
        decision.updated_at = now.isoformat()
        decision.attributes.update(
            {
                "area": self._resolve_area(),
                "currency": self._resolve_currency(),
                "min_soc": floor_soc,
                "normal_max_soc": normal_max_soc,
                "max_soc": max_soc,
                **self._battery_capacity_attributes(battery_config),
                "temperature_guard": temp_reason,
                "control_enabled": bool(self._option(CONF_CONTROL_ENABLED)),
                "strategy_profile": str(self._option(CONF_STRATEGY_PROFILE)),
                "terminal_soc_mode": str(self._option(CONF_TERMINAL_SOC_MODE)),
                "grid_import_limit_w": float(self._option(CONF_GRID_IMPORT_LIMIT_W)),
                "grid_export_limit_w": float(self._option(CONF_GRID_EXPORT_LIMIT_W)),
                "grid_import_power_entity": str(
                    self._option(CONF_GRID_IMPORT_POWER_ENTITY)
                ),
                "grid_import_average_source": "internal_15_minute_recorder_trend",
                "grid_import_trend_w_per_min": (
                    round(self._grid_import_trend_w_per_min, 1)
                    if self._grid_import_trend_w_per_min is not None
                    else None
                ),
                "grid_import_trend_samples": self._grid_import_sample_count,
                "load_power_entity": str(self._option(CONF_LOAD_POWER_ENTITY)),
                "home_load_power_source": load_source,
                "shelly_total_power_entity": str(
                    self._option(CONF_SHELLY_TOTAL_POWER_ENTITY)
                ),
                "shelly_phase_a_power_entity": str(
                    self._option(CONF_SHELLY_PHASE_A_POWER_ENTITY)
                ),
                "shelly_phase_b_power_entity": str(
                    self._option(CONF_SHELLY_PHASE_B_POWER_ENTITY)
                ),
                "shelly_phase_c_power_entity": str(
                    self._option(CONF_SHELLY_PHASE_C_POWER_ENTITY)
                ),
                "solar_power_entity": str(self._option(CONF_SOLAR_POWER_ENTITY)),
                "pv_orientation": str(self._option(CONF_PV_ORIENTATION)).upper(),
                "pv_panel_count": float(self._option(CONF_PV_PANEL_COUNT)),
                "pv_panel_wp": float(self._option(CONF_PV_PANEL_WP)),
                "pv_inverter_limit_w": float(self._option(CONF_PV_INVERTER_LIMIT_W)),
                "pv_peak_power_w": round(
                    float(self._option(CONF_PV_PANEL_COUNT))
                    * float(self._option(CONF_PV_PANEL_WP)),
                    1,
                ),
                "solar_forecast_source": solar_forecast_source,
                "solar_forecast_scale": round(solar_forecast_scale, 3),
                "solcast_fetched_at": (
                    self._solcast_fetched_at.isoformat()
                    if self._solcast_fetched_at is not None
                    else None
                ),
                "solcast_interval_count": len(self._solcast_forecast),
                "solcast_status": self._solcast_status(),
                "solcast_error": self._solcast_error,
                "load_forecast_source": load_forecast.metrics.source,
                "load_forecast_observations": load_forecast.metrics.observations,
                "load_forecast_days": load_forecast.metrics.days_covered,
                "load_forecast_mae_w": (
                    round(load_forecast.metrics.mae_w, 1)
                    if load_forecast.metrics.mae_w is not None
                    else None
                ),
                "load_forecast_bias_w": (
                    round(load_forecast.metrics.bias_w, 1)
                    if load_forecast.metrics.bias_w is not None
                    else None
                ),
                "ev_forecast_mode": str(self._option(CONF_EV_FORECAST_MODE)),
                "ev_sessions_detected": load_forecast.metrics.ev_sessions,
                "load_forecast": self._serialize_forecast_bands(
                    future_slots, load_forecast.bands
                ),
                "solar_forecast": self._serialize_forecast_bands(
                    optimization_slots, solar_forecast
                ),
                **periodic_full_charge,
                "discharge_power_mode": str(self._option(CONF_DISCHARGE_POWER_MODE)),
                "discharge_spread_price_tolerance_pct": float(
                    self._option(CONF_DISCHARGE_SPREAD_PRICE_TOLERANCE)
                ),
                "discharge_spread_max_hours": float(
                    self._option(CONF_DISCHARGE_SPREAD_MAX_HOURS)
                ),
                "nordpool_resolution_minutes": (
                    self._configured_resolution_minutes()
                ),
                "price_fetch_errors": list(self._last_price_fetch_errors),
                **self._price_trend_attributes(future_slots),
                "price_slots": [
                    self._serialize_price_slot(slot) for slot in future_slots
                ],
                "today_slots": [
                    self._serialize_price_slot(slot)
                    for slot in future_slots
                    if dt_util.as_local(slot.start).date() == dt_util.now().date()
                ],
                "tomorrow_slots": [
                    self._serialize_price_slot(slot)
                    for slot in future_slots
                    if dt_util.as_local(slot.start).date()
                    == dt_util.now().date() + timedelta(days=1)
                ],
            }
        )

        if decision.action == "charge" and not charge_allowed:
            return self._idle_from(decision, temp_reason or "charging not allowed")
        if decision.action == "discharge" and not discharge_allowed:
            return self._idle_from(decision, temp_reason or "discharging not allowed")

        if decision.action in {"charge", "discharge"}:
            if decision.action == "charge":
                decision.grid_charge_headroom_w = self._grid_charge_headroom_w(
                    load_power_w=decision.load_power_w,
                    grid_import_power_w=decision.grid_import_power_w,
                    grid_import_average_power_w=decision.grid_import_average_power_w,
                )
            limited_power = self._apply_grid_limit(
                decision.action,
                decision.target_power_w,
                load_power_w=decision.load_power_w,
                grid_import_power_w=decision.grid_import_power_w,
                grid_import_average_power_w=decision.grid_import_average_power_w,
            )
            if limited_power < decision.target_power_w:
                decision.attributes["target_power_before_grid_limit_w"] = round(
                    decision.target_power_w, 1
                )
                decision.reason = (
                    f"{decision.reason}; grid limit reduced target power"
                )
            if limited_power < float(self._option(CONF_MIN_ACTIVE_POWER_W)):
                return self._idle_from(decision, "target below minimum active power")
            decision.target_power_w = limited_power
            decision.target_power_percent = self._power_to_percent(
                decision.action, limited_power
            )

        return decision

    def _finalize_decision_diagnostics(self, decision: Decision) -> None:
        """Attach always-on diagnostics used by UI sensors and dashboards."""
        configured_resolution = self._configured_resolution_minutes()
        if decision.resolution_minutes is None:
            decision.resolution_minutes = configured_resolution
        decision.attributes.setdefault(
            "nordpool_resolution_minutes", configured_resolution
        )
        self._ensure_capacity_attributes(decision)
        self._set_target_c_rate_attribute(decision)
        self._attach_plan_summaries(decision)

    def _configured_resolution_minutes(self) -> int:
        """Return a valid persisted Nord Pool resolution."""
        try:
            resolution = int(self._option(CONF_RESOLUTION))
        except (TypeError, ValueError):
            return DEFAULT_RESOLUTION
        return resolution if resolution in RESOLUTIONS else DEFAULT_RESOLUTION

    def _ensure_capacity_attributes(self, decision: Decision) -> None:
        """Keep capacity diagnostics available even when price fetching fails."""
        if "battery_usable_capacity_kwh" in decision.attributes:
            if self._last_price_fetch_errors:
                decision.attributes["price_fetch_errors"] = list(
                    self._last_price_fetch_errors
                )
            return
        try:
            battery_config = self._battery_configuration()
        except Exception:  # pylint: disable=broad-except
            LOGGER.exception("Failed to attach battery capacity diagnostics")
            return
        decision.attributes.update(self._battery_capacity_attributes(battery_config))
        decision.attributes["price_fetch_errors"] = list(self._last_price_fetch_errors)

    def _set_target_c_rate_attribute(self, decision: Decision) -> None:
        """Derive target C-rate from final target power and usable capacity."""
        usable_capacity = decision.attributes.get("battery_usable_capacity_kwh")
        try:
            usable_capacity_kwh = float(usable_capacity)
        except (TypeError, ValueError):
            decision.attributes["target_c_rate"] = None
            return

        if usable_capacity_kwh <= 0:
            decision.attributes["target_c_rate"] = None
            return
        decision.attributes["target_c_rate"] = round(
            abs(decision.target_power_w) / (usable_capacity_kwh * 1000),
            3,
        )

    def _attach_plan_summaries(self, decision: Decision) -> None:
        """Expose concise plan summaries without requiring large attribute parsing."""
        plan = decision.attributes.get("dispatch_plan")
        if not isinstance(plan, list):
            plan = []

        charge_slots = [
            self._compact_plan_slot(row)
            for row in plan
            if self._plan_slot_action(row) == "charge"
        ]
        discharge_slots = [
            self._compact_plan_slot(row)
            for row in plan
            if self._plan_slot_action(row) == "discharge"
        ]
        charge_slots = [slot for slot in charge_slots if slot is not None]
        discharge_slots = [slot for slot in discharge_slots if slot is not None]
        now = dt_util.utcnow()
        charge_slots = self._mark_action_slot_timing(charge_slots, now)
        discharge_slots = self._mark_action_slot_timing(discharge_slots, now)

        decision.attributes["planned_charge_slots"] = charge_slots[:12]
        decision.attributes["planned_discharge_slots"] = discharge_slots[:12]
        decision.attributes["next_charge_slot"] = (
            charge_slots[0] if charge_slots else {"state": "none"}
        )
        decision.attributes["next_discharge_slot"] = (
            discharge_slots[0] if discharge_slots else {"state": "none"}
        )

        due = decision.attributes.get("periodic_full_charge_due")
        enabled_attr = decision.attributes.get("periodic_full_charge_enabled")
        enabled = (
            bool(enabled_attr)
            if enabled_attr is not None
            else bool(self._option(CONF_PERIODIC_FULL_CHARGE_ENABLED))
        )
        if due is True and charge_slots:
            full_charge_slot = dict(charge_slots[0])
            full_charge_slot["state"] = "planned"
        elif due is True:
            full_charge_slot = {
                "state": "waiting_for_charge_slot",
                "target_soc": decision.attributes.get(
                    "periodic_full_charge_target_soc",
                    self._option(CONF_PERIODIC_FULL_CHARGE_TARGET_SOC),
                ),
            }
        elif due is False:
            full_charge_slot = {
                "state": "not_due" if enabled else "disabled",
                "next_due_at": decision.attributes.get(
                    "periodic_full_charge_next_due_at"
                ),
                "target_soc": decision.attributes.get(
                    "periodic_full_charge_target_soc",
                    self._option(CONF_PERIODIC_FULL_CHARGE_TARGET_SOC),
                ),
            }
        else:
            full_charge_slot = {
                "state": "waiting_for_soc",
                "target_soc": self._option(CONF_PERIODIC_FULL_CHARGE_TARGET_SOC),
            }
        decision.attributes["periodic_full_charge_slot"] = full_charge_slot

    @staticmethod
    def _mark_action_slot_timing(
        slots: list[dict[str, Any]],
        now: datetime,
    ) -> list[dict[str, Any]]:
        """Remove expired rows and distinguish active from future actions."""
        result: list[dict[str, Any]] = []
        for slot in slots:
            start = dt_util.parse_datetime(str(slot.get("start") or ""))
            end = dt_util.parse_datetime(str(slot.get("end") or ""))
            if start is None or end is None:
                continue
            start = dt_util.as_utc(start)
            end = dt_util.as_utc(end)
            if end <= now:
                continue
            row = dict(slot)
            row["state"] = "active" if start <= now < end else "planned"
            result.append(row)
        return result

    @staticmethod
    def _plan_slot_action(row: Any) -> str | None:
        """Return the action for a serialized plan slot."""
        if not isinstance(row, dict):
            return None
        try:
            energy = float(row.get("energy_kwh") or 0.0)
        except (TypeError, ValueError):
            energy = 0.0
        action = str(row.get("action") or "")
        if action in {"charge", "discharge"} and energy > 0:
            return action
        return None

    @staticmethod
    def _compact_plan_slot(row: Any) -> dict[str, Any] | None:
        """Return a small, UI-friendly plan-slot dictionary."""
        if not isinstance(row, dict):
            return None
        planned_target_w = row.get("target_power_w")
        live_target_w = row.get("live_target_power_w")
        return {
            "state": "planned",
            "start": row.get("start"),
            "end": row.get("end"),
            "action": row.get("action"),
            "intent": row.get("intent"),
            "execution": row.get("execution"),
            "energy_kwh": row.get("energy_kwh"),
            "target_power_w": (
                live_target_w if live_target_w is not None else planned_target_w
            ),
            "planned_target_power_w": planned_target_w,
            "live_surplus_w": row.get("live_surplus_w"),
            "value": row.get("value"),
            "price": row.get("price"),
            "grid_charge_kwh": row.get("grid_charge_kwh"),
            "solar_charge_kwh": row.get("solar_charge_kwh"),
            "self_consumption_kwh": row.get("self_consumption_kwh"),
            "battery_export_kwh": row.get("battery_export_kwh"),
            "net_grid_with_battery_w": row.get("net_grid_with_battery_w"),
        }

    def _battery_capacity_attributes(
        self,
        battery_config: BatteryConfiguration,
    ) -> dict[str, Any]:
        """Return capacity diagnostics derived from the resolved battery stack."""
        usable_capacity_kwh = battery_config.usable_capacity_kwh
        return {
            "capacity_kwh": usable_capacity_kwh,
            "capacity_basis": "usable",
            "battery_system_capacity_kwh": battery_config.system_capacity_kwh,
            "battery_usable_capacity_kwh": usable_capacity_kwh,
            "battery_usable_depth_of_discharge": FORCE_H3_USABLE_DOD,
            "battery_module_count": battery_config.module_count,
            "battery_module_capacity_kwh": FORCE_H3_MODULE_CAPACITY_KWH,
            "battery_capacity_source": battery_config.source,
            "battery_capacity_warning": battery_config.warning,
            "max_charge_c_rate": float(self._option(CONF_MAX_CHARGE_C_RATE)),
            "max_discharge_c_rate": float(self._option(CONF_MAX_DISCHARGE_C_RATE)),
            "max_charge_c_rate_power_w": round(
                usable_capacity_kwh * float(self._option(CONF_MAX_CHARGE_C_RATE)) * 1000,
                1,
            ),
            "max_discharge_c_rate_power_w": round(
                usable_capacity_kwh
                * float(self._option(CONF_MAX_DISCHARGE_C_RATE))
                * 1000,
                1,
            ),
        }

    def _battery_configuration(self) -> BatteryConfiguration:
        """Resolve module count and datasheet capacity for the Force H3 stack."""
        module_entity = str(self._option(CONF_BATTERY_MODULE_COUNT_ENTITY)).strip()
        module_count_from_entity = self._state_float(module_entity)
        if module_count_from_entity is not None:
            modules = round(module_count_from_entity)
            if self._valid_module_count(modules):
                return self._configuration_for_modules(
                    modules,
                    source=f"entity:{module_entity}",
                )

        configured_modules = self._configured_value(CONF_BATTERY_MODULE_COUNT)
        if configured_modules is not None:
            modules = self._clamp_module_count(configured_modules)
            warning = None
            if (
                module_count_from_entity is not None
                and not self._valid_module_count(round(module_count_from_entity))
            ):
                warning = (
                    f"module count entity {module_entity} is unavailable or outside "
                    f"{FORCE_H3_MIN_MODULES}-{FORCE_H3_MAX_MODULES}; using configured value"
                )
            return self._configuration_for_modules(
                modules,
                source="configured_module_count",
                warning=warning,
            )

        legacy_capacity = self._configured_value(CONF_BATTERY_CAPACITY_KWH)
        if legacy_capacity is not None:
            inferred_modules = self._modules_from_capacity(legacy_capacity)
            if inferred_modules is not None:
                return self._configuration_for_modules(
                    inferred_modules,
                    source="legacy_capacity",
                )

        modules = int(DEFAULTS[CONF_BATTERY_MODULE_COUNT])
        return self._configuration_for_modules(
            modules,
            source="default_module_count",
            warning=(
                "using the default Force H3 module count; confirm the real number "
                "of installed modules before enabling automatic control"
            ),
        )

    def _configuration_for_modules(
        self,
        module_count: int,
        *,
        source: str,
        warning: str | None = None,
    ) -> BatteryConfiguration:
        """Build a battery configuration and validate capacity entities."""
        system_capacity = self._system_capacity_for_modules(module_count)
        usable_capacity = self._usable_capacity_for_modules(module_count)
        warnings = [warning] if warning else []
        sources = [source]

        system_entity = str(self._option(CONF_BATTERY_SYSTEM_CAPACITY_ENTITY)).strip()
        usable_entity = str(self._option(CONF_BATTERY_USABLE_CAPACITY_ENTITY)).strip()
        system_from_entity = self._energy_state_kwh(system_entity)
        usable_from_entity = self._energy_state_kwh(usable_entity)

        if system_from_entity is not None:
            if self._capacity_deviation_pct(system_from_entity, system_capacity) <= 5.0:
                system_capacity = round(system_from_entity, 2)
                sources.append(f"system_entity:{system_entity}")
            else:
                warnings.append(
                    f"system capacity entity {system_entity} reads "
                    f"{system_from_entity:.2f} kWh, expected about "
                    f"{system_capacity:.2f} kWh for {module_count} modules"
                )

        if usable_from_entity is not None:
            expected_usable = self._usable_capacity_for_modules(module_count)
            if self._capacity_deviation_pct(usable_from_entity, expected_usable) <= 5.0:
                usable_capacity = round(usable_from_entity, 2)
                sources.append(f"usable_entity:{usable_entity}")
            else:
                warnings.append(
                    f"usable capacity entity {usable_entity} reads "
                    f"{usable_from_entity:.2f} kWh, expected about "
                    f"{expected_usable:.2f} kWh for {module_count} modules"
                )

        theoretical_usable = system_capacity * FORCE_H3_USABLE_DOD
        if self._capacity_deviation_pct(usable_capacity, theoretical_usable) > 5.0:
            warnings.append(
                f"usable capacity {usable_capacity:.2f} kWh differs by more than "
                f"5% from 95% of system capacity ({theoretical_usable:.2f} kWh)"
            )

        return BatteryConfiguration(
            module_count=module_count,
            system_capacity_kwh=round(system_capacity, 2),
            usable_capacity_kwh=round(usable_capacity, 2),
            source="+".join(sources),
            warning="; ".join(warnings) if warnings else None,
        )

    def _configured_value(self, key: str) -> Any:
        """Return a value only when the config entry explicitly stores it."""
        if key in self.entry.options:
            return self.entry.options[key]
        if key in self.entry.data:
            return self.entry.data[key]
        return None

    def _modules_from_capacity(self, capacity_kwh: Any) -> int | None:
        """Infer Force H3 module count from a system or usable capacity value."""
        try:
            capacity = float(capacity_kwh)
        except (TypeError, ValueError):
            return None

        for modules in range(FORCE_H3_MIN_MODULES, FORCE_H3_MAX_MODULES + 1):
            if self._capacity_deviation_pct(
                capacity,
                self._system_capacity_for_modules(modules),
            ) <= 5.0:
                return modules
            if self._capacity_deviation_pct(
                capacity,
                self._usable_capacity_for_modules(modules),
            ) <= 5.0:
                return modules
        return None

    @staticmethod
    def _system_capacity_for_modules(module_count: int) -> float:
        """Return datasheet Force H3 system capacity for a module count."""
        return FORCE_H3_SYSTEM_CAPACITY_KWH[module_count]

    @staticmethod
    def _usable_capacity_for_modules(module_count: int) -> float:
        """Return datasheet Force H3 usable capacity for a module count."""
        return FORCE_H3_USABLE_CAPACITY_KWH[module_count]

    @staticmethod
    def _capacity_deviation_pct(value: float, expected: float) -> float:
        """Return absolute percentage deviation from the expected capacity."""
        if expected <= 0:
            return 0.0
        return abs(value - expected) / expected * 100

    @staticmethod
    def _valid_module_count(module_count: int) -> bool:
        """Return whether a Force H3 module count is valid for one inverter."""
        return FORCE_H3_MIN_MODULES <= module_count <= FORCE_H3_MAX_MODULES

    def _clamp_module_count(self, value: Any) -> int:
        """Clamp and round a module count to the supported Force H3 range."""
        try:
            modules = round(float(value))
        except (TypeError, ValueError):
            modules = int(DEFAULTS[CONF_BATTERY_MODULE_COUNT])
        return min(max(modules, FORCE_H3_MIN_MODULES), FORCE_H3_MAX_MODULES)

    def _update_battery_capacity_issue(self, decision: Decision) -> None:
        """Create or clear a Home Assistant repair issue for unconfirmed capacity."""
        attributes = decision.attributes or {}
        warning = attributes.get("battery_capacity_warning")
        if not warning:
            ir.async_delete_issue(self.hass, DOMAIN, BATTERY_CAPACITY_ISSUE_ID)
            return

        ir.async_create_issue(
            self.hass,
            DOMAIN,
            BATTERY_CAPACITY_ISSUE_ID,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=BATTERY_CAPACITY_ISSUE_ID,
            translation_placeholders={
                "modules": str(attributes.get("battery_module_count") or "?"),
                "system_capacity": str(
                    attributes.get("battery_system_capacity_kwh") or "?"
                ),
                "usable_capacity": str(
                    attributes.get("battery_usable_capacity_kwh") or "?"
                ),
                "warning": str(warning),
            },
        )

    def _periodic_full_charge_state(self, soc: float) -> dict[str, Any]:
        """Return periodic full-charge state for top balancing and SOC calibration."""
        enabled = bool(self._option(CONF_PERIODIC_FULL_CHARGE_ENABLED))
        interval_days = float(self._option(CONF_PERIODIC_FULL_CHARGE_INTERVAL_DAYS))
        target_soc = float(self._option(CONF_PERIODIC_FULL_CHARGE_TARGET_SOC))
        threshold_soc = float(self._option(CONF_PERIODIC_FULL_CHARGE_THRESHOLD_SOC))
        now = dt_util.utcnow()
        anchor = (
            self._last_full_charge_at
            or self._full_charge_schedule_started_at
            or now
        )
        next_due = anchor + timedelta(days=interval_days)
        next_due_at = next_due.isoformat() if enabled else None
        due = enabled and now >= next_due and soc < threshold_soc

        return {
            "periodic_full_charge_enabled": enabled,
            "periodic_full_charge_due": due,
            "periodic_full_charge_target_soc": target_soc,
            "periodic_full_charge_threshold_soc": threshold_soc,
            "periodic_full_charge_interval_days": interval_days,
            "periodic_full_charge_last_at": (
                self._last_full_charge_at.isoformat()
                if self._last_full_charge_at is not None
                else None
            ),
            "periodic_full_charge_next_due_at": next_due_at,
        }

    def _home_load_power_w(self) -> tuple[float | None, str]:
        """Resolve the preferred house load power reading."""
        total_entity = str(self._option(CONF_SHELLY_TOTAL_POWER_ENTITY)).strip()
        total_power = self._positive_power_state_w(total_entity)
        if total_power is not None:
            return total_power, f"shelly_total:{total_entity}"

        phase_entities = [
            str(self._option(key)).strip()
            for key in (
                CONF_SHELLY_PHASE_A_POWER_ENTITY,
                CONF_SHELLY_PHASE_B_POWER_ENTITY,
                CONF_SHELLY_PHASE_C_POWER_ENTITY,
            )
            if str(self._option(key)).strip()
        ]
        phase_values = [self._positive_power_state_w(entity) for entity in phase_entities]
        available_phases = [value for value in phase_values if value is not None]
        if available_phases:
            return sum(available_phases), "shelly_phases:" + ",".join(phase_entities)

        fallback_entity = str(self._option(CONF_LOAD_POWER_ENTITY)).strip()
        fallback_power = self._positive_power_state_w(fallback_entity)
        if fallback_power is not None:
            return fallback_power, f"fallback:{fallback_entity}"

        return None, "unavailable"

    def _positive_power_state_w(self, entity_id: str | None) -> float | None:
        """Read a power entity and clamp impossible negative consumption to zero."""
        value = self._power_state_w(entity_id)
        if value is None:
            return None
        return max(value, 0.0)

    def _forecast_load(
        self,
        future_slots: list[PriceSlot],
        current_load_w: float | None,
    ) -> LoadForecast:
        """Build a historical load forecast with an explicit flat fallback."""
        ev_mode = str(self._option(CONF_EV_FORECAST_MODE))
        ev_power = self._positive_power_state_w(
            str(self._option(CONF_EV_POWER_ENTITY)).strip()
        )
        forecaster = HistoricalLoadForecaster(
            self._historical_observations,
            ev_mode=ev_mode,
            ev_threshold_w=float(self._option(CONF_EV_CHARGING_THRESHOLD_W)),
        )
        return forecaster.forecast(
            future_slots,
            current_load_w=current_load_w,
            current_ev_w=ev_power,
        )

    @staticmethod
    def _solar_forecast_bands(
        forecast_w: list[float],
        *,
        source: str,
    ) -> list[ForecastBand]:
        """Add calibrated uncertainty bands to the deterministic PV model."""
        calibrated = "calibrated" in source
        spread = 0.20 if calibrated else 0.35
        confidence = 0.75 if calibrated else 0.45
        return [
            ForecastBand(
                p10_w=max(power_w * (1 - spread), 0.0),
                p50_w=max(power_w, 0.0),
                p90_w=max(power_w * (1 + spread), 0.0),
                samples=0,
                confidence=confidence,
            )
            for power_w in forecast_w
        ]

    def _serialize_forecast_bands(
        self,
        slots: list[PriceSlot],
        bands: list[ForecastBand],
    ) -> list[dict[str, Any]]:
        """Serialize probabilistic forecasts for dashboard charts."""
        serialized: list[dict[str, Any]] = []
        now = dt_util.utcnow()
        for index, slot in enumerate(slots):
            band = bands[index] if index < len(bands) else ForecastBand(0, 0, 0, 0, 0)
            duration_h = self._slot_duration_hours(
                slot,
                now if index == 0 else None,
            )
            serialized.append(
                {
                    **self._serialize_price_slot(slot),
                    "power_w": round(band.p50_w, 1),
                    "p10_w": round(band.p10_w, 1),
                    "p50_w": round(band.p50_w, 1),
                    "p90_w": round(band.p90_w, 1),
                    "energy_kwh": round(band.p50_w * duration_h / 1000, 3),
                    "samples": band.samples,
                    "confidence": round(band.confidence, 3),
                    "ev_power_w": round(band.ev_w, 1),
                }
            )
        return serialized

    def _tariff_settings(self) -> TariffSettings:
        """Resolve the retail tariff model from integration options."""
        return TariffSettings(
            dutch_enabled=bool(self._option(CONF_DUTCH_TARIFF_ENABLED)),
            vat_percent=float(self._option(CONF_VAT_PERCENT)),
            energy_tax_per_kwh=float(self._option(CONF_ENERGY_TAX_PER_KWH)),
            supplier_buy_markup_per_kwh=float(
                self._option(CONF_SUPPLIER_BUY_MARKUP)
            ),
            supplier_sell_markdown_per_kwh=float(
                self._option(CONF_SUPPLIER_SELL_MARKDOWN)
            ),
            legacy_buy_adder_per_kwh=float(self._option(CONF_BUY_COST_ADDER)),
            legacy_sell_adder_per_kwh=float(self._option(CONF_SELL_COST_ADDER)),
        )

    def _run_predictive_optimizer(
        self,
        *,
        future_slots: list[PriceSlot],
        current_energy: float,
        min_energy: float,
        max_energy: float,
        terminal_energy: float,
        charge_allowed: bool,
        discharge_allowed: bool,
        usable_capacity_kwh: float,
        periodic_full_charge_due: bool,
        load_forecast: LoadForecast,
        solar_forecast: list[ForecastBand],
        current_load_power_w: float | None,
        current_solar_power_w: float | None,
    ) -> Decision:
        """Run the modular forecast-aware model-predictive optimizer."""
        tariff = self._tariff_settings()
        optimizer_slots: list[OptimizerSlot] = []
        for index, slot in enumerate(future_slots):
            price = retail_price(slot.price, tariff)
            optimizer_slots.append(
                OptimizerSlot(
                    start=slot.start,
                    end=slot.end,
                    wholesale_price=slot.price,
                    buy_price=price.buy,
                    sell_price=price.sell,
                    load=(
                        load_forecast.bands[index]
                        if index < len(load_forecast.bands)
                        else ForecastBand(0, 0, 0, 0, 0)
                    ),
                    solar=(
                        solar_forecast[index]
                        if index < len(solar_forecast)
                        else ForecastBand(0, 0, 0, 0, 0)
                    ),
                )
            )
        charge_limit = self._slot_power_limit(
            future_slots, "charge", usable_capacity_kwh
        )
        discharge_limit = self._slot_power_limit(
            future_slots, "discharge", usable_capacity_kwh
        )
        settings = OptimizerSettings(
            min_energy_kwh=min_energy,
            max_energy_kwh=max_energy,
            initial_energy_kwh=current_energy,
            terminal_energy_kwh=terminal_energy,
            charge_efficiency=math.sqrt(
                float(self._option(CONF_ROUND_TRIP_EFFICIENCY))
            ),
            discharge_efficiency=math.sqrt(
                float(self._option(CONF_ROUND_TRIP_EFFICIENCY))
            ),
            max_charge_power_w=charge_limit,
            max_discharge_power_w=discharge_limit,
            min_active_power_w=float(self._option(CONF_MIN_ACTIVE_POWER_W)),
            grid_import_limit_w=float(self._option(CONF_GRID_IMPORT_LIMIT_W)),
            grid_export_limit_w=float(self._option(CONF_GRID_EXPORT_LIMIT_W)),
            cycle_cost_per_kwh=float(self._option(CONF_CYCLE_COST)),
            min_profit_margin_per_kwh=float(
                self._option(CONF_MIN_PROFIT_MARGIN)
            ),
            action_start_cost=float(self._option(CONF_ACTION_START_COST)),
            direction_change_cost=float(
                self._option(CONF_DIRECTION_CHANGE_COST)
            ),
            min_action_duration_minutes=float(
                self._option(CONF_MIN_ACTION_DURATION_MINUTES)
            ),
            risk_percentile=float(self._option(CONF_FORECAST_RISK_PERCENTILE)),
            power_profile=str(self._option(CONF_STRATEGY_PROFILE)),
            charge_allowed=charge_allowed,
            discharge_allowed=discharge_allowed,
        )
        result = self._predictive_optimizer.optimize(optimizer_slots, settings)
        if not result.schedule:
            return Decision(action="idle", reason=result.reason)

        plan = [row.as_dict() for row in result.schedule]
        first = result.schedule[0]
        first_row = plan[0]
        action = first.action
        command_target_power_w = abs(first.target_power_w)
        reason = f"{first.intent}: {result.reason}"
        if action == "charge" and first.intent == "solar_storage":
            live_surplus_w = (
                max(current_solar_power_w - current_load_power_w, 0.0)
                if current_solar_power_w is not None
                and current_load_power_w is not None
                else 0.0
            )
            command_target_power_w = live_solar_charge_target_w(
                command_target_power_w,
                current_solar_power_w,
                current_load_power_w,
            )
            if command_target_power_w < float(
                self._option(CONF_MIN_ACTIVE_POWER_W)
            ):
                action = "idle"
                command_target_power_w = 0.0
                reason = (
                    "solar storage planned, but live SMA surplus is below the "
                    "minimum forced-charge power"
                )
            else:
                reason = (
                    "live SMA surplus charge; forced target follows measured "
                    "solar minus home load"
                )
            first_row["execution"] = "live_surplus_following"
            first_row["live_surplus_w"] = round(live_surplus_w, 1)
            first_row["live_target_power_w"] = round(command_target_power_w, 1)

        today = dt_util.now().date()
        planned_charge = sum(
            float(row["energy_kwh"]) for row in plan if row["action"] == "charge"
        )
        planned_discharge = sum(
            float(row["energy_kwh"])
            for row in plan
            if row["action"] == "discharge"
        )
        grid_charge = sum(float(row["grid_charge_kwh"]) for row in plan)
        solar_charge = sum(float(row["solar_charge_kwh"]) for row in plan)
        self_consumption = sum(float(row["self_consumption_kwh"]) for row in plan)
        grid_export = sum(float(row["battery_export_kwh"]) for row in plan)
        today_value = sum(
            float(row["value"])
            for row in plan
            if dt_util.as_local(
                datetime.fromisoformat(str(row["start"]))
            ).date()
            == today
        )
        load_kwh = sum(
            slot.load.p50_w * slot.duration_h / 1000 for slot in optimizer_slots
        )
        solar_kwh = sum(
            slot.solar.p50_w * slot.duration_h / 1000 for slot in optimizer_slots
        )
        decision = Decision(
            action=action,
            reason=reason,
            target_power_w=command_target_power_w if action != "idle" else 0.0,
            target_power_percent=(
                self._power_to_percent(action, command_target_power_w)
                if action != "idle"
                else 0.0
            ),
            estimated_first_slot_value=float(first_row["value"]),
            estimated_plan_value=result.estimated_savings,
            estimated_today_value=today_value,
            planned_charge_kwh=planned_charge,
            planned_discharge_kwh=planned_discharge,
            planned_grid_charge_kwh=grid_charge,
            planned_solar_charge_kwh=solar_charge,
            planned_self_consumption_kwh=self_consumption,
            planned_grid_export_kwh=grid_export,
            forecast_load_kwh=load_kwh,
            forecast_solar_kwh=solar_kwh,
            attributes={
                "dispatch_plan": plan,
                "baseline_grid_cost": round(result.baseline_cost, 4),
                "optimized_grid_cost": round(result.optimized_cost, 4),
                "modeled_cycle_cost": round(result.cycle_cost, 4),
                "modeled_transition_cost": round(result.transition_cost, 4),
                "equivalent_full_cycles": round(
                    result.equivalent_full_cycles, 4
                ),
                "optimizer": "predictive_dispatch_dp_v1",
                "optimizer_diagnostics": result.diagnostics,
                "periodic_full_charge_forced": periodic_full_charge_due,
                "dutch_tariff_enabled": tariff.dutch_enabled,
                "vat_percent": tariff.vat_percent,
                "energy_tax_per_kwh": tariff.energy_tax_per_kwh,
                "supplier_buy_markup_per_kwh": (
                    tariff.supplier_buy_markup_per_kwh
                ),
                "supplier_sell_markdown_per_kwh": (
                    tariff.supplier_sell_markdown_per_kwh
                ),
            },
        )
        return decision

    def _solar_forecast_for_slots(
        self,
        future_slots: list[PriceSlot],
        current_solar_power_w: float | None,
    ) -> tuple[list[ForecastBand], str, float]:
        """Return Solcast forecasts with a calibrated local-model fallback."""
        raw_forecast = [self._solar_power_model_w(slot) for slot in future_slots]
        panel_count = float(self._option(CONF_PV_PANEL_COUNT))
        panel_wp = float(self._option(CONF_PV_PANEL_WP))
        solar_entity = str(self._option(CONF_SOLAR_POWER_ENTITY)).strip()
        scale = 1.0
        source = "panel_model"
        measured_w = max(current_solar_power_w or 0.0, 0.0)
        current_model_w = raw_forecast[0] if raw_forecast else 0.0
        panel_enabled = panel_count > 0 and panel_wp > 0
        if panel_enabled and solar_entity and measured_w > 50.0 and current_model_w > 50.0:
            scale = min(max(measured_w / current_model_w, 0.25), 1.5)
            source = "panel_model_calibrated_by_sma_power"

        limit_w = float(self._option(CONF_PV_INVERTER_LIMIT_W))
        scaled = [
            min(power_w * scale, limit_w) if limit_w > 0 else power_w * scale
            for power_w in raw_forecast
        ]
        if not panel_enabled:
            scaled = [0.0 for _slot in future_slots]
            source = "disabled_panel_config"
        panel_bands = self._solar_forecast_bands(scaled, source=source)

        selected_source = str(self._option(CONF_SOLAR_FORECAST_SOURCE))
        solcast_aligned = align_solcast_forecasts(
            self._solcast_forecast,
            future_slots,
        )
        use_solcast = selected_source in {"auto", "solcast"} and any(
            band is not None for band in solcast_aligned
        )
        if use_solcast:
            bands = [
                solcast_band or panel_band
                for solcast_band, panel_band in zip(
                    solcast_aligned,
                    panel_bands,
                    strict=True,
                )
            ]
            source = (
                "solcast_cached_with_panel_fallback"
                if any(band is None for band in solcast_aligned)
                else "solcast"
            )
            scale = 1.0
        else:
            bands = panel_bands
            if selected_source == "solcast":
                source = "solcast_unavailable_panel_fallback"

        if solar_entity and bands and current_solar_power_w is not None:
            bands[0] = ForecastBand(
                p10_w=max(measured_w * 0.9, 0.0),
                p50_w=measured_w,
                p90_w=measured_w * 1.1,
                samples=1,
                confidence=0.95,
            )
            source += "_live_sma_current_slot"
        return bands, source, scale

    def _solar_power_model_w(self, slot: PriceSlot) -> float:
        """Estimate PV power for a slot from panel size, orientation, and daylight."""
        panel_count = float(self._option(CONF_PV_PANEL_COUNT))
        panel_wp = float(self._option(CONF_PV_PANEL_WP))
        peak_w = panel_count * panel_wp
        if peak_w <= 0:
            return 0.0

        orientation = str(self._option(CONF_PV_ORIENTATION)).upper()
        orientation_factor, peak_shift_h = PV_ORIENTATION_PROFILE.get(
            orientation,
            PV_ORIENTATION_PROFILE["S"],
        )
        midpoint = dt_util.as_local(slot.start + (slot.end - slot.start) / 2)
        daylight_h = self._daylight_hours(midpoint)
        if daylight_h <= 0:
            return 0.0

        peak_hour = self._solar_noon_hour(midpoint) + peak_shift_h
        local_hour = (
            midpoint.hour
            + midpoint.minute / 60
            + midpoint.second / 3600
            + midpoint.microsecond / 3_600_000_000
        )
        half_day_h = max(daylight_h / 2, 1.0)
        normalized_distance = abs(local_hour - peak_hour) / half_day_h
        if normalized_distance >= 1.0:
            return 0.0

        daylight_shape = math.cos(normalized_distance * math.pi / 2) ** 1.6
        power_w = peak_w * orientation_factor * daylight_shape
        inverter_limit = float(self._option(CONF_PV_INVERTER_LIMIT_W))
        return min(power_w, inverter_limit) if inverter_limit > 0 else power_w

    def _daylight_hours(self, local_time: datetime) -> float:
        """Approximate daylight hours for the Home Assistant latitude."""
        latitude = float(getattr(self.hass.config, "latitude", 0.0) or 0.0)
        latitude = min(max(latitude, -66.0), 66.0)
        lat_rad = math.radians(latitude)
        day_of_year = local_time.timetuple().tm_yday
        declination = math.radians(23.44) * math.sin(
            2 * math.pi * (284 + day_of_year) / 365
        )
        cos_hour_angle = -math.tan(lat_rad) * math.tan(declination)
        if cos_hour_angle >= 1:
            return 0.0
        if cos_hour_angle <= -1:
            return 24.0
        hour_angle = math.acos(cos_hour_angle)
        return min(max(24 * hour_angle / math.pi, 0.0), 24.0)

    def _solar_noon_hour(self, local_time: datetime) -> float:
        """Approximate true solar noon in local clock hours."""
        longitude = float(getattr(self.hass.config, "longitude", 0.0) or 0.0)
        utc_offset = local_time.utcoffset()
        offset_h = utc_offset.total_seconds() / 3600 if utc_offset else 0.0
        standard_meridian = offset_h * 15
        return 12.0 + (standard_meridian - longitude) / 15


    def _terminal_energy(
        self, current_energy: float, min_energy: float, max_energy: float
    ) -> float:
        """Return the terminal energy floor for the optimization horizon."""
        mode = str(self._option(CONF_TERMINAL_SOC_MODE))
        if mode == "reserve_only":
            return min_energy
        return min(max(current_energy, min_energy), max_energy)

    def _slot_duration_hours(self, slot: PriceSlot, now: datetime | None = None) -> float:
        """Return usable duration for a price slot."""
        start = max(slot.start, now) if now is not None else slot.start
        return max((slot.end - start).total_seconds() / 3600, 0.0)

    def _slot_power_limit(
        self,
        slots: list[PriceSlot],
        action: str,
        usable_capacity_kwh: float,
    ) -> float:
        """Return the allowed AC power for a slot after economics and C-rate."""
        continuous = float(self._option(CONF_CONTINUOUS_POWER_W))
        peak = float(self._option(CONF_PEAK_POWER_W))
        economic_limit = continuous
        if not bool(self._option(CONF_ENABLE_PEAK_POWER)):
            economic_limit = continuous
        else:
            buy_adder = float(self._option(CONF_BUY_COST_ADDER))
            sell_adder = float(self._option(CONF_SELL_COST_ADDER))
            required_margin = (
                float(self._option(CONF_CYCLE_COST))
                + float(self._option(CONF_MIN_PROFIT_MARGIN))
                + float(self._option(CONF_PEAK_EXTRA_MARGIN))
            )
            min_buy = min(price_slot.price + buy_adder for price_slot in slots)
            max_sell = max(price_slot.price - sell_adder for price_slot in slots)
            if max_sell - min_buy > required_margin:
                economic_limit = peak

        c_rate_key = (
            CONF_MAX_CHARGE_C_RATE if action == "charge" else CONF_MAX_DISCHARGE_C_RATE
        )
        c_rate_limit_w = max(usable_capacity_kwh, 0.0) * float(
            self._option(c_rate_key)
        ) * 1000
        if c_rate_limit_w <= 0:
            return economic_limit
        return min(economic_limit, c_rate_limit_w)

    def _temperature_permissions(
        self, bms_temp: float | None
    ) -> tuple[bool, bool, str | None]:
        """Return charge and discharge permissions from BMS temperature."""
        if bms_temp is None:
            return True, True, None
        min_charge = float(self._option(CONF_MIN_CHARGE_TEMP_C))
        max_temp = float(self._option(CONF_MAX_BMS_TEMP_C))
        if bms_temp < min_charge:
            return False, True, f"BMS temperature below charge guard ({bms_temp:.1f} C)"
        if bms_temp > max_temp:
            return False, False, f"BMS temperature above guard ({bms_temp:.1f} C)"
        return True, True, None


    def _apply_grid_limit(
        self,
        action: str,
        target_power_w: float,
        *,
        load_power_w: float | None,
        grid_import_power_w: float | None,
        grid_import_average_power_w: float | None,
    ) -> float:
        """Limit battery power to avoid exceeding configured grid connection limits."""
        load_power = max(load_power_w or 0.0, 0.0)
        if action == "charge":
            charge_headroom_w = self._grid_charge_headroom_w(
                load_power_w=load_power_w,
                grid_import_power_w=grid_import_power_w,
                grid_import_average_power_w=grid_import_average_power_w,
            )
            if charge_headroom_w is not None:
                return min(target_power_w, charge_headroom_w)
        elif action == "discharge":
            export_limit = float(self._option(CONF_GRID_EXPORT_LIMIT_W))
            if export_limit > 0:
                return min(target_power_w, max(export_limit + load_power, 0.0))
        return target_power_w

    def _grid_charge_headroom_w(
        self,
        *,
        load_power_w: float | None,
        grid_import_power_w: float | None,
        grid_import_average_power_w: float | None,
    ) -> float | None:
        """Return allowed charge power from house/grid import readings."""
        import_limit = float(self._option(CONF_GRID_IMPORT_LIMIT_W))
        if import_limit <= 0:
            return None

        has_load_power = load_power_w is not None
        load_power = max(load_power_w or 0.0, 0.0)
        limits = [max(import_limit - load_power, 0.0)]
        grid_readings = [
            max(value, 0.0)
            for value in (grid_import_power_w, grid_import_average_power_w)
            if value is not None
        ]
        if grid_readings:
            current_charge_w = (
                self._requested_charge_power_w() if has_load_power else 0.0
            )
            limits.append(max(import_limit - max(grid_readings) + current_charge_w, 0.0))
        return min(limits)

    def _requested_charge_power_w(self) -> float:
        """Return the currently requested battery charge power, if known."""
        percent = self._state_float(str(self._option(CONF_POWER_REF_ENTITY)))
        if percent is None:
            percent = self._last_power_percent
        if percent is None or percent >= 0:
            return 0.0

        full_scale = max(float(self._option(CONF_INVERTER_FULL_SCALE_POWER_W)), 1.0)
        return min(abs(percent) / 100 * full_scale, full_scale)

    def _power_to_percent(self, action: str, power_w: float) -> float:
        """Convert AC watt target into the signed H3X power reference percentage."""
        full_scale = max(float(self._option(CONF_INVERTER_FULL_SCALE_POWER_W)), 1.0)
        percent = min(max(power_w / full_scale * 100, 0.0), 100.0)
        return -percent if action == "charge" else percent

    def _idle_from(self, decision: Decision, reason: str) -> Decision:
        """Return an idle decision preserving diagnostic context."""
        decision.action = "idle"
        decision.reason = reason
        decision.target_power_w = 0.0
        decision.target_power_percent = 0.0
        return decision

    def _infer_resolution_minutes(self, slots: list[PriceSlot]) -> int | None:
        """Infer the active price resolution from the first slot."""
        if not slots:
            return None
        return round(slots[0].duration_hours * 60)

    def _serialize_price_slot(self, slot: PriceSlot) -> dict[str, Any]:
        """Serialize wholesale and effective retail prices."""
        price = retail_price(slot.price, self._tariff_settings())
        return {
            "start": dt_util.as_local(slot.start).isoformat(),
            "end": dt_util.as_local(slot.end).isoformat(),
            "price": round(price.buy, 5),
            "wholesale_price": round(price.wholesale, 5),
            "buy_price": round(price.buy, 5),
            "sell_price": round(price.sell, 5),
        }

    def _price_trend_attributes(self, slots: list[PriceSlot]) -> dict[str, Any]:
        """Return current and per-slot price trend diagnostics."""
        trend_slots = self._price_trend_slots(slots)
        current = trend_slots[0] if trend_slots else {}
        return {
            "price_trend_direction": current.get("trend_direction", "unknown"),
            "price_trend_delta_next": current.get("delta_next"),
            "price_trend_price": current.get("trend_price"),
            "price_trend": trend_slots,
        }

    def _price_trend_slots(self, slots: list[PriceSlot]) -> list[dict[str, Any]]:
        """Build a rolling trend line over future price slots."""
        trend_slots: list[dict[str, Any]] = []
        for index, slot in enumerate(slots):
            window = slots[max(index - 2, 0) : min(index + 3, len(slots))]
            trend_price = (
                sum(
                    retail_price(price_slot.price, self._tariff_settings()).buy
                    for price_slot in window
                )
                / len(window)
                if window
                else retail_price(slot.price, self._tariff_settings()).buy
            )
            current_price = retail_price(slot.price, self._tariff_settings()).buy
            next_price = (
                retail_price(slots[index + 1].price, self._tariff_settings()).buy
                if index + 1 < len(slots)
                else current_price
            )
            delta_next = next_price - current_price
            trend_slots.append(
                {
                    **self._serialize_price_slot(slot),
                    "trend_price": round(trend_price, 5),
                    "delta_next": round(delta_next, 5),
                    "trend_direction": self._price_trend_direction(delta_next),
                }
            )
        return trend_slots

    @staticmethod
    def _price_trend_direction(delta: float) -> str:
        """Return a stable direction label for a price delta."""
        if delta > 0.0005:
            return "up"
        if delta < -0.0005:
            return "down"
        return "flat"

    def _power_state_w(self, entity_id: str | None) -> float | None:
        """Read a Home Assistant power entity and normalize W/kW/MW to watts."""
        value = self._state_float(entity_id)
        if value is None or not entity_id:
            return value

        state = self.hass.states.get(entity_id)
        if state is None:
            return value
        unit = str((state.attributes or {}).get("unit_of_measurement") or "").lower()
        unit = unit.replace(" ", "")
        if unit in {"kw", "kilowatt", "kilowatts"}:
            return value * 1000
        if unit in {"mw", "megawatt", "megawatts"}:
            return value * 1_000_000
        return value

    def _energy_state_kwh(self, entity_id: str | None) -> float | None:
        """Read a Home Assistant energy entity and normalize Wh/kWh/MWh to kWh."""
        value = self._state_float(entity_id)
        if value is None or not entity_id:
            return value

        state = self.hass.states.get(entity_id)
        if state is None:
            return value
        unit = str((state.attributes or {}).get("unit_of_measurement") or "").lower()
        unit = unit.replace(" ", "")
        if unit in {"wh", "watthour", "watthours"}:
            return value / 1000
        if unit in {"mwh", "megawatthour", "megawatthours"}:
            return value * 1000
        return value

    def _state_float(self, entity_id: str | None) -> float | None:
        """Read a Home Assistant entity as a float."""
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in {STATE_UNKNOWN, STATE_UNAVAILABLE, ""}:
            return None
        try:
            return float(state.state)
        except (TypeError, ValueError):
            return None

    async def _apply_decision(self, decision: Decision) -> None:
        """Apply the control decision through Home Assistant entity services."""
        try:
            self._stabilize_runtime_action(decision)
            await self._set_soc_limits(decision)
            if decision.action in {"charge", "discharge"}:
                await self._set_ems_mode(str(self._option(CONF_USER_EMS_MODE)))
                await self._set_power_ref(decision.target_power_percent)
            else:
                await self._set_power_ref(0.0)
                await self._set_ems_mode(str(self._option(CONF_IDLE_EMS_MODE)))
            decision.applied = True
            if decision.action != self._last_applied_action:
                self._last_action_changed_at = dt_util.utcnow()
            self._last_applied_action = decision.action
            self._last_target_power_w = decision.target_power_w
        except Exception as err:  # pylint: disable=broad-except
            LOGGER.exception("Failed to apply H3X arbitrage decision")
            decision.applied = False
            decision.apply_error = str(err)

    def _stabilize_runtime_action(self, decision: Decision) -> None:
        """Prevent re-planning from creating short or reversing commands."""
        if self._last_applied_action is None:
            percent = self._state_float(str(self._option(CONF_POWER_REF_ENTITY)))
            if percent is not None and percent < -0.2:
                self._last_applied_action = "charge"
            elif percent is not None and percent > 0.2:
                self._last_applied_action = "discharge"
            else:
                self._last_applied_action = "idle"
            self._last_action_changed_at = dt_util.utcnow()
            self._last_target_power_w = (
                abs(percent or 0.0)
                / 100
                * float(self._option(CONF_INVERTER_FULL_SCALE_POWER_W))
            )

        previous = self._last_applied_action
        changed_at = self._last_action_changed_at
        if previous not in {"charge", "discharge"} or changed_at is None:
            return
        if decision.action == previous:
            return
        elapsed = dt_util.utcnow() - changed_at
        minimum = timedelta(
            minutes=float(self._option(CONF_MIN_ACTION_DURATION_MINUTES))
        )
        safety_stop = decision.action == "failsafe" or (
            decision.action == "idle"
            and any(
                token in decision.reason.lower()
                for token in (
                    "temperature",
                    "soc",
                    "unavailable",
                    "grid limit",
                    "not allowed",
                )
            )
        )
        if elapsed >= minimum or safety_stop:
            return

        remaining = minimum - elapsed
        decision.attributes["runtime_hysteresis_applied"] = True
        decision.attributes["runtime_hysteresis_remaining_minutes"] = round(
            remaining.total_seconds() / 60, 1
        )
        decision.reason = (
            f"{decision.reason}; holding {previous} for minimum action duration"
        )
        decision.action = previous
        decision.target_power_w = max(
            self._last_target_power_w,
            float(self._option(CONF_MIN_ACTIVE_POWER_W)),
        )
        decision.target_power_percent = self._power_to_percent(
            previous, decision.target_power_w
        )

    async def _set_soc_limits(self, decision: Decision) -> None:
        """Set conservative SOC limits on the H3X integration when entities exist."""
        charge_entity = str(self._option(CONF_CHARGE_LIMIT_SOC_ENTITY)).strip()
        discharge_entity = str(self._option(CONF_DISCHARGE_LIMIT_SOC_ENTITY)).strip()
        max_soc = float(self._option(CONF_MAX_SOC))
        floor_soc = max(float(self._option(CONF_MIN_SOC)), float(self._option(CONF_RESERVE_SOC)))
        attributes = decision.attributes or {}
        if attributes.get("periodic_full_charge_due"):
            max_soc = max(
                max_soc,
                float(attributes.get("periodic_full_charge_target_soc") or max_soc),
            )

        if charge_entity and self.hass.states.get(charge_entity) is not None:
            await self.hass.services.async_call(
                "number",
                "set_value",
                {"value": round(max_soc)},
                target={"entity_id": charge_entity},
                blocking=True,
            )
        if discharge_entity and self.hass.states.get(discharge_entity) is not None:
            await self.hass.services.async_call(
                "number",
                "set_value",
                {"value": round(floor_soc)},
                target={"entity_id": discharge_entity},
                blocking=True,
            )

    async def _set_ems_mode(self, mode: str) -> None:
        """Set EMS mode if it changed."""
        entity_id = str(self._option(CONF_EMS_MODE_ENTITY)).strip()
        if not entity_id:
            return
        state = self.hass.states.get(entity_id)
        if state and state.state == mode and self._last_ems_mode == mode:
            return
        await self.hass.services.async_call(
            "select",
            "select_option",
            {"option": mode},
            target={"entity_id": entity_id},
            blocking=True,
        )
        self._last_ems_mode = mode

    async def _set_power_ref(self, percent: float) -> None:
        """Set signed charge/discharge power reference percentage."""
        entity_id = str(self._option(CONF_POWER_REF_ENTITY)).strip()
        if not entity_id:
            raise RuntimeError("power reference entity is not configured")

        percent = round(percent, 1)
        state = self.hass.states.get(entity_id)
        current = None
        if state and state.state not in {STATE_UNKNOWN, STATE_UNAVAILABLE}:
            try:
                current = float(state.state)
            except ValueError:
                current = None
        if current is not None and abs(current - percent) < 0.2:
            self._last_power_percent = percent
            return
        if self._last_power_percent is not None and abs(self._last_power_percent - percent) < 0.2:
            return

        await self.hass.services.async_call(
            "number",
            "set_value",
            {"value": percent},
            target={"entity_id": entity_id},
            blocking=True,
        )
        self._last_power_percent = percent
