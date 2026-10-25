# Predictive Dispatch 0.2.13

- Require H3X Bridge 0.4.1 for stable override/weather dashboard IDs and actionable force-charge errors.
- Show available charging headroom, grid load excluding the battery, signed register read-back and last-command verification in repository and HACS-packaged dashboards.
- Retain the native controls-first layout and existing dispatch strategy; no sign reversal or optimizer behavior change.
- Validate both dashboard copies and the bridge entity contract. The sibling bridge runtime suite registers actual Home Assistant entities and checks every bridge attribute referenced in both controller dashboards before and after a charge command.

Requires H3X Bridge 0.4.1 and Home Assistant 2025.3 or newer. Update the bridge and restart Home Assistant first. Refresh storage-mode dashboards from `custom_components/h3x_predictive_dispatch/dashboards/h3x-predictive-dispatch.yaml`; YAML mode referencing that file follows HACS package updates. Explicitly customized bridge IDs require matching dashboard YAML.

Register verification is not proof of physical charging; check measured battery power/status. No physical inverter was connected during validation.
