# Enphase Envoy — Indigo Plugin Wiki

![Enphase Envoy Indigo Plugin](https://raw.githubusercontent.com/Ghawken/IndigoEnphaseEnvoy/master/Images/banner.png)

> **Monitor. Measure. Optimise.**  
> Connect locally to your Enphase Envoy-S and monitor solar production, home consumption, net import/export, and individual panel output in Indigo.

---

## Wiki Pages

| Page | Description |
|------|-------------|
| [Installation & Setup](Installation-and-Setup) | Prerequisites, downloading, creating your first device |
| [Authentication](Authentication) | No-token, manual JWT, and auto-generated token modes |
| [Device Types](Device-Types) | All 5 device types and when to use each |
| [Device States Reference](Device-States-Reference) | Every state across all device types |
| [Actions Reference](Actions-Reference) | All Indigo actions the plugin provides |
| [Plugin Menu & Diagnostics](Plugin-Menu-and-Diagnostics) | Menu items, endpoint checker, freshness tool |
| [Automation Examples](Automation-Examples) | Triggers, conditions, and action group recipes |
| [Polling & Data Flow](Polling-and-Data-Flow) | How and when each endpoint is polled |
| [Troubleshooting](Troubleshooting) | Common problems and fixes |

---

## Quick Summary

| Feature | Detail |
|---------|--------|
| **Supported Envoys** | Envoy-S Metered, Envoy-S Unmetered, Envoy-C (Legacy) |
| **Firmware** | Pre-7 (Digest auth) and 7.x+ (JWT token required) |
| **Poll interval** | 60 s (main data), 60 s (panel watts), 5 min (inventory), 15 min (extended panel) |
| **Panel data** | Per-inverter watts, temperature, DC/AC voltage & current, lifetime energy |
| **Battery control** | Storage mode, charge-from-grid, reserve SOC (installer token) |
| **Production control** | Enable/disable solar production (installer token) |
| **DPEL** | Dynamic Power Export Limiting — set watts cap + slew rate (installer token) |
| **Cost tracking** | Separate Cost Device with configurable $/kWh tariffs |
| **Multi-phase** | Per-phase L1/L2/L3 voltage, current, watts, power factor, frequency |

---

## What's New (v1.8.0)

- **Menu → Log All Panels Last Heard** — see at a glance how old each panel's last report is, with 👍/👌/👎 emoji indicators.
- `lastHeard` state on panel devices shows a human-readable elapsed time (e.g. `"12.21 mins"`, `"1hr 5.00mins"`).
- `grid_text` summary state on the Envoy device.
- `grid_in_use` Boolean state.
- `grid_usage` (Watts) state — positive = importing, negative = exporting.
- Neutral power status when net flow is within ±100 W buffer.
- Voltage correctly divided by number of channels.

---

## Architecture Overview

```
Indigo Server
  └─ Enphase Envoy Plugin
        ├─ EnphaseEnvoyDevice          (main device, 1 per physical Envoy)
        │     polls production.json, /ivp/meters/readings, /ivp/pdm/*
        │     updates → EnphaseEnvoyCostDevice (auto)
        │              → EnphaseEnvoyBatteryDevice (auto)
        │
        ├─ EnphaseEnvoyLegacy          (older Envoy-C, no consumption data)
        ├─ EnphasePanelDevice           (1 per microinverter, auto-generated)
        ├─ EnphaseEnvoyBatteryDevice    (battery + grid aggregated view)
        └─ EnphaseEnvoyCostDevice       ($/kWh cost calculations)
```

---

![](https://raw.githubusercontent.com/Ghawken/IndigoEnphaseEnvoy/master/Images/pageend.png)
