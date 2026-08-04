"""Pylontech H3X energy arbitrage integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_GRID_IMPORT_AVERAGE_POWER_ENTITY,
    CONF_GRID_IMPORT_POWER_ENTITY,
    CONF_RESOLUTION,
    CONF_SHELLY_PHASE_A_POWER_ENTITY,
    CONF_SHELLY_PHASE_B_POWER_ENTITY,
    CONF_SHELLY_PHASE_C_POWER_ENTITY,
    CONF_SHELLY_TOTAL_POWER_ENTITY,
    CONF_SOLAR_POWER_ENTITY,
    DEFAULT_RESOLUTION,
    PLATFORMS,
    RESOLUTIONS,
)
from .coordinator import H3XPredictiveDispatchCoordinator
from .meter import (
    autodetect_shelly_total_active_power,
    autodetect_sma_pv_power,
    entity_has_numeric_state,
)

CONFIG_ENTRY_VERSION = 5


async def async_migrate_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> bool:
    """Persist resolution and migrate grid monitoring to configured Shelly data."""
    if entry.version > CONFIG_ENTRY_VERSION:
        return False
    if entry.version == CONFIG_ENTRY_VERSION:
        return True

    data = dict(entry.data)
    options = dict(entry.options)
    raw_resolution = options.get(
        CONF_RESOLUTION,
        data.get(CONF_RESOLUTION, DEFAULT_RESOLUTION),
    )
    try:
        resolution = int(raw_resolution)
    except (TypeError, ValueError):
        resolution = DEFAULT_RESOLUTION
    if resolution not in RESOLUTIONS:
        resolution = DEFAULT_RESOLUTION

    data[CONF_RESOLUTION] = resolution
    if CONF_RESOLUTION in options:
        options[CONF_RESOLUTION] = resolution
    data.pop(CONF_GRID_IMPORT_AVERAGE_POWER_ENTITY, None)
    options.pop(CONF_GRID_IMPORT_AVERAGE_POWER_ENTITY, None)

    configured_grid = str(
        options.get(
            CONF_GRID_IMPORT_POWER_ENTITY,
            data.get(CONF_GRID_IMPORT_POWER_ENTITY, ""),
        )
    ).strip()
    shelly_total = str(
        options.get(
            CONF_SHELLY_TOTAL_POWER_ENTITY,
            data.get(CONF_SHELLY_TOTAL_POWER_ENTITY, ""),
        )
    ).strip()
    shelly_phases = [
        str(options.get(key, data.get(key, ""))).strip()
        for key in (
            CONF_SHELLY_PHASE_A_POWER_ENTITY,
            CONF_SHELLY_PHASE_B_POWER_ENTITY,
            CONF_SHELLY_PHASE_C_POWER_ENTITY,
        )
    ]
    shelly_available = (
        bool(shelly_total and hass.states.get(shelly_total))
        or bool(
            all(shelly_phases)
            and all(hass.states.get(entity_id) for entity_id in shelly_phases)
        )
    )
    if (
        configured_grid
        and not entity_has_numeric_state(hass, configured_grid)
        and shelly_available
    ):
        data.pop(CONF_GRID_IMPORT_POWER_ENTITY, None)
        options.pop(CONF_GRID_IMPORT_POWER_ENTITY, None)

    detected_grid = autodetect_shelly_total_active_power(hass)
    if detected_grid and not entity_has_numeric_state(hass, configured_grid):
        _replace_setting(
            data,
            options,
            CONF_GRID_IMPORT_POWER_ENTITY,
            detected_grid,
        )

    configured_solar = str(
        options.get(
            CONF_SOLAR_POWER_ENTITY,
            data.get(CONF_SOLAR_POWER_ENTITY, ""),
        )
    ).strip()
    detected_solar = autodetect_sma_pv_power(hass)
    if detected_solar and not entity_has_numeric_state(hass, configured_solar):
        _replace_setting(
            data,
            options,
            CONF_SOLAR_POWER_ENTITY,
            detected_solar,
        )
    hass.config_entries.async_update_entry(
        entry,
        data=data,
        options=options,
        version=CONFIG_ENTRY_VERSION,
    )
    return True


def _replace_setting(
    data: dict[str, object],
    options: dict[str, object],
    key: str,
    value: object,
) -> None:
    """Replace an entry setting without changing data/options precedence."""
    if key in options:
        options[key] = value
    else:
        data[key] = value


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> bool:
    """Set up the integration from a config entry."""
    entry.async_on_unload(entry.add_update_listener(async_options_updated))
    coordinator = H3XPredictiveDispatchCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    coordinator = getattr(entry, "runtime_data", None)
    if unload_ok and coordinator:
        await coordinator.async_shutdown()
    return unload_ok


async def async_options_updated(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Handle options updated from the options flow or control entities."""
    coordinator = getattr(entry, "runtime_data", None)
    if coordinator:
        await coordinator.async_options_updated()
