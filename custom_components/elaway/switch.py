"""Elaway charging switch."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import ElawayApiError
from .const import DOMAIN, STATUS_UNAVAILABLE
from .coordinator import ElawayCoordinator
from .entity import device_info

_LOGGER = logging.getLogger(__name__)

# After a start/stop the charger takes a few seconds to transition; re-poll at
# these offsets so the switch catches up quickly regardless of the scan interval.
_FOLLOWUP_DELAYS = (5, 15)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: ElawayCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ElawayChargingSwitch(coordinator, entry)])


class ElawayChargingSwitch(CoordinatorEntity[ElawayCoordinator], SwitchEntity):
    """Start/stop charging.

    Confirm-by-poll: state derives from coordinator data, never an unconfirmed
    target. Start is allowed unless already charging (the API rejects a start
    when no vehicle is connected); stop only acts while charging. Usage is
    primarily start-at-night; stop usually happens by unplugging.
    """

    _attr_has_entity_name = True
    _attr_name = "Charging"
    _attr_icon = "mdi:ev-station"

    def __init__(self, coordinator: ElawayCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_charging"
        self._attr_device_info = device_info(entry)

    @property
    def _data(self) -> dict[str, Any]:
        return self.coordinator.data or {}

    @property
    def is_on(self) -> bool:
        return bool(self._data.get("is_charging"))

    @property
    def available(self) -> bool:
        return (
            super().available
            and self._data.get("evse_status") != STATUS_UNAVAILABLE
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        session = self._data.get("session") or {}
        return {
            "evse_status": self._data.get("evse_status"),
            "ready_to_start": self._data.get("is_ready"),
            "session_id": session.get("id"),
            "started_at": session.get("startedAt"),
        }

    def _schedule_followups(self) -> None:
        """Re-poll a couple of times after an action to catch the transition."""
        for delay in _FOLLOWUP_DELAYS:
            async_call_later(self.hass, delay, self._delayed_refresh)

    async def _delayed_refresh(self, _now=None) -> None:
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        # Check live state to avoid a duplicate start when our cached "off" is
        # stale (the charger lags a few seconds behind a start).
        ongoing = await self.coordinator.api.async_get_ongoing()
        if ongoing:
            await self.coordinator.async_request_refresh()
            return
        if self._data.get("is_suspended"):
            raise HomeAssistantError(
                "Charger is suspended — the car may be fully charged. Nothing to start."
            )
        if not self._data.get("is_connected"):
            raise HomeAssistantError("No vehicle connected to the charger.")
        try:
            await self.coordinator.api.async_start()
        except ElawayApiError as err:
            raise HomeAssistantError(f"Could not start charging: {err}") from err
        await self.coordinator.async_request_refresh()
        self._schedule_followups()

    async def async_turn_off(self, **kwargs: Any) -> None:
        ongoing = await self.coordinator.api.async_get_ongoing()
        if not ongoing:
            # Nothing to stop (e.g. already unplugged); just reconcile state.
            await self.coordinator.async_request_refresh()
            return
        try:
            await self.coordinator.api.async_stop(ongoing[0]["id"])
        except ElawayApiError as err:
            raise HomeAssistantError(f"Could not stop charging: {err}") from err
        await self.coordinator.async_request_refresh()
        self._schedule_followups()
