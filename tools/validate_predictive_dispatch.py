#!/usr/bin/env python3
"""Deterministic simulations for the predictive dispatch engine."""

from __future__ import annotations

import importlib.util
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "h3x_energy_arbitrage"
PACKAGE = "h3x_energy_arbitrage_validation"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(INTEGRATION)]  # type: ignore[attr-defined]
sys.modules[PACKAGE] = package


def load_module(name: str):
    """Load a pure integration module without importing Home Assistant."""
    spec = importlib.util.spec_from_file_location(
        f"{PACKAGE}.{name}", INTEGRATION / f"{name}.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


forecast_module = load_module("forecast")
optimizer_module = load_module("optimizer")
tariff_module = load_module("tariff")
ForecastBand = forecast_module.ForecastBand
HistoricalLoadForecaster = forecast_module.HistoricalLoadForecaster
PowerObservation = forecast_module.PowerObservation
OptimizerSettings = optimizer_module.OptimizerSettings
OptimizerSlot = optimizer_module.OptimizerSlot
PredictiveDispatchOptimizer = optimizer_module.PredictiveDispatchOptimizer
TariffSettings = tariff_module.TariffSettings
retail_price = tariff_module.retail_price


def slots(prices: list[float], load_w: float = 1200.0) -> list[OptimizerSlot]:
    """Build quarter-hour test slots."""
    start = datetime(2026, 8, 3, tzinfo=timezone.utc)
    result = []
    for index, price in enumerate(prices):
        begin = start + timedelta(minutes=15 * index)
        band = ForecastBand(load_w * 0.8, load_w, load_w * 1.25, 10, 0.8)
        result.append(
            OptimizerSlot(
                start=begin,
                end=begin + timedelta(minutes=15),
                wholesale_price=price,
                buy_price=price,
                sell_price=price,
                load=band,
                solar=ForecastBand(0.0, 0.0, 0.0, 0, 0.5),
            )
        )
    return result


def settings(**overrides: object) -> OptimizerSettings:
    """Return a six-module H3 test configuration."""
    values: dict[str, object] = {
        "min_energy_kwh": 4.4,
        "max_energy_kwh": 26.25,
        "initial_energy_kwh": 15.0,
        "terminal_energy_kwh": 15.0,
        "charge_efficiency": 0.95,
        "discharge_efficiency": 0.95,
        "max_charge_power_w": 11000.0,
        "max_discharge_power_w": 11000.0,
        "min_active_power_w": 500.0,
        "grid_import_limit_w": 17500.0,
        "grid_export_limit_w": 0.0,
        "cycle_cost_per_kwh": 0.035,
        "min_profit_margin_per_kwh": 0.015,
        "action_start_cost": 0.035,
        "direction_change_cost": 0.08,
        "min_action_duration_minutes": 30.0,
        "risk_percentile": 70.0,
        "power_profile": "typical",
    }
    values.update(overrides)
    return OptimizerSettings(**values)  # type: ignore[arg-type]


def validate_tariff() -> None:
    """Validate 2026 Dutch import tax and VAT treatment."""
    price = retail_price(0.08, TariffSettings())
    expected = (0.08 + 0.09161 + 0.02) * 1.21
    assert abs(price.buy - expected) < 1e-9
    assert price.sell == 0.08


def validate_flat_prices_do_not_cycle() -> None:
    """Wear and conversion losses must reject pointless movement."""
    result = PredictiveDispatchOptimizer().optimize(slots([0.20] * 32), settings())
    assert all(row.action == "idle" for row in result.schedule)


def validate_two_peak_schedule() -> None:
    """The optimizer may use two economic valleys/peaks in one day."""
    prices = [0.09] * 8 + [0.34] * 8 + [0.07] * 8 + [0.38] * 8
    result = PredictiveDispatchOptimizer().optimize(
        slots(prices),
        settings(initial_energy_kwh=10.0, terminal_energy_kwh=10.0),
    )
    charge_windows = _windows(result.schedule, "charge")
    discharge_windows = _windows(result.schedule, "discharge")
    assert len(charge_windows) >= 2, charge_windows
    assert len(discharge_windows) >= 2, discharge_windows
    assert result.estimated_savings > 0


def validate_grid_limit() -> None:
    """High household demand must reduce the feasible charge set."""
    high_load_slots = slots([0.03] * 8 + [0.40] * 8, load_w=16000.0)
    result = PredictiveDispatchOptimizer().optimize(
        high_load_slots,
        settings(initial_energy_kwh=8.0, terminal_energy_kwh=8.0),
    )
    for row in result.schedule:
        assert row.load_p90_w + max(row.target_power_w, 0.0) <= 17500.0 + 1e-6


def validate_ev_detection() -> None:
    """Repeated rectangular evening loads are separated and forecast as EV demand."""
    start = datetime(2026, 7, 20, tzinfo=timezone.utc)
    observations = []
    for day in range(14):
        for quarter in range(96):
            timestamp = start + timedelta(days=day, minutes=15 * quarter)
            ev = 7400.0 if 72 <= quarter < 84 and day % 2 == 0 else 0.0
            observations.append(PowerObservation(timestamp, 900.0 + ev))
    target = [
        type("Slot", (), {
            "start": start + timedelta(days=14, minutes=15 * quarter),
            "end": start + timedelta(days=14, minutes=15 * (quarter + 1)),
        })()
        for quarter in range(96)
    ]
    forecast = HistoricalLoadForecaster(
        observations, ev_mode="detect", ev_threshold_w=2800.0
    ).forecast(target, current_load_w=900.0)
    assert forecast.metrics.ev_sessions >= 6
    assert max(band.ev_w for band in forecast.bands) > 1000.0


def _windows(schedule: list[object], action: str) -> list[int]:
    """Return starting indexes of contiguous action windows."""
    starts = []
    previous = "idle"
    for index, row in enumerate(schedule):
        current = row.action
        if current == action and previous != action:
            starts.append(index)
        previous = current
    return starts


def main() -> None:
    validate_tariff()
    validate_flat_prices_do_not_cycle()
    validate_two_peak_schedule()
    validate_grid_limit()
    validate_ev_detection()
    print("predictive dispatch simulations passed")


if __name__ == "__main__":
    main()
