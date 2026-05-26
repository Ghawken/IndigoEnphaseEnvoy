# Authentication

![Enphase Envoy Indigo Plugin](https://raw.githubusercontent.com/Ghawken/IndigoEnphaseEnvoy/master/Images/banner.png)

Enphase changed the Envoy's local API authentication model in firmware **7.x**. Older hardware uses HTTP Digest auth; newer hardware requires a JWT Bearer token.

---

## Mode Comparison

| Mode | Firmware | Token Type | API Access | Setup Effort |
|------|----------|-----------|------------|--------------|
| **No token** | < 7 | None (Digest) | Production only | None |
| **Manual token — Owner** | ≥ 7 | JWT (owner) | Read-only | Low |
| **Manual token — Installer** | ≥ 7 | JWT (installer) | Full (power control, DPEL) | Medium |
| **Auto-generated token** | ≥ 7 | JWT (owner or installer, depends on account) | Depends on account | Low |

---

## Mode 1: No Token (Pre-firmware 7 / Legacy)

Leave both **Use Manual Token** and **Generate Token** unchecked.

The plugin uses:
- `http://` (not HTTPS)
- HTTP Digest auth with username `envoy` and the last 6 digits of the serial number as password (auto-fetched from `/info.xml`)

**Used automatically** for `EnphaseEnvoyLegacy` devices.

---

## Mode 2: Manual Token

Tick **Use Manual Token** in the device settings.

### How to Get a Token

**Option A — Enphase Entrez Portal (recommended)**
1. Visit [https://entrez.enphaseenergy.com/](https://entrez.enphaseenergy.com/)
2. Log in with your Enlighten credentials.
3. Enter your **Envoy serial number** (visible on the Envoy label or in the Enlighten app).
4. Click **Generate Token**.
5. Copy the token and paste it into the **Authentication Token** field.

**Option B — Installer account**
If you have installer credentials, use them to generate an installer token. The token type (owner/installer) is shown in the Indigo log when the device starts.

### Token Expiry
Tokens from the Entrez portal are valid for **~1 year**. The plugin logs the token type and expiry date at startup:

```
[My Envoy] Enphase Token Type: ** OWNER ** (manual)  —  Expires: Mon May 26 2027 09:00:00
[My Envoy] Owner/Homeowner token detected — read-only data access.
```

When a manual token is nearing expiry, generate a new one from the portal and paste it into the device settings.

---

## Mode 3: Auto-Generated Token

Tick **Generate Token** in the device settings and enter your:
- **Enphase Login** (email)
- **Enphase Password**

The plugin:
1. Uses the **PKCE OAuth flow** (same as the Envoy web UI) to authenticate with Enlighten.
2. Exchanges the authorisation code for a JWT directly from the local Envoy at `/auth/get_jwt`.
3. Validates the token against `/auth/check_jwt` on the Envoy.
4. Caches the token in the device's plugin props and refreshes it automatically when it is within **7 days** of expiry.

**Fallback:** If the PKCE flow fails (e.g. MFA is enabled on the account), the plugin falls back to the `pyenphase` cloud token flow.

### Token Caching

| Event | Behaviour |
|-------|-----------|
| Plugin starts | Existing saved generated token is cleared; a fresh token is fetched on first use. |
| Credentials changed in device settings | Saved token is cleared immediately. |
| Token mode changed (generate ↔ manual) | `token_source` is reset; new token is fetched. |
| Plugin prefs → "Force clear tokens" | All generated tokens cleared at next startup. |
| Token within 7 days of expiry | Automatic silent refresh. |

### Token Type at Startup

```
[My Envoy] Enphase Token Type: ** INSTALLER ** (newly generated)  —  Expires: Mon May 26 2027 …
[My Envoy] Installer token detected — full Envoy API access including power control.
```

Or for an owner account:

```
[My Envoy] Enphase Token Type: ** OWNER ** (newly generated)
[My Envoy] Owner/Homeowner token detected — read-only data access.
```

---

## Token Type vs. API Access

| Endpoint | Owner token | Installer token |
|----------|-------------|-----------------|
| `/production.json` | ✅ | ✅ |
| `/api/v1/production/inverters` | ✅ | ✅ |
| `/ivp/pdm/device_data` | ✅ | ✅ |
| `/ivp/meters/readings` | ✅ | ✅ |
| `/ivp/ensemble/inventory` | ✅ | ✅ |
| `/inventory.json` | ✅ | ✅ |
| `/ivp/peb/devstatus` | ❌ | ✅ |
| `/ivp/mod/.../mode/power` (enable/disable production) | ❌ | ✅ |
| `/ivp/ss/dpel` (DPEL export limiting) | ❌ | ✅ |
| `/ivp/peb/newscan` (poll interval) | ❌ | ✅ |
| `/admin/lib/tariff` (battery control) | ❌/⚠️ | ✅ |

> **Note:** Battery tariff control (`/admin/lib/tariff`) may work with an owner token on some firmware versions, but an installer token is recommended for full control.

---

## Debug: Installer Password Calculator

If you need the local installer password (for old firmware Digest auth), open the Envoy-S device settings and click **[Debug] Print Installer password to Log**. The plugin calculates it from the serial number using Enphase's known algorithm and logs it to the Indigo event log.

---

## MFA / Two-Factor Authentication

If your Enlighten account has Multi-Factor Authentication enabled, auto-generated tokens will fail. You must:
1. Temporarily disable MFA on your Enlighten account, generate a token, then re-enable MFA; **or**
2. Use a **manual token** obtained from the Entrez portal while MFA is temporarily disabled.

---

![](https://raw.githubusercontent.com/Ghawken/IndigoEnphaseEnvoy/master/Images/pageend.png)
