"""Apply the native Home Assistant control/operations/diagnostics layout."""

from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


def override_controls():
    return {
        "type": "entities",
        "title": "Battery override and weather reserve",
        "show_header_toggle": False,
        "entities": [
            {"entity": f"{domain}.pylontech_h3x_bridge_{key}", "name": name}
            for domain, key, name in (
                ("switch", "force_charge", "Force charge (up to 2 hours)"),
                ("number", "force_charge_rate", "Charge rate (% of rated power)"),
                ("select", "charge_method", "Charge command method"),
                ("switch", "weather_reserve", "Natural disaster / KNMI reserve"),
                ("select", "weather_alert_threshold", "Minimum warning colour"),
                ("number", "weather_discharge_rate", "Emergency discharge cap (%)"),
                ("sensor", "control_owner", "Active controller"),
                ("sensor", "charge_control_status", "Measured response / reason"),
            )
        ]
        + [
            {
                "type": "button",
                "name": "Connection, Shelly, KNMI and siren settings",
                "icon": "mdi:cog",
                "tap_action": {
                    "action": "navigate",
                    "navigation_path": "/config/integrations/integration/pylontech_h3x_bridge",
                },
            }
        ],
    }


def main():
    path = ROOT / "dashboards/h3x-predictive-dispatch.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    view = doc["views"][0]
    if "sections" in view:
        return
    groups = {"controls": [override_controls()], "operations": [], "diagnostics": []}
    control_titles = {
        "Optimizer controls",
        "Strategy profile guide",
        "Forecast configuration and status",
        "Pylontech H3X controls",
    }
    for card in view.pop("cards"):
        if card.get("type") == "heading":
            # Section headings replace the old scattered headings.
            continue
        title = card.get("title", "")
        if title in control_titles:
            groups["controls"].append(card)
        elif title in {
            "Arbitrage diagnostics",
            "Shelly Pro 3EM grid trend and limits",
            "Dutch retail price assumptions",
        }:
            groups["diagnostics"].append(card)
        else:
            if any(
                child.get("entity", "").endswith("_next_charge_slot")
                for child in card.get("cards", [])
            ):
                groups["operations"].append(
                    {
                        "type": "heading",
                        "heading": "Planned actions",
                        "icon": "mdi:calendar-clock",
                    }
                )
            if card.get("type") == "grid":
                card["columns"] = min(card.get("columns", 2), 2)
            groups["operations"].append(card)
    # Retain searchable headings expected by the dashboard contract.
    groups["operations"].insert(0, {"type": "heading", "heading": "EV charging policy"})
    groups["diagnostics"].insert(0, {"type": "heading", "heading": "Price assumptions"})
    view.update(
        {
            "type": "sections",
            "max_columns": 3,
            "sections": [
                {
                    "type": "grid",
                    "column_span": 3,
                    "cards": [
                        {"type": "heading", "heading": title, "icon": icon},
                        *groups[key],
                    ],
                }
                for key, title, icon in (
                    ("controls", "Settings and control", "mdi:tune"),
                    ("operations", "Usage, savings and power", "mdi:chart-line"),
                    ("diagnostics", "Statistics and diagnostics", "mdi:table-search"),
                )
            ],
        }
    )
    source = yaml.safe_dump(doc, sort_keys=False, allow_unicode=False, width=140)
    path.write_text(source, encoding="utf-8")
    (
        ROOT
        / "custom_components/h3x_predictive_dispatch/dashboards/h3x-predictive-dispatch.yaml"
    ).write_text(source, encoding="utf-8")


if __name__ == "__main__":
    main()
