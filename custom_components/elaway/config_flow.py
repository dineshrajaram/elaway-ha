"""Config flow for the Elaway integration."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    ElawayApi,
    ElawayApiError,
    ElawayAuthError,
    parse_charge_points_list,
)
from .const import (
    CONF_CHARGE_POINT_ID,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_EVSE_ID,
    CONF_NAME,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    DEFAULT_BASE_URL,
    DEFAULT_CLIENT_ID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)


def _schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    d = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_REFRESH_TOKEN, default=d.get(CONF_REFRESH_TOKEN, "")): str,
            vol.Optional(
                CONF_CLIENT_ID, default=d.get(CONF_CLIENT_ID, DEFAULT_CLIENT_ID)
            ): str,
            vol.Required(
                CONF_CLIENT_SECRET,
                default=d.get(CONF_CLIENT_SECRET, ""),
            ): str,
            vol.Optional(
                CONF_SCAN_INTERVAL,
                default=d.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): int,
        }
    )


class ElawayConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Elaway config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._creds: dict[str, Any] = {}
        self._chargers: list[dict[str, Any]] = []

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> "ElawayOptionsFlow":
        return ElawayOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            session = async_get_clientsession(self.hass)
            api = ElawayApi(
                session,
                base_url=DEFAULT_BASE_URL,
                client_id=user_input[CONF_CLIENT_ID],
                client_secret=user_input[CONF_CLIENT_SECRET],
                evse_id=0,
                charge_point_id="",
                refresh_token=user_input[CONF_REFRESH_TOKEN],
            )
            try:
                # Validate the token (this rotates it) then discover chargers.
                await api.async_refresh()
                charge_points = await api.async_list_charge_points()
            except ElawayAuthError:
                errors["base"] = "invalid_auth"
            except ElawayApiError:
                errors["base"] = "cannot_connect"
            else:
                chargers = [
                    c
                    for c in parse_charge_points_list(charge_points)
                    if c["evse_id"] is not None
                ]
                if not chargers:
                    errors["base"] = "no_charge_point"
                else:
                    self._creds = {**user_input, **api.tokens}
                    self._chargers = chargers
                    if len(chargers) == 1:
                        return await self._create_entry(chargers[0])
                    return await self.async_step_select()

        return self.async_show_form(
            step_id="user", data_schema=_schema(user_input), errors=errors
        )

    async def async_step_select(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            chosen = next(
                c
                for c in self._chargers
                if c["id"] == user_input[CONF_CHARGE_POINT_ID]
            )
            return await self._create_entry(chosen)

        options = {c["id"]: c["name"] for c in self._chargers}
        return self.async_show_form(
            step_id="select",
            data_schema=vol.Schema({vol.Required(CONF_CHARGE_POINT_ID): vol.In(options)}),
        )

    async def _create_entry(self, charger: dict[str, Any]) -> ConfigFlowResult:
        await self.async_set_unique_id(charger["id"])
        self._abort_if_unique_id_configured()
        data = {
            **self._creds,
            CONF_CHARGE_POINT_ID: charger["id"],
            CONF_EVSE_ID: charger["evse_id"],
            CONF_NAME: charger["name"],
        }
        return self.async_create_entry(title=charger["name"], data=data)


class ElawayOptionsFlow(OptionsFlow):
    """Let the user change the poll interval without re-adding the integration."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self._entry.options.get(
            CONF_SCAN_INTERVAL,
            self._entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {vol.Optional(CONF_SCAN_INTERVAL, default=current): int}
            ),
        )
