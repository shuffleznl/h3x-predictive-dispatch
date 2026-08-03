"""Coordinator and optimizer for Pylontech H3X energy arbitrage."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
import logging
import math
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
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
    CONF_DISCHARGE_LIMIT_SOC_ENTITY,
    CONF_DISCHARGE_POWER_MODE,
    CONF_DISCHARGE_SPREAD_MAX_HOURS,
    CONF_DISCHARGE_SPREAD_PRICE_TOLERANCE,
    CONF_EMS_MODE_ENTITY,
    CONF_ENABLE_PEAK_POWER,
    CONF_GRID_EXPORT_LIMIT_W,
    CONF_GRID_IMPORT_AVERAGE_POWER_ENTITY,
    CONF_GRID_IMPORT_LIMIT_W,
    CONF_GRID_IMPORT_POWER_ENTITY,
    CONF_HORIZON_HOURS,
    CONF_IDLE_EMS_MODE,
    CONF_INVERTER_FULL_SCALE_POWER_W,
    CONF_LOAD_POWER_ENTITY,
    CONF_MAX_BMS_TEMP_C,
    CONF_MAX_CHARGE_C_RATE,
    CONF_MAX_DISCHARGE_C_RATE,
    CONF_MAX_SOC,
    CONF_MIN_ACTIVE_POWER_W,
    CONF_MIN_CHARGE_TEMP_C,
    CONF_MIN_PROFIT_MARGIN,
    CONF_MIN_SOC,
    CONF_NORDPOOL_CONFIG_ENTRY,
    CONF_PERIODIC_FULL_CHARGE_ENABLED,
    CONF_PERIODIC_FULL_CHARGE_INTERVAL_DAYS,
    CONF_PERIODIC_FULL_CHARGE_TARGET_SOC,
    CONF_PERIODIC_FULL_CHARGE_THRESHOLD_SOC,
    CONF_PEAK_EXTRA_MARGIN,
    CONF_PEAK_POWER_W,
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
    CONF_SOLAR_POWER_ENTITY,
    CONF_SOC_ENTITY,
    CONF_STRATEGY_PROFILE,
    CONF_TERMINAL_SOC_MODE,
    CONF_UPDATE_INTERVAL_MINUTES,
    CONF_USER_EMS_MODE,
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
    STRATEGY_PROFILE_SETTINGS,
)

LOGGER = logging.getLogger(__name__)
STORAGE_VERSION = 1
LAST_FULL_CHARGE_KEY = "last_periodic_full_charge_at"
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


class H3XArbitrageCoordinator(DataUpdateCoordinator[dict[str, Any]]):
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
        self._store = Store(
            hass,
            STORAGE_VERSION,
            f"{DOMAIN}_{entry.entry_id}_state",
        )
        self._state_loaded = False
        self._last_full_charge_at: datetime | None = None
        self._last_price_fetch_errors: list[str] = []

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
            decision = self._compute_decision(slots)
        except Exception as err:  # pylint: disable=broad-except
            LOGGER.exception("Failed to compute arbitrage decision")
            decision = Decision(action="failsafe", reason=str(err))

        self._finalize_decision_diagnostics(decision)
        self._update_battery_capacity_issue(decision)

        if bool(self._option(CONF_CONTROL_ENABLED)):
            await self._apply_decision(decision)
        else:
            decision.reason = f"{decision.reason}; control disabled"

        return decision.as_dict()

    async def async_shutdown(self) -> None:
        """Shut down coordinator resources."""
        return None

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
        self._state_loaded = True

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
        await self._store.async_save({LAST_FULL_CHARGE_KEY: now.isoformat()})

    async def _fetch_price_slots(self) -> list[PriceSlot]:
        """Fetch today and tomorrow price slots from Home Assistant Nord Pool."""
        entry_id = self._resolve_nordpool_entry_id()
        area = self._resolve_area()
        currency = self._resolve_currency()
        resolution = int(self._option(CONF_RESOLUTION))
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
        load_power_w, load_source = self._home_load_power_w()
        solar_power_w = self._positive_power_state_w(
            str(self._option(CONF_SOLAR_POWER_ENTITY)).strip()
        )
        load_forecast_w = self._load_forecast_for_slots(future_slots, load_power_w)
        solar_forecast_w, solar_forecast_source, solar_forecast_scale = (
            self._solar_forecast_for_slots(future_slots, solar_power_w)
        )
        decision = self._run_optimizer(
            future_slots=future_slots,
            current_energy=current_energy,
            min_energy=min_energy,
            max_energy=max_energy,
            terminal_energy=terminal_energy,
            charge_allowed=charge_allowed,
            discharge_allowed=discharge_allowed,
            usable_capacity_kwh=usable_capacity_kwh,
            periodic_full_charge_due=force_full_charge,
            load_forecast_w=load_forecast_w,
            solar_forecast_w=solar_forecast_w,
        )

        current_slot = future_slots[0]
        decision.soc = soc
        decision.current_price = current_slot.price
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
        decision.grid_import_average_power_w = self._power_state_w(
            str(self._option(CONF_GRID_IMPORT_AVERAGE_POWER_ENTITY))
        )
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
                "grid_import_average_power_entity": str(
                    self._option(CONF_GRID_IMPORT_AVERAGE_POWER_ENTITY)
                ),
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
                "load_forecast": self._serialize_power_forecast(
                    future_slots, load_forecast_w
                ),
                "solar_forecast": self._serialize_power_forecast(
                    future_slots, solar_forecast_w
                ),
                **periodic_full_charge,
                "discharge_power_mode": str(self._option(CONF_DISCHARGE_POWER_MODE)),
                "discharge_spread_price_tolerance_pct": float(
                    self._option(CONF_DISCHARGE_SPREAD_PRICE_TOLERANCE)
                ),
                "discharge_spread_max_hours": float(
                    self._option(CONF_DISCHARGE_SPREAD_MAX_HOURS)
                ),
                "nordpool_resolution_minutes": int(self._option(CONF_RESOLUTION)),
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

        if decision.action == "discharge":
            self._shape_discharge_decision(
                decision=decision,
                future_slots=future_slots,
                current_energy=current_energy,
                min_energy=min_energy,
                now=now,
            )

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
        self._ensure_capacity_attributes(decision)
        self._set_target_c_rate_attribute(decision)
        self._attach_plan_summaries(decision)

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
        return {
            "state": "planned",
            "start": row.get("start"),
            "end": row.get("end"),
            "action": row.get("action"),
            "energy_kwh": row.get("energy_kwh"),
            "target_power_w": row.get("target_power_w"),
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
            modules = int(round(module_count_from_entity))
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
                and not self._valid_module_count(int(round(module_count_from_entity)))
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
            modules = int(round(float(value)))
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
        next_due_at = None
        due = False

        if enabled and self._last_full_charge_at is not None:
            next_due = self._last_full_charge_at + timedelta(days=interval_days)
            next_due_at = next_due.isoformat()
            due = now >= next_due
        elif enabled:
            due = soc < threshold_soc

        if soc >= threshold_soc:
            due = False

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

    @staticmethod
    def _load_forecast_for_slots(
        future_slots: list[PriceSlot],
        current_load_w: float | None,
    ) -> list[float]:
        """Return a stable load forecast aligned to price slots."""
        load_w = max(current_load_w or 0.0, 0.0)
        return [load_w for _slot in future_slots]

    def _solar_forecast_for_slots(
        self,
        future_slots: list[PriceSlot],
        current_solar_power_w: float | None,
    ) -> tuple[list[float], str, float]:
        """Return a simple orientation-based PV forecast aligned to price slots."""
        raw_forecast = [self._solar_power_model_w(slot) for slot in future_slots]
        panel_count = float(self._option(CONF_PV_PANEL_COUNT))
        panel_wp = float(self._option(CONF_PV_PANEL_WP))
        solar_entity = str(self._option(CONF_SOLAR_POWER_ENTITY)).strip()
        if panel_count <= 0 or panel_wp <= 0:
            return [0.0 for _slot in future_slots], "disabled_panel_config", 1.0

        scale = 1.0
        source = "panel_model"
        measured_w = max(current_solar_power_w or 0.0, 0.0)
        current_model_w = raw_forecast[0] if raw_forecast else 0.0
        if solar_entity and measured_w > 50.0 and current_model_w > 50.0:
            scale = min(max(measured_w / current_model_w, 0.25), 1.5)
            source = "panel_model_calibrated_by_sma_power"

        limit_w = float(self._option(CONF_PV_INVERTER_LIMIT_W))
        scaled = [
            min(power_w * scale, limit_w) if limit_w > 0 else power_w * scale
            for power_w in raw_forecast
        ]
        if solar_entity and scaled and current_solar_power_w is not None:
            scaled[0] = measured_w
        return [round(max(power_w, 0.0), 1) for power_w in scaled], source, scale

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

    def _serialize_power_forecast(
        self,
        slots: list[PriceSlot],
        power_values_w: list[float],
    ) -> list[dict[str, Any]]:
        """Serialize a power forecast for dashboard attributes."""
        serialized: list[dict[str, Any]] = []
        now = dt_util.utcnow()
        for index, slot in enumerate(slots):
            power_w = power_values_w[index] if index < len(power_values_w) else 0.0
            duration_h = self._slot_duration_hours(
                slot,
                now if index == 0 else None,
            )
            serialized.append(
                {
                    **self._serialize_price_slot(slot),
                    "power_w": round(max(power_w, 0.0), 1),
                    "energy_kwh": round(max(power_w, 0.0) * duration_h / 1000, 3),
                }
            )
        return serialized

    def _run_optimizer(
        self,
        future_slots: list[PriceSlot],
        current_energy: float,
        min_energy: float,
        max_energy: float,
        terminal_energy: float,
        charge_allowed: bool,
        discharge_allowed: bool,
        usable_capacity_kwh: float,
        periodic_full_charge_due: bool = False,
        load_forecast_w: list[float] | None = None,
        solar_forecast_w: list[float] | None = None,
    ) -> Decision:
        """Run a dynamic-programming arbitrage optimizer."""
        now = dt_util.utcnow()
        load_forecast_w = load_forecast_w or [0.0 for _slot in future_slots]
        solar_forecast_w = solar_forecast_w or [0.0 for _slot in future_slots]
        capacity_range = max_energy - min_energy
        step_kwh = max(0.25, capacity_range / 100)
        level_count = max(int(round(capacity_range / step_kwh)), 1)
        levels = [
            min_energy + index * capacity_range / level_count
            for index in range(level_count + 1)
        ]
        initial_idx = min(
            range(len(levels)),
            key=lambda index: abs(levels[index] - current_energy),
        )

        terminal_values = {
            index: 0.0 if energy + step_kwh / 2 >= terminal_energy else -1_000_000.0
            for index, energy in enumerate(levels)
        }
        values = terminal_values
        policy: dict[tuple[int, int], int] = {}
        first_rewards: dict[tuple[int, int], float] = {}

        charge_eff = math.sqrt(float(self._option(CONF_ROUND_TRIP_EFFICIENCY)))
        discharge_eff = charge_eff
        buy_adder = float(self._option(CONF_BUY_COST_ADDER))
        sell_adder = float(self._option(CONF_SELL_COST_ADDER))
        required_margin = float(self._option(CONF_CYCLE_COST)) + float(
            self._option(CONF_MIN_PROFIT_MARGIN)
        )

        for slot_index in range(len(future_slots) - 1, -1, -1):
            slot = future_slots[slot_index]
            duration_h = self._slot_duration_hours(
                slot,
                now if slot_index == 0 else None,
            )
            charge_pmax_w = self._slot_power_limit(
                future_slots,
                "charge",
                usable_capacity_kwh,
            )
            discharge_pmax_w = self._slot_power_limit(
                future_slots,
                "discharge",
                usable_capacity_kwh,
            )
            max_charge_delta = charge_pmax_w * duration_h / 1000 * charge_eff
            max_discharge_delta = discharge_pmax_w * duration_h / 1000 / discharge_eff
            buy_price = slot.price + buy_adder
            sell_price = slot.price - sell_adder
            load_kwh = self._power_to_energy_kwh(
                load_forecast_w,
                slot_index,
                duration_h,
            )
            solar_kwh = self._power_to_energy_kwh(
                solar_forecast_w,
                slot_index,
                duration_h,
            )
            baseline_net_kwh = load_kwh - solar_kwh
            baseline_cost = self._net_grid_cost(
                baseline_net_kwh,
                buy_price,
                sell_price,
            )

            next_values: dict[int, float] = {}
            for idx, energy in enumerate(levels):
                best_value = values[idx]
                best_idx = idx
                best_reward = 0.0

                if charge_allowed:
                    for next_idx in range(idx + 1, len(levels)):
                        delta = levels[next_idx] - energy
                        if delta > max_charge_delta + step_kwh / 2:
                            break
                        ac_kwh = delta / charge_eff
                        candidate_net_kwh = baseline_net_kwh + ac_kwh
                        candidate_cost = self._net_grid_cost(
                            candidate_net_kwh,
                            buy_price,
                            sell_price,
                        )
                        reward = baseline_cost - candidate_cost
                        candidate = reward + values[next_idx]
                        if candidate > best_value:
                            best_value = candidate
                            best_idx = next_idx
                            best_reward = reward

                if discharge_allowed:
                    for next_idx in range(idx - 1, -1, -1):
                        delta = energy - levels[next_idx]
                        if delta > max_discharge_delta + step_kwh / 2:
                            break
                        ac_kwh = delta * discharge_eff
                        candidate_net_kwh = baseline_net_kwh - ac_kwh
                        candidate_cost = self._net_grid_cost(
                            candidate_net_kwh,
                            buy_price,
                            sell_price,
                        )
                        reward = baseline_cost - candidate_cost
                        reward -= ac_kwh * required_margin
                        candidate = reward + values[next_idx]
                        if candidate > best_value:
                            best_value = candidate
                            best_idx = next_idx
                            best_reward = reward

                next_values[idx] = best_value
                policy[(slot_index, idx)] = best_idx
                if slot_index == 0:
                    first_rewards[(slot_index, idx)] = best_reward

            values = next_values

        plan_value = values.get(initial_idx, 0.0)
        plan_slots, plan_totals = self._build_plan_summary(
            future_slots=future_slots,
            policy=policy,
            levels=levels,
            initial_idx=initial_idx,
            step_kwh=step_kwh,
            charge_eff=charge_eff,
            discharge_eff=discharge_eff,
            buy_adder=buy_adder,
            sell_adder=sell_adder,
            required_margin=required_margin,
            now=now,
            load_forecast_w=load_forecast_w,
            solar_forecast_w=solar_forecast_w,
        )
        planned_charge_kwh = plan_totals["planned_charge_kwh"]
        planned_discharge_kwh = plan_totals["planned_discharge_kwh"]
        today_value = plan_totals["estimated_today_value"]

        next_idx = policy.get((0, initial_idx), initial_idx)
        delta = levels[next_idx] - levels[initial_idx]
        duration_h = self._slot_duration_hours(future_slots[0], now)
        if abs(delta) < step_kwh / 2 or duration_h <= 0:
            reason = "optimizer selected no economic movement"
            if periodic_full_charge_due:
                reason = "periodic full charge due; waiting for selected charge slot"
            return Decision(
                action="idle",
                reason=reason,
                estimated_first_slot_value=first_rewards.get((0, initial_idx), 0.0),
                estimated_plan_value=plan_value,
                estimated_today_value=today_value,
                planned_charge_kwh=planned_charge_kwh,
                planned_discharge_kwh=planned_discharge_kwh,
                planned_grid_charge_kwh=plan_totals["planned_grid_charge_kwh"],
                planned_solar_charge_kwh=plan_totals["planned_solar_charge_kwh"],
                planned_self_consumption_kwh=plan_totals[
                    "planned_self_consumption_kwh"
                ],
                planned_grid_export_kwh=plan_totals["planned_grid_export_kwh"],
                forecast_load_kwh=plan_totals["forecast_load_kwh"],
                forecast_solar_kwh=plan_totals["forecast_solar_kwh"],
                attributes={"dispatch_plan": plan_slots},
            )

        if delta > 0:
            target_power = delta / charge_eff / duration_h * 1000
            reason = "current slot is economical for grid charging"
            if periodic_full_charge_due:
                reason = "periodic full charge due; charging toward top-balance target"
            first_slot = plan_slots[0] if plan_slots else {}
            grid_charge_kwh = float(first_slot.get("grid_charge_kwh") or 0.0)
            solar_charge_kwh = float(first_slot.get("solar_charge_kwh") or 0.0)
            if grid_charge_kwh <= 0.05 and solar_charge_kwh > 0.05:
                return Decision(
                    action="idle",
                    reason=(
                        "solar surplus is expected; allow self-consumption mode to "
                        "charge instead of forcing grid charge"
                    ),
                    estimated_first_slot_value=first_rewards.get((0, initial_idx), 0.0),
                    estimated_plan_value=plan_value,
                    estimated_today_value=today_value,
                    planned_charge_kwh=planned_charge_kwh,
                    planned_discharge_kwh=planned_discharge_kwh,
                    planned_grid_charge_kwh=plan_totals["planned_grid_charge_kwh"],
                    planned_solar_charge_kwh=plan_totals["planned_solar_charge_kwh"],
                    planned_self_consumption_kwh=plan_totals[
                        "planned_self_consumption_kwh"
                    ],
                    planned_grid_export_kwh=plan_totals["planned_grid_export_kwh"],
                    forecast_load_kwh=plan_totals["forecast_load_kwh"],
                    forecast_solar_kwh=plan_totals["forecast_solar_kwh"],
                    attributes={"dispatch_plan": plan_slots},
                )
            return Decision(
                action="charge",
                reason=reason,
                target_power_w=min(
                    target_power,
                    self._slot_power_limit(
                        future_slots,
                        "charge",
                        usable_capacity_kwh,
                    ),
                ),
                estimated_first_slot_value=first_rewards.get((0, initial_idx), 0.0),
                estimated_plan_value=plan_value,
                estimated_today_value=today_value,
                planned_charge_kwh=planned_charge_kwh,
                planned_discharge_kwh=planned_discharge_kwh,
                planned_grid_charge_kwh=plan_totals["planned_grid_charge_kwh"],
                planned_solar_charge_kwh=plan_totals["planned_solar_charge_kwh"],
                planned_self_consumption_kwh=plan_totals[
                    "planned_self_consumption_kwh"
                ],
                planned_grid_export_kwh=plan_totals["planned_grid_export_kwh"],
                forecast_load_kwh=plan_totals["forecast_load_kwh"],
                forecast_solar_kwh=plan_totals["forecast_solar_kwh"],
                attributes={"dispatch_plan": plan_slots},
            )

        target_power = abs(delta) * discharge_eff / duration_h * 1000
        reason = "current slot is economical for battery discharge"
        if periodic_full_charge_due:
            reason = "periodic full charge due; export remains economical before recharge"
        return Decision(
            action="discharge",
            reason=reason,
            target_power_w=min(
                target_power,
                self._slot_power_limit(
                    future_slots,
                    "discharge",
                    usable_capacity_kwh,
                ),
            ),
            estimated_first_slot_value=first_rewards.get((0, initial_idx), 0.0),
            estimated_plan_value=plan_value,
            estimated_today_value=today_value,
            planned_charge_kwh=planned_charge_kwh,
            planned_discharge_kwh=planned_discharge_kwh,
            planned_grid_charge_kwh=plan_totals["planned_grid_charge_kwh"],
            planned_solar_charge_kwh=plan_totals["planned_solar_charge_kwh"],
            planned_self_consumption_kwh=plan_totals["planned_self_consumption_kwh"],
            planned_grid_export_kwh=plan_totals["planned_grid_export_kwh"],
            forecast_load_kwh=plan_totals["forecast_load_kwh"],
            forecast_solar_kwh=plan_totals["forecast_solar_kwh"],
            attributes={"dispatch_plan": plan_slots},
        )

    def _build_plan_summary(
        self,
        future_slots: list[PriceSlot],
        policy: dict[tuple[int, int], int],
        levels: list[float],
        initial_idx: int,
        step_kwh: float,
        charge_eff: float,
        discharge_eff: float,
        buy_adder: float,
        sell_adder: float,
        required_margin: float,
        now: datetime,
        load_forecast_w: list[float],
        solar_forecast_w: list[float],
    ) -> tuple[list[dict[str, Any]], dict[str, float]]:
        """Reconstruct the selected dispatch path for dashboard diagnostics."""
        local_today = dt_util.now().date()
        idx = initial_idx
        plan_slots: list[dict[str, Any]] = []
        totals = {
            "planned_charge_kwh": 0.0,
            "planned_discharge_kwh": 0.0,
            "planned_grid_charge_kwh": 0.0,
            "planned_solar_charge_kwh": 0.0,
            "planned_self_consumption_kwh": 0.0,
            "planned_grid_export_kwh": 0.0,
            "forecast_load_kwh": 0.0,
            "forecast_solar_kwh": 0.0,
            "estimated_today_value": 0.0,
        }

        for slot_index, slot in enumerate(future_slots):
            next_idx = policy.get((slot_index, idx), idx)
            delta = levels[next_idx] - levels[idx]
            duration_h = self._slot_duration_hours(
                slot, now if slot_index == 0 else None
            )
            action = "idle"
            target_power_w = 0.0
            grid_energy_kwh = 0.0
            value = 0.0
            grid_charge_kwh = 0.0
            solar_charge_kwh = 0.0
            self_consumption_kwh = 0.0
            battery_export_kwh = 0.0
            buy_price = slot.price + buy_adder
            sell_price = slot.price - sell_adder
            load_kwh = self._power_to_energy_kwh(
                load_forecast_w,
                slot_index,
                duration_h,
            )
            solar_kwh = self._power_to_energy_kwh(
                solar_forecast_w,
                slot_index,
                duration_h,
            )
            baseline_net_kwh = load_kwh - solar_kwh
            net_grid_kwh = baseline_net_kwh
            baseline_cost = self._net_grid_cost(
                baseline_net_kwh,
                buy_price,
                sell_price,
            )
            totals["forecast_load_kwh"] += load_kwh
            totals["forecast_solar_kwh"] += solar_kwh

            if abs(delta) >= step_kwh / 2 and duration_h > 0:
                if delta > 0:
                    action = "charge"
                    grid_energy_kwh = delta / charge_eff
                    target_power_w = grid_energy_kwh / duration_h * 1000
                    solar_surplus_kwh = max(-baseline_net_kwh, 0.0)
                    solar_charge_kwh = min(grid_energy_kwh, solar_surplus_kwh)
                    grid_charge_kwh = max(grid_energy_kwh - solar_charge_kwh, 0.0)
                    net_grid_kwh = baseline_net_kwh + grid_energy_kwh
                    value = baseline_cost - self._net_grid_cost(
                        net_grid_kwh,
                        buy_price,
                        sell_price,
                    )
                    totals["planned_charge_kwh"] += grid_energy_kwh
                    totals["planned_grid_charge_kwh"] += grid_charge_kwh
                    totals["planned_solar_charge_kwh"] += solar_charge_kwh
                else:
                    action = "discharge"
                    grid_energy_kwh = abs(delta) * discharge_eff
                    target_power_w = grid_energy_kwh / duration_h * 1000
                    home_import_kwh = max(baseline_net_kwh, 0.0)
                    self_consumption_kwh = min(grid_energy_kwh, home_import_kwh)
                    battery_export_kwh = max(
                        grid_energy_kwh - self_consumption_kwh,
                        0.0,
                    )
                    net_grid_kwh = baseline_net_kwh - grid_energy_kwh
                    value = baseline_cost - self._net_grid_cost(
                        net_grid_kwh,
                        buy_price,
                        sell_price,
                    )
                    value -= grid_energy_kwh * required_margin
                    totals["planned_discharge_kwh"] += grid_energy_kwh
                    totals["planned_self_consumption_kwh"] += self_consumption_kwh
                    totals["planned_grid_export_kwh"] += battery_export_kwh

            if dt_util.as_local(slot.start).date() == local_today:
                totals["estimated_today_value"] += value

            net_grid_without_w = (
                baseline_net_kwh / duration_h * 1000 if duration_h > 0 else 0.0
            )
            net_grid_with_w = (
                net_grid_kwh / duration_h * 1000 if duration_h > 0 else 0.0
            )

            plan_slots.append(
                {
                    **self._serialize_price_slot(slot),
                    "action": action,
                    "target_power_w": round(target_power_w, 1),
                    "energy_kwh": round(grid_energy_kwh, 3),
                    "value": round(value, 4),
                    "load_power_w": round(
                        load_forecast_w[slot_index]
                        if slot_index < len(load_forecast_w)
                        else 0.0,
                        1,
                    ),
                    "solar_power_w": round(
                        solar_forecast_w[slot_index]
                        if slot_index < len(solar_forecast_w)
                        else 0.0,
                        1,
                    ),
                    "net_grid_without_battery_w": round(net_grid_without_w, 1),
                    "net_grid_with_battery_w": round(net_grid_with_w, 1),
                    "baseline_grid_import_kwh": round(max(baseline_net_kwh, 0.0), 3),
                    "baseline_grid_export_kwh": round(max(-baseline_net_kwh, 0.0), 3),
                    "grid_import_kwh": round(max(net_grid_kwh, 0.0), 3),
                    "grid_export_kwh": round(max(-net_grid_kwh, 0.0), 3),
                    "grid_charge_kwh": round(grid_charge_kwh, 3),
                    "solar_charge_kwh": round(solar_charge_kwh, 3),
                    "self_consumption_kwh": round(self_consumption_kwh, 3),
                    "battery_export_kwh": round(battery_export_kwh, 3),
                }
            )
            idx = next_idx

        return plan_slots, totals

    @staticmethod
    def _power_to_energy_kwh(
        power_values_w: list[float],
        index: int,
        duration_h: float,
    ) -> float:
        """Convert one forecast power point into slot energy."""
        if index >= len(power_values_w) or duration_h <= 0:
            return 0.0
        return max(power_values_w[index], 0.0) * duration_h / 1000

    @staticmethod
    def _net_grid_cost(net_grid_kwh: float, buy_price: float, sell_price: float) -> float:
        """Return import cost minus export revenue for a net grid energy value."""
        if net_grid_kwh >= 0:
            return net_grid_kwh * buy_price
        return net_grid_kwh * sell_price

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

    def _shape_discharge_decision(
        self,
        decision: Decision,
        future_slots: list[PriceSlot],
        current_energy: float,
        min_energy: float,
        now: datetime,
    ) -> None:
        """Spread export over nearby high-price slots when the economic loss is small."""
        mode = str(self._option(CONF_DISCHARGE_POWER_MODE))
        decision.attributes["target_power_before_shaping_w"] = round(
            decision.target_power_w, 1
        )

        if mode != "spread" or decision.target_power_w <= 0 or not future_slots:
            decision.attributes["discharge_spread_reason"] = "disabled"
            return

        tolerance_pct = max(
            float(self._option(CONF_DISCHARGE_SPREAD_PRICE_TOLERANCE)), 0.0
        )
        max_window_h = max(float(self._option(CONF_DISCHARGE_SPREAD_MAX_HOURS)), 0.25)
        charge_eff = math.sqrt(float(self._option(CONF_ROUND_TRIP_EFFICIENCY)))
        discharge_eff = charge_eff
        sell_adder = float(self._option(CONF_SELL_COST_ADDER))
        required_margin = float(self._option(CONF_CYCLE_COST)) + float(
            self._option(CONF_MIN_PROFIT_MARGIN)
        )

        current_sell_price = future_slots[0].price - sell_adder
        if current_sell_price <= required_margin:
            decision.attributes["discharge_spread_reason"] = (
                "current slot below required discharge margin"
            )
            return

        price_floor = current_sell_price - abs(current_sell_price) * tolerance_pct / 100
        price_floor = max(price_floor, required_margin)
        eligible_slots: list[PriceSlot] = []
        eligible_duration_h = 0.0
        for slot_index, slot in enumerate(future_slots):
            duration_h = self._slot_duration_hours(
                slot, now if slot_index == 0 else None
            )
            if duration_h <= 0:
                continue
            sell_price = slot.price - sell_adder
            if sell_price + 1e-9 < price_floor:
                break
            if eligible_duration_h >= max_window_h:
                break

            remaining_h = max(max_window_h - eligible_duration_h, 0.0)
            if remaining_h <= 0:
                break
            eligible_slots.append(slot)
            eligible_duration_h += min(duration_h, remaining_h)

        if len(eligible_slots) <= 1 or eligible_duration_h <= 0:
            decision.attributes["discharge_spread_reason"] = (
                "no adjacent high-price slots within tolerance"
            )
            return

        planned_window_kwh = self._planned_discharge_for_slots(
            decision.attributes.get("dispatch_plan", []),
            eligible_slots,
        )
        if planned_window_kwh <= 0:
            planned_window_kwh = (
                decision.target_power_w
                * self._slot_duration_hours(future_slots[0], now)
                / 1000
            )

        available_ac_kwh = max(current_energy - min_energy, 0.0) * discharge_eff
        energy_to_spread_kwh = min(planned_window_kwh, available_ac_kwh)
        if energy_to_spread_kwh <= 0:
            decision.attributes["discharge_spread_reason"] = (
                "no discharge energy available above reserve"
            )
            return

        spread_power_w = energy_to_spread_kwh / eligible_duration_h * 1000
        shaped_power_w = min(decision.target_power_w, spread_power_w)
        if decision.target_power_w - shaped_power_w < 100:
            decision.attributes["discharge_spread_reason"] = (
                "planned energy already uses the selected high-price window"
            )
            return

        decision.target_power_w = shaped_power_w
        decision.target_power_percent = self._power_to_percent("discharge", shaped_power_w)
        decision.reason = (
            f"{decision.reason}; discharge spread over "
            f"{eligible_duration_h:.2f} h high-price window"
        )
        decision.attributes.update(
            {
                "discharge_spread_reason": "applied",
                "discharge_spread_price_floor": round(price_floor, 5),
                "discharge_spread_slots": len(eligible_slots),
                "discharge_spread_window_hours": round(eligible_duration_h, 3),
                "discharge_spread_energy_kwh": round(energy_to_spread_kwh, 3),
            }
        )

    def _planned_discharge_for_slots(
        self,
        dispatch_plan: Any,
        slots: list[PriceSlot],
    ) -> float:
        """Return planned discharge energy for serialized slots."""
        if not isinstance(dispatch_plan, list):
            return 0.0

        slot_starts = {self._serialize_price_slot(slot)["start"] for slot in slots}
        planned = 0.0
        for row in dispatch_plan:
            if not isinstance(row, dict):
                continue
            if row.get("action") != "discharge" or row.get("start") not in slot_starts:
                continue
            try:
                planned += float(row.get("energy_kwh") or 0.0)
            except (TypeError, ValueError):
                continue
        return max(planned, 0.0)

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
        return int(round(slots[0].duration_hours * 60))

    def _serialize_price_slot(self, slot: PriceSlot) -> dict[str, Any]:
        """Serialize a price slot using local wall-clock timestamps."""
        return {
            "start": dt_util.as_local(slot.start).isoformat(),
            "end": dt_util.as_local(slot.end).isoformat(),
            "price": round(slot.price, 5),
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
                sum(price_slot.price for price_slot in window) / len(window)
                if window
                else slot.price
            )
            next_price = slots[index + 1].price if index + 1 < len(slots) else slot.price
            delta_next = next_price - slot.price
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
            await self._set_soc_limits(decision)
            if decision.action in {"charge", "discharge"}:
                await self._set_ems_mode(str(self._option(CONF_USER_EMS_MODE)))
                await self._set_power_ref(decision.target_power_percent)
            else:
                await self._set_power_ref(0.0)
                await self._set_ems_mode(str(self._option(CONF_IDLE_EMS_MODE)))
            decision.applied = True
        except Exception as err:  # pylint: disable=broad-except
            LOGGER.exception("Failed to apply H3X arbitrage decision")
            decision.applied = False
            decision.apply_error = str(err)

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
