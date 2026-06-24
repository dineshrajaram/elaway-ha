"""DataUpdateCoordinator polling Elaway charger status + ongoing session."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ElawayApi, ElawayApiError, ElawayAuthError, parse_charger_state
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class ElawayCoordinator(DataUpdateCoordinator):
    """Fetch charger status and ongoing-session state on an interval."""

    def __init__(self, hass: HomeAssistant, api: ElawayApi, scan_interval: int) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.api = api

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            charge_point = await self.api.async_get_status()
            ongoing = await self.api.async_get_ongoing()
        except ElawayAuthError as err:
            # Dead refresh token -> prompt reconfigure rather than spin.
            raise ConfigEntryAuthFailed(str(err)) from err
        except ElawayApiError as err:
            raise UpdateFailed(str(err)) from err

        state = parse_charger_state(charge_point, ongoing)
        return {
            "charge_point": charge_point,
            "ongoing": ongoing,
            "session": ongoing[0] if ongoing else None,
            **state,
        }
