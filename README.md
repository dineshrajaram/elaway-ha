# Elaway (Home Assistant custom integration)

Unofficial Home Assistant integration for [Elaway](https://elaway.io/) EV chargers, via the AMPECO app API. It exposes your charger as a **device** with:

- **`switch.elaway_charging`** — turn charging on/off
- **`sensor.elaway_charger_status`** — live EVSE status (`available` / `preparing` / `charging` / `finishing` / `suspended` / …)
- **`button.elaway_refresh`** — force an immediate status poll

> ⚠️ **Unofficial / reverse-engineered.** Not affiliated with or endorsed by Elaway or AMPECO. The API is undocumented and may change or break at any time. Use at your own risk.

## Installation

### Via HACS (recommended)

1. In **HACS**, open the **⋮** menu (top-right) → **Custom repositories**.
2. Add this repository — URL: `https://github.com/dineshrajaram/elaway-ha`, type: **Integration** → **Add**.
3. Search HACS for **Elaway**, open it, and click **Download** (pick the latest version and confirm).
4. **Restart Home Assistant** (Settings → System → Restart) so the integration is loaded.
5. Go to **Settings → Devices & Services → Add Integration**, search **Elaway**, and follow the setup (paste your refresh token — see [Configuration](#configuration)).

### Manual

1. Copy the `custom_components/elaway/` folder from this repo into your Home Assistant `config/custom_components/` directory.
2. **Restart Home Assistant.**
3. Go to **Settings → Devices & Services → Add Integration**, search **Elaway**, and follow the setup.

## Configuration

All you need is your **AMPECO refresh token**. After you paste it, the integration discovers your charger(s) automatically — it picks the one, or lets you choose if you have several. Advanced fields (client ID, client secret, poll interval — default 60s) are pre-filled; the poll interval can be changed later via the integration's **Configure**.

### Getting the refresh token

Elaway logs in via Auth0 (PKCE + DPoP), which can't be scripted, so you capture the token once from the app's own traffic:

1. Install [mitmproxy](https://mitmproxy.org/) on a computer and start it (`mitmweb` or `mitmproxy`).
2. On your phone, set that computer as the HTTP proxy and install/trust mitmproxy's CA certificate.
3. Open the Elaway app — log out and back in to force a fresh token exchange.
4. In mitmproxy, find the call to `POST .../api/v1/app/oauth/token` and copy the `refresh_token` value from the JSON **response**.
5. Paste that into the integration's config flow.

> **Regions:** the API host is country-specific (e.g. `no.eu-elaway.charge.ampeco.tech` for Norway). This integration currently defaults to the Norway host.

### What happens to the app's login (important)

The refresh token is **single-use and rotates** on every refresh, and the token you capture is the *same one the app is currently using*. So once the integration refreshes it, the app's copy becomes invalid:

1. You paste the token → the integration validates it (one refresh, which **rotates** it) and takes ownership.
2. Shortly after, **the app logs you out** — its saved token is now stale. This is expected and one-time.
3. **Log back into the app.** That performs a fresh login and gives the app a brand-new, *independent* token family.
4. From then on the app and the integration run on **separate** tokens and both keep working — AMPECO allows multiple concurrent sessions.

After that, the integration keeps itself alive on its own: it refreshes **reactively** — only when its ~30-day access token nears expiry or a request returns `401` — rotating and storing the new refresh token in its config entry each time. That's roughly **once a month**, so the app is never disturbed again.

> **Don't** re-seed the integration by capturing the app's token a second time — that merges them back onto one family and they'll log each other out. If the integration's token ever dies (e.g. after a long idle period), it raises an auth error; just capture a fresh token and re-add the integration.

## How it works

- Token refresh is **reactive** (only when the cached 30‑day access token is near expiry or a call returns 401) and serialized with an `asyncio.Lock`, minimizing rotations.
- A `DataUpdateCoordinator` polls charger status + ongoing session; the switch reconciles state from polling (with quick follow-up refreshes after a toggle).
- Start is gated: it won't fire when the car is fully charged (`suspended`) or no vehicle is connected, surfacing a clear message instead of a raw API error.

## Disclaimer

Provided as-is under the MIT license. You are responsible for complying with Elaway's and AMPECO's terms of service.
