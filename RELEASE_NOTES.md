# Predictive Dispatch 0.2.14

- Recheck bridge ownership before and after each awaited EMS/SOC/power service call, including a takeover inside service dispatch.
- Treat manual/weather preemption as an expected pause, reset action/power/mode caches and preserve genuine failures when no override is active.
- Separate control intent from measured charging response on both dashboard copies. Add the last competing entity and actual Modbus-command failure.
- Require H3X Bridge 0.4.2 for these diagnostics. CI exercises real Home Assistant entity services, authenticated manual actions, takeover races and dashboard attributes.

Requires H3X Bridge 0.4.2 and Home Assistant 2025.3 or newer. Update both integrations and restart Home Assistant. Refresh storage-mode dashboards from `custom_components/h3x_predictive_dispatch/dashboards/h3x-predictive-dispatch.yaml`; YAML mode referencing that file follows HACS package updates. Existing configuration and entity IDs are preserved.

Register verification is not proof of physical charging; check measured battery power/status. No physical inverter was connected during validation.
