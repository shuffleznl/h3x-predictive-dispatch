"""Switch controls for Pylontech H3X energy arbitrage."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_DUTCH_TARIFF_ENABLED, CONF_PERIODIC_FULL_CHARGE_ENABLED, DOMAIN
from .coordinator import H3XArbitrageCoordinator


@dataclass(frozen=True, kw_only=True)
class H3XArbitrageSwitchDescription(SwitchEntityDescription):
    """Describe an arbitrage switch control."""

    option_key: str


SWITCHES: tuple[H3XArbitrageSwitchDescription, ...] = (
    H3XArbitrageSwitchDescription(
        key="dutch_tariff_enabled",
        translation_key="dutch_tariff_enabled",
        name="Dutch retail tariff",
        icon="mdi:currency-eur",
        option_key=CONF_DUTCH_TARIFF_ENABLED,
    ),
    H3XArbitrageSwitchDescription(
        key="periodic_full_charge_enabled",
        translation_key="periodic_full_charge_enabled",
        name="Periodic full charge",
        icon="mdi:battery-sync",
        option_key=CONF_PERIODIC_FULL_CHARGE_ENABLED,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switch controls from a config entry."""
    coordinator: H3XArbitrageCoordinator = entry.runtime_data
    async_add_entities(
        H3XArbitrageSwitch(coordinator, entry, description)
        for description in SWITCHES
    )


class H3XArbitrageSwitch(CoordinatorEntity[H3XArbitrageCoordinator], SwitchEntity):
    """A runtime switch control for the arbitrage optimizer."""

    entity_description: H3XArbitrageSwitchDescription
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: H3XArbitrageCoordinator,
        entry: ConfigEntry,
        description: H3XArbitrageSwitchDescription,
    ) -> None:
        """Initialize the switch control."""
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
    def is_on(self) -> bool:
        """Return whether the option is enabled."""
        return bool(self.coordinator._option(self.entity_description.option_key))

    async def async_turn_on(self, **kwargs: object) -> None:
        """Enable the option."""
        await self.coordinator.async_set_option(self.entity_description.option_key, True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: object) -> None:
        """Disable the option."""
        await self.coordinator.async_set_option(self.entity_description.option_key, False)
        self.async_write_ha_state()
