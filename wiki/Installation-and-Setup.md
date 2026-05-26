# Installation & Setup

![Enphase Envoy Indigo Plugin](https://raw.githubusercontent.com/Ghawken/IndigoEnphaseEnvoy/master/Images/banner.png)

## Prerequisites

| Requirement | Details |
|-------------|---------|
| **Indigo** | Indigo Domotics 2022.1 or newer (2025.x recommended) |
| **Python** | Python 3.10+ (bundled with modern Indigo) |
| **Network** | Indigo Mac and Envoy must be on the same LAN |
| **Envoy IP** | A static IP for the Envoy (set via your router's DHCP reservation) |
| **Enphase account** | Required only for firmware ≥7 token generation |

> **Tip:** The Envoy's default mDNS name is `envoy.local`, but a static IP is strongly recommended to prevent the plugin losing contact after a DHCP renewal.

---

## Download & Install

1. Download the latest release from the [Indigo Plugin Store](http://www.indigodomo.com/pluginstore/105/) or from the [GitHub releases page](https://github.com/GlennNZ/EnphaseEnvoy).
2. Double-click `EnphaseEnvoy.indigoPlugin` — Indigo will prompt to install it.
3. Click **Install and Enable**.

The plugin bundles all required Python packages (`aiohttp`, `pyenphase`, `jwt`, `requests`, `flatdict`) inside its `Packages/` directory — no manual pip installs required.

---

## Plugin Preferences

Open **Plugins → Enphase Envoy → Configure…** to access global settings.

| Setting | Default | Description |
|---------|---------|-------------|
| Force clear all generated tokens on next startup | Off | Tick this to force all auto-generated tokens to be regenerated at next plugin reload. Resets itself automatically after clearing. |
| Enable/Disable Debugging | Off | Turns verbose logging on or off. |
| Indigo Log Debug Level | Informational | Controls how much detail goes to the Indigo event log. |
| File Debug Level | Detailed | Controls detail level saved to the plugin's log file. |

> Always leave debugging **off** in normal operation. Turn it on temporarily when diagnosing an issue, then turn it off. Debug output may include sensitive headers.

---

## Creating Your First Device

### Step 1 — Create an Enphase Envoy-S Device

1. Go to **Devices → New Device…**
2. Set **Type** to **Enphase Envoy** (Plugin device).
3. Set **Model** to **Enphase Envoy-S**.
4. Click **Edit Device Settings…**

### Step 2 — Configure the Device

#### IP Address
Enter the static LAN IP of your Envoy (e.g., `192.168.1.50`).

#### Firmware & Authentication
See the [Authentication](Authentication) page for which option to choose. For most modern installs (firmware ≥7):
- Use **Generate Token** (easiest) — enter your Enphase Enlighten email and password.
- Or use **Manual Token** — paste a token from [entrez.enphaseenergy.com](https://entrez.enphaseenergy.com/).

#### Panel Data (optional)
If you want per-inverter panel devices:
1. Tick **Enable Panel Data?**
2. Click **Generate Panel Indigo Devices** — the plugin queries the Envoy and creates one `Enphase Panel` device per microinverter.

Click **Save**.

### Step 3 — Verify the Device is Online

After saving, the plugin immediately polls the Envoy. Within 30 seconds the device state should show:
- `deviceIsOnline` = **True**
- `typeEnvoy` = **Metered** (or **Unmetered** for older hardware)
- `productionWattsNow` = current watts

If the device stays offline, see [Troubleshooting](Troubleshooting).

---

## Creating Additional Devices

You can create these devices in any order; they work independently.

### Battery & Grid Device (`EnphaseEnvoyBatteryDevice`)
Required if you have Enphase Encharge batteries.

1. **Devices → New Device…** → Model: **Enphase Battery and Grid**.
2. No IP address needed — it pulls data from the first online `EnphaseEnvoyDevice`.
3. The device updates automatically every time the parent Envoy device refreshes.

### Cost Device (`EnphaseEnvoyCostDevice`)
1. **Devices → New Device…** → Model: **Enphase Cost Device**.
2. Enter your **Consumption Tariff** ($/kWh) and **Production Tariff** ($/kWh).
3. The plugin calculates today's/7-day/lifetime costs automatically.

### Legacy Device (`EnphaseEnvoyLegacy`)
Only for older Envoy-C hardware without metering support.

1. **Devices → New Device…** → Model: **Enphase Legacy**.
2. Enter IP address and (optionally) the Envoy serial number.

---

## Folder Organisation (Recommended)

Create a device folder called **Enphase** to keep everything tidy:

```
Enphase/
  Enphase Envoy-S          (EnphaseEnvoyDevice)
  Enphase Battery & Grid   (EnphaseEnvoyBatteryDevice)
  Enphase Cost             (EnphaseEnvoyCostDevice)
  Enphase Panel 1          (EnphasePanelDevice)
  Enphase Panel 2
  …
```

When you click **Generate Panel Devices**, panels are created in the same folder as the parent Envoy device automatically.

---

## Removing Panels

Open the Envoy-S device settings and click **Delete Panel Indigo Devices**. All `EnphasePanelDevice` devices are removed from Indigo.

> Panel devices do **not** need to be deleted when you re-generate them — duplicate serial numbers are automatically skipped.
