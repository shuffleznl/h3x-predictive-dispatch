"""Forecast-aware model-predictive battery optimizer."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from .forecast import ForecastBand


class TimeSlot(Protocol):
    """Minimum market slot interface."""

    start: datetime
    end: datetime


@dataclass(frozen=True, slots=True)
class OptimizerSlot:
    """One complete optimizer interval."""

    start: datetime
    end: datetime
    wholesale_price: float
    buy_price: float
    sell_price: float
    load: ForecastBand
    solar: ForecastBand
    discharge_allowed: bool = True

    @property
    def duration_h(self) -> float:
        return max((self.end - self.start).total_seconds() / 3600, 0.0)


@dataclass(frozen=True, slots=True)
class OptimizerSettings:
    """Physical, economic and anti-chatter constraints."""

    min_energy_kwh: float
    max_energy_kwh: float
    initial_energy_kwh: float
    terminal_energy_kwh: float
    charge_efficiency: float
    discharge_efficiency: float
    max_charge_power_w: float
    max_discharge_power_w: float
    min_active_power_w: float
    grid_import_limit_w: float
    grid_export_limit_w: float
    cycle_cost_per_kwh: float
    min_profit_margin_per_kwh: float
    action_start_cost: float
    direction_change_cost: float
    min_action_duration_minutes: float
    risk_percentile: float
    power_profile: str = "typical"
    charge_allowed: bool = True
    discharge_allowed: bool = True


@dataclass(slots=True)
class DispatchSlot:
    """Selected battery action and modeled energy flows."""

    start: datetime
    end: datetime
    action: str
    target_power_w: float
    soc_start_kwh: float
    soc_end_kwh: float
    wholesale_price: float
    buy_price: float
    sell_price: float
    load_power_w: float
    load_p10_w: float
    load_p90_w: float
    solar_power_w: float
    solar_p10_w: float
    solar_p90_w: float
    ev_power_w: float
    ev_discharge_blocked: bool
    grid_without_battery_w: float
    grid_with_battery_w: float
    baseline_cost: float
    optimized_cost: float
    wear_cost: float
    transition_cost: float
    value: float
    intent: str
    confidence: float

    def as_dict(self) -> dict[str, object]:
        """Return compact dashboard-safe data."""
        duration_h = max((self.end - self.start).total_seconds() / 3600, 0.0)
        energy_kwh = abs(self.target_power_w) * duration_h / 1000
        net_without_kwh = self.grid_without_battery_w * duration_h / 1000
        net_with_kwh = self.grid_with_battery_w * duration_h / 1000
        solar_surplus_kwh = max(-net_without_kwh, 0.0)
        solar_charge_kwh = (
            min(energy_kwh, solar_surplus_kwh) if self.action == "charge" else 0.0
        )
        grid_charge_kwh = (
            max(energy_kwh - solar_charge_kwh, 0.0)
            if self.action == "charge" else 0.0
        )
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "action": self.action,
            "intent": self.intent,
            "target_power_w": round(abs(self.target_power_w), 1),
            "signed_power_w": round(self.target_power_w, 1),
            "energy_kwh": round(energy_kwh, 3),
            "soc_start_kwh": round(self.soc_start_kwh, 3),
            "soc_end_kwh": round(self.soc_end_kwh, 3),
            "price": round(self.buy_price, 5),
            "wholesale_price": round(self.wholesale_price, 5),
            "buy_price": round(self.buy_price, 5),
            "sell_price": round(self.sell_price, 5),
            "load_power_w": round(self.load_power_w, 1),
            "load_p10_w": round(self.load_p10_w, 1),
            "load_p90_w": round(self.load_p90_w, 1),
            "solar_power_w": round(self.solar_power_w, 1),
            "solar_p10_w": round(self.solar_p10_w, 1),
            "solar_p90_w": round(self.solar_p90_w, 1),
            "ev_power_w": round(self.ev_power_w, 1),
            "ev_discharge_blocked": self.ev_discharge_blocked,
            "net_grid_without_battery_w": round(self.grid_without_battery_w, 1),
            "net_grid_with_battery_w": round(self.grid_with_battery_w, 1),
            "baseline_grid_import_kwh": round(max(net_without_kwh, 0.0), 3),
            "baseline_grid_export_kwh": round(max(-net_without_kwh, 0.0), 3),
            "grid_import_kwh": round(max(net_with_kwh, 0.0), 3),
            "grid_export_kwh": round(max(-net_with_kwh, 0.0), 3),
            "grid_charge_kwh": round(grid_charge_kwh, 3),
            "solar_charge_kwh": round(solar_charge_kwh, 3),
            "self_consumption_kwh": round(
                min(energy_kwh, max(net_without_kwh, 0.0))
                if self.action == "discharge" else 0.0,
                3,
            ),
            "battery_export_kwh": round(
                max(energy_kwh - max(net_without_kwh, 0.0), 0.0)
                if self.action == "discharge" else 0.0,
                3,
            ),
            "baseline_cost": round(self.baseline_cost, 4),
            "optimized_cost": round(self.optimized_cost, 4),
            "wear_cost": round(self.wear_cost, 4),
            "transition_cost": round(self.transition_cost, 4),
            "value": round(self.value, 4),
            "forecast_confidence": round(self.confidence, 3),
        }


@dataclass(slots=True)
class OptimizationResult:
    """Complete optimal schedule and counterfactual economics."""

    schedule: list[DispatchSlot]
    baseline_cost: float
    optimized_cost: float
    estimated_savings: float
    cycle_cost: float
    transition_cost: float
    equivalent_full_cycles: float
    reason: str
    diagnostics: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _State:
    energy_index: int
    mode: int
    run_slots: int


@dataclass(slots=True)
class _Node:
    cost: float
    energy_kwh: float
    parent: _State | None
    power_w: float
    slot_cost: float
    wear_cost: float
    transition_cost: float


def live_solar_charge_target_w(
    planned_target_w: float,
    current_solar_power_w: float | None,
    current_load_power_w: float | None,
    *,
    economic_grid_charge_w: float = 0.0,
    safety_margin_w: float = 100.0,
) -> float:
    """Combine live AC-coupled PV surplus with optimized grid charging."""
    planned_target_w = max(planned_target_w, 0.0)
    economic_grid_charge_w = min(
        max(economic_grid_charge_w, 0.0),
        planned_target_w,
    )
    if current_solar_power_w is None or current_load_power_w is None:
        return economic_grid_charge_w
    measured_surplus_w = max(current_solar_power_w - current_load_power_w, 0.0)
    usable_surplus_w = max(measured_surplus_w - max(safety_margin_w, 0.0), 0.0)
    return min(planned_target_w, economic_grid_charge_w + usable_surplus_w)


class PredictiveDispatchOptimizer:
    """Forward dynamic program with action-state and forecast-risk costs."""

    def optimize(
        self, slots: list[OptimizerSlot], settings: OptimizerSettings
    ) -> OptimizationResult:
        if not slots:
            return OptimizationResult([], 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, "no price slots")
        step_kwh = max((settings.max_energy_kwh - settings.min_energy_kwh) / 160, 0.1)
        min_run_slots = max(
            math.ceil(settings.min_action_duration_minutes / max(slots[0].duration_h * 60, 1)),
            1,
        )
        initial_index = self._energy_index(settings.initial_energy_kwh, settings, step_kwh)
        initial = _State(initial_index, 0, min_run_slots)
        layers: list[dict[_State, _Node]] = [
            {initial: _Node(0.0, settings.initial_energy_kwh, None, 0.0, 0.0, 0.0, 0.0)}
        ]

        for slot_index, slot in enumerate(slots):
            next_layer: dict[_State, _Node] = {}
            for state, node in layers[-1].items():
                for power_w in self._candidate_powers(slot, node.energy_kwh, settings):
                    mode = 1 if power_w > 0 else -1 if power_w < 0 else 0
                    if state.mode and state.run_slots < min_run_slots and mode != state.mode:
                        continue
                    remaining_slots = len(slots) - slot_index
                    if mode and mode != state.mode and remaining_slots < min_run_slots:
                        continue
                    transition_cost = self._transition_cost(state.mode, mode, settings)
                    energy_next = self._next_energy(node.energy_kwh, power_w, slot.duration_h, settings)
                    if energy_next < settings.min_energy_kwh - 1e-6 or energy_next > settings.max_energy_kwh + 1e-6:
                        continue
                    if not self._grid_feasible(slot, power_w, settings):
                        continue
                    grid_cost = self._risk_adjusted_grid_cost(slot, power_w, settings.risk_percentile)
                    throughput_kwh = abs(power_w) * slot.duration_h / 1000
                    wear_cost = throughput_kwh * settings.cycle_cost_per_kwh / 2
                    margin_cost = throughput_kwh * settings.min_profit_margin_per_kwh / 2
                    total = node.cost + grid_cost + wear_cost + margin_cost + transition_cost
                    energy_index = self._energy_index(energy_next, settings, step_kwh)
                    run_slots = min(state.run_slots + 1, min_run_slots) if mode == state.mode else (1 if mode else min_run_slots)
                    next_state = _State(energy_index, mode, run_slots)
                    existing = next_layer.get(next_state)
                    if existing is None or total < existing.cost:
                        next_layer[next_state] = _Node(
                            cost=total,
                            energy_kwh=energy_next,
                            parent=state,
                            power_w=power_w,
                            slot_cost=grid_cost,
                            wear_cost=wear_cost,
                            transition_cost=transition_cost,
                        )
            if not next_layer:
                return OptimizationResult([], 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, "no feasible dispatch path")
            layers.append(next_layer)

        terminal_state, terminal_node = min(
            layers[-1].items(),
            key=lambda item: item[1].cost + self._terminal_penalty(item[1].energy_kwh, settings),
        )
        powers: list[float] = []
        nodes: list[_Node] = []
        state = terminal_state
        for layer_index in range(len(slots), 0, -1):
            node = layers[layer_index][state]
            powers.append(node.power_w)
            nodes.append(node)
            if node.parent is None:
                break
            state = node.parent
        powers.reverse()
        nodes.reverse()

        schedule = self._build_schedule(slots, powers, nodes, settings)
        baseline = sum(self._risk_adjusted_grid_cost(slot, 0.0, settings.risk_percentile) for slot in slots)
        optimized = terminal_node.cost + self._terminal_penalty(terminal_node.energy_kwh, settings)
        wear = sum(row.wear_cost for row in schedule)
        transitions = sum(row.transition_cost for row in schedule)
        discharged = sum(
            abs(row.target_power_w) * (row.end - row.start).total_seconds() / 3_600_000
            for row in schedule if row.action == "discharge"
        )
        usable = max(settings.max_energy_kwh - settings.min_energy_kwh, 0.1)
        savings = baseline - optimized
        reason = "optimal schedule after tariff, forecast risk, losses and battery wear"
        return OptimizationResult(
            schedule=schedule,
            baseline_cost=baseline,
            optimized_cost=optimized,
            estimated_savings=savings,
            cycle_cost=wear,
            transition_cost=transitions,
            equivalent_full_cycles=discharged / usable,
            reason=reason,
            diagnostics={
                "state_step_kwh": round(step_kwh, 4),
                "states_evaluated": sum(len(layer) for layer in layers),
                "minimum_action_slots": min_run_slots,
                "risk_percentile": settings.risk_percentile,
                "terminal_energy_kwh": settings.terminal_energy_kwh,
                "ev_discharge_blocked_slots": sum(
                    not slot.discharge_allowed for slot in slots
                ),
            },
        )

    @staticmethod
    def _energy_index(energy: float, settings: OptimizerSettings, step: float) -> int:
        return round((energy - settings.min_energy_kwh) / step)

    @staticmethod
    def _next_energy(energy: float, power_w: float, duration_h: float, settings: OptimizerSettings) -> float:
        if power_w > 0:
            return energy + power_w * duration_h / 1000 * settings.charge_efficiency
        if power_w < 0:
            return energy + power_w * duration_h / 1000 / settings.discharge_efficiency
        return energy

    @staticmethod
    def _transition_cost(previous: int, mode: int, settings: OptimizerSettings) -> float:
        if mode == previous:
            return 0.0
        if previous and mode and previous != mode:
            return settings.direction_change_cost
        if mode:
            return settings.action_start_cost
        return 0.0

    def _candidate_powers(
        self, slot: OptimizerSlot, energy: float, settings: OptimizerSettings
    ) -> list[float]:
        levels = {
            "conservative": (0.35, 0.6, 1.0),
            "spread": (0.25, 0.5, 0.75, 1.0),
            "typical": (0.25, 0.5, 0.75, 1.0),
            "aggressive": (0.25, 0.5, 0.75, 1.0),
            "max_economic": (0.5, 0.75, 1.0),
        }.get(settings.power_profile, (0.25, 0.5, 0.75, 1.0))
        result = [0.0]
        if settings.charge_allowed:
            available = max(settings.max_energy_kwh - energy, 0.0)
            max_by_energy = available / max(slot.duration_h * settings.charge_efficiency, 1e-6) * 1000
            limit = min(settings.max_charge_power_w, max_by_energy)
            for fraction in levels:
                power = min(settings.max_charge_power_w * fraction, limit)
                if power >= settings.min_active_power_w:
                    result.append(power)
        if settings.discharge_allowed and slot.discharge_allowed:
            available = max(energy - settings.min_energy_kwh, 0.0)
            max_by_energy = available * settings.discharge_efficiency / max(slot.duration_h, 1e-6) * 1000
            limit = min(settings.max_discharge_power_w, max_by_energy)
            for fraction in levels:
                power = min(settings.max_discharge_power_w * fraction, limit)
                if power >= settings.min_active_power_w:
                    result.append(-power)
        return sorted({round(value, 3) for value in result})

    @staticmethod
    def _grid_feasible(slot: OptimizerSlot, power_w: float, settings: OptimizerSettings) -> bool:
        # Positive battery power means charging/import; negative means discharge/export.
        worst_import = slot.load.p90_w - slot.solar.p10_w + power_w
        worst_export = slot.solar.p90_w - slot.load.p10_w - power_w
        return not (
            (
                settings.grid_import_limit_w > 0
                and worst_import > settings.grid_import_limit_w + 1e-6
            )
            or (
                settings.grid_export_limit_w > 0
                and worst_export > settings.grid_export_limit_w + 1e-6
            )
        )

    @staticmethod
    def _net_cost(net_grid_kwh: float, buy: float, sell: float) -> float:
        return net_grid_kwh * (buy if net_grid_kwh >= 0 else sell)

    def _risk_adjusted_grid_cost(self, slot: OptimizerSlot, power_w: float, percentile: float) -> float:
        duration = slot.duration_h
        scenarios = (
            (slot.load.p10_w - slot.solar.p90_w + power_w) * duration / 1000,
            (slot.load.p50_w - slot.solar.p50_w + power_w) * duration / 1000,
            (slot.load.p90_w - slot.solar.p10_w + power_w) * duration / 1000,
        )
        costs = [self._net_cost(value, slot.buy_price, slot.sell_price) for value in scenarios]
        expected = costs[0] * 0.2 + costs[1] * 0.6 + costs[2] * 0.2
        risk = min(max((percentile - 50.0) / 40.0, 0.0), 1.0)
        return expected + risk * (max(costs) - expected)

    @staticmethod
    def _terminal_penalty(energy: float, settings: OptimizerSettings) -> float:
        shortage = max(settings.terminal_energy_kwh - energy, 0.0)
        return shortage * 1000.0

    def _build_schedule(
        self,
        slots: list[OptimizerSlot],
        powers: list[float],
        nodes: list[_Node],
        settings: OptimizerSettings,
    ) -> list[DispatchSlot]:
        result: list[DispatchSlot] = []
        energy = settings.initial_energy_kwh
        for slot, power_w, node in zip(slots, powers, nodes, strict=True):
            next_energy = self._next_energy(energy, power_w, slot.duration_h, settings)
            action = "charge" if power_w > 0 else "discharge" if power_w < 0 else "idle"
            net_without = slot.load.p50_w - slot.solar.p50_w
            net_with = net_without + power_w
            baseline = self._net_cost(net_without * slot.duration_h / 1000, slot.buy_price, slot.sell_price)
            optimized = self._net_cost(net_with * slot.duration_h / 1000, slot.buy_price, slot.sell_price)
            intent = self._intent(action, net_without, net_with)
            result.append(
                DispatchSlot(
                    start=slot.start,
                    end=slot.end,
                    action=action,
                    target_power_w=power_w,
                    soc_start_kwh=energy,
                    soc_end_kwh=next_energy,
                    wholesale_price=slot.wholesale_price,
                    buy_price=slot.buy_price,
                    sell_price=slot.sell_price,
                    load_power_w=slot.load.p50_w,
                    load_p10_w=slot.load.p10_w,
                    load_p90_w=slot.load.p90_w,
                    solar_power_w=slot.solar.p50_w,
                    solar_p10_w=slot.solar.p10_w,
                    solar_p90_w=slot.solar.p90_w,
                    ev_power_w=slot.load.ev_w,
                    ev_discharge_blocked=not slot.discharge_allowed,
                    grid_without_battery_w=net_without,
                    grid_with_battery_w=net_with,
                    baseline_cost=baseline,
                    optimized_cost=optimized,
                    wear_cost=node.wear_cost,
                    transition_cost=node.transition_cost,
                    value=baseline - optimized - node.wear_cost - node.transition_cost,
                    intent=intent,
                    confidence=min(slot.load.confidence, slot.solar.confidence),
                )
            )
            energy = next_energy
        return result

    @staticmethod
    def _intent(action: str, net_without_w: float, net_with_w: float) -> str:
        if action == "charge":
            return "solar_storage" if net_without_w < 0 else "grid_arbitrage"
        if action == "discharge":
            return "load_support" if net_without_w > 0 and net_with_w >= 0 else "battery_export"
        if net_without_w < 0:
            return "solar_export"
        return "hold"
