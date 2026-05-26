# Polling & Data Flow

Understanding how the plugin fetches data helps you set appropriate expectations and build reliable automations.

---

## Main Loop Cadence

The plugin runs a single background thread (`runConcurrentThread`) with a **25-second base loop delay**. Within each loop iteration it evaluates whether each check's timer has elapsed:

| Check | Cadence | Method | Purpose |
|-------|---------|--------|---------|
| Main Envoy data | **60 s** | `refreshDataForDev` | Production, consumption, storage, net flow, per-phase |
| Panel health (watts) | **60 s** | `checkThePanels_New` | Per-inverter current watts and online/offline status |
| Panel inventory | **5 min** | `checkPanelInventory` | Model numbers, producing/communicating flags from inventory.json |
| Panel extended data | **15 min** | `_refreshPanelExtendedData` | Temperature, DC/AC voltage, energy totals — cached and merged into 60 s cycle |
| Envoy type check | **6 hr** | `checkEnvoyType` | Confirms Metered vs Unmetered classification |
| Datetime reset | **22 min** | `checkDayTime` | Resets `productionWattsMaxToday` at midnight; `productionWattsMaxWeek` on Sunday |

> **Timer semantics:** Timers advance *before* each call, so a failure doesn't trigger an immediate retry. The next attempt waits the full cadence period.

---

## Startup Sequence

1. Plugin initialises — clears any saved generated tokens if "Force clear" was set.
2. `runConcurrentThread` starts.
3. **One-off startup refresh** runs immediately for every enabled `EnphaseEnvoyDevice`.
4. Polling interval is fetched from `/ivp/peb/newscan` (installer token only).
5. First pass of all timers fires (all are initialised to 0, so all checks run immediately).
6. Normal cadence begins.

---

## Forced Immediate Refresh

Several events cause all timers for a device to be reset to 0 (all checks run ASAP):

| Event | Trigger |
|-------|---------|
| `deviceStartComm` called | Device enabled, plugin reloaded, or Indigo restart |
| Device was just enabled | `enabled_state` changed from False → True |
| Back-off wait completes | After the WaitInterval sleep ends, short-cadence checks are bumped |

---

## Back-off (`WaitInterval`)

When an operation needs a temporary pause (e.g. endpoint checker is running, a timeout occurred), `self.WaitInterval` is set to the number of seconds to sleep:

| Event | Back-off |
|-------|----------|
| HTTP timeout | 60 s |
| Endpoint checker running | 360 s |
| Generate panel devices | 180 s |
| Unhandled exception in main loop | 60 s |

After the back-off sleep, **short-cadence checks** (panel inventory, panel health, panel extended, main refresh) have their timers bumped so they don't all fire simultaneously.

---

## Panel Data Pipeline

```
Every 60 s — getthePanels()
  ├─ If installer token → /ivp/peb/devstatus (freshest watts + timestamps)
  ├─ Else              → /api/v1/production/inverters (Digest auth, basic watts)
  │
  └─ Merge with cached extended data (from last 15 min run)
        ├─ /ivp/pdm/device_data (preferred: AC/DC V/I, temperature, energy)
        └─ /ivp/peb/devstatus as extended fallback (installer token)

Every 15 min — _refreshPanelExtendedData()
  ├─ /ivp/pdm/device_data (any token, richest data)
  └─ /ivp/peb/devstatus (installer token, fallback)
  → Stored in self._cached_panel_extended[dev.id]
```

**Freshness merge logic:** When merging cached extended data with fresh real-time data, the source with the newer timestamp "wins" for watts. Extended fields (temperature, voltage, etc.) are always merged from the cache regardless of timestamp.

---

## Main Envoy Data Pipeline

```
Every 60 s — refreshDataForDev()
  │
  ├─ If typeEnvoy unknown → getTheData() → detect Metered vs Unmetered
  │
  ├─ If typeEnvoy == Metered → getTheData() → /production.json (PC endpoint)
  │   └─ parseStateValues(): production, consumption, storage, grid_usage, powerStatus
  │       └─ updateCostDevice()     → cost calculations
  │       └─ updateBatteryDevice()  → battery + grid states
  │
  ├─ If typeEnvoy == Unmetered → legacyGetTheData() → /api/v1/production
  │   └─ parseStateValues(): production only
  │
  ├─ _pollPowerProductionStatus() → /ivp/mod/.../mode/power (any token)
  │
  └─ If Metered → getMetersReadings() → /ivp/meters/readings
      └─ parseMetersReadings() → per-phase L1/L2/L3 states
```

---

## HTTP Session Reuse

The plugin maintains a **per-host `requests.Session` cache** (`self.session_cache`). Each unique IP address gets its own persistent HTTPS session with keep-alive enabled.

- On **timeout**: the session is closed and a fresh one is created; `WaitInterval` = 60 s.
- On **connection error**: the session is closed and recreated.
- On successful response: the session is reused for subsequent requests.

This avoids the overhead of TLS renegotiation on every poll, which is significant for a 60-second polling loop.

---

## HTTPS vs HTTP

| Condition | Protocol |
|-----------|----------|
| No token configured | `http://` |
| Manual token configured | `https://` |
| Generate token configured | `https://` |

The `https_flag` variable is set to `"s"` when any token is in use, making all URLs `https://...`. TLS certificate verification is disabled (`verify=False`) because Envoys use self-signed certificates.

---

## Battery Device Update Flow

The Battery device does not poll independently. It is updated as a **side effect** of `parseStateValues()` which is called every time the parent Envoy device refreshes:

```
Envoy refresh (60 s)
  └─ parseStateValues(dev, data)
        └─ for battdev in indigo.devices.iter('self.EnphaseEnvoyBatteryDevice'):
              updateBatteryDevice(envoyDev, battdev)
                ├─ Pull storage states from parent Envoy device
                ├─ GET /ivp/ensemble/inventory → per-battery details
                ├─ GET /admin/lib/tariff → storageMode, chargeFromGrid, reserveSOC
                └─ Update all battdev states
```
