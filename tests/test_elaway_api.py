"""Stdlib-only unit tests for the Elaway API core (no aiohttp / HA needed).

Run:  python3 -m unittest discover -s tests -v
"""
import asyncio
import importlib.util
import os
import sys
import time
import unittest

# Load const.py and api.py directly from the package dir, bypassing the HA
# package __init__ (which imports homeassistant).
PKG = os.path.join(os.path.dirname(__file__), "..", "custom_components", "elaway")
sys.path.insert(0, os.path.abspath(PKG))
import const  # noqa: E402
import api  # noqa: E402


class FakeResp:
    def __init__(self, status, payload, delay=0.0):
        self.status = status
        self._payload = payload
        self._delay = delay

    async def __aenter__(self):
        if self._delay:
            await asyncio.sleep(self._delay)
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self):
        return self._payload


class FakeSession:
    """Programmable async session double."""

    def __init__(self, oauth_delay=0.0):
        self.oauth_calls = 0
        self.request_calls = 0
        self.oauth_delay = oauth_delay
        self._rot = 0
        # queue of (status, payload) for request(); default 200/{} if empty
        self.request_queue: list[tuple[int, dict]] = []

    def post(self, url, json=None):
        # only /oauth/token uses post in this client
        self.oauth_calls += 1
        self._rot += 1
        return FakeResp(
            200,
            {
                "access_token": f"ACCESS_{self._rot}",
                "expires_in": 2592000,
                "refresh_token": f"REFRESH_{self._rot}",
            },
            delay=self.oauth_delay,
        )

    def request(self, method, url, headers=None, json=None):
        self.request_calls += 1
        if self.request_queue:
            status, payload = self.request_queue.pop(0)
        else:
            status, payload = 200, {"ok": True}
        return FakeResp(status, payload)


def make_api(session, **kw):
    defaults = dict(
        base_url="https://x/api",
        client_id="1",
        client_secret="secret",
        evse_id=30597,
        charge_point_id="31620",
        refresh_token="INIT_REFRESH",
        access_token=None,
        token_expiry=0.0,
    )
    defaults.update(kw)
    return api.ElawayApi(session, **defaults)


def run(coro):
    return asyncio.run(coro)


class TestRefresh(unittest.TestCase):
    def test_refresh_parses_rotates_and_persists(self):
        s = FakeSession()
        captured = {}

        async def cb(d):
            captured.update(d)

        a = make_api(s, token_update_cb=cb)
        run(a.async_refresh())
        self.assertEqual(s.oauth_calls, 1)
        self.assertEqual(captured["access_token"], "ACCESS_1")
        self.assertEqual(captured["refresh_token"], "REFRESH_1")
        self.assertGreater(captured["token_expiry"], time.time())

    def test_no_refresh_when_token_valid(self):
        s = FakeSession()
        a = make_api(
            s, access_token="GOOD", token_expiry=time.time() + 10 * 86400
        )
        run(a.async_get_ongoing())
        self.assertEqual(s.oauth_calls, 0)  # reactive: did not refresh
        self.assertEqual(s.request_calls, 1)

    def test_refresh_when_expired(self):
        s = FakeSession()
        a = make_api(s, access_token="OLD", token_expiry=time.time() - 10)
        run(a.async_get_ongoing())
        self.assertEqual(s.oauth_calls, 1)  # expired -> refreshed first

    def test_401_refreshes_and_retries(self):
        s = FakeSession()
        # first request 401, retry 200
        s.request_queue = [(401, {}), (200, {"data": []})]
        a = make_api(s, access_token="GOOD", token_expiry=time.time() + 10 * 86400)
        run(a.async_get_ongoing())
        self.assertEqual(s.oauth_calls, 1)  # refreshed once on 401
        self.assertEqual(s.request_calls, 2)  # retried once

    def test_persistent_401_raises_auth(self):
        s = FakeSession()
        s.request_queue = [(401, {}), (401, {})]
        a = make_api(s, access_token="GOOD", token_expiry=time.time() + 10 * 86400)
        with self.assertRaises(api.ElawayAuthError):
            run(a.async_get_ongoing())

    def test_token_refresh_rejected_raises_auth(self):
        s = FakeSession()

        def bad_post(url, json=None):
            s.oauth_calls += 1
            return FakeResp(401, {"message": "Unauthenticated"})

        s.post = bad_post
        a = make_api(s, access_token=None, token_expiry=0)
        with self.assertRaises(api.ElawayAuthError):
            run(a.async_get_ongoing())

    def test_concurrent_refresh_one_rotation(self):
        s = FakeSession(oauth_delay=0.05)  # widen the race window
        a = make_api(s, access_token="OLD", token_expiry=time.time() - 10)

        async def hammer():
            await asyncio.gather(*[a._ensure_token() for _ in range(8)])

        run(hammer())
        self.assertEqual(s.oauth_calls, 1)  # lock + double-check collapse to one


class TestParseChargerState(unittest.TestCase):
    # Real capture (2026-06-10): car connected, session finished, charger rebooting.
    FINISHING = {
        "data": {
            "id": "31620",
            "status": "available",  # top-level is ALWAYS available — must be ignored
            "is_rebooting": True,
            "evses": [
                {
                    "id": "30597",
                    "status": "finishing",
                    "connectors": [{"name": "Type 2", "status": "active"}],
                }
            ],
        }
    }

    def test_finishing_is_connected_and_ready(self):
        st = api.parse_charger_state(self.FINISHING, [])
        self.assertEqual(st["evse_status"], "finishing")
        self.assertTrue(st["is_connected"])
        self.assertFalse(st["is_charging"])
        self.assertTrue(st["is_ready"])
        self.assertTrue(st["is_rebooting"])
        self.assertEqual(st["connector_status"], "active")

    def test_top_level_available_ignored(self):
        # Even though data.status == "available", the EVSE says finishing.
        st = api.parse_charger_state(self.FINISHING, [])
        self.assertNotEqual(st["evse_status"], "available")

    def test_ongoing_means_charging(self):
        st = api.parse_charger_state(self.FINISHING, [{"id": "1"}])
        self.assertTrue(st["is_charging"])
        self.assertFalse(st["is_ready"])

    def test_evse_charging(self):
        cp = {"data": {"evses": [{"status": "charging", "connectors": []}]}}
        st = api.parse_charger_state(cp, [])
        self.assertTrue(st["is_charging"])

    def test_preparing_is_ready(self):
        cp = {"data": {"evses": [{"status": "preparing", "connectors": []}]}}
        st = api.parse_charger_state(cp, [])
        self.assertTrue(st["is_ready"])
        self.assertEqual(st["evse_status"], "preparing")

    def test_available_no_car_not_ready(self):
        cp = {"data": {"evses": [{"status": "available", "connectors": []}]}}
        st = api.parse_charger_state(cp, [])
        self.assertFalse(st["is_connected"])
        self.assertFalse(st["is_ready"])
        self.assertEqual(st["evse_status"], "available")

    def test_suspended_connected_but_not_ready(self):
        # Car fully charged -> suspended. Connected, but starting returns 406.
        cp = {"data": {"evses": [{"status": "suspended", "connectors": [{"status": "active"}]}]}}
        st = api.parse_charger_state(cp, [])
        self.assertTrue(st["is_connected"])
        self.assertTrue(st["is_suspended"])
        self.assertFalse(st["is_ready"])
        self.assertFalse(st["is_charging"])
        self.assertEqual(st["evse_status"], "suspended")

    def test_missing_evses_unavailable(self):
        st = api.parse_charger_state({"data": {}}, [])
        self.assertEqual(st["evse_status"], const.STATUS_UNAVAILABLE)
        self.assertFalse(st["is_connected"])

    def test_none_safe(self):
        st = api.parse_charger_state(None, None)
        self.assertEqual(st["evse_status"], const.STATUS_UNAVAILABLE)


class TestChargePointMeta(unittest.TestCase):
    def test_extracts_name_and_evse(self):
        cp = {"data": {"name": "ZCS012577-162", "evses": [{"id": "30597"}]}}
        meta = api.parse_charge_point_meta(cp)
        self.assertEqual(meta["name"], "ZCS012577-162")
        self.assertEqual(meta["evse_id"], 30597)

    def test_missing_evse_returns_none(self):
        meta = api.parse_charge_point_meta({"data": {"name": "X", "evses": []}})
        self.assertIsNone(meta["evse_id"])

    def test_defaults_when_empty(self):
        meta = api.parse_charge_point_meta({})
        self.assertEqual(meta["name"], "Elaway charger")
        self.assertIsNone(meta["evse_id"])


class TestChargePointsList(unittest.TestCase):
    def test_maps_list_items(self):
        items = [
            {"id": 31620, "name": "ZCS012577-162", "evses": [{"id": "30597"}]},
            {"id": 9, "name": "Other", "evses": [{"id": 11}]},
        ]
        out = api.parse_charge_points_list(items)
        self.assertEqual(out[0], {"id": "31620", "name": "ZCS012577-162", "evse_id": 30597})
        self.assertEqual(out[1]["evse_id"], 11)

    def test_no_evse_yields_none(self):
        out = api.parse_charge_points_list([{"id": 5, "name": "X", "evses": []}])
        self.assertIsNone(out[0]["evse_id"])

    def test_empty(self):
        self.assertEqual(api.parse_charge_points_list(None), [])


if __name__ == "__main__":
    unittest.main()
