"""Database setup and connection handling for rig."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

# The database sits at the repo root next to the code. RIG_DB overrides it,
# which is how the tests point at a throwaway file instead of your real data.
DEFAULT_DB = Path(__file__).resolve().parent.parent / "rig.db"

SCHEMA = """
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


def db_path() -> Path:
    """Where the database file lives."""
    return Path(os.environ.get("RIG_DB", DEFAULT_DB))


def connect() -> sqlite3.Connection:
    """Open the database, creating the file and tables on first use."""
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn
