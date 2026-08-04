# Pylontech H3X Predictive Dispatch Dashboard

`h3x-predictive-dispatch.yaml` is the Lovelace dashboard for the standalone
predictive integration.

It shows:

- current and future dynamic electricity prices,
- current optimizer decision and reason,
- planned charge/discharge slots with grid-charge, solar-charge, self-consumption, and export split,
- estimated arbitrage value for today and for the active horizon,
- baseline-versus-optimized grid cost, modeled battery wear, action penalties, and planned equivalent cycles,
- Shelly/SMA load and solar readings when configured,
- historical load-learning, optional EV-analysis, Dutch tariff, risk, and anti-chatter controls,
- load forecast p10/p50/p90, solar, net-grid, price, dispatch, battery-power, and SOC charts,
- battery power and state-of-charge over time,
- Pylontech H3X Bridge controls and diagnostics.

## Requirements

1. Install `https://github.com/shuffleznl/pylontech-fh3x-bridge` through HACS.
2. Install `https://github.com/shuffleznl/h3x-predictive-dispatch` through HACS.
3. No custom Lovelace cards are required. The dashboard uses Home Assistant's native tile, entities, attribute, heading, grid, and history-graph cards.

## Install The YAML Dashboard

Predictive Dispatch `v0.2.3` and newer package the dashboard inside the
HACS-managed integration directory. Point Home Assistant directly at that copy
so future HACS upgrades refresh the dashboard automatically:

```text
config/custom_components/h3x_predictive_dispatch/dashboards/h3x-predictive-dispatch.yaml
```

Then add this to `configuration.yaml`:

```yaml
lovelace:
  mode: storage
  dashboards:
    h3x-predictive-dispatch:
      mode: yaml
      title: H3X Predictive Dispatch
      icon: mdi:battery-charging-70
      show_in_sidebar: true
      filename: custom_components/h3x_predictive_dispatch/dashboards/h3x-predictive-dispatch.yaml
```

Restart Home Assistant after changing the filename. After later HACS upgrades,
refresh the browser once the integration files have been replaced.

## Planned Slot Display

The optimizer exposes a full `dispatch_plan` with one row per price interval. The native dashboard avoids template-generated Markdown/HTML tables and instead uses structured entity and attribute rows for the active/next charge, active/next discharge, and periodic full-charge schedule. Open a slot entity's More Info dialog for all remaining attributes.

Planned values can change when Nord Pool publishes new prices, the battery SOC changes, the house load changes, the SMA/PV forecast changes, or grid-limit sensors update.

## PV And Load Display

The dashboard requires `h3x_predictive_dispatch` `0.2.3` or newer. If
historical data has not accumulated yet, the optimizer uses its live-load
fallback and forecast-quality cards remain unavailable until Recorder has
enough samples.

## Entity IDs

The dashboard assumes the default entity IDs created by:

- `pylontech_h3x_bridge`
- `h3x_predictive_dispatch`

For the predictive integration, Home Assistant prefixes entities with the
device name by default, for example
`sensor.pylontech_h3x_predictive_dispatch_decision` and
`sensor.pylontech_h3x_predictive_dispatch_price_plan`.

If Home Assistant adds suffixes such as `_2`, edit the dashboard YAML and replace the entity IDs.
