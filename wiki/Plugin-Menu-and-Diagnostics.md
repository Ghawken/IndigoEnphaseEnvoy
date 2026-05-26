# Plugin Menu & Diagnostics

![Enphase Envoy Indigo Plugin](https://raw.githubusercontent.com/Ghawken/IndigoEnphaseEnvoy/master/Images/banner.png)

Access the plugin menu from **Plugins → Enphase Envoy → …** in Indigo.

---

## Menu Items

### Manually Refresh Enphase Data
Triggers an immediate poll of all enabled `EnphaseEnvoyDevice` devices: production data, panel inventory, and panel health. This is the same as the `refreshData` action, but accessible without creating an action group.

Useful for testing that the plugin can communicate with your Envoy after a network change.

---

### Start Panel Freshness Check (15 min)
Launches a background diagnostic thread that runs for up to **15 minutes**, polling all three panel data endpoints every **60 seconds** and comparing their timestamps for 5 randomly selected inverters.

**Purpose:** Determine which endpoint (`devstatus`, `device_data`, or `legacy inverters`) is returning the most up-to-date per-panel timestamps for your specific Envoy and firmware combination.

**Output example in the Indigo log:**
```
[My Envoy] ── Panel Freshness Check (43 total inverters) ──
[My Envoy]   Sources responding: legacy, device_data, devstatus
[My Envoy]   SN 122345678901: legacy=14:32:01 210W  device_data=14:32:15 208W  devstatus=14:32:20 209W  → devstatus
[My Envoy]   SN 122345678902: legacy=14:31:58 195W  device_data=14:32:10 193W  devstatus=14:32:18 194W  → devstatus
[My Envoy]   Tally: legacy=0  device_data=1  devstatus=4  tie=0
[My Envoy] ── End Freshness Check ──
```

The 5 sample panels are locked for the entire 15-minute run so results are comparable across cycles.

> **Note:** This tool is informational only. The plugin automatically uses the best endpoint based on your token type. The freshness check helps diagnose why a specific panel might appear stale.

---

### Stop Panel Freshness Check
Stops the running freshness diagnostic before the 15-minute window expires.

---

### Log All Panels Last Heard
Immediately logs every panel device's `lastHeard` value to the Indigo event log, sorted by most-recent first, with visual indicators:

| Emoji | Meaning |
|-------|---------|
| 👍 | Last heard < 10 minutes ago — healthy |
| 👌 | Last heard 10–15 minutes ago — normal (Envoy reporting delay) |
| 👎 | Last heard > 15 minutes ago — may be stale or offline |

**Output example:**
```
── All Panels Last Heard (43 panels) ──
  Enphase Panel 1          👍 3.42 mins ago
  Enphase Panel 7          👍 4.10 mins ago
  Enphase Panel 23         👌 11.55 mins ago
  Enphase Panel 38         👎 27.03 mins ago
── End All Panels Last Heard ──
```

**Use case:** Quick visual check if any panels have gone silent. Run this before checking individual panel devices.

---

### Toggle Debugging
Toggles verbose debug logging on or off without opening the Plugin Configuration dialog. The current state is announced in the Indigo event log.

> Same as opening Plugin Config and changing the **Enable/Disable** debugging checkbox, but faster.

---

## Device Config Debug Buttons

These appear in the **Edit Device Settings** dialog for `EnphaseEnvoyDevice` devices.

### [Debug] Check all device endpoints
Opens a background thread that tests every known Envoy API endpoint — both HTTPS and HTTP — logging the response code and (on success) the JSON response body for each.

Pauses the normal polling loop for **6 minutes** while testing to avoid concurrent requests.

**Endpoints tested:**
```
/ivp/pdm/energy           /ivp/pdm/production
/production.json          /production
/inventory.json           /api/v1/production
/api/v1/production/inverters
/auth/check_jwt           /ivp/meters
/ivp/meters/readings      /ivp/ensemble/inventory
/ivp/livedata/status      /ivp/peb/devstatus
/ivp/ss/dpel              /ivp/meters/reports/consumption
/info.xml
```

Both `https://` and `http://` variants are tested for each endpoint.

**Use case:** Determine which endpoints your specific Envoy firmware supports before filing a bug report or changing configuration.

---

### [Debug] Print Installer password to Log
Calculates the legacy installer Digest auth password from the Envoy's serial number using Enphase's known algorithm. The password is printed to the Indigo event log (not saved anywhere).

**When to use:**
- You need to log in to the Envoy local web interface as "installer".
- You're debugging token issues on older firmware.
- You want to verify the serial number was fetched correctly.

> The password is only valid for older firmware (pre-7). On firmware 7.x+ the local web UI requires a JWT token.

---

## Reading the Indigo Event Log

Key log messages to watch for:

### Startup
```
===== Initializing New Plugin Session =====
Plugin name:   Enphase Envoy
Plugin version: 1.8.0
Indigo version: 2025.1.0
Python version: 3.13.x
=============================================
```

### Token Events
```
[My Envoy] Enphase Token Type: ** INSTALLER ** (newly generated) — Expires: Mon May 26 2027 ...
[My Envoy] Installer token detected — full Envoy API access including power control.
```

### Panel Updates
```
Checking all panels with devstatus+device_data (43 inverters)
[My Envoy] Envoy polling interval: 900s
```

### Errors
```
Error connecting to Device: My Envoy  (HTTP 401 from https://192.168.1.50/production.json)
Authorization failed enabling DPEL for My Envoy. HTTP 403. This endpoint requires an installer-level JWT token.
```
