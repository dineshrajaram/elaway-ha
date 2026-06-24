"""Elaway manual refresh button."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ElawayCoordinator
from .entity import device_info


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: ElawayCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ElawayRefreshButton(coordinator, entry)])


class ElawayRefreshButton(CoordinatorEntity[ElawayCoordinator], ButtonEntity):
    """Force an immediate poll of charger status + ongoing session."""

    _attr_has_entity_name = True
    _attr_name = "Refresh"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: ElawayCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_refresh"
        self._attr_device_info = device_info(entry)

    async def async_press(self) -> None:
        await self.coordinator.async_request_refresh()
