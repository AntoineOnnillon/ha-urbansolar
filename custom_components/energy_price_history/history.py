from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
from typing import Optional

from homeassistant.core import HomeAssistant

from .const import (
    CONF_ENERGY_SENSOR,
    CONF_PRICE_SENSOR,
    CONF_COST_SENSOR,
    CONF_PRICE_PERIODS,
    UNIT_EUR,
)
from .utils import periods_to_ranges, price_for_ts

_LOGGER = logging.getLogger(__name__)


async def async_rebuild_price_history(hass: HomeAssistant, entry) -> Optional[int]:
    energy_entity_id = entry.data.get(CONF_ENERGY_SENSOR)
    if not energy_entity_id:
        _LOGGER.error("Missing energy entity id; cost rebuild skipped")
        return None
    cost_entity_id = entry.data.get(CONF_COST_SENSOR) or entry.data.get(CONF_PRICE_SENSOR)
    if not cost_entity_id:
        _LOGGER.error("Missing cost entity id; cost rebuild skipped")
        return None

    ranges = periods_to_ranges(entry.data.get(CONF_PRICE_PERIODS, []))

    engine = await _wait_recorder_engine(hass)
    if engine is None:
        _LOGGER.error("Recorder engine not ready; cost rebuild skipped")
        return None

    dialect = getattr(engine, "dialect", None)
    dialect_name = getattr(dialect, "name", None)

    if dialect_name == "sqlite":
        db_path = _sqlite_path_from_engine(engine) or hass.config.path("home-assistant_v2.db")
        if not os.path.isfile(db_path):
            _LOGGER.error("Recorder DB not found at %s; cost rebuild skipped", db_path)
            return None
        return await hass.async_add_executor_job(
            _rebuild_sqlite,
            db_path,
            energy_entity_id,
            cost_entity_id,
            ranges,
        )

    if dialect_name in ("mysql", "mariadb"):
        return await hass.async_add_executor_job(
            _rebuild_sqlalchemy,
            engine,
            energy_entity_id,
            cost_entity_id,
            ranges,
        )

    _LOGGER.error("Unsupported recorder backend '%s'; cost rebuild skipped", dialect_name)
    return None


def _rebuild_sqlite(
    db_path: str,
    energy_entity_id: str,
    cost_entity_id: str,
    ranges,
) -> Optional[int]:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        energy_meta_id = _get_meta_id(cur, energy_entity_id, create=False)
        if energy_meta_id is None:
            _LOGGER.error("Missing statistics meta for energy; cost rebuild skipped")
            return None

        cost_meta_id = _get_meta_id(
            cur,
            cost_entity_id,
            create=True,
            unit=UNIT_EUR,
            unit_class="monetary",
            has_mean=None,
            has_sum=1,
            mean_type=0,
        )

        energy_rows = cur.execute(
            "SELECT start_ts, sum, state FROM statistics WHERE metadata_id = ? ORDER BY start_ts",
            (energy_meta_id,),
        ).fetchall()
        if not energy_rows:
            _LOGGER.error("No energy statistics found; cost rebuild skipped")
            return None

        cur.execute("DELETE FROM statistics WHERE metadata_id = ?", (cost_meta_id,))
        cur.execute("DELETE FROM statistics_short_term WHERE metadata_id = ?", (cost_meta_id,))

        rows_to_insert = []
        last_state = None
        last_sum = None
        cost_sum = 0.0

        for start_ts, energy_sum, energy_state in energy_rows:
            if energy_sum is None or energy_sum < 0:
                energy_sum = 0.0

            delta = None
            if energy_state is not None and last_state is not None:
                delta = energy_state - last_state
            if delta is None:
                if last_sum is None:
                    delta = 0.0
                else:
                    delta = energy_sum - last_sum
            if delta < 0:
                delta = 0.0

            price = price_for_ts(ranges, float(start_ts))
            cost_sum += delta * price

            created_ts = start_ts + 3600
            rows_to_insert.append(
                (created_ts, cost_meta_id, start_ts, cost_sum, cost_sum)
            )

            if energy_state is not None:
                last_state = energy_state
            last_sum = energy_sum

        cur.executemany(
            "INSERT INTO statistics (created_ts, metadata_id, start_ts, state, sum) VALUES (?,?,?,?,?)",
            rows_to_insert,
        )
        conn.commit()
        return len(rows_to_insert)
    finally:
        conn.close()


def _rebuild_sqlalchemy(
    engine,
    energy_entity_id: str,
    cost_entity_id: str,
    ranges,
) -> Optional[int]:
    from sqlalchemy import text

    dialect = getattr(engine, "dialect", None)
    dialect_name = getattr(dialect, "name", None)
    sum_col = "`sum`" if dialect_name in ("mysql", "mariadb") else "sum"

    with engine.begin() as conn:
        energy_meta_id = _get_meta_id_sa(conn, energy_entity_id, create=False)
        if energy_meta_id is None:
            _LOGGER.error("Missing statistics meta for energy; cost rebuild skipped")
            return None

        cost_meta_id = _get_meta_id_sa(
            conn,
            cost_entity_id,
            create=True,
            unit=UNIT_EUR,
            unit_class="monetary",
            has_mean=None,
            has_sum=1,
            mean_type=0,
        )

        energy_rows = conn.execute(
            text(
                f"SELECT start_ts, {sum_col} AS sum_value, state "
                "FROM statistics WHERE metadata_id = :mid ORDER BY start_ts"
            ),
            {"mid": energy_meta_id},
        ).fetchall()
        if not energy_rows:
            _LOGGER.error("No energy statistics found; cost rebuild skipped")
            return None

        conn.execute(text("DELETE FROM statistics WHERE metadata_id = :mid"), {"mid": cost_meta_id})
        conn.execute(text("DELETE FROM statistics_short_term WHERE metadata_id = :mid"), {"mid": cost_meta_id})

        rows_to_insert = []
        last_state = None
        last_sum = None
        cost_sum = 0.0

        for start_ts, energy_sum, energy_state in energy_rows:

            if energy_sum is None or energy_sum < 0:
                energy_sum = 0.0

            delta = None
            if energy_state is not None and last_state is not None:
                delta = energy_state - last_state
            if delta is None:
                if last_sum is None:
                    delta = 0.0
                else:
                    delta = energy_sum - last_sum
            if delta < 0:
                delta = 0.0

            price = price_for_ts(ranges, float(start_ts))
            cost_sum += delta * price

            created_ts = start_ts + 3600
            rows_to_insert.append(
                {
                    "created_ts": created_ts,
                    "metadata_id": cost_meta_id,
                    "start_ts": start_ts,
                    "state": cost_sum,
                    "sum_value": cost_sum,
                }
            )

            if energy_state is not None:
                last_state = energy_state
            last_sum = energy_sum

        conn.execute(
            text(
                f"INSERT INTO statistics (created_ts, metadata_id, start_ts, state, {sum_col}) "
                "VALUES (:created_ts, :metadata_id, :start_ts, :state, :sum_value)"
            ),
            rows_to_insert,
        )

        return len(rows_to_insert)


def _get_meta_id(
    cur: sqlite3.Cursor,
    statistic_id: str,
    create: bool,
    unit: str = "EUR",
    unit_class: str = "monetary",
    has_mean: Optional[int] = None,
    has_sum: int = 1,
    mean_type: int = 0,
) -> Optional[int]:
    row = cur.execute(
        "SELECT id FROM statistics_meta WHERE statistic_id = ?",
        (statistic_id,),
    ).fetchone()
    if row:
        return int(row[0])

    if not create:
        return None

    cur.execute(
        "INSERT INTO statistics_meta (statistic_id, source, unit_of_measurement, unit_class, has_mean, has_sum, name, mean_type) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (statistic_id, "recorder", unit, unit_class, has_mean, has_sum, None, mean_type),
    )
    return int(cur.lastrowid)


def _get_meta_id_sa(
    conn,
    statistic_id: str,
    create: bool,
    unit: str = "EUR",
    unit_class: str = "monetary",
    has_mean: Optional[int] = None,
    has_sum: int = 1,
    mean_type: int = 0,
) -> Optional[int]:
    from sqlalchemy import text

    row = conn.execute(
        text("SELECT id FROM statistics_meta WHERE statistic_id = :sid"),
        {"sid": statistic_id},
    ).fetchone()
    if row:
        return int(row[0])

    if not create:
        return None

    row = conn.execute(
        text(
            "INSERT INTO statistics_meta (statistic_id, source, unit_of_measurement, unit_class, has_mean, has_sum, name, mean_type) "
            "VALUES (:sid, :source, :unit, :unit_class, :has_mean, :has_sum, :name, :mean_type)"
        ),
        {
            "sid": statistic_id,
            "source": "recorder",
            "unit": unit,
            "unit_class": unit_class,
            "has_mean": has_mean,
            "has_sum": has_sum,
            "name": None,
            "mean_type": mean_type,
        },
    )
    return int(row.lastrowid)




def _get_recorder_engine(hass: HomeAssistant):
    instance = hass.data.get("recorder")
    if instance is not None:
        engine = getattr(instance, "engine", None)
        if engine is None:
            engine = getattr(instance, "_engine", None)
        if engine is not None:
            return engine

    try:
        from homeassistant.components import recorder
    except Exception:
        return None

    try:
        instance = recorder.get_instance(hass)
    except Exception:
        return None

    engine = getattr(instance, "engine", None)
    if engine is None:
        engine = getattr(instance, "_engine", None)
    return engine


def _sqlite_path_from_engine(engine) -> Optional[str]:
    url = getattr(engine, "url", None)
    if url is None:
        return None
    return getattr(url, "database", None)


async def _wait_recorder_engine(hass: HomeAssistant, timeout: int = 60, interval: float = 2.0):
    deadline = hass.loop.time() + timeout
    while hass.loop.time() < deadline:
        engine = _get_recorder_engine(hass)
        if engine is not None:
            return engine
        await asyncio.sleep(interval)
    return None
