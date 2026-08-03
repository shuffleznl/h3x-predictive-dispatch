"""Home Assistant Recorder adapter for local energy forecasting."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.history import get_significant_states
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .forecast import PowerObservation

LOGGER = logging.getLogger(__name__)


class RecorderHistoryLoader:
    """Read short-term mean power statistics without blocking HA's event loop."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    async def async_load_power_history(
        self,
        load_entity_id: str,
        *,
        days: int,
        ev_entity_id: str | None = None,
    ) -> list[PowerObservation]:
        """Return aligned load and optional EV observations.

        Five-minute short-term statistics are preferred and aggregated by the
        forecaster into quarter-hours. Recorder retention may provide fewer days
        than requested; this is a normal warm-up condition, not a failure.
        """
        if not load_entity_id:
            return []
        end = dt_util.utcnow()
        start = end - timedelta(days=min(max(days, 2), 90))
        entity_ids = {load_entity_id}
        if ev_entity_id:
            entity_ids.add(ev_entity_id)
        try:
            result = await get_instance(self._hass).async_add_executor_job(
                statistics_during_period,
                self._hass,
                start,
                end,
                entity_ids,
                "5minute",
                None,
                {"mean"},
            )
        except Exception:  # Recorder is optional and must never stop dispatch.
            LOGGER.warning("Unable to load Recorder power history", exc_info=True)
            result = {}

        load_rows = self._rows_by_timestamp(
            result.get(load_entity_id, []), self._power_factor(load_entity_id)
        )
        ev_rows = (
            self._rows_by_timestamp(
                result.get(ev_entity_id, []), self._power_factor(ev_entity_id)
            )
            if ev_entity_id
            else {}
        )
        if not load_rows:
            return await self._async_load_raw_history(
                load_entity_id,
                ev_entity_id=ev_entity_id,
                start=start,
                end=end,
            )
        observations: list[PowerObservation] = []
        for timestamp, load_w in sorted(load_rows.items()):
            observations.append(
                PowerObservation(
                    timestamp=timestamp,
                    load_w=max(load_w, 0.0),
                    ev_w=max(ev_rows[timestamp], 0.0) if timestamp in ev_rows else None,
                )
            )
        return self._aggregate_quarter_hours(observations)

    async def _async_load_raw_history(
        self,
        load_entity_id: str,
        *,
        ev_entity_id: str | None,
        start: datetime,
        end: datetime,
    ) -> list[PowerObservation]:
        """Fall back to raw Recorder states for sensors without statistics."""
        entity_ids = [load_entity_id]
        if ev_entity_id:
            entity_ids.append(ev_entity_id)
        try:
            result = await get_instance(self._hass).async_add_executor_job(
                get_significant_states,
                self._hass,
                start,
                end,
                entity_ids,
                None,
                False,
                False,
                False,
                True,
                False,
            )
        except Exception:
            LOGGER.warning("Unable to load raw Recorder power history", exc_info=True)
            return []
        load = self._raw_quarter_buckets(
            result.get(load_entity_id, []), self._power_factor(load_entity_id)
        )
        ev = (
            self._raw_quarter_buckets(
                result.get(ev_entity_id, []), self._power_factor(ev_entity_id)
            )
            if ev_entity_id
            else {}
        )
        return [
            PowerObservation(timestamp, power_w, ev.get(timestamp))
            for timestamp, power_w in sorted(load.items())
        ]

    @staticmethod
    def _raw_quarter_buckets(rows: list[Any], factor: float) -> dict[datetime, float]:
        """Average raw State values into local quarter-hour buckets."""
        buckets: dict[datetime, list[float]] = {}
        for row in rows:
            try:
                state_value = row.state if hasattr(row, "state") else row.get("state")
                timestamp_value = (
                    row.last_updated if hasattr(row, "last_updated") else row.get("last_updated")
                )
                timestamp = RecorderHistoryLoader._timestamp(timestamp_value)
                quarter = timestamp.replace(
                    minute=(timestamp.minute // 15) * 15,
                    second=0,
                    microsecond=0,
                )
                buckets.setdefault(quarter, []).append(float(state_value) * factor)
            except (AttributeError, TypeError, ValueError, OverflowError):
                continue
        return {
            timestamp: sum(values) / len(values)
            for timestamp, values in buckets.items()
            if values
        }

    @staticmethod
    def _rows_by_timestamp(
        rows: list[dict[str, Any]], factor: float
    ) -> dict[datetime, float]:
        """Normalize Recorder rows and their units to watts."""
        values: dict[datetime, float] = {}
        for row in rows:
            mean = row.get("mean")
            start = row.get("start")
            if mean is None or start is None:
                continue
            try:
                timestamp = RecorderHistoryLoader._timestamp(start)
                values[timestamp] = float(mean) * factor
            except (TypeError, ValueError, OverflowError):
                continue
        return values

    def _power_factor(self, entity_id: str) -> float:
        """Convert the entity's displayed power unit to watts."""
        state = self._hass.states.get(entity_id)
        unit = str((state.attributes if state else {}).get("unit_of_measurement") or "W")
        return {"W": 1.0, "kW": 1000.0, "MW": 1_000_000.0}.get(unit, 1.0)

    @staticmethod
    def _timestamp(value: Any) -> datetime:
        """Parse current and legacy Recorder timestamp forms."""
        if isinstance(value, datetime):
            timestamp = value
        elif isinstance(value, (float, int)):
            epoch = float(value) / 1000 if value > 1e12 else float(value)
            timestamp = datetime.fromtimestamp(epoch, tz=dt_util.UTC)
        else:
            timestamp = dt_util.parse_datetime(str(value))
            if timestamp is None:
                raise ValueError("invalid Recorder timestamp")
        return dt_util.as_local(timestamp)

    @staticmethod
    def _aggregate_quarter_hours(
        observations: list[PowerObservation],
    ) -> list[PowerObservation]:
        """Average 5-minute observations into stable local quarter-hours."""
        buckets: dict[datetime, list[PowerObservation]] = {}
        for row in observations:
            start = row.timestamp.replace(
                minute=(row.timestamp.minute // 15) * 15,
                second=0,
                microsecond=0,
            )
            buckets.setdefault(start, []).append(row)
        result: list[PowerObservation] = []
        for timestamp, rows in sorted(buckets.items()):
            if len(rows) < 2:
                continue
            ev_values = [row.ev_w for row in rows if row.ev_w is not None]
            result.append(
                PowerObservation(
                    timestamp=timestamp,
                    load_w=sum(row.load_w for row in rows) / len(rows),
                    ev_w=sum(ev_values) / len(ev_values) if ev_values else None,
                )
            )
        return result
