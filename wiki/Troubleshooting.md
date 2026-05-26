# Troubleshooting

![Enphase Envoy Indigo Plugin](https://raw.githubusercontent.com/Ghawken/IndigoEnphaseEnvoy/master/Images/banner.png)

---

## Device Won't Come Online

### Symptom
`deviceIsOnline` stays `False`, device shows error state immediately after creation.

### Checklist

| Check | How |
|-------|-----|
| Envoy IP is correct | Browse to `http://<IP>` in Safari — should show the Envoy local page |
| Envoy is on the same LAN as Indigo | Ping from the Mac: `ping 192.168.1.50` |
| Static IP set | Check your router's DHCP reservations; the Envoy should have a fixed IP |
| No token / wrong token mode | Old firmware (<7) needs no token. New firmware (≥7) needs a token. |
| TLS issue (firmware ≥7) | Try the endpoint checker (device settings → **[Debug] Check all device endpoints**) |

### Quick Test
Open the device settings dialog and click **[Debug] Check all device endpoints**. Watch the Indigo log for 2–3 minutes. A working endpoint will log `Success: http(s)://<IP>/production.json` with a JSON response.

---

## Authentication Errors (HTTP 401 / 403)

### Symptom
Log shows:
```
Error connecting to Device: My Envoy  (HTTP 401 from https://192.168.1.50/production.json)
```

### Causes & Fixes

| Cause | Fix |
|-------|-----|
| Token expired | Manual token: get a new one from [entrez.enphaseenergy.com](https://entrez.enphaseenergy.com/). Auto-generated: credentials may have changed — re-enter password in device settings. |
| Wrong token mode | Old firmware uses no token + HTTP. New firmware uses HTTPS + JWT. |
| Token is for a different Envoy | Each Envoy requires its own token bound to its serial number. |
| MFA enabled on account | Auto-generated token flow fails with MFA. Use a manual token. |
| Token not yet propagated | After generating a new auto-token, wait 30–60 seconds for the first poll. |

### Force Token Regeneration
1. Open **Plugins → Enphase Envoy → Configure…**
2. Tick **Force clear all generated tokens on next startup**.
3. Save.
4. **Plugins → Enphase Envoy → Reload Plugin**.

---

## DPEL / Power Control Fails (HTTP 403)

### Symptom
```
Authorization failed enabling DPEL for My Envoy. HTTP 403.
This endpoint requires an installer-level JWT token.
```

### Cause
Power production control (`/ivp/mod/.../mode/power`) and DPEL (`/ivp/ss/dpel`) require an **installer-level** JWT token. Owner tokens are rejected.

### Fix
1. Verify your token type: check the Indigo log at startup for `** INSTALLER **` vs `** OWNER **`.
2. If you see `OWNER`, you need an installer account to generate/obtain an installer token.
3. Some Enphase installers will provide an installer token on request.
4. Alternatively, the Installer Password calculator (**[Debug] Print Installer password to Log**) can help derive credentials for older firmware.

---

## Panel Devices Not Appearing

### Symptom
Clicked **Generate Panel Devices** but no panel devices were created.

### Checklist

| Check | Notes |
|-------|-------|
| **Enable Panel Data?** is ticked | The checkbox must be ticked before clicking Generate |
| Envoy device is online | Panels can only be fetched if the Envoy is reachable |
| Serial number available | The plugin needs the serial number for Digest auth (auto-fetched from `/info.xml`) |
| Token configured | Without a token, the legacy endpoint requires Digest auth — check serial number was fetched |

### Debug Steps
1. Enable debugging (Plugins → Configure → Debug).
2. Click Generate Panel Devices.
3. Check the log for `getthePanels` calls and any errors.
4. Try the endpoint checker to verify `/api/v1/production/inverters` responds.

---

## Panel Shows 0W / Offline

### Symptom
A panel device shows 0 watts and `deviceIsOnline = False` even when the sun is shining.

### Causes

| Cause | Fix |
|-------|-----|
| Panel data is stale (>25 min) | Normal if a single inverter has been quiet — check physical hardware, look for shading |
| Panel's `lastCommunication` shows epoch 1970 | The inverter has never reported since the device was created. Wait until solar is producing and regenerate. |
| All panels affected | Check the parent Envoy device is online first |
| No extended data in first 15 min | Extended states (temp, voltage) are blank until the 15-minute cache fills |

### Checking Staleness
Run **Plugins → Enphase Envoy → Log All Panels Last Heard** to see which panels are genuinely silent.

---

## Production Data Seems Wrong

### Symptom
`productionWattsNow` doesn't match what the Enphase app shows.

### Explanation
- The **Enphase app** uses cloud data from Enlighten, which may lag by up to 15 minutes.
- The **plugin** reads local Envoy data in real-time (60-second poll).
- Slight differences are normal — the Envoy measures at the gateway; the app may show aggregated/rounded values.

### Unmetered Envoy
If `typeEnvoy` = `"Unmetered"`, consumption data is not available — this is a hardware limitation, not a bug. Tick **Unmetered Envoy >7 Firmware** in device settings if you are on firmware ≥7 with an unmetered Envoy.

---

## Battery Device Shows Unknown / No Data

### Symptom
`batteryState` = `"unknown"`, `batteryCount` = 0, but you have batteries installed.

### Checklist

| Check | Notes |
|-------|-------|
| Parent Envoy device is online | Battery data comes from the Envoy |
| Batteries are Encharge (not Enpower) | The plugin reads `ENCHARGE` entries from inventory |
| `/ivp/ensemble/inventory` returns data | Run the endpoint checker and look for this endpoint |
| Token is configured | The inventory endpoint may require a token on newer firmware |

---

## "Cannot find serial number" Errors

### Symptom
```
Error connecting to info.xml to find Serial Number
```

### Cause
The plugin auto-fetches the serial number from `/info.xml`. If this endpoint is unavailable (some firmware versions restrict it), the serial number lookup fails.

### Fix
Manually enter the serial number in the device settings:
1. Open the Envoy device settings.
2. Tick **Use Manual Token**.
3. Enter the serial number in the **Serial Number** field.
4. Untick if you don't want manual token mode (the serial number field will be saved from a prior save).

Or enter it in the **Generate Token** flow — the serial number is also used there.

The serial number is on the physical Envoy label and in the Enphase Enlighten app (under the system's device list).

---

## Debugging Tips

### Enable Detailed Logging
1. **Plugins → Enphase Envoy → Configure…**
2. Set **Indigo Log Debug Level** to `Debugging Messages` (level 10).
3. Set **File Debug Level** to `Detailed Debugging Messages` (level 5).
4. Save.

### What to Look For
- `[HTTP] GET …` lines show every outbound request and response code.
- `[HTTP] Created NEW session` vs `Re-using session` shows connection health.
- Token info lines show type and expiry at device start.
- Exception tracebacks are shown with file, function, and line number.

### Sharing Logs
When posting to the Indigo forum, attach the plugin log file (found at `~/Library/Application Support/Perceptive Automation/Indigo X/Logs/com.GlennNZ.indigoplugin.EnphaseEnvoy/`) rather than the full Indigo event log. **Redact your token** before sharing any log output.

---

## Resetting Everything

### Plugin Reload (non-destructive)
**Plugins → Enphase Envoy → Reload Plugin** — restarts the plugin without deleting devices or settings. Useful after config changes.

### Token Reset
Tick **Force clear all generated tokens on next startup** in Plugin Config, then reload.

### Clean Re-install
1. Disable the plugin.
2. Delete all Enphase devices from Indigo.
3. Uninstall the plugin.
4. Re-install from the plugin store.
5. Re-create devices.

---

## Error Reference

| Error Message | Meaning | Fix |
|--------------|---------|-----|
| `HTTP 401` from production.json | Token missing or wrong for FW≥7 | Add a JWT token |
| `HTTP 403` from DPEL/power | Owner token on installer-only endpoint | Get installer token |
| `Timeout for host …` | Network unreachable or Envoy overloaded | Check network; increase server timeout in Plugin Config |
| `Could not connect or determine Envoy model` | IP wrong or Envoy offline | Verify IP and network |
| `Both PKCE and pyenphase token flows failed` | Credential error or MFA | Check credentials; disable MFA; use manual token |
| `No storage_settings found in tariff data` | Battery not configured on Envoy | Set up battery in Enphase app first |
| `No online EnphaseEnvoyDevice found` | Battery action called but Envoy is offline | Ensure Envoy device is online before battery actions |
