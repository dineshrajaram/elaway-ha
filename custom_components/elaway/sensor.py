"""Elaway charger status sensor (granular EVSE status passthrough)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, STATUS_UNAVAILABLE
from .coordinator import ElawayCoordinator
from .entity import device_info


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: ElawayCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ElawayStatusSensor(coordinator, entry)])


class ElawayStatusSensor(CoordinatorEntity[ElawayCoordinator], SensorEntity):
    """Charger status — the raw EVSE status (available/preparing/charging/finishing/...)."""

    _attr_has_entity_name = True
    _attr_name = "Charger status"
    _attr_icon = "mdi:ev-plug-type2"

    def __init__(self, coordinator: ElawayCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_status"
        self._attr_device_info = device_info(entry)

    @property
    def native_value(self) -> str | None:
        return (self.coordinator.data or {}).get("evse_status") or STATUS_UNAVAILABLE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        return {
            "connector_status": data.get("connector_status"),
            "connected": data.get("is_connected"),
            "ready_to_start": data.get("is_ready"),
            "charging": data.get("is_charging"),
            "suspended": data.get("is_suspended"),
            "rebooting": data.get("is_rebooting"),
        }
