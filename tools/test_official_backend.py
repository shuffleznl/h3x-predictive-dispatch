"""Registry migration and mode contracts, without a live inverter."""

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "official_backend", ROOT / "custom_components/h3x_predictive_dispatch/backend.py"
)
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)


def entry(key, domain="sensor", serial="test", config="official"):
    return {
        "platform": "pylontech_fh3x",
        "config_entry_id": config,
        "unique_id": serial + "_" + key,
        "entity_id": domain + ".renamed_" + serial + "_" + key,
    }


class OfficialBindingsTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            entry("charge_discharge_power_reference", "number"),
            entry("ems_mode", "select"),
        ]
        self.rows += [
            entry(key)
            for key in (
                "battery_soc",
                "battery_capacity",
                "bms_temperature",
                "bms_module_count",
            )
        ]

    def test_exact_keys_and_renamed_entities(self):
        self.rows.append(entry("parallel_system_battery_soc"))
        result = backend.official_bindings(self.rows, {})
        self.assertEqual(result["soc_entity"], "sensor.renamed_test_battery_soc")
        self.assertEqual(
            result["battery_system_capacity_entity"],
            "sensor.renamed_test_battery_capacity",
        )
        self.assertNotIn("battery_usable_capacity_entity", result)
        self.assertEqual(result["user_ems_mode"], "user")

    def test_migration_preserves_all_other_settings(self):
        old = {
            "power_ref_entity": "number.pylontech_h3x_bridge_charge_discharge_power_ref",
            "battery_usable_capacity_entity": "sensor.pylontech_h3x_bridge_battery_usable_capacity",
            "user_ems_mode": "User mode",
            "idle_ems_mode": "Self-Consumption",
            "grid_import_power_entity": "sensor.shelly_grid",
            "solar_power_entity": "sensor.sma",
            "buy_cost_adder": 0.123,
            "solcast_api_key": "test-placeholder",
            "grid_import_limit_w": 27600,
            "battery_circuit_limit_w": 13800,
            "battery_module_count": 6,
            "resolution": 15,
            "control_enabled": False,
        }
        result = {**old, **backend.official_bindings(self.rows, old)}
        for key in old.keys() - {
            "power_ref_entity",
            "battery_usable_capacity_entity",
            "user_ems_mode",
            "idle_ems_mode",
        }:
            self.assertEqual(result[key], old[key])
        self.assertEqual(result["battery_usable_capacity_entity"], "")
        self.assertEqual(result["idle_ems_mode"], "user")

    def test_legacy_renamed_registry_entity(self):
        self.rows.append(
            {
                "platform": "pylontech_h3x_bridge",
                "entity_id": "number.my_battery",
                "unique_id": "legacy",
            }
        )
        result = backend.official_bindings(
            self.rows, {"power_ref_entity": "number.my_battery"}
        )
        self.assertEqual(result["power_ref_entity"], self.rows[0]["entity_id"])

    def test_preserve_explicit_custom_inputs(self):
        settings = {
            "soc_entity": "sensor.custom_soc",
            "bms_temperature_entity": "sensor.my_temperature",
            "idle_ems_mode": "backup",
        }
        result = backend.official_bindings(self.rows, settings)
        self.assertNotIn("soc_entity", result)
        self.assertNotIn("bms_temperature_entity", result)
        self.assertNotIn("idle_ems_mode", result)

    def test_refuse_other_or_missing_custom_backend(self):
        for rows in (
            self.rows,
            self.rows + [{"platform": "other", "entity_id": "number.other"}],
        ):
            self.assertEqual(
                backend.official_bindings(rows, {"power_ref_entity": "number.other"}),
                {},
            )

    def test_multiple_devices_require_explicit_selection(self):
        self.rows += [
            entry("charge_discharge_power_reference", "number", "second", "second")
        ]
        self.assertEqual(backend.official_bindings(self.rows, {}), {})
        selected = {"power_ref_entity": self.rows[0]["entity_id"]}
        self.assertEqual(
            backend.official_bindings(self.rows, selected)["soc_entity"],
            "sensor.renamed_test_battery_soc",
        )

    def test_mode_aliases_and_failure(self):
        options = ["user", "self_consumption", "backup"]
        self.assertEqual(backend.resolve_ems_option("User mode", options), "user")
        self.assertEqual(
            backend.resolve_ems_option("Self-Consumption", options), "self_consumption"
        )
        with self.assertRaises(ValueError):
            backend.resolve_ems_option("Unknown", options)


if __name__ == "__main__":
    unittest.main()
