from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_CAPACITY_BATTERY,
    CONF_INDEX_BASE_EMULATED,
    CONF_INDEX_BASE_SENSOR,
    CONF_INDEX_BATTERY_IN,
    CONF_INDEX_BATTERY_OUT,
    CONF_INDEX_INJECTION_SENSOR,
    CONF_INDEX_INJECTION_EMULATED,
    CONF_START_BATTERY_ENERGY,
)

_LOGGER = logging.getLogger(__name__)
# Slower batch settings to reduce MariaDB lock pressure on slow instances.
REBUILD_BATCH_SIZE = 300
REBUILD_BATCH_SLEEP_S = 0.1


@dataclass
class RebuildResult:
    battery_in: float
    battery_out: float
    capacity: float
    base_emulated: float
    last_base_state: Optional[float]
    last_injection_state: Optional[float]
    rows: int


async def async_rebuild_history(hass: HomeAssistant, config_entry) -> Optional[RebuildResult]:
    """Rebuild derived statistics from recorder history (SQLite/MariaDB)."""
    base_entity_id = config_entry.data.get(CONF_INDEX_BASE_SENSOR)
    injection_entity_id = config_entry.data.get(CONF_INDEX_INJECTION_SENSOR)
    if not base_entity_id or not injection_entity_id:
        _LOGGER.error("Missing base or injection entity id; history rebuild skipped")
        return None

    ent_reg = er.async_get(hass)
    entries = er.async_entries_for_config_entry(ent_reg, config_entry.entry_id)
    entity_ids: Dict[str, str] = {e.unique_id: e.entity_id for e in entries if e.unique_id}

    battery_in_entity_id = entity_ids.get(CONF_INDEX_BATTERY_IN)
    battery_out_entity_id = entity_ids.get(CONF_INDEX_BATTERY_OUT)
    capacity_entity_id = entity_ids.get(CONF_CAPACITY_BATTERY)
    base_emulated_entity_id = entity_ids.get(CONF_INDEX_BASE_EMULATED)
    injection_emulated_entity_id = entity_ids.get(CONF_INDEX_INJECTION_EMULATED)

    missing = [
        name
        for name, value in {
            "battery_in": battery_in_entity_id,
            "battery_out": battery_out_entity_id,
            "capacity": capacity_entity_id,
            "base_emulated": base_emulated_entity_id,
            "injection_emulated": injection_emulated_entity_id,
        }.items()
        if not value
    ]
    if missing:
        _LOGGER.error("Missing derived entities in registry (%s); history rebuild skipped", ", ".join(missing))
        return None

    start_capacity = float(config_entry.data.get(CONF_START_BATTERY_ENERGY, 0.0) or 0.0)
    _LOGGER.info("Rebuilding UrbanSolar history (this can take a while)...")

    engine = await _wait_recorder_engine(hass)
    if engine is None:
        _LOGGER.error("Recorder engine not ready; history rebuild skipped")
        return None

    dialect = getattr(engine, "dialect", None)
    dialect_name = getattr(dialect, "name", None)
    _LOGGER.info("UrbanSolar rebuild using recorder backend: %s", dialect_name)

    if dialect_name == "sqlite":
        db_path = _sqlite_path_from_engine(engine) or hass.config.path("home-assistant_v2.db")
        if not os.path.isfile(db_path):
            _LOGGER.error("Recorder DB not found at %s; history rebuild skipped", db_path)
            return None
        result: Optional[RebuildResult] = await hass.async_add_executor_job(
            _rebuild_sqlite,
            db_path,
            base_entity_id,
            injection_entity_id,
            battery_in_entity_id,
            battery_out_entity_id,
            capacity_entity_id,
            base_emulated_entity_id,
            injection_emulated_entity_id,
            start_capacity,
        )
    elif dialect_name in ("mysql", "mariadb"):
        result = await hass.async_add_executor_job(
            _rebuild_sqlalchemy,
            engine,
            base_entity_id,
            injection_entity_id,
            battery_in_entity_id,
            battery_out_entity_id,
            capacity_entity_id,
            base_emulated_entity_id,
            injection_emulated_entity_id,
            start_capacity,
        )
    else:
        _LOGGER.error("Unsupported recorder backend '%s'; history rebuild skipped", dialect_name)
        return None

    if result:
        _LOGGER.info("Rebuild finished: %s rows written", result.rows)
    return result


def _rebuild_sqlite(
    db_path: str,
    base_entity_id: str,
    injection_entity_id: str,
    battery_in_entity_id: str,
    battery_out_entity_id: str,
    capacity_entity_id: str,
    base_emulated_entity_id: str,
    injection_emulated_entity_id: str,
    start_capacity: float,
) -> Optional[RebuildResult]:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()

        base_meta_id = _get_meta_id(cur, base_entity_id, create=False)
        injection_meta_id = _get_meta_id(cur, injection_entity_id, create=False)
        if base_meta_id is None or injection_meta_id is None:
            _LOGGER.error("Missing statistics meta for base/injection; history rebuild skipped")
            return None

        battery_in_meta_id = _get_meta_id(cur, battery_in_entity_id, create=True)
        battery_out_meta_id = _get_meta_id(cur, battery_out_entity_id, create=True)
        capacity_meta_id = _get_meta_id(cur, capacity_entity_id, create=True, unit="kW", unit_class="power")
        base_emulated_meta_id = _get_meta_id(cur, base_emulated_entity_id, create=True)
        injection_emulated_meta_id = _get_meta_id(cur, injection_emulated_entity_id, create=True)

        base_rows = cur.execute(
            "SELECT start_ts, sum, state FROM statistics WHERE metadata_id = ? ORDER BY start_ts",
            (base_meta_id,),
        ).fetchall()
        if not base_rows:
            _LOGGER.error("No base statistics found; history rebuild skipped")
            return None

        injection_rows = cur.execute(
            "SELECT start_ts, sum, state FROM statistics WHERE metadata_id = ? ORDER BY start_ts",
            (injection_meta_id,),
        ).fetchall()
        injection_by_ts: Dict[float, Tuple[float, Optional[float]]] = {
            row[0]: (row[1] if row[1] is not None else 0.0, row[2]) for row in injection_rows
        }

        derived_meta_ids = (
            battery_in_meta_id,
            battery_out_meta_id,
            capacity_meta_id,
            base_emulated_meta_id,
            injection_emulated_meta_id,
        )
        cur.execute(
            "DELETE FROM statistics WHERE metadata_id IN (?,?,?,?,?)",
            derived_meta_ids,
        )
        cur.execute(
            "DELETE FROM statistics_short_term WHERE metadata_id IN (?,?,?,?,?)",
            derived_meta_ids,
        )

        battery_in_total = max(start_capacity, 0.0)
        battery_out_total = 0.0
        base_emulated_total = 0.0
        capacity = max(battery_in_total - battery_out_total, 0.0)
        base_total = 0.0

        sum_battery_in = 0.0
        sum_battery_out = 0.0
        sum_base_emulated = 0.0
        sum_injection_emulated = 0.0

        sum_battery_in = 0.0
        sum_battery_out = 0.0
        sum_base_emulated = 0.0
        sum_injection_emulated = 0.0

        sum_battery_in = 0.0
        sum_battery_out = 0.0
        sum_base_emulated = 0.0
        sum_injection_emulated = 0.0

        rows_to_insert = []
        last_base_state = None
        last_injection_state = None
        last_base_sum = None
        last_injection_sum = None
        injection_emulated_state = None

        for start_ts, base_sum, base_state in base_rows:
            if base_sum is None or base_sum < 0:
                base_sum = 0.0
            inj_sum, inj_state = injection_by_ts.get(start_ts, (0.0, None))
            if inj_sum is None or inj_sum < 0:
                inj_sum = 0.0

            delta_base = None
            if base_state is not None and last_base_state is not None:
                delta_base = base_state - last_base_state
            if delta_base is None:
                if last_base_sum is None:
                    delta_base = 0.0
                else:
                    delta_base = base_sum - last_base_sum
            if delta_base < 0:
                delta_base = 0.0

            delta_inj = None
            if inj_state is not None and last_injection_state is not None:
                delta_inj = inj_state - last_injection_state
            if delta_inj is None:
                if last_injection_sum is None:
                    delta_inj = 0.0
                else:
                    delta_inj = inj_sum - last_injection_sum
            if delta_inj < 0:
                delta_inj = 0.0

            battery_in_total += delta_inj
            capacity_before = max(battery_in_total - battery_out_total, 0.0)
            delta_out = min(delta_base, capacity_before)
            battery_out_total += delta_out
            capacity = max(battery_in_total - battery_out_total, 0.0)

            base_total += delta_base
            base_emulated_total = max(base_total - battery_out_total, 0.0)
            delta_emulated = max(delta_base - delta_out, 0.0)

            sum_battery_in += delta_inj
            sum_battery_out += delta_out
            sum_base_emulated += delta_emulated
            sum_injection_emulated += delta_inj

            if inj_state is not None:
                injection_emulated_state = inj_state
            elif injection_emulated_state is None:
                injection_emulated_state = last_injection_state or 0.0

            created_ts = start_ts + 3600
            rows_to_insert.extend(
                [
                    (created_ts, battery_in_meta_id, start_ts, battery_in_total, sum_battery_in),
                    (created_ts, battery_out_meta_id, start_ts, battery_out_total, sum_battery_out),
                    (created_ts, capacity_meta_id, start_ts, capacity, 0.0),
                    (created_ts, base_emulated_meta_id, start_ts, base_emulated_total, sum_base_emulated),
                    (created_ts, injection_emulated_meta_id, start_ts, injection_emulated_state, sum_injection_emulated),
                ]
            )

            if base_state is not None:
                last_base_state = base_state
            if inj_state is not None:
                last_injection_state = inj_state
            last_base_sum = base_sum
            last_injection_sum = inj_sum

        cur.executemany(
            "INSERT INTO statistics (created_ts, metadata_id, start_ts, state, sum) VALUES (?,?,?,?,?)",
            rows_to_insert,
        )
        conn.commit()

        return RebuildResult(
            battery_in=battery_in_total,
            battery_out=battery_out_total,
            capacity=capacity,
            base_emulated=base_emulated_total,
            last_base_state=last_base_state,
            last_injection_state=last_injection_state,
            rows=len(rows_to_insert),
        )
    finally:
        conn.close()


def _get_meta_id(
    cur: sqlite3.Cursor,
    statistic_id: str,
    create: bool,
    unit: str = "kWh",
    unit_class: str = "energy",
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
        (statistic_id, "recorder", unit, unit_class, None, 1, None, 0),
    )
    return int(cur.lastrowid)


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
    except Exception:  # pragma: no cover - HA core may change
        return None

    try:
        instance = recorder.get_instance(hass)
    except Exception:  # pragma: no cover
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


def _rebuild_sqlalchemy(
    engine,
    base_entity_id: str,
    injection_entity_id: str,
    battery_in_entity_id: str,
    battery_out_entity_id: str,
    capacity_entity_id: str,
    base_emulated_entity_id: str,
    injection_emulated_entity_id: str,
    start_capacity: float,
) -> Optional[RebuildResult]:
    from sqlalchemy import text

    dialect = getattr(engine, "dialect", None)
    dialect_name = getattr(dialect, "name", None)
    sum_col = "`sum`" if dialect_name in ("mysql", "mariadb") else "sum"

    base_meta_id = _get_meta_id_sa_engine(engine, base_entity_id, create=False)
    injection_meta_id = _get_meta_id_sa_engine(engine, injection_entity_id, create=False)
    if base_meta_id is None or injection_meta_id is None:
        _LOGGER.error("Missing statistics meta for base/injection; history rebuild skipped")
        return None

    battery_in_meta_id = _get_meta_id_sa_engine(engine, battery_in_entity_id, create=True)
    battery_out_meta_id = _get_meta_id_sa_engine(engine, battery_out_entity_id, create=True)
    capacity_meta_id = _get_meta_id_sa_engine(
        engine, capacity_entity_id, create=True, unit="kW", unit_class="power"
    )
    base_emulated_meta_id = _get_meta_id_sa_engine(engine, base_emulated_entity_id, create=True)
    injection_emulated_meta_id = _get_meta_id_sa_engine(engine, injection_emulated_entity_id, create=True)

    derived_meta_ids = (
        battery_in_meta_id,
        battery_out_meta_id,
        capacity_meta_id,
        base_emulated_meta_id,
        injection_emulated_meta_id,
    )

    conn = engine.connect()
    try:
        with conn.begin():
            conn.execute(
                text("DELETE FROM statistics WHERE metadata_id IN (:a,:b,:c,:d,:e)"),
                {
                    "a": derived_meta_ids[0],
                    "b": derived_meta_ids[1],
                    "c": derived_meta_ids[2],
                    "d": derived_meta_ids[3],
                    "e": derived_meta_ids[4],
                },
            )
            conn.execute(
                text("DELETE FROM statistics_short_term WHERE metadata_id IN (:a,:b,:c,:d,:e)"),
                {
                    "a": derived_meta_ids[0],
                    "b": derived_meta_ids[1],
                    "c": derived_meta_ids[2],
                    "d": derived_meta_ids[3],
                    "e": derived_meta_ids[4],
                },
            )

        base_rows = conn.execute(
            text(
                f"SELECT start_ts, {sum_col} AS sum_value, state "
                "FROM statistics WHERE metadata_id = :mid ORDER BY start_ts"
            ),
            {"mid": base_meta_id},
        ).fetchall()
        if not base_rows:
            _LOGGER.error("No base statistics found; history rebuild skipped")
            return None

        injection_rows = conn.execute(
            text(
                f"SELECT start_ts, {sum_col} AS sum_value, state "
                "FROM statistics WHERE metadata_id = :mid ORDER BY start_ts"
            ),
            {"mid": injection_meta_id},
        ).fetchall()
        injection_by_ts: Dict[float, Tuple[float, Optional[float]]] = {
            row[0]: (row[1] if row[1] is not None else 0.0, row[2]) for row in injection_rows
        }

        battery_in_total = max(start_capacity, 0.0)
        battery_out_total = 0.0
        base_emulated_total = 0.0
        capacity = max(battery_in_total - battery_out_total, 0.0)
        base_total = 0.0
        sum_battery_in = 0.0
        sum_battery_out = 0.0
        sum_base_emulated = 0.0
        sum_injection_emulated = 0.0

        rows_to_insert = []
        inserted_rows = 0
        last_base_state = None
        last_injection_state = None
        last_base_sum = None
        last_injection_sum = None
        injection_emulated_state = None

        insert_stmt = text(
            f"INSERT INTO statistics (created_ts, metadata_id, start_ts, state, {sum_col}) "
            "VALUES (:created_ts, :metadata_id, :start_ts, :state, :sum_value)"
        )

        def _flush_rows():
            nonlocal rows_to_insert, inserted_rows
            if not rows_to_insert:
                return
            with conn.begin():
                conn.execute(insert_stmt, rows_to_insert)
            inserted_rows += len(rows_to_insert)
            rows_to_insert = []
            if REBUILD_BATCH_SLEEP_S > 0:
                time.sleep(REBUILD_BATCH_SLEEP_S)

        for start_ts, base_sum, base_state in base_rows:
            if base_sum is None or base_sum < 0:
                base_sum = 0.0
            inj_sum, inj_state = injection_by_ts.get(start_ts, (0.0, None))
            if inj_sum is None or inj_sum < 0:
                inj_sum = 0.0

            delta_base = None
            if base_state is not None and last_base_state is not None:
                delta_base = base_state - last_base_state
            if delta_base is None:
                if last_base_sum is None:
                    delta_base = 0.0
                else:
                    delta_base = base_sum - last_base_sum
            if delta_base < 0:
                delta_base = 0.0

            delta_inj = None
            if inj_state is not None and last_injection_state is not None:
                delta_inj = inj_state - last_injection_state
            if delta_inj is None:
                if last_injection_sum is None:
                    delta_inj = 0.0
                else:
                    delta_inj = inj_sum - last_injection_sum
            if delta_inj < 0:
                delta_inj = 0.0

            battery_in_total += delta_inj
            capacity_before = max(battery_in_total - battery_out_total, 0.0)
            delta_out = min(delta_base, capacity_before)
            battery_out_total += delta_out
            capacity = max(battery_in_total - battery_out_total, 0.0)

            base_total += delta_base
            base_emulated_total = max(base_total - battery_out_total, 0.0)
            delta_emulated = max(delta_base - delta_out, 0.0)

            sum_battery_in += delta_inj
            sum_battery_out += delta_out
            sum_base_emulated += delta_emulated
            sum_injection_emulated += delta_inj

            if inj_state is not None:
                injection_emulated_state = inj_state
            elif injection_emulated_state is None:
                injection_emulated_state = last_injection_state or 0.0

            created_ts = start_ts + 3600
            rows_to_insert.extend(
                [
                    {
                        "created_ts": created_ts,
                        "metadata_id": battery_in_meta_id,
                        "start_ts": start_ts,
                        "state": battery_in_total,
                        "sum_value": sum_battery_in,
                    },
                    {
                        "created_ts": created_ts,
                        "metadata_id": battery_out_meta_id,
                        "start_ts": start_ts,
                        "state": battery_out_total,
                        "sum_value": sum_battery_out,
                    },
                    {
                        "created_ts": created_ts,
                        "metadata_id": capacity_meta_id,
                        "start_ts": start_ts,
                        "state": capacity,
                        "sum_value": 0.0,
                    },
                    {
                        "created_ts": created_ts,
                        "metadata_id": base_emulated_meta_id,
                        "start_ts": start_ts,
                        "state": base_emulated_total,
                        "sum_value": sum_base_emulated,
                    },
                    {
                        "created_ts": created_ts,
                        "metadata_id": injection_emulated_meta_id,
                        "start_ts": start_ts,
                        "state": injection_emulated_state,
                        "sum_value": sum_injection_emulated,
                    },
                ]
            )

            if len(rows_to_insert) >= REBUILD_BATCH_SIZE:
                _flush_rows()

            if base_state is not None:
                last_base_state = base_state
            if inj_state is not None:
                last_injection_state = inj_state
            last_base_sum = base_sum
            last_injection_sum = inj_sum

        _flush_rows()

        return RebuildResult(
            battery_in=battery_in_total,
            battery_out=battery_out_total,
            capacity=capacity,
            base_emulated=base_emulated_total,
            last_base_state=last_base_state,
            last_injection_state=last_injection_state,
            rows=inserted_rows,
        )
    finally:
        conn.close()


def _get_meta_id_sa(
    conn,
    statistic_id: str,
    create: bool,
    unit: str = "kWh",
    unit_class: str = "energy",
) -> Optional[int]:
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError

    row = conn.execute(
        text("SELECT id FROM statistics_meta WHERE statistic_id = :sid"),
        {"sid": statistic_id},
    ).fetchone()
    if row:
        return int(row[0])

    if not create:
        return None

    params = {
        "sid": statistic_id,
        "source": "recorder",
        "uom": unit,
        "uclass": unit_class,
        "has_mean": None,
        "has_sum": 1,
        "name": None,
        "mean_type": 0,
    }
    stmt = text(
        "INSERT INTO statistics_meta (statistic_id, source, unit_of_measurement, unit_class, has_mean, has_sum, name, mean_type) "
        "VALUES (:sid, :source, :uom, :uclass, :has_mean, :has_sum, :name, :mean_type)"
    )

    for attempt in range(5):
        try:
            result = conn.execute(stmt, params)
            last_id = getattr(result, "lastrowid", None)
            return int(last_id) if last_id is not None else None
        except OperationalError as exc:
            orig = getattr(exc, "orig", None)
            code = getattr(orig, "args", [None])[0] if orig is not None else None
            # 1205 = lock wait timeout, 1213 = deadlock
            if code in (1205, 1213) and attempt < 4:
                time.sleep(0.5 * (2 ** attempt))
                continue
            raise

    return None


def _get_meta_id_sa_engine(
    engine,
    statistic_id: str,
    create: bool,
    unit: str = "kWh",
    unit_class: str = "energy",
) -> Optional[int]:
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError

    params = {
        "sid": statistic_id,
        "source": "recorder",
        "uom": unit,
        "uclass": unit_class,
        "has_mean": None,
        "has_sum": 1,
        "name": None,
        "mean_type": 0,
    }
    stmt_select = text("SELECT id FROM statistics_meta WHERE statistic_id = :sid")
    stmt_insert = text(
        "INSERT IGNORE INTO statistics_meta (statistic_id, source, unit_of_measurement, unit_class, has_mean, has_sum, name, mean_type) "
        "VALUES (:sid, :source, :uom, :uclass, :has_mean, :has_sum, :name, :mean_type)"
    )

    for attempt in range(6):
        try:
            with engine.connect() as conn:
                try:
                    conn.exec_driver_sql("SET SESSION innodb_lock_wait_timeout=120")
                except Exception:
                    pass

                row = conn.execute(stmt_select, {"sid": statistic_id}).fetchone()
                if row:
                    return int(row[0])
                if not create:
                    return None

                conn.execute(stmt_insert, params)
                conn.commit()

                row = conn.execute(stmt_select, {"sid": statistic_id}).fetchone()
                if row:
                    return int(row[0])
        except OperationalError as exc:
            orig = getattr(exc, "orig", None)
            code = getattr(orig, "args", [None])[0] if orig is not None else None
            if code in (1205, 1213) and attempt < 5:
                time.sleep(0.5 * (2 ** attempt))
                continue
            raise

    return None
