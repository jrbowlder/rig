"""Database setup, schema versioning and connection handling for rig."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

# The database sits at the repo root next to the code. RIG_DB overrides it,
# which is how the tests point at a throwaway file instead of your real data.
DEFAULT_DB = Path(__file__).resolve().parent.parent / "rig.db"

# Bump this when the schema changes, and add the statements that get an
# existing database from the old version to the new one in MIGRATIONS below.
SCHEMA_VERSION = 1

BASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS vehicles (
    id               INTEGER PRIMARY KEY,
    name             TEXT NOT NULL UNIQUE,
    year             INTEGER,
    make             TEXT,
    model            TEXT,
    odometer         INTEGER NOT NULL DEFAULT 0,
    odometer_updated TEXT
);

CREATE TABLE IF NOT EXISTS services (
    id           INTEGER PRIMARY KEY,
    vehicle_id   INTEGER NOT NULL REFERENCES vehicles(id),
    service      TEXT NOT NULL,
    service_date TEXT NOT NULL,
    odometer     INTEGER,
    cost_cents   INTEGER NOT NULL DEFAULT 0,
    notes        TEXT
);

CREATE INDEX IF NOT EXISTS idx_services_vehicle
    ON services (vehicle_id, service_date);

CREATE TABLE IF NOT EXISTS schedule (
    id              INTEGER PRIMARY KEY,
    vehicle_id      INTEGER NOT NULL REFERENCES vehicles(id),
    job             TEXT NOT NULL,
    interval_miles  INTEGER,
    interval_months INTEGER,
    UNIQUE (vehicle_id, job)
);
"""

# Keyed by the version the step produces. An empty dict is correct at version 1:
# there is nothing to migrate an existing database towards yet.
MIGRATIONS: dict[int, list[str]] = {}


def db_path() -> Path:
    """Where the database file lives."""
    return Path(os.environ.get("RIG_DB", DEFAULT_DB))


def _backfill_schedules(conn: sqlite3.Connection) -> None:
    """Give every existing vehicle any default rules it does not have yet.

    Only runs while the schema is being set up, so ordinary commands never
    write to the database just to read from it.
    """
    from .schedule import DEFAULTS

    conn.executemany(
        """
        INSERT INTO schedule (vehicle_id, job, interval_miles, interval_months)
        SELECT v.id, ?, ?, ?
        FROM vehicles v
        WHERE 1
        ON CONFLICT (vehicle_id, job) DO NOTHING
        """,
        [(job, miles, months) for job, miles, months, _k in DEFAULTS],
    )


def migrate(conn: sqlite3.Connection) -> None:
    """Bring the database up to SCHEMA_VERSION.

    Version 0 means a new file or one created before versioning existed. The
    base schema uses IF NOT EXISTS throughout, so running it over an old
    database adds what is missing and changes nothing else.
    """
    version = conn.execute("PRAGMA user_version").fetchone()[0]

    if version == 0:
        conn.executescript(BASE_SCHEMA)
        _backfill_schedules(conn)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
        return

    while version < SCHEMA_VERSION:
        for statement in MIGRATIONS.get(version + 1, []):
            conn.execute(statement)
        version += 1
        conn.execute(f"PRAGMA user_version = {version}")
        conn.commit()


def connect() -> sqlite3.Connection:
    """Open the database, migrating it on first use."""
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    return conn
