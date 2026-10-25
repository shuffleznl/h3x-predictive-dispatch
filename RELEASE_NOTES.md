# Predictive Dispatch 0.2.12

- Pause optimizer writes while H3X Bridge owns a manual or KNMI weather-reserve override; clear command caches before resuming.
- Add Force Charge/rate, charge-method, warning-threshold, emergency discharge and measured-response controls to both repository and HACS-packaged dashboards.
- Use native Home Assistant sections: settings above usage/savings/power histories, with statistics and diagnostics below.
- Update bridge contract checks and documentation. Dashboard entity checks, forecast/tariff/control validators and economic simulations pass.

Requires H3X Bridge 0.4.0 and Home Assistant 2025.3 or newer. Configure KNMI/Shelly/siren entities on the bridge. Refresh storage-mode dashboards from `custom_components/h3x_predictive_dispatch/dashboards/h3x-predictive-dispatch.yaml`; YAML mode referencing that file follows HACS package updates automatically.
