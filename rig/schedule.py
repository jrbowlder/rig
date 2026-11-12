"""Service schedule rules and the due engine.

The rule for a job is an interval in miles, in months, or both. When both are
set, the job is due at whichever limit arrives first.
"""

from __future__ import annotations

import sqlite3
from calendar import monthrange
from datetime import date, datetime

DUE_SOON_MILES = 500
DUE_SOON_DAYS = 30

# Shipped defaults: job name, miles interval, months interval, and the words
# that make a logged service count for this job.
DEFAULTS = (
    ("oil change", 5000, 12, ("oil",)),
    ("air filter", 15000, 24, ("air filter", "airfilter")),
    ("tyres", 30000, 60, ("tyre", "tire")),
    ("brake fluid", 30000, 24, ("brake fluid",)),
    ("annual inspection", None, 12, ("inspection", "annual", "mot", "warrant")),
)


def add_months(start: date, months: int) -> date:
    """Add whole months to a date, clamping the day to the month's length."""
    year = start.year + (start.month - 1 + months) // 12
    month = (start.month - 1 + months) % 12 + 1
    day = min(start.day, monthrange(year, month)[1])
    return date(year, month, day)


def keywords_for(job: str) -> tuple[str, ...]:
    """Words that make a logged service count toward this job."""
    for name, _miles, _months, keywords in DEFAULTS:
        if name == job:
            return keywords
    return (job.lower(),)


def seed_schedule(conn: sqlite3.Connection, vehicle_id: int) -> None:
    """Give a vehicle the default rules for any job it does not already have."""
    conn.executemany(
        """
        INSERT INTO schedule (vehicle_id, job, interval_miles, interval_months)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (vehicle_id, job) DO NOTHING
        """,
        [(vehicle_id, job, miles, months) for job, miles, months, _k in DEFAULTS],
    )
    conn.commit()


def last_service_for(
    conn: sqlite3.Connection, vehicle_id: int, job: str
) -> sqlite3.Row | None:
    """The most recent logged service that matches this job."""
    keywords = keywords_for(job)
    rows = conn.execute(
        """
        SELECT * FROM services
        WHERE vehicle_id = ?
        ORDER BY service_date DESC, id DESC
        """,
        (vehicle_id,),
    ).fetchall()
    for row in rows:
        text = row["service"].lower()
        if any(word in text for word in keywords):
            return row
    return None


def describe_left(miles_left: int | None, days_left: int | None) -> str:
    """One line saying how urgent a job is, in whichever units apply."""
    parts = []
    for value, unit in ((miles_left, "mi"), (days_left, "days")):
        if value is None:
            continue
        if value < 0:
            parts.append(f"overdue by {abs(value):,} {unit}")
        elif value == 0:
            parts.append(f"due now ({unit})")
        else:
            parts.append(f"{value:,} {unit} left")
    return " / ".join(parts) if parts else "no usable limit"


def compute_due(
    conn: sqlite3.Connection, vehicle: sqlite3.Row, today: date | None = None
) -> list[dict]:
    """Work out where every scheduled job stands for one vehicle."""
    today = today or date.today()
    seed_schedule(conn, vehicle["id"])

    rules = conn.execute(
        "SELECT * FROM schedule WHERE vehicle_id = ? ORDER BY job",
        (vehicle["id"],),
    ).fetchall()

    results = []
    for rule in rules:
        last = last_service_for(conn, vehicle["id"], rule["job"])

        miles_left = days_left = None
        due_odo = due_date = None
        status = "never"

        if last is not None:
            if rule["interval_miles"] is not None and last["odometer"] is not None:
                due_odo = last["odometer"] + rule["interval_miles"]
                miles_left = due_odo - vehicle["odometer"]

            if rule["interval_months"]:
                last_date = datetime.strptime(last["service_date"], "%Y-%m-%d").date()
                due_date = add_months(last_date, rule["interval_months"])
                days_left = (due_date - today).days

            overdue = (miles_left is not None and miles_left <= 0) or (
                days_left is not None and days_left <= 0
            )
            soon = (miles_left is not None and miles_left <= DUE_SOON_MILES) or (
                days_left is not None and days_left <= DUE_SOON_DAYS
            )
            status = "overdue" if overdue else "due soon" if soon else "ok"

        results.append(
            {
                "job": rule["job"],
                "interval_miles": rule["interval_miles"],
                "interval_months": rule["interval_months"],
                "last": last,
                "due_odo": due_odo,
                "due_date": due_date,
                "miles_left": miles_left,
                "days_left": days_left,
                "status": status,
            }
        )

    rank = {"never": 0, "overdue": 0, "due soon": 1, "ok": 2}
    results.sort(
        key=lambda r: (
            rank[r["status"]],
            r["days_left"] if r["days_left"] is not None else 0,
            r["miles_left"] if r["miles_left"] is not None else 0,
        )
    )
    return results
