![Enphase Envoy Indigo Plugin](https://raw.githubusercontent.com/Ghawken/IndigoEnphaseEnvoy/master/Images/banner.png)

# Enphase Envoy Plugin for Indigo Domotics

Monitor your Enphase solar system — production, consumption, battery, and individual panel output — directly from [Indigo Domotics](https://www.indigodomo.com/) via your local Envoy gateway. No cloud dependency; data updates every 60 seconds.

[![Latest Release](https://img.shields.io/github/v/release/Ghawken/IndigoEnphaseEnvoy)](https://github.com/Ghawken/IndigoEnphaseEnvoy/releases/latest)
[![Indigo](https://img.shields.io/badge/Indigo-2025.1%2B-blue)](https://www.indigodomo.com/)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Features

- **Real-time solar monitoring** — production, consumption, net flow, and grid status updated every 60 seconds direct from the local Envoy
- **Per-panel microinverter devices** — one Indigo device per panel, showing watts, temperature, DC/AC voltage, energy totals, and last-heard time
- **Battery & grid support** — full Encharge battery state, charge/discharge rate, state of charge, storage mode, and grid import/export
- **Cost tracking** — optional Cost device that calculates daily, 7-day, and lifetime energy costs against your configured tariff rates
- **Power production control** — enable or disable all inverter output via an Indigo action (installer token required)
- **DPEL — Dynamic Power Export Limiting** — cap grid export or total production at a configurable watt limit and slew rate
- **Battery storage mode control** — switch between Self-Consumption, Savings (TOU), and Full Backup modes; enable/disable grid charging; set reserve SOC
- **Firmware ≥7 JWT authentication** — auto-generates and refreshes installer or owner tokens; supports manual token entry for advanced setups
- **Multi-Envoy** — run multiple `EnphaseEnvoyDevice` devices simultaneously for homes with more than one gateway
- **No external dependencies to install** — all required packages (`aiohttp`, `pyenphase`, `jwt`, `requests`, `flatdict`) are bundled inside the plugin

---

## Screenshots

**Live device states (Envoy-S Metered, 50 panels, firmware D8.3.5232):**

![Live Enphase Envoy-S device states in Indigo](https://raw.githubusercontent.com/Ghawken/IndigoEnphaseEnvoy/master/Images/EnvoySStates.png)

**Device settings dialog:**

![Enphase Envoy-S device settings](https://raw.githubusercontent.com/Ghawken/IndigoEnphaseEnvoy/master/Images/EnvoyDeviceSettings.png)

---

## Quick Start

1. **Download** the latest `.indigoPlugin` from the [Indigo Plugin Store](http://www.indigodomo.com/pluginstore/105/) or [GitHub Releases](https://github.com/Ghawken/IndigoEnphaseEnvoy/releases/latest).
2. **Double-click** the downloaded file — Indigo will prompt to install and enable it.
3. **Create a device** — go to **Devices → New Device…**, select model **Enphase Envoy-S**, and enter your Envoy's local IP address.
4. **Add a token** (firmware ≥7 only) — use **Generate Token** with your Enphase Enlighten credentials, or paste a manual token from [entrez.enphaseenergy.com](https://entrez.enphaseenergy.com/).
5. **Save** — the plugin polls immediately; within 30 seconds `deviceIsOnline` will be `True` and live data will appear.

For full step-by-step instructions, see the **[Installation & Setup wiki page](https://github.com/Ghawken/IndigoEnphaseEnvoy/wiki/Installation-and-Setup)**.

---

## Documentation

All documentation lives in the [GitHub Wiki](https://github.com/Ghawken/IndigoEnphaseEnvoy/wiki).

| Page | Contents |
|------|----------|
| [Home](https://github.com/Ghawken/IndigoEnphaseEnvoy/wiki/Home) | Overview, architecture, what's new |
| [Installation & Setup](https://github.com/Ghawken/IndigoEnphaseEnvoy/wiki/Installation-and-Setup) | Prerequisites, install steps, device creation, startup log guide |
| [Authentication](https://github.com/Ghawken/IndigoEnphaseEnvoy/wiki/Authentication) | Token types, auto-generate vs manual, MFA handling, token refresh |
| [Device Types](https://github.com/Ghawken/IndigoEnphaseEnvoy/wiki/Device-Types) | All 5 device models and their configuration options |
| [Device States Reference](https://github.com/Ghawken/IndigoEnphaseEnvoy/wiki/Device-States-Reference) | Every state across all device types, with types and descriptions |
| [Actions Reference](https://github.com/Ghawken/IndigoEnphaseEnvoy/wiki/Actions-Reference) | All plugin actions — DPEL, power control, battery modes |
| [Plugin Menu & Diagnostics](https://github.com/Ghawken/IndigoEnphaseEnvoy/wiki/Plugin-Menu-and-Diagnostics) | Menu items, endpoint checker, log panel freshness |
| [Polling & Data Flow](https://github.com/Ghawken/IndigoEnphaseEnvoy/wiki/Polling-and-Data-Flow) | Cadence table, panel pipeline, HTTP session reuse, back-off logic |
| [Automation Examples](https://github.com/Ghawken/IndigoEnphaseEnvoy/wiki/Automation-Examples) | 14 ready-to-use automation recipes |
| [Troubleshooting](https://github.com/Ghawken/IndigoEnphaseEnvoy/wiki/Troubleshooting) | Common problems, authentication errors, error reference table |

---

## Supported Device Types

| Indigo Model | Purpose |
|---|---|
| **Enphase Envoy-S** | Main gateway device — production, consumption, storage, per-phase metering |
| **Enphase Legacy** | Older Envoy-C hardware without metering support |
| **Enphase Panel** | One device per microinverter — watts, temperature, DC/AC voltage, energy |
| **Enphase Battery & Grid** | Encharge battery state, grid flow, storage mode settings |
| **Enphase Cost** | Calculates energy costs against your tariff rates |

---

## What's New — v1.8.0

- **Menu item: Log Last Time Envoy Heard from Panels** — shows panel reporting delay and highlights any panels that have gone silent
- `panelLastUpdated`, `panelLastUpdatedUTC`, `panelDataSource` states added to `EnphaseEnvoyDevice`
- Grid summary `grid_text` state (e.g. `"Grid in use & Importing 450 Watts"`)
- `grid_in_use` Boolean and `grid_usage` signed-watt states
- `powerStatus` neutral band — less than 100 W flow in either direction is classified as `neutral` rather than importing/exporting
- Bug fix: voltage states were not divided by phase count on multi-phase systems

Full changelog in [GitHub Releases](https://github.com/Ghawken/IndigoEnphaseEnvoy/releases).

---

## Requirements

| Requirement | Minimum |
|---|---|
| Indigo Domotics | 2025.1+ |
| Python | 3.10+ (bundled with modern Indigo) |
| Network | Indigo Mac and Envoy on same LAN |
| Enphase account | Required for firmware ≥7 token generation |

---

## Actions at a Glance

| Action | Requires |
|---|---|
| Refresh all devices / Refresh single device | Any |
| Enable / Disable power production | Installer token |
| Enable / Disable DPEL (export limiting) | Installer token |
| Set storage mode (self-consumption / savings / backup) | Installer token (recommended) |
| Enable / Disable charge from grid | Installer token (recommended) |
| Set battery reserve SOC | Installer token (recommended) |

See the [Actions Reference](https://github.com/Ghawken/IndigoEnphaseEnvoy/wiki/Actions-Reference) for full parameter details and workflow examples.

---

## Support & Community

- **Indigo Plugin Forum:** [forums.indigodomo.com](https://forums.indigodomo.com/viewforum.php?f=65)
- **Bug reports & feature requests:** [GitHub Issues](https://github.com/Ghawken/IndigoEnphaseEnvoy/issues)
- **Plugin Store listing:** [indigodomo.com/pluginstore/105](http://www.indigodomo.com/pluginstore/105/)

---

![](https://raw.githubusercontent.com/Ghawken/IndigoEnphaseEnvoy/master/Images/pageend.png)
