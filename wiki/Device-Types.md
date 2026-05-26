# Device Types

The plugin provides five device types. Each is independent — you can create only the ones you need.

---

## 1. Enphase Envoy-S (`EnphaseEnvoyDevice`)

**The primary device.** Represents one physical Envoy gateway on your network.

### Configuration Fields

| Field | Required | Description |
|-------|----------|-------------|
| IP Address | ✅ | LAN IP of the Envoy (e.g. `192.168.1.50`) |
| Use Manual Token | For FW≥7 | Tick to enter a pre-generated JWT token |
| Serial Number | When manual token | Serial number for the Envoy |
| Authentication Token | When manual token | The JWT from entrez.enphaseenergy.com |
| Generate Token | For FW≥7 | Auto-fetch token using Enlighten credentials |
| Enphase Login | When generate token | Your Enlighten email |
| Enphase Password | When generate token | Your Enlighten password |
| Enable Panel Data? | Optional | Enables per-inverter panel devices |
| Unmetered Envoy >7 Firmware | Rare | Force production-only mode if Envoy-S is unmetered |

### Display State
The device's summary display state is **`powerStatus`** — shown in the Indigo device list and control pages.

| Value | Meaning |
|-------|---------|
| `offline` | Cannot contact Envoy |
| `producing` | Solar generating but no metering info |
| `exporting` | Net power > +100 W (feeding grid) |
| `importing` | Net power < −100 W (drawing from grid) |
| `neutral` | Net power within ±100 W (batteries or near-balance) |
| `idle` | No production detected |

### One Envoy per Device
Create one `EnphaseEnvoyDevice` per physical Envoy gateway. If you have two Envoy systems, create two devices.

---

## 2. Enphase Legacy (`EnphaseEnvoyLegacy`)

For older **Envoy-C** hardware (pre-Envoy-S) that only reports production — no consumption metering.

### Configuration Fields

| Field | Required | Description |
|-------|----------|-------------|
| IP Address | ✅ | LAN IP of the Envoy |
| Envoy Serial Number | Optional | Enables per-panel data access (if supported) |

### States
- `wattsNow` — current production (W)
- `wattHoursToday`, `wattHoursSevenDays`, `wattHoursLifetime`
- `powerStatus` — producing / idle / offline

No consumption, no per-phase data, no panel devices.

---

## 3. Enphase Panel (`EnphasePanelDevice`)

One device per microinverter. **Auto-created** by clicking **Generate Panel Indigo Devices** in the parent Envoy-S device settings. Never create manually.

### Auto-Creation Behaviour
- The plugin fetches the inverter list from the Envoy.
- One `EnphasePanelDevice` is created for each unique serial number.
- Devices are placed in the **same Indigo folder** as the parent Envoy device.
- If a device with the same serial number already exists, it is skipped (safe to re-generate).
- Panel devices are named `Enphase Panel 1`, `Enphase Panel 2`, etc. (or the next available number if names already exist).

### Display State
`watts` — current AC power output for this panel (W).

### Data Sources (priority order)

| Source | Requires | Data Richness | Freshness |
|--------|----------|---------------|-----------|
| `/ivp/peb/devstatus` | Installer token | Medium (watts, voltage, temp) | ⭐⭐⭐ Best |
| `/ivp/pdm/device_data` | Any token | Full (watts, AC/DC V/I, energy) | ⭐⭐ Good |
| `/api/v1/production/inverters` | Legacy/any | Basic (watts only) | ⭐ Fallback |

The plugin uses devstatus for real-time watts (fastest), and device_data for the extended fields (temperature, DC voltage, energy) cached every 15 minutes.

### Staleness Detection
A panel is marked **offline** (watts→0, `communicating`→False) if:
- The Envoy reports it as `gone`; or
- Its last report timestamp is more than **25 minutes** old.

The last known `lastCommunication` timestamp is preserved even when a panel goes offline, so you can see when it last spoke.

---

## 4. Enphase Battery and Grid (`EnphaseEnvoyBatteryDevice`)

Aggregates data from all Encharge batteries and presents a combined view with grid flow data.

### Configuration Fields
No configuration required. The device automatically uses the first **online** `EnphaseEnvoyDevice` for all API calls.

### Display State
`batteryState` — `idle`, `charging`, `discharging`, `offline`, or `unknown`.

### What It Monitors
- Combined battery state of charge (%), watts, capacity (Wh/kW)
- Per-battery temperature and maximum cell temperature
- Battery serial numbers and firmware versions
- Grid import/export watts and net flow
- Storage mode, charge-from-grid setting, reserve SOC

### Data Update Timing
Updated automatically every time the parent Envoy device refreshes (every 60 seconds). Use the **Refresh Battery & Grid Data** action for an on-demand refresh.

---

## 5. Enphase Cost Device (`EnphaseEnvoyCostDevice`)

Calculates energy costs based on configurable tariff rates.

### Configuration Fields

| Field | Description |
|-------|-------------|
| All day Consumption Tariff $/kWh | What you pay for grid electricity |
| All day Production Tariff $/kWh | What you receive for exported solar (feed-in tariff) |

> **Note:** The plugin uses a flat (single) rate for both consumption and production. Time-of-use (TOU) tariffs with multiple rates are not yet supported.

### Display State
`netTarrifToday` — today's net cost/credit in dollars.

### States Calculated
All monetary values are formatted as `$x,xxx.xx` strings.

| State | Description |
|-------|-------------|
| `productionTarrifToday` | Solar earnings today |
| `consumptionTarrifToday` | Grid electricity cost today |
| `netTarrifToday` | Net today (production earnings − consumption cost) |
| `productionkWToday` | kWh produced today |
| `consumptionkWToday` | kWh consumed today |
| `netkWToday` | Net kWh today |
| `productionTarrif7days` / `consumptionTarrif7days` / `netTarrif7days` | 7-day equivalents |
| `productionTarrifLifetime` / `consumptionTarrifLifetime` / `netconsumptionTarrifLifetime` | Lifetime equivalents |

### Update Timing
Recalculated automatically every time the parent Envoy device updates states — no separate polling.
