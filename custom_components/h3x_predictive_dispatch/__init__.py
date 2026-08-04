"""Pylontech H3X energy arbitrage integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_GRID_IMPORT_AVERAGE_POWER_ENTITY,
    CONF_RESOLUTION,
    DEFAULT_RESOLUTION,
    PLATFORMS,
    RESOLUTIONS,
)
from .coordinator import H3XPredictiveDispatchCoordinator

CONFIG_ENTRY_VERSION = 3


async def async_migrate_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> bool:
    """Persist resolution and remove the obsolete external average meter."""
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
    hass.config_entries.async_update_entry(
        entry,
        data=data,
        options=options,
        version=CONFIG_ENTRY_VERSION,
    )
    return True


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
