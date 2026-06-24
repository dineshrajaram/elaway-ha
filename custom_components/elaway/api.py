"""Elaway / AMPECO API client.

Deliberately free of Home Assistant and aiohttp imports so the token logic and
status mapping can be unit-tested with only the standard library (a duck-typed
async session is injected). The relative-vs-absolute import shim below lets the
module load both inside the HA package and standalone in tests.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable

try:  # inside the HA package
    from .const import STATUS_UNAVAILABLE, TOKEN_REFRESH_BUFFER
except ImportError:  # standalone (tests/tooling)
    from const import STATUS_UNAVAILABLE, TOKEN_REFRESH_BUFFER  # type: ignore[no-redef]

_LOGGER = logging.getLogger(__name__)


class ElawayApiError(Exception):
    """A non-auth API failure (transport, 5xx, bad payload)."""


class ElawayAuthError(ElawayApiError):
    """The refresh token is no longer valid; re-bootstrap required."""


def parse_charge_point_meta(charge_point: dict[str, Any] | None) -> dict[str, Any]:
    """Extract display name and first EVSE id from a charge-point response."""
    cp = (charge_point or {}).get("data", charge_point) or {}
    evses = cp.get("evses") or []
    evse_id = evses[0].get("id") if evses else None
    return {
        "name": cp.get("name") or "Elaway charger",
        "evse_id": int(evse_id) if evse_id is not None else None,
    }


def parse_charge_points_list(charge_points: list | None) -> list[dict[str, Any]]:
    """Map a /personal/charge-points list response to {id, name, evse_id} items."""
    out: list[dict[str, Any]] = []
    for cp in charge_points or []:
        evses = cp.get("evses") or []
        evse_id = evses[0].get("id") if evses else None
        out.append(
            {
                "id": str(cp.get("id")),
                "name": cp.get("name") or f"Charger {cp.get('id')}",
                "evse_id": int(evse_id) if evse_id is not None else None,
            }
        )
    return out


def parse_charger_state(charge_point: dict[str, Any] | None, ongoing: list | None) -> dict[str, Any]:
    """Derive charger state from the real API shape.

    Discovered 2026-06-10: the top-level `data.status` is always "available" and
    does NOT reflect connection. The real EVSE state lives in
    `data.evses[0].status` (e.g. available / preparing / charging / finishing /
    suspendedEV) with the cable in `data.evses[0].connectors[0].status`.

    Returns: evse_status (raw, lowercased — the sensor value), connector_status,
    session_id (from ongoing or, when suspended, the charger status),
    is_charging, is_connected, is_ready (connected and not charging), is_rebooting.
    """
    cp = charge_point or {}
    cp = cp.get("data", cp) or {}
    evses = cp.get("evses") or []
    evse = evses[0] if evses else {}
    evse_status = str(evse.get("status") or "").lower()
    connectors = evse.get("connectors") or []
    connector_status = str(connectors[0].get("status") or "").lower() if connectors else ""

    # The session id can come from /session/ongoing (only populated while power
    # is actively flowing) OR from the charger status itself under
    # evses[0].session.id — the latter survives a *suspended* session (car full),
    # which /session/ongoing drops. Prefer ongoing, fall back to status.
    evse_session = evse.get("session") or {}
    session_id = None
    if ongoing:
        session_id = ongoing[0].get("id")
    if session_id is None:
        session_id = evse_session.get("id")
    session_id = str(session_id) if session_id is not None else None

    has_session = session_id is not None
    # Suspended is a charger-reported fact (vehicle connected, charging paused —
    # e.g. car full); independent of whether we resolved a session id.
    is_suspended = evse_status in _SUSPENDED_STATES
    # Charging = actively drawing power, or a live (non-suspended) session exists.
    is_charging = evse_status == "charging" or (has_session and not is_suspended)
    # Connected = a vehicle is engaged but not (necessarily) charging.
    is_connected = is_charging or is_suspended or evse_status in _CONNECTED_STATES
    # Startable = connected, not already charging, and not suspended (car full).
    is_ready = is_connected and not is_charging and not is_suspended

    if not evse_status and not evses:
        evse_status = STATUS_UNAVAILABLE

    return {
        "evse_status": evse_status or STATUS_UNAVAILABLE,
        "connector_status": connector_status,
        "session_id": session_id,
        "is_charging": is_charging,
        "is_connected": is_connected,
        "is_suspended": is_suspended,
        "is_ready": is_ready,
        "is_rebooting": bool(cp.get("is_rebooting")),
    }


# EVSE statuses meaning "connected, charging suspended" (e.g. car fully charged).
_SUSPENDED_STATES = {"suspended", "suspendedev", "suspendedevse"}
# EVSE statuses that mean "a vehicle is connected but not actively charging".
_CONNECTED_STATES = {"preparing", "finishing", "occupied"} | _SUSPENDED_STATES


class ElawayApi:
    """Async client for the Elaway AMPECO app API."""

    def __init__(
        self,
        session: Any,
        *,
        base_url: str,
        client_id: str,
        client_secret: str,
        evse_id: int,
        charge_point_id: str,
        refresh_token: str,
        access_token: str | None = None,
        token_expiry: float = 0.0,
        token_update_cb: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
        self._evse_id = evse_id
        self._charge_point_id = charge_point_id
        self._refresh_token = refresh_token
        self._access_token = access_token
        self._token_expiry = token_expiry
        self._token_update_cb = token_update_cb
        self._lock = asyncio.Lock()

    # --- token lifecycle ---
    def _token_valid(self) -> bool:
        return bool(self._access_token) and time.time() < (
            self._token_expiry - TOKEN_REFRESH_BUFFER
        )

    async def _ensure_token(self) -> None:
        if self._token_valid():
            return
        await self._refresh()

    async def _refresh(self, force: bool = False) -> None:
        async with self._lock:
            # Double-check: another coroutine may have refreshed while we waited.
            if not force and self._token_valid():
                return
            payload = {
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            }
            try:
                async with self._session.post(
                    f"{self._base_url}/oauth/token", json=payload
                ) as resp:
                    status = resp.status
                    data = await _json(resp)
            except ElawayApiError:
                raise
            except Exception as err:  # noqa: BLE001 - transport
                raise ElawayApiError(f"token refresh transport error: {err}") from err

            if status < 200 or status >= 300:
                raise ElawayAuthError(f"token refresh rejected (HTTP {status})")
            access = data.get("access_token")
            if not access:
                raise ElawayApiError("token refresh response missing access_token")
            self._access_token = access
            self._refresh_token = data.get("refresh_token", self._refresh_token)
            self._token_expiry = time.time() + int(data.get("expires_in", 0))
            if self._token_update_cb:
                await self._token_update_cb(
                    {
                        "refresh_token": self._refresh_token,
                        "access_token": self._access_token,
                        "token_expiry": self._token_expiry,
                    }
                )

    async def _request(
        self, method: str, path: str, json: dict | None = None, _retry: bool = True
    ) -> Any:
        await self._ensure_token()
        url = f"{self._base_url}{path}"
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }
        try:
            async with self._session.request(
                method, url, headers=headers, json=json
            ) as resp:
                status = resp.status
                if status == 401 and _retry:
                    await self._refresh(force=True)
                    return await self._request(method, path, json=json, _retry=False)
                if status == 401:
                    raise ElawayAuthError("still 401 after refresh — refresh token dead")
                if status < 200 or status >= 300:
                    raise ElawayApiError(f"HTTP {status} for {method} {path}")
                return await _json(resp)
        except ElawayApiError:
            raise
        except Exception as err:  # noqa: BLE001 - transport
            raise ElawayApiError(f"{method} {path} transport error: {err}") from err

    # --- public API ---
    async def async_refresh(self) -> None:
        await self._refresh(force=True)

    @property
    def tokens(self) -> dict[str, Any]:
        """Current token state, for persisting into the config entry."""
        return {
            "refresh_token": self._refresh_token,
            "access_token": self._access_token,
            "token_expiry": self._token_expiry,
        }

    async def async_get_status(self) -> dict[str, Any]:
        return await self._request(
            "GET", f"/personal/charge-points/{self._charge_point_id}"
        )

    async def async_get_ongoing(self) -> list:
        data = await self._request("GET", "/session/ongoing")
        if isinstance(data, dict):
            return data.get("data") or []
        return data or []

    async def async_list_charge_points(self) -> list:
        data = await self._request("GET", "/personal/charge-points")
        if isinstance(data, dict):
            return data.get("data") or []
        return data or []

    async def async_start(self) -> dict[str, Any]:
        return await self._request("POST", "/session/start", json={"evseId": self._evse_id})

    async def async_stop(self, session_id: str) -> Any:
        return await self._request("POST", f"/session/{session_id}/end")


async def _json(resp: Any) -> Any:
    """Best-effort JSON decode; tolerate empty bodies (e.g. 202)."""
    try:
        return await resp.json()
    except Exception:  # noqa: BLE001
        return {}
