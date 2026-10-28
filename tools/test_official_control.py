"""Exercise actual coordinator services with official-shaped HA states."""

import importlib
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
package = ModuleType("official_dispatch_test")
package.__path__ = [str(ROOT / "custom_components/h3x_predictive_dispatch")]
sys.modules[package.__name__] = package
module = importlib.import_module(package.__name__ + ".coordinator")
integration_setup = importlib.import_module(package.__name__ + ".__init__")


class OfficialControlTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.calls = []
        self.options = {
            "ems_mode_entity": "select.device",
            "power_ref_entity": "number.reference",
            "user_ems_mode": "User mode",
            "idle_ems_mode": "user",
        }
        self.states = {
            "select.device": SimpleNamespace(
                state="self_consumption",
                attributes={"options": ["user", "self_consumption"]},
            ),
            "number.reference": SimpleNamespace(state="unavailable", attributes={}),
        }

        async def call(domain, service, data, **kwargs):
            self.calls.append((domain, service, data))
            if domain == "select":
                self.states["select.device"].state = data["option"]
                self.states["number.reference"].state = (
                    "0.0" if data["option"] == "user" else "unavailable"
                )
            else:
                assert self.states["select.device"].state == "user"
                self.states["number.reference"].state = str(data["value"])

        self.coordinator = object.__new__(module.H3XPredictiveDispatchCoordinator)
        self.coordinator.hass = SimpleNamespace(
            states=SimpleNamespace(get=self.states.get),
            services=SimpleNamespace(async_call=call),
        )
        self.coordinator._option = self.options.get
        self.coordinator._stabilize_runtime_action = lambda decision: None
        self.coordinator._set_soc_limits = AsyncMock()
        self.coordinator._last_applied_action = None
        self.coordinator._last_power_percent = None
        self.coordinator._last_ems_mode = None

    async def test_negative_and_positive_numbers_are_not_raw_registers(self):
        for action, percent in (("charge", -20), ("discharge", 20)):
            decision = module.Decision(
                action=action, target_power_percent=percent, target_power_w=3000
            )
            await self.coordinator._apply_decision(decision)
            self.assertTrue(decision.applied, decision.apply_error)
            self.assertEqual(
                self.calls[-1], ("number", "set_value", {"value": percent})
            )

    async def test_idle_selects_user_before_zero(self):
        self.states["number.reference"].state = "-20"
        # Switching mode updates availability and reads back a nonzero reference.
        original = self.coordinator.hass.services.async_call

        async def call(domain, service, data, **kwargs):
            await original(domain, service, data, **kwargs)
            if domain == "select":
                self.states["number.reference"].state = "-20"

        self.coordinator.hass.services.async_call = call
        decision = module.Decision(action="idle")
        await self.coordinator._apply_decision(decision)
        self.assertTrue(decision.applied, decision.apply_error)
        self.assertEqual(
            self.calls,
            [
                ("select", "select_option", {"option": "user"}),
                ("number", "set_value", {"value": 0.0}),
            ],
        )
        self.assertEqual(self.states["select.device"].state, "user")

    async def test_actual_reference_overrides_cached_intent(self):
        self.states["select.device"].state = "user"
        self.states["number.reference"].state = "-5"
        self.coordinator._last_power_percent = -20
        await self.coordinator._set_power_ref(-20)
        self.assertEqual(self.calls[-1][2], {"value": -20})

    async def test_unavailable_reference_is_not_success(self):
        with self.assertRaisesRegex(RuntimeError, "unavailable"):
            await self.coordinator._set_power_ref(-20)
        self.assertEqual(self.calls, [])

    async def test_unavailable_mode_is_not_success(self):
        self.states["select.device"].state = "unavailable"
        with self.assertRaisesRegex(RuntimeError, "unavailable"):
            await self.coordinator._set_ems_mode("user")

    def test_reported_rating_not_grid_connection_for_percent(self):
        self.options.update(
            {
                "inverter_rated_power_entity": "sensor.rated",
                "inverter_full_scale_power_w": 17500,
            }
        )
        self.states["sensor.rated"] = SimpleNamespace(
            state="15000", attributes={"unit_of_measurement": "W"}
        )
        self.assertEqual(self.coordinator._power_to_percent("charge", 3000), -20)
        self.assertEqual(self.coordinator._power_to_percent("discharge", 3000), 20)

    def test_headroom_does_not_credit_undelivered_charge_request(self):
        self.options["battery_power_entity"] = "sensor.measured"
        self.states["sensor.measured"] = SimpleNamespace(
            state="0", attributes={"unit_of_measurement": "W"}
        )
        self.coordinator._grid_connection_limit_w = lambda: 17500
        self.coordinator._last_power_percent = -100
        self.assertEqual(
            self.coordinator._grid_charge_headroom_w(
                load_power_w=None,
                grid_import_power_w=16000,
                grid_import_average_power_w=15000,
            ),
            1500,
        )
        self.states["sensor.measured"].state = "-3000"
        self.assertEqual(
            self.coordinator._grid_charge_headroom_w(
                load_power_w=None,
                grid_import_power_w=16000,
                grid_import_average_power_w=15000,
            ),
            4500,
        )
        self.states["sensor.measured"].state = "3000"
        self.assertEqual(
            self.coordinator._grid_charge_headroom_w(
                load_power_w=None,
                grid_import_power_w=16000,
                grid_import_average_power_w=15000,
            ),
            0,
        )

    def test_six_modules_keep_nominal_and_usable_separate(self):
        self.options.update(
            {
                "battery_module_count_entity": "sensor.modules",
                "battery_system_capacity_entity": "sensor.nominal",
                "battery_usable_capacity_entity": "",
            }
        )
        self.states["sensor.modules"] = SimpleNamespace(state="6", attributes={})
        self.states["sensor.nominal"] = SimpleNamespace(
            state="30.72", attributes={"unit_of_measurement": "kWh"}
        )
        configuration = self.coordinator._battery_configuration()
        self.assertEqual(configuration.module_count, 6)
        self.assertEqual(configuration.system_capacity_kwh, 30.72)
        self.assertEqual(configuration.usable_capacity_kwh, 29.17)
        self.assertIsNone(configuration.warning)

    async def test_setup_merges_real_stored_options_without_resetting_settings(self):
        reference = {
            "platform": "pylontech_fh3x",
            "entity_id": "number.reference",
            "unique_id": "test_charge_discharge_power_reference",
            "config_entry_id": "official",
        }
        registry = SimpleNamespace(entities={"number.reference": reference})
        data = {
            "solar_power_entity": "sensor.sma",
            "grid_import_limit_w": 17500,
            "buy_cost_adder": 0.14,
        }
        options = {
            "power_ref_entity": "number.pylontech_h3x_bridge_charge_discharge_power_ref",
            "solcast_api_key": "test-placeholder",
            "battery_circuit_limit_w": 13800,
            "control_enabled": True,
        }
        entry = SimpleNamespace(
            data=data.copy(),
            options=options.copy(),
            add_update_listener=Mock(),
            async_on_unload=Mock(),
        )

        def update(actual, **changes):
            actual.options = changes["options"]

        hass = SimpleNamespace(
            config_entries=SimpleNamespace(
                async_update_entry=update, async_forward_entry_setups=AsyncMock()
            )
        )
        coordinator = SimpleNamespace(async_config_entry_first_refresh=AsyncMock())
        with (
            patch.object(integration_setup.er, "async_get", return_value=registry),
            patch.object(
                integration_setup,
                "H3XPredictiveDispatchCoordinator",
                return_value=coordinator,
            ),
        ):
            await integration_setup.async_setup_entry(hass, entry)
        self.assertEqual(entry.data, data)
        for key in options.keys() - {"power_ref_entity", "control_enabled"}:
            self.assertEqual(entry.options[key], options[key])
        self.assertEqual(entry.options["power_ref_entity"], "number.reference")
        self.assertFalse(entry.options["control_enabled"])


if __name__ == "__main__":
    unittest.main()
