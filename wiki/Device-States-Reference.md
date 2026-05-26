# Device States Reference

![Enphase Envoy Indigo Plugin](https://raw.githubusercontent.com/Ghawken/IndigoEnphaseEnvoy/master/Images/banner.png)

---

## EnphaseEnvoyDevice States

### Core Status

| State ID | Type | Description |
|----------|------|-------------|
| `deviceIsOnline` | Boolean | True when Envoy is reachable |
| `deviceLastUpdated` | String | Timestamp of last successful update (e.g. `"05/26/2026 at 14:32"`) |
| `typeEnvoy` | String | `"Metered"`, `"Unmetered"`, or `"unknown"` |
| `serial_number` | String | Full Envoy serial number (e.g. `"122011012345"`) |
| `firmware_version` | String | Envoy firmware (e.g. `"R8.2.4144"`) |
| `token_expires` | String | JWT token expiry date/time |
| `envoyPollingInterval` | Number | Envoy's internal scan interval in seconds (installer token only) |

### Power Flow

| State ID | Type | Description |
|----------|------|-------------|
| `powerStatus` | List | `offline`, `exporting`, `importing`, `neutral`, `producing`, `idle` |
| `generatingPower` | Boolean | True when producing or exporting |
| `productionWattsNow` | Number | Current solar output (W) |
| `consumptionWattsNow` | Number | Current home consumption (W) |
| `netConsumptionWattsNow` | Number | Net watts (consumption − production); negative = exporting |
| `grid_usage` | Number | Same as `netConsumptionWattsNow` — positive = importing, negative = exporting |
| `grid_in_use` | Boolean | True when grid flow > 100 W |
| `grid_text` | String | Human-readable summary (e.g. `"Grid in use & Importing 450 Watts"`) |

### Energy Totals

| State ID | Type | Description |
|----------|------|-------------|
| `productionWattsToday` | Number | Solar energy generated today (Wh) |
| `productionWattsMaxToday` | Number | Peak solar production today (W) |
| `productionWattsMaxWeek` | Number | Peak solar production this week (W) |
| `productionWattsMaxEver` | Number | Peak solar production all-time (W) |
| `production7days` | Number | Solar energy last 7 days (Wh) |
| `productionwhLifetime` | Number | Lifetime solar energy (Wh) |
| `consumptionWattsToday` | Number | Energy consumed today (Wh) |
| `consumption7days` | Number | Energy consumed last 7 days (Wh) |
| `consumptionwhLifetime` | Number | Lifetime energy consumed (Wh) |
| `netconsumptionwhLifetime` | Number | Lifetime net consumption (Wh) |

### Inverter Summary

| State ID | Type | Description |
|----------|------|-------------|
| `numberInverters` | Number | Number of active microinverters |

### Reading Timestamps

| State ID | Type | Description |
|----------|------|-------------|
| `readingTime` | Number | Timestamp of last Envoy data reading |
| `secsSinceReading` | Number | Seconds since the last data reading |

### Per-Phase Production (L1/L2/L3)

| State ID | Type | Description |
|----------|------|-------------|
| `productionWattsL1` | Number | Production on phase L1 (W) |
| `productionWattsL2` | Number | Production on phase L2 (W) |
| `productionWattsL3` | Number | Production on phase L3 (W) |
| `voltageL1` / `voltageL2` / `voltageL3` | Number | Line voltage per phase (V) |
| `currentL1` / `currentL2` / `currentL3` | Number | Current per phase (A) |
| `apparentPowerL1` / `apparentPowerL2` / `apparentPowerL3` | Number | Apparent power per phase (VA) |
| `powerFactorL1` / `powerFactorL2` / `powerFactorL3` | Number | Power factor per phase |
| `frequencyL1` / `frequencyL2` / `frequencyL3` | Number | Frequency per phase (Hz) |

> Per-phase states are only populated when `/ivp/meters/readings` returns data (metered systems with a token).

### Per-Phase Consumption (L1/L2/L3)

| State ID | Type | Description |
|----------|------|-------------|
| `consumptionWattsL1` | Number | Consumption on phase L1 (W) |
| `consumptionWattsL2` | Number | Consumption on phase L2 (W) |
| `consumptionWattsL3` | Number | Consumption on phase L3 (W) |

### Aggregate Meter Readings

| State ID | Type | Description |
|----------|------|-------------|
| `productionVoltage` | Number | Average production voltage (V, sum/channels) |
| `productionCurrent` | Number | Production current (A) |
| `productionPowerFactor` | Number | Production power factor |
| `productionFrequency` | Number | Production frequency (Hz) |
| `consumptionVoltage` | Number | Average consumption voltage (V) |
| `consumptionCurrent` | Number | Consumption current (A) |
| `consumptionPowerFactor` | Number | Consumption power factor |
| `consumptionFrequency` | Number | Consumption frequency (Hz) |
| `metersEnabled` | Boolean | True when meter readings are available |

### Storage (from production.json)

| State ID | Type | Description |
|----------|------|-------------|
| `storageActiveCount` | Number | Number of active storage units |
| `storageWattsNow` | Number | Aggregate battery power (W); positive = discharging, negative = charging |
| `storageState` | String | `idle`, `charging`, `discharging`, `full`, `Offline` |
| `storagePercentFull` | Number | Average battery state of charge (%) |

### Power Production Control

| State ID | Type | Description |
|----------|------|-------------|
| `powerProductionEnabled` | String | `Enabled`, `Disabled`, `Status Unavailable`, or `N/A – Installer Token Required` |

### DPEL (Dynamic Power Export Limiting)

| State ID | Type | Description |
|----------|------|-------------|
| `dpelEnabled` | String | `Enabled (Export Limit)`, `Enabled (Production Limit)`, `Disabled`, or `Status Unavailable` |
| `dpelLimitWatts` | Number | Current DPEL watt limit |

### Panel Tracking

| State ID | Type | Description |
|----------|------|-------------|
| `panelLastUpdated` | String | Datetime of last panel update |
| `panelLastUpdatedUTC` | Number | UTC epoch of last panel update |
| `panelDataSource` | String | Which endpoint(s) were used (e.g. `"devstatus+device_data"`) |

---

## EnphaseEnvoyLegacy States

| State ID | Type | Description |
|----------|------|-------------|
| `deviceIsOnline` | Boolean | Reachability |
| `deviceLastUpdated` | String | Last update timestamp |
| `powerStatus` | List | `offline`, `producing`, `idle`, `importing`, `exporting`, `neutral` |
| `wattsNow` | Number | Current production (W) |
| `wattHoursToday` | Number | Production today (Wh) |
| `wattHoursSevenDays` | Number | Production last 7 days (Wh) |
| `wattHoursLifetime` | Number | Lifetime production (Wh) |

---

## EnphasePanelDevice States

| State ID | Type | Description |
|----------|------|-------------|
| `deviceIsOnline` | Boolean | True when panel is communicating and data is fresh (<25 min) |
| `deviceLastUpdated` | String | Timestamp of last update |
| `watts` | Number | Current AC power output (W) — **primary display state** |
| `maxWatts` | Number | Highest watts ever seen for this panel |
| `serialNo` | Number | Microinverter serial number |
| `modelNo` | String | Inverter model (from inventory) |
| `status` | String | Device status string from inventory |
| `producing` | Boolean | True when the inverter is actively producing |
| `communicating` | Boolean | True when the inverter has checked in recently |
| `lastCommunication` | String | Date/time of last report (e.g. `"Mon May 26 14:28:00 2026"`) |
| `lastHeard` | String | Elapsed time since last report (e.g. `"8.42 mins"`, `"1hr 5.00mins"`) |
| `acFrequency` | Number | AC frequency (Hz) — from device_data |
| `acCurrent` | Number | AC current (A) — from device_data |
| `acVoltage` | Number | AC voltage (V) — from devstatus or device_data |
| `acPower` | Number | AC power (W) — from devstatus |
| `dcVoltage` | Number | DC input voltage (V) — from devstatus or device_data |
| `dcCurrent` | Number | DC input current (A) — from devstatus or device_data |
| `temperature` | Number | Inverter temperature (°C) — from devstatus or device_data |
| `wattHoursToday` | Number | Energy produced today by this panel (Wh) |
| `wattHoursWeek` | Number | Energy produced this week (Wh) |
| `lifetimeEnergy` | Number | Lifetime energy from this inverter (Wh) |

> Extended states (`temperature`, `dcVoltage`, `acFrequency`, etc.) require a token (any type). They are refreshed every **15 minutes**.

---

## EnphaseEnvoyBatteryDevice States

### Battery Summary

| State ID | Type | Description |
|----------|------|-------------|
| `deviceIsOnline` | Boolean | True when data is available |
| `deviceLastUpdated` | String | Last update timestamp |
| `batteryCount` | Number | Number of Encharge batteries found |
| `batteryState` | String | `idle`, `charging`, `discharging`, `offline`, `unknown` — **display state** |
| `batteryPercentFull` | Number | Average charge level across all batteries (%) |
| `batteryWattsNow` | Number | Aggregate battery power (W) |
| `batteryWhNow` | Number | Estimated energy stored (Wh) |
| `batteryTotalCapacityWh` | Number | Total installed capacity (Wh) |
| `batteryTotalkW` | Number | Total installed capacity (kW) |
| `batteryChargeWatts` | Number | Charge rate when charging (W), 0 otherwise |
| `batteryDischargeWatts` | Number | Discharge rate when discharging (W), 0 otherwise |
| `batteryTemperature` | Number | Average battery temperature (°C) |
| `batteryMaxCellTemp` | Number | Maximum cell temperature across all batteries (°C) |
| `batteryCommunicating` | Boolean | True when all batteries are communicating |
| `batteryOperating` | Boolean | True when all batteries are operating |
| `batterySerialNumbers` | String | Comma-separated list of battery serial numbers |
| `batteryFirmware` | String | Battery firmware version(s) |

### Grid

| State ID | Type | Description |
|----------|------|-------------|
| `gridStatus` | String | `Exporting`, `Importing`, `Neutral`, `Offline`, `Unknown` |
| `gridImportWatts` | Number | Watts being imported from grid (0 when exporting) |
| `gridExportWatts` | Number | Watts being exported to grid (0 when importing) |
| `gridNetWatts` | Number | Net grid flow (positive = import, negative = export) |

### Storage Settings (from `/admin/lib/tariff`)

| State ID | Type | Description |
|----------|------|-------------|
| `storageMode` | String | `self-consumption`, `savings`, `backup` |
| `chargeFromGrid` | Boolean | True when grid charging is enabled |
| `reserveSOC` | Number | Reserve state of charge percentage |

---

## EnphaseEnvoyCostDevice States

All monetary values are formatted as `$x,xxx.xx` strings.

| State ID | Type | Description |
|----------|------|-------------|
| `deviceIsOnline` | Boolean | Reachability |
| `deviceLastUpdated` | String | Last update |
| `productionkWToday` | Number | kWh produced today |
| `consumptionkWToday` | Number | kWh consumed today |
| `netkWToday` | Number | Net kWh today |
| `productionkW7days` | Number | kWh produced last 7 days |
| `consumptionkW7days` | Number | kWh consumed last 7 days |
| `netkW7days` | Number | Net kWh last 7 days |
| `productionkwhLifetime` | Number | Lifetime kWh produced |
| `consumptionkwhLifetime` | Number | Lifetime kWh consumed |
| `netconsumptionkwhLifetime` | Number | Lifetime net kWh |
| `productionTarrifToday` | String | Production earnings today |
| `consumptionTarrifToday` | String | Consumption cost today |
| `netTarrifToday` | String | Net cost/credit today |
| `productionTarrif7days` | String | Production earnings last 7 days |
| `consumptionTarrif7days` | String | Consumption cost last 7 days |
| `netTarrif7days` | String | Net cost/credit last 7 days |
| `productionTarrifLifetime` | String | Lifetime production earnings |
| `consumptionTarrifLifetime` | String | Lifetime consumption cost |
| `netconsumptionTarrifLifetime` | String | Lifetime net cost/credit |
