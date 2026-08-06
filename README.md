# Pylontech H3X Predictive Dispatch

Home Assistant custom integration for Nord Pool driven charge/discharge decisions for a Pylontech Force H3X system.

This standalone repository is the coexistence build of the ground-up predictive
optimizer redesign. Home Assistant I/O remains in the coordinator, while
historical forecasting, tariff transformation, and model-predictive dispatch
are independent modules that can be simulated without Home Assistant or live
Modbus hardware.

This repository contains one HACS integration:

| Integration | Domain | Purpose |
| --- | --- | --- |
| Pylontech H3X Predictive Dispatch | `h3x_predictive_dispatch` | Ingest Nord Pool prices, compute battery arbitrage decisions, and optionally control Pylontech H3X Bridge entities. |

## Requirements

- Home Assistant `2024.12.0` or newer.
- HACS.
- Nord Pool integration configured in Home Assistant.
- Pylontech H3X Bridge installed from `https://github.com/shuffleznl/pylontech-fh3x-bridge`.
- Optional but recommended for self-consumption optimization: Shelly Pro 3EM power sensors, an SMA Sunny Boy PV power sensor, and a Solcast rooftop forecast API key.

## Predictive Dispatch Architecture

The controller recalculates a rolling schedule every five minutes over every published Nord Pool slot, normally 36 hours. It does not rely on fixed charge windows.

1. Home Assistant Recorder supplies up to 28 days of five-minute Shelly/home-load statistics, aggregated into local 15-minute quarters.
2. A robust recency-weighted forecast learns quarter-hour and weekday/weekend patterns. Median demand drives the plan; p10/p90 bands represent observed variability, and the current load residual is blended out over two hours.
3. EV analysis is selectable: `off`, automatic rectangular-load detection, or a dedicated EV charger power sensor. Detected EV power is separated from heat pumps, water heaters, HVAC and normal household demand, then added back as a probability-weighted session forecast.
4. PV is modeled from Home Assistant latitude/longitude, panel count, Wp, inverter cap and one of eight compass orientations. Current SMA AC power calibrates the near-term curve. The optimizer carries a wider uncertainty band when no live calibration is available.
5. Dutch retail import is derived from Nord Pool wholesale price plus configurable supplier markup and energy tax, then VAT. Export is modeled separately and never receives the import energy-tax credit.
6. A dynamic program minimizes expected grid cost plus forecast-tail risk, conversion losses, battery throughput cost, minimum profit margin, action-start cost and direction-change cost. SOC, C-rate, inverter power, import/export limits, minimum action duration, temperature permissions and terminal SOC are hard constraints.
7. Only the current slot is dispatched. New measurements or prices cause a complete re-optimization, which is model-predictive control rather than a once-daily schedule.

This follows the operational strengths visible in [ChargeIQ](https://github.com/johanzander/bess-manager), [Predbat](https://github.com/springfall2008/batpred), and [EMHASS](https://github.com/davidusb-geek/emhass): explicit counterfactual cost, degradation-aware optimization, forecast-vs-actual diagnostics, fuse protection and continuous re-planning. The implementation remains a native HACS integration and does not require a separate add-on or cloud service.

The controller calls the Nord Pool `get_price_indices_for_date` service, falls back to `get_prices_for_date` when custom-resolution indices are empty, reads the Pylontech H3X Bridge sensors, and writes the Pylontech H3X Bridge EMS mode and charge/discharge power entities when automatic control is enabled.

The Nord Pool config entry is resolved automatically at runtime. If Home Assistant recreates the Nord Pool entry during an update, the controller falls back from the old stored entry ID to the current entry instead of returning empty price slots.

## Load-Forecast Economic Simulation

A controlled simulation was run to determine whether household-load forecasting adds enough economic value to justify its complexity, or whether a simpler PV/price policy with fewer battery cycles performs just as well. Every policy received the same price and PV information; only its knowledge of future household demand changed.

### Inputs And Assumptions

- 672 actual Dutch quarter-hour day-ahead prices for 27 July through 2 August 2026 from the [Fraunhofer Energy-Charts API](https://api.energy-charts.info/price?bzn=NL&start=2026-07-27&end=2026-08-02). Wholesale prices ranged from `-0.00452 EUR/kWh` to `0.33901 EUR/kWh`.
- A six-module Force H3 battery with a `21.85 kWh` modeled operating span, `11 kW` charge/discharge power and `90%` round-trip efficiency.
- The integration's Dutch retail tariff transformation and `0.035 EUR/kWh` modeled battery cycle cost.
- A synthetic electrified-home load profile totaling `255.5 kWh/week`, containing morning and evening demand, heat-pump background load, random appliance/water-heating events and measurement noise.
- A synthetic modest PV installation producing `78.5 kWh/week`, with different cloud factors per day. PV generation was identical for all policies so the experiment isolated load-forecast value.
- Initial and terminal battery energy were both `15 kWh`, preventing a policy from reporting artificial savings by simply emptying the battery at the end.

The simulation supplied the complete price week to every policy, rather than reproducing the integration's rolling 36-hour information boundary. Its absolute savings should therefore be treated as an optimistic controlled comparison, not an annual return forecast. The load and PV profiles are representative synthetic data, not Recorder data from this installation. Fixed charges, the annual tax rebate, inverter standby consumption and supplier-specific export restrictions were excluded.

### Results

Net savings are electricity-bill savings after modeled battery wear. Equivalent full cycles (`EFC`) use the modeled `21.85 kWh` operating span. A charge/discharge window is one contiguous non-idle action and is not itself a full cycle.

| Policy | Net savings/week | EFC/week | Charge/discharge windows |
| --- | ---: | ---: | ---: |
| Perfect household-load foresight | `17.91 EUR` | `5.72` | `20` |
| Historical morning/evening load profile | `17.13 EUR` | `5.69` | `19` |
| Flat average household load | `14.14 EUR` | `5.15` | `14` |
| Optimized price/PV policy with no load knowledge | `8.46 EUR` | `3.50` | `10` |
| PV-only charging with one daily peak discharge period | `7.23 EUR` | `1.15` | `20` |

The historical quarter-hour pattern retained `95.7%` of the perfect-foresight savings. Perfect appliance-level prediction was worth only another `0.78 EUR` during this test week, while replacing the historical shape with one flat average lost `2.99 EUR`. Removing load knowledge entirely lost `8.67 EUR`, approximately half the forecast-aware result.

The main cause is Dutch tariff asymmetry. Battery energy used behind the meter can avoid the wholesale import price, energy tax, supplier markup and VAT. Export normally earns only the export tariff. A load-unaware controller can therefore export stored energy during a wholesale peak and later repurchase taxed electricity for household demand. A coarse load forecast helps retain the right amount of energy for morning/evening self-consumption without requiring exact appliance prediction.

### Fewer-Cycle Sensitivity

The historical-profile policy was rerun with stronger action-start and direction-change penalties plus a longer minimum action duration:

| Setting | Net savings/week | EFC/week | Charge/discharge windows |
| --- | ---: | ---: | ---: |
| Current-style anti-chatter settings | `17.13 EUR` | `5.69` | `19` |
| Moderate anti-cycling settings | `16.98 EUR` | `5.49` | `15` |

Moderate anti-cycling removed `21%` of action windows and reduced throughput by about `3.5%`, while sacrificing only `0.15 EUR`, or `0.9%`, of net savings. Raising the penalties further produced the same schedule, indicating that the remaining cycles cleared a meaningful economic threshold.

### Interpretation

- Retain a coarse Recorder-trained weekday/weekend and quarter-hour load forecast. It materially improves energy reservation for taxed self-consumption.
- Keep live-load correction and rolling re-optimization. With a large `30 kWh` battery, these feedback mechanisms make precise appliance-level forecasting less valuable.
- Prefer explicit minimum-duration, action-start, direction-change and minimum-profit constraints over deleting load forecasting as a way to reduce battery activity.
- Do not infer annual savings from this one volatile summer week. A trustworthy site-specific decision requires replaying at least one year of actual Shelly load, SMA PV, Nord Pool prices and realized battery behavior.

Related Home Assistant energy optimizers provide useful reference points. [Predbat documentation](https://springfall2008.github.io/batpred/) describes battery/PV prediction, actual-versus-predicted calibration, cost tracking and automatic re-planning. [EMHASS documentation](https://emhass.readthedocs.io/en/latest/) describes a configurable linear-programming energy manager with load/PV forecasts, batteries, deferrable loads and model-predictive operation. Broader forecasting evidence includes [Using solar and load predictions in battery scheduling at the residential level](https://arxiv.org/abs/1810.11178) and Stanford's [Home Battery Dispatch under a Tiered Peak Power Tariff](https://web.stanford.edu/~boyd/papers/hbd.html). These projects and studies informed the comparison criteria; this integration does not copy their control code and the results above are not cross-project benchmarks.

## HACS Installation

1. In HACS, add `https://github.com/shuffleznl/h3x-predictive-dispatch` as a custom repository of type **Integration**.
2. Install **Pylontech H3X Predictive Dispatch**.
3. Restart Home Assistant.
4. Go to **Settings > Devices & services > Add integration**.
5. Add **Pylontech H3X Predictive Dispatch** and review the detected Nord Pool area and Pylontech H3X Bridge entity IDs.

## Dashboard Updates

Version `0.2.9` and newer package the matching entity-validated native-card dashboard at `config/custom_components/h3x_predictive_dispatch/dashboards/h3x-predictive-dispatch.yaml`. Point a YAML dashboard at that file once so subsequent Predictive Dispatch upgrades installed by HACS also refresh the dashboard source.

The configured Nord Pool resolution is persisted as `15`, `30`, or `60` minutes. The price-resolution sensor reports the active slot duration when prices are available and falls back to the configured resolution during startup or a failsafe update.

## Safe First Run

Set **Enable automatic control** to off for the first run. The integration will still compute and expose decisions, prices, planned charge/discharge energy, and estimated value, but it will not write to the H3X entities.

After the decision sensors look correct, enable automatic control from the integration options.

### Parallel-operation safety

`h3x_predictive_dispatch` can be installed and calculate schedules alongside
the earlier `h3x_energy_arbitrage` integration because its domain, config entry,
device, unique IDs, and entity namespace are separate. Both integrations still
target the same Pylontech bridge actuator entities. Keep automatic control
disabled in at least one integration at all times; enabling both controllers can
make them overwrite each other's EMS mode and power reference every update.

## Default Controlled Entities

| Purpose | Default entity |
| --- | --- |
| EMS mode | `select.pylontech_h3x_bridge_ems_mode` |
| Charge/discharge power | `number.pylontech_h3x_bridge_charge_discharge_power_ref` |
| Battery SOC | `sensor.pylontech_h3x_bridge_battery_soc` |
| House load | `sensor.pylontech_h3x_bridge_load_power` |
| Real-time grid import/export | Auto-detected Shelly Pro 3EM `total_active_power`, or the configured signed Shelly grid sensor. |
| Grid import trend | Derived internally from the selected Shelly Pro 3EM source and Home Assistant Recorder. |
| Battery module count | `sensor.pylontech_h3x_bridge_battery_module_count` |
| Battery system capacity | `sensor.pylontech_h3x_bridge_battery_system_capacity` |
| Battery usable capacity | `sensor.pylontech_h3x_bridge_battery_usable_capacity` |
| BMS temperature | `sensor.pylontech_h3x_bridge_bms_temperature` |
| Charge SOC limit | `number.pylontech_h3x_bridge_charge_limit_soc` |
| Discharge SOC limit | `number.pylontech_h3x_bridge_discharge_limit_soc_eps` |

## Optional Load And PV Inputs

Shelly and SMA entity IDs are generated from the device names in Home Assistant, so the integration leaves these inputs configurable instead of assuming one fixed entity name.

| Purpose | Recommended input |
| --- | --- |
| Shelly Pro 3EM grid power | Set **Shelly Pro 3EM grid total active power sensor entity (signed)** to the meter at the grid connection. Positive values are import and negative values are export. New entries auto-detect a Shelly `total_active_power` entity when its name identifies it clearly. |
| Shelly Pro 3EM household load | Set the optional household-load total sensor only when its CT placement measures household consumption rather than net grid flow. |
| Shelly Pro 3EM per-phase household load | If no total household-load sensor is available, set all phase A/B/C active-power sensors. The controller sums available load phases; grid-limit fallback requires all three phases. |
| SMA Sunny Boy PV power | Set **SMA Sunny Boy current PV power sensor entity** to the SMA `pv_power` sensor. Version 0.2.5 auto-detects one unambiguous, available SMA `pv_power` entity and replaces a stale saved selection during migration. |
| Solar forecast | Choose `auto`, `solcast`, or `panel_model`. Configure the API key in integration options. Hobbyist accounts should also provide their rooftop resource ID; leaving it blank uses Solcast's location-based rooftop endpoint when the account permits it. |
| EV charger power | Optional. Select EV mode `sensor` and set the EV power entity for the cleanest session forecast and live discharge blocking; `detect` learns repeated high rectangular loads from total home power. |
| PV orientation | Select one of `N`, `NE`, `E`, `SE`, `S`, `SW`, `W`, or `NW`. |
| PV size | Set panel count and Wp rating. A zero panel count disables the internal PV forecast. |
| PV inverter cap | Defaults to `2000 W` for a Sunny Boy 2.0 style setup; adjust if the inverter or export limit differs. |

The Home Assistant [SMA Solar integration](https://www.home-assistant.io/integrations/sma) exposes `pv_power` as current AC-side solar power, and the [Shelly integration](https://www.home-assistant.io/integrations/shelly/) communicates locally with the device. Home Assistant Recorder short-term statistics train the load model and derive the grid-import average/trend locally; no consumption history leaves Home Assistant. Solcast requests include only the configured rooftop resource ID or Home Assistant location and PV configuration.

## EV Forecast And Discharge Policy

EV mode controls how charger demand is identified:

- `off`: EV demand remains ordinary household load and no EV-specific discharge protection can activate.
- `detect`: repeated, sustained demand above the learned household baseline is treated as an EV session. This is a statistical fallback and is less reliable for immediate control.
- `sensor`: the configured charger power sensor is authoritative. Use this mode when the charger exposes current power.

The **EV detection threshold** is the minimum EV power that counts as active charging. In `sensor` mode it applies directly to the charger sensor; in `detect` mode it applies to excess power above the learned household baseline. The default `2800 W` rejects standby noise and many unrelated loads, but it can miss low-current single-phase charging. Set it below the charger's lowest real charging power and above its idle/standby value. For example, `500-1000 W` is usually more appropriate when a dedicated, clean charger sensor is available.

When **Block battery discharge while EV charging** is enabled, predicted EV intervals are marked unavailable for discharge and a live charger reading at or above the threshold stops an active discharge immediately. Charging the battery remains possible when prices justify it and the configured grid-import limit has enough headroom. EV demand remains in total grid-cost and fuse-limit calculations, but it is subtracted from the separate battery-supported-load diagnostic.

## Runtime Controls

The integration exposes Home Assistant control entities so the strategy can be adjusted without opening the full options form:

- `select.pylontech_h3x_predictive_dispatch_strategy_profile`: `conservative`, `typical`, `spread`, `aggressive`, or `custom`.
- `select.pylontech_h3x_predictive_dispatch_load_forecast_mode`: use Recorder history or the live flat fallback.
- `select.pylontech_h3x_predictive_dispatch_ev_forecast_mode`: `off`, automatic detection, or a dedicated EV power sensor.
- `switch.pylontech_h3x_predictive_dispatch_ev_discharge_block`: prevent battery discharge during measured or forecast EV charging intervals.
- `number.pylontech_h3x_predictive_dispatch_ev_detection_threshold`: minimum charger or detected excess power counted as active EV charging.
- `switch.pylontech_h3x_predictive_dispatch_dutch_retail_tariff`: apply the Dutch retail transformation to Nord Pool wholesale prices.
- Load-history, EV threshold, forecast-risk, minimum-duration, start-penalty and direction-change number controls expose the model assumptions at runtime.
- VAT, energy tax, supplier import markup and supplier export deduction controls keep yearly contract changes user-adjustable.
- `select.pylontech_h3x_predictive_dispatch_end_of_horizon_soc`: preserve the current SOC by the end of the horizon, or allow discharge down to reserve.
- `select.pylontech_h3x_predictive_dispatch_discharge_power_mode`: spread discharge over adjacent high-price slots, or keep the maximum economic target power.
- `number.pylontech_h3x_predictive_dispatch_battery_module_count`: set the installed Force H3 module count when it is not available from a bridge sensor.
- `switch.pylontech_h3x_predictive_dispatch_periodic_full_charge`: enable or disable the periodic full-charge constraint.
- `number.pylontech_h3x_predictive_dispatch_periodic_full_charge_interval`, `target_soc`, and `threshold_soc`: tune the periodic full-charge cadence and completion threshold.
- `number.pylontech_h3x_predictive_dispatch_discharge_spread_price_tolerance` and `discharge_spread_max_hours`: tune how far and how long discharge can be spread.
- `number.pylontech_h3x_predictive_dispatch_maximum_charge_c_rate` and `maximum_discharge_c_rate`: cap battery current demand from usable capacity. The range is `0.05C` to `0.5C`.
- `select.pylontech_h3x_predictive_dispatch_pv_orientation`: set the basic PV plane orientation.
- `number.pylontech_h3x_predictive_dispatch_pv_panel_count`, `pv_panel_wp_rating`, and `pv_inverter_limit`: tune the internal PV generation forecast.

Strategy profiles apply these tradeoffs:

- `conservative`: preserve current SOC, keep periodic full charge enabled, spread discharge over a wider price band, use a higher profit margin, lower normal maximum SOC, disable peak power, and cap charge/discharge at `0.35C`.
- `typical`: balanced default behavior with discharge spread across nearby high-price slots when prices are within 10% of the current expensive slot, charge capped at `0.5C`, and discharge capped at `0.45C`.
- `spread`: use lower charge/discharge power, longer minimum action windows, and a `0.3C` discharge cap to distribute profitable energy over broader morning/evening peaks.
- `aggressive`: prioritize estimated savings by allowing reserve-only end-of-horizon behavior, disabling periodic full-charge forcing, allowing 100% maximum SOC, using maximum economic discharge power, removing extra profit margin, and allowing up to `0.5C`. This is economically aggressive and less battery-conservative.

## Economics And Limits

The optimizer supports:

- 15, 30, and 60 minute price slots,
- Force H3 module-count based system and usable battery capacity, minimum SOC, reserve SOC, maximum SOC, and terminal SOC behavior,
- periodic full-charge/top-balance cycle scheduled into the cheapest available slots,
- round-trip efficiency,
- cycle cost and minimum margin,
- buy-side and sell-side tariff adders,
- continuous, peak, and C-rate based power limits,
- house load aware grid import/export caps,
- real-time grid import plus an internally calculated 15-minute Recorder average and trend for charging guards,
- optional Shelly load and SMA solar power inputs,
- internal PV forecast from orientation, panel count, Wp rating, inverter cap, and current SMA power,
- self-consumption value: discharge avoids household import before exporting, and charge uses forecast PV surplus before grid energy,
- profile-controlled power candidates and minimum action duration inside the optimizer,
- p10/p50/p90 historical load and PV uncertainty with configurable risk percentile,
- explicit action-start and charge/discharge direction-change penalties to reject short marginal cycles,
- baseline-versus-optimized grid cost, modeled wear cost and planned equivalent full-cycle diagnostics,
- BMS temperature guards for LiFePO4 charging.

**Forecast risk percentile** controls how much the optimizer prices uncertainty rather than changing the forecast itself. At `50%`, it minimizes the weighted expected cost across low, median, and high net-load scenarios. Values toward `90%` increasingly add the most expensive scenario, which favors retaining energy for unexpectedly high load or low solar production. Import/export feasibility remains conservatively checked against p90 load and p10 solar at every setting.

Default power settings are `11 kW` continuous and `13.8 kW` peak, with peak power only used when the price spread clears the configured extra margin. C-rate and dedicated-circuit caps are applied after those economic limits: for a 6-module pack with `29.17 kWh` usable capacity, `0.5C` is `14.6 kW`, while the default `3x20 A` battery circuit limits the final setpoint to `13.8 kW`.

### Electrical Ratings

**Grid connection rating** is selected from common European single- and three-phase residential services. The default is the modern Dutch standard `3x25 A`, equivalent to `17.25 kW` nominal at `230 V` per phase. This deployment should select `3x40 A`, equivalent to `27.6 kW`. The selected connection rating is the physical aggregate import and export limit; the optional export cap can impose a lower contractual limit, and `0 W` means use the connection rating.

**Battery circuit rating** is independent of the main connection and caps both H3X charge and discharge. This deployment should select `3x20 A`, equivalent to `13.8 kW`. The circuit cap is combined with the inverter, economic and C-rate limits by taking the lowest applicable value. Choose `custom` only for a nonstandard installation, then set the corresponding custom watt control.

Legacy entries are migrated conservatively: an existing `17.5 kW` grid limit becomes `3x25 A`; values not within 5% of a standard rating remain `custom`. The calculation uses nominal aggregate real power at unity power factor: `phases x 230 V x amperes`. Aggregate power cannot detect one overloaded phase in an unbalanced installation, so upstream protective devices and the installer's phase design remain authoritative.

Charging is not intentionally spread across many hours. The rolling optimizer charges at the cheapest economic speed needed to support later household consumption or export, capped by inverter power, the configured charge C-rate, BMS temperature, SOC limits, and the grid import limit. When a slot contains both PV surplus and economically justified grid energy, the live target combines the measured PV surplus with only the grid-charge component selected by the optimizer. If PV falls, that economic grid component continues; lost PV is not blindly replaced with uneconomic grid energy.

Night-to-morning dispatch is evaluated automatically rather than enabled by a clock schedule. Morning self-consumption compares the taxed retail import avoided against night charging cost, efficiency loss, modeled battery wear, profit margin, and action penalties. Export arbitrage compares the same night import cost against the lower export tariff, which normally excludes import energy tax; it therefore needs a substantially larger wholesale spread. Deterministic Dutch-tariff simulations verify that a `0.01 EUR/kWh` night wholesale price followed by `0.16 EUR/kWh` in the morning charges for a `3 kW` household load, but does not charge solely to export. With the same night price, a `0.32 EUR/kWh` morning export price does clear the modeled costs and produces an export cycle.

The default tariff model uses the official 2026 first-band electricity tax of `0.09161 EUR/kWh` excluding VAT and applies `21%` VAT to imported energy. The fixed annual tax reduction is excluded because battery dispatch cannot change it. Confirm supplier-specific import markup, export deduction, and any contractual battery-export restrictions in the integration options.

Charging headroom is calculated continuously. A configured live grid meter is preferred and the internal time-weighted 15-minute average guards against a transient low reading; the current battery charge command is accounted for so repeated updates do not progressively reduce the same target. Household load is used only when the grid meter is unavailable.

Because the SMA PV inverter and Pylontech battery inverter are separate AC systems, H3X self-consumption mode cannot infer SMA surplus. For a `solar_storage` slot the controller therefore issues an explicit H3X charge command capped by live SMA power minus live home load and a safety margin. If measured surplus falls below minimum active power, a purely solar charge idles; an independently economic grid-charge component continues. Solcast affects future planning; the live SMA and load readings govern the current surplus-following component.

Solcast forecasts are cached across Home Assistant restarts and refresh every six hours by default, keeping hobbyist usage below the published daily request allowance. A valid cached forecast survives temporary API failures. `auto` falls back to the local panel/orientation model when Solcast is not configured or unavailable.

Shelly Pro 3EM `total_active_power` is signed at the grid connection. The controller preserves its sign while reading the source, treats positive power as import, and clamps negative export to `0 W` only for import-limit calculations. If a configured grid entity is unavailable, it falls back to the configured Shelly total and then to the sum of all three configured phase sensors. Auto-detection uses Home Assistant's entity registry and the Shelly `total_act_power` unique ID, so renaming the entity does not hide it. Multiple matching Shelly grid meters are intentionally treated as ambiguous and require explicit selection. Use the Shelly grid diagnostics status sensor to distinguish `recorder_history`, `live_only`, `entity_unavailable`, and `shelly_meter_not_configured`; its attributes include the selected source, entity IDs, sample count, sample span, and import limit.

Discharge duration is decided inside the optimizer. The `conservative`, `typical`, and `aggressive` profiles change power candidates, terminal reserve, forecast risk, minimum action duration, and action penalties. A larger battery can therefore support both morning and evening peaks when two independent cycles remain profitable after losses and wear, while flat or marginal price spreads remain idle.

## Dutch Tariff Defaults

The branch defaults to the 2026 Dutch first-band electricity tax of `0.09161 EUR/kWh` excluding VAT, `21%` VAT, and a configurable `0.02 EUR/kWh` supplier import markup. The fixed annual energy-tax rebate is excluded because battery dispatch cannot change it. Retail contract terms differ, so verify the supplier markup and export deduction against the current Zonneplan contract before enabling control. Tax and VAT defaults are assumptions, not an auto-updating tax service.

## Battery Capacity

Force H3 capacity is modeled by module count, not by an arbitrary kWh default. The Pylontech Force H3 datasheet lists each FH10050 module as `5.12 kWh`; one inverter stack supports `2` to `7` modules. The optimizer displays both system capacity and usable capacity, but all SOC-to-energy math uses usable capacity so discharge/charge plans do not assume the hidden reserve is available.

| Modules | System capacity | Usable capacity |
| --- | --- | --- |
| 2 | 10.24 kWh | 9.69 kWh |
| 3 | 15.36 kWh | 14.73 kWh |
| 4 | 20.48 kWh | 19.48 kWh |
| 5 | 25.60 kWh | 24.32 kWh |
| 6 | 30.72 kWh | 29.17 kWh |
| 7 | 35.84 kWh | 34.01 kWh |

Your current target system is `6` modules, therefore `30.72 kWh` system capacity and `29.17 kWh` usable capacity. The older `20 kWh` default was only a scaffold value and was not read from the inverter or BMS.

The Pylontech Modbus documentation includes a BMS/ESS register for "Module number in series" at offset `0x0036`; with ESS base address `0x1400`, this is register `0x1436` / decimal `5174` on the BMS side. The arbitrage integration does not open its own Modbus connection. Instead, it consumes `sensor.pylontech_h3x_bridge_battery_module_count`, `sensor.pylontech_h3x_bridge_battery_system_capacity`, and `sensor.pylontech_h3x_bridge_battery_usable_capacity` when the bridge exposes those values. Until those sensors exist, set the module count manually in the integration options or with the runtime number entity; the system and usable capacity values are derived from the datasheet table.

Capacity is safety-critical for this optimizer. If the module count is too low, the controller underestimates available energy and may miss profitable discharge/charge windows. If it is too high, it can overestimate energy above reserve and plan charge/discharge energy the physical battery cannot deliver. The usable capacity is validated against both the datasheet table and the datasheet `95%` depth-of-discharge basis, with roughly `5%` tolerance. Existing installs that still have only the old non-multiple capacity value will raise a Home Assistant repair warning until the module count is confirmed.

## Periodic Full Charge

LiFePO4 packs are normally happier cycling below 100% SOC, but the BMS may need an occasional full charge for top balancing and SOC calibration. The integration therefore defaults to one 100% target every 7 days, counted complete when the SOC sensor reaches 99%.

When the full-charge interval is due, the optimizer temporarily raises the charge SOC limit to the configured target and adds that energy requirement to the price plan. It still uses Nord Pool pricing, so the extra charge is placed in the cheapest available slot inside the configured horizon instead of at a fixed clock time. After the threshold is reached, the timestamp is stored in Home Assistant storage and the normal maximum SOC limit is restored on the next control pass.

## Charging Caveat

This controller writes through Pylontech H3X Bridge. If discharging works but grid charging does not, verify the H3X inverter configuration first: Work Mode `P5` charge/discharge time control or another grid-charge-capable mode, Power from Grid/import limit, charge SOC limit, BMS state, and meter configuration.

## Nord Pool Update Caveat

If current price is `unknown` after updating or recreating the Nord Pool integration, check the `Decision` sensor attributes for `price_fetch_errors`. Capacity sensors should still stay populated from the bridge or module-count fallback even when price fetching is temporarily unavailable.

## Exposed Sensors

- `sensor.pylontech_h3x_predictive_dispatch_decision`
- `sensor.pylontech_h3x_predictive_dispatch_target_power`
- `sensor.pylontech_h3x_predictive_dispatch_target_power_percent`
- `sensor.pylontech_h3x_predictive_dispatch_battery_system_capacity`
- `sensor.pylontech_h3x_predictive_dispatch_battery_usable_capacity`
- `sensor.pylontech_h3x_predictive_dispatch_target_c_rate`
- `sensor.pylontech_h3x_predictive_dispatch_home_load_power`
- `sensor.pylontech_h3x_predictive_dispatch_ev_charger_power`
- `sensor.pylontech_h3x_predictive_dispatch_battery_supported_load_power`
- `sensor.pylontech_h3x_predictive_dispatch_ev_discharge_status`
- `sensor.pylontech_h3x_predictive_dispatch_solar_power`
- `sensor.pylontech_h3x_predictive_dispatch_economic_grid_charge_power`
- `sensor.pylontech_h3x_predictive_dispatch_live_solar_surplus_power`
- `sensor.pylontech_h3x_predictive_dispatch_grid_net_power` (positive import, negative export)
- `sensor.pylontech_h3x_predictive_dispatch_grid_import_power` (non-negative import guard value)
- `sensor.pylontech_h3x_predictive_dispatch_grid_import_15_minute_average`
- `sensor.pylontech_h3x_predictive_dispatch_grid_import_trend`
- `sensor.pylontech_h3x_predictive_dispatch_grid_charge_headroom`
- `sensor.pylontech_h3x_predictive_dispatch_grid_diagnostics_status`
- `sensor.pylontech_h3x_predictive_dispatch_forecast_load_power`
- `sensor.pylontech_h3x_predictive_dispatch_forecast_solar_power`
- `sensor.pylontech_h3x_predictive_dispatch_next_charge_slot`
- `sensor.pylontech_h3x_predictive_dispatch_next_discharge_slot`
- `sensor.pylontech_h3x_predictive_dispatch_periodic_full_charge_slot`
- `sensor.pylontech_h3x_predictive_dispatch_current_price`
- `sensor.pylontech_h3x_predictive_dispatch_price_trend`
- `sensor.pylontech_h3x_predictive_dispatch_decision_reason`
- `sensor.pylontech_h3x_predictive_dispatch_first_slot_value`
- `sensor.pylontech_h3x_predictive_dispatch_estimated_savings`
- `sensor.pylontech_h3x_predictive_dispatch_estimated_savings_today`
- `sensor.pylontech_h3x_predictive_dispatch_baseline_grid_cost`
- `sensor.pylontech_h3x_predictive_dispatch_optimized_grid_cost`
- `sensor.pylontech_h3x_predictive_dispatch_modeled_cycle_cost`
- `sensor.pylontech_h3x_predictive_dispatch_modeled_transition_cost`
- `sensor.pylontech_h3x_predictive_dispatch_load_forecast_mae`
- `sensor.pylontech_h3x_predictive_dispatch_planned_equivalent_full_cycles`
- `sensor.pylontech_h3x_predictive_dispatch_planned_charge_energy`
- `sensor.pylontech_h3x_predictive_dispatch_planned_discharge_energy`
- `sensor.pylontech_h3x_predictive_dispatch_planned_grid_charge_energy`
- `sensor.pylontech_h3x_predictive_dispatch_planned_solar_charge_energy`
- `sensor.pylontech_h3x_predictive_dispatch_planned_self_consumption_energy`
- `sensor.pylontech_h3x_predictive_dispatch_planned_battery_export_energy`
- `sensor.pylontech_h3x_predictive_dispatch_forecast_load_energy`
- `sensor.pylontech_h3x_predictive_dispatch_forecast_solar_energy`
- `sensor.pylontech_h3x_predictive_dispatch_price_plan`
- `sensor.pylontech_h3x_predictive_dispatch_price_resolution`
- `sensor.pylontech_h3x_predictive_dispatch_price_slots_available`

The `next_charge_slot`, `next_discharge_slot`, and `periodic_full_charge_slot` sensors expose the first planned slot as the state and keep `start`, `end`, `energy_kwh`, `target_power_w`, `price`, `value`, `grid_charge_kwh`, `solar_charge_kwh`, `self_consumption_kwh`, and `battery_export_kwh` in attributes.

Live load and solar sensors are measurements at the current update. The forecast load and solar sensors represent the next price interval, not the calibrated current interval; the decision attributes expose that interval's start and end. Current economic grid-charge power and measured solar surplus are always present on the decision entity, including as `0 W` when inactive, instead of appearing only on a current solar-charge plan row.

The `price_plan` sensor is a unitless diagnostic carrier for Lovelace charting. It carries `price_slots`, `price_trend`, `load_forecast`, `solar_forecast`, and `dispatch_plan` attributes, and those large chart arrays are excluded from recorder history to keep the Home Assistant database small. `price_trend` is a rolling trendline over the price slots with `trend_price`, `delta_next`, and `trend_direction` values. Currency values use the resolved Nord Pool ISO 4217 currency code, for example `EUR` or `DKK`.

## Validation

Run local validation with `uv`:

```powershell
$env:UV_PYTHON_INSTALL_DIR='.uv-python'
uv --cache-dir .uv-cache run --python 3.13 python -m compileall custom_components tools
uv --cache-dir .uv-cache run --python 3.13 python tools/validate_hacs_structure.py
uv --cache-dir .uv-cache run --python 3.13 python tools/validate_sensor_metadata.py
uv --cache-dir .uv-cache run --python 3.13 python tools/validate_periodic_full_charge.py
uv --cache-dir .uv-cache run --python 3.13 python tools/validate_control_entities.py
uv --cache-dir .uv-cache run --python 3.13 python tools/validate_solar_self_consumption.py
uv --cache-dir .uv-cache run --python 3.13 python tools/validate_predictive_dispatch.py
uv --cache-dir .uv-cache run --python 3.13 --with pyyaml==6.0.2 python tools/validate_predictive_dashboard.py
```
