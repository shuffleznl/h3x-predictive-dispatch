"""Migrate both native dashboard copies to the official Pylontech backend."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ENTITY_MAP = {
    "select.pylontech_h3x_bridge_ems_mode": "select.fh3x15khy3peu_ems_mode",
    "number.pylontech_h3x_bridge_charge_discharge_power_ref": "number.fh3x15khy3peu_charge_discharge_power_reference",
    "number.pylontech_h3x_bridge_charge_limit_soc": "number.fh3x15khy3peu_charge_limit_soc",
    "number.pylontech_h3x_bridge_discharge_limit_soc_eps": "number.fh3x15khy3peu_on_grid_eps_reserve_soc",
    "sensor.pylontech_h3x_bridge_battery_power": "sensor.fh3x15khy3peu_battery_power",
    "sensor.pylontech_h3x_bridge_battery_soc": "sensor.fh3x15khy3peu_battery_level",
}


def official_controls():
    return {
        "type": "entities",
        "title": "Pylontech device controls",
        "show_header_toggle": False,
        "entities": [
            {"entity": entity, "name": name}
            for entity, name in (
                ("select.fh3x15khy3peu_ems_mode", "Device EMS mode"),
                (
                    "number.fh3x15khy3peu_charge_discharge_power_reference",
                    "Signed reference (%; negative charges)",
                ),
                ("number.fh3x15khy3peu_charge_limit_soc", "Charge limit SOC"),
                (
                    "number.fh3x15khy3peu_on_grid_eps_reserve_soc",
                    "On-grid discharge reserve SOC",
                ),
                ("sensor.fh3x15khy3peu_battery_power", "Measured battery power"),
                ("sensor.fh3x15khy3peu_battery_current", "Measured battery current"),
                ("sensor.fh3x15khy3peu_bms_temperature", "BMS temperature"),
                ("sensor.fh3x15khy3peu_bms_module_count", "Installed module count"),
                ("sensor.fh3x15khy3peu_battery_capacity", "Nominal system capacity"),
                (
                    "number.pylontech_h3x_predictive_dispatch_inverter_reference_full_scale",
                    "Inverter 100% reference rating (W)",
                ),
            )
        ]
        + [
            {
                "type": "button",
                "name": "Pylontech connection and diagnostics",
                "icon": "mdi:cog",
                "tap_action": {
                    "action": "navigate",
                    "navigation_path": "/config/integrations/integration/pylontech_fh3x",
                },
            }
        ],
    }


def migrate(value):
    if isinstance(value, str):
        return ENTITY_MAP.get(value, value)
    if isinstance(value, list):
        return [migrate(child) for child in value]
    if isinstance(value, dict):
        return {key: migrate(child) for key, child in value.items()}
    return value


def main():
    source = ROOT / "dashboards/h3x-predictive-dispatch.yaml"
    dashboard = yaml.safe_load(source.read_text(encoding="utf-8"))
    cards = dashboard["views"][0]["sections"][0]["cards"]
    cards[:] = [
        card
        for card in cards
        if card.get("title")
        not in {
            "Battery override and weather reserve",
            "Pylontech H3X controls",
            "Pylontech device controls",
        }
    ]
    cards.insert(1, official_controls())
    dashboard = migrate(dashboard)
    content = yaml.safe_dump(dashboard, sort_keys=False, allow_unicode=False, width=110)
    for path in (
        source,
        ROOT
        / "custom_components/h3x_predictive_dispatch/dashboards/h3x-predictive-dispatch.yaml",
    ):
        path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
