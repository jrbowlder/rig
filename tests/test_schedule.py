"""Tests for the due engine.

Run from the repo root:  python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date
from pathlib import Path

from rig.db import connect
from rig.schedule import add_months, compute_due, matches_keywords, seed_schedule

TODAY = date(2026, 11, 12)


class DueEngineTest(unittest.TestCase):
    def setUp(self) -> None:
        """Each test gets its own empty database file."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.environ["RIG_DB"] = str(Path(self.tmp.name) / "test.db")
        self.addCleanup(os.environ.pop, "RIG_DB", None)
        self.conn = connect()
        self.addCleanup(self.conn.close)
        self.vehicle_id = self.add_vehicle(0)

    def add_vehicle(self, odometer: int) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO vehicles (name, odometer, odometer_updated)
            VALUES ('Test', ?, '2026-01-01')
            """,
            (odometer,),
        )
        self.conn.commit()
        # Rules are created with the vehicle in the real code path.
        seed_schedule(self.conn, cur.lastrowid)
        return cur.lastrowid

    def set_odometer(self, miles: int) -> None:
        self.conn.execute(
            "UPDATE vehicles SET odometer = ? WHERE id = ?",
            (miles, self.vehicle_id),
        )
        self.conn.commit()

    def add_service(self, text: str, when: str, odometer: int) -> None:
        self.conn.execute(
            """
            INSERT INTO services (vehicle_id, service, service_date, odometer, cost_cents)
            VALUES (?, ?, ?, ?, 0)
            """,
            (self.vehicle_id, text, when, odometer),
        )
        self.conn.commit()

    def due_for(self, job: str) -> dict:
        vehicle = self.conn.execute(
            "SELECT * FROM vehicles WHERE id = ?", (self.vehicle_id,)
        ).fetchone()
        rows = compute_due(self.conn, vehicle, today=TODAY)
        return next(row for row in rows if row["job"] == job)

    def test_mileage_limit_fires_while_date_is_fine(self) -> None:
        self.set_odometer(50000)
        self.add_service("oil change", "2026-11-01", 100)
        row = self.due_for("oil change")
        self.assertEqual(row["status"], "overdue")
        self.assertEqual(row["miles_left"], -44900)
        self.assertEqual(row["days_left"], 354)

    def test_date_limit_fires_while_mileage_is_fine(self) -> None:
        self.set_odometer(10000)
        self.add_service("air filter", "2024-01-01", 9000)
        row = self.due_for("air filter")
        self.assertEqual(row["status"], "overdue")
        self.assertEqual(row["miles_left"], 14000)
        self.assertLess(row["days_left"], 0)

    def test_exactly_at_the_mileage_limit_is_due_not_fine(self) -> None:
        self.set_odometer(10000)
        self.add_service("oil change", "2026-11-01", 5000)
        row = self.due_for("oil change")
        self.assertEqual(row["miles_left"], 0)
        self.assertEqual(row["status"], "overdue")

    def test_one_mile_inside_the_limit_is_due_soon(self) -> None:
        self.set_odometer(9999)
        self.add_service("oil change", "2026-11-01", 5000)
        row = self.due_for("oil change")
        self.assertEqual(row["miles_left"], 1)
        self.assertEqual(row["status"], "due soon")

    def test_no_history_is_never_not_overdue_by_the_odometer(self) -> None:
        row = self.due_for("oil change")
        self.assertEqual(row["status"], "never")
        self.assertIsNone(row["miles_left"])
        self.assertIsNone(row["due_odo"])

    def test_keyword_match_counts_oil_plus_filter_as_an_oil_change(self) -> None:
        self.set_odometer(61500)
        self.add_service("oil + filter", "2026-11-10", 61500)
        row = self.due_for("oil change")
        self.assertEqual(row["last"]["service"], "oil + filter")
        self.assertEqual(row["due_odo"], 66500)

    def test_unrelated_service_does_not_count(self) -> None:
        self.set_odometer(61500)
        self.add_service("wiper blades", "2026-11-10", 61500)
        row = self.due_for("oil change")
        self.assertEqual(row["status"], "never")

    def test_coil_pack_is_not_an_oil_change(self) -> None:
        """The old substring test matched 'oil' inside 'coil'."""
        self.set_odometer(20000)
        self.add_service("coil pack replaced", "2026-11-01", 20000)
        row = self.due_for("oil change")
        self.assertEqual(row["status"], "never")

    def test_boiling_over_is_not_an_oil_change(self) -> None:
        self.set_odometer(20000)
        self.add_service("boiling over, coolant topped up", "2026-11-01", 20000)
        row = self.due_for("oil change")
        self.assertEqual(row["status"], "never")

    def test_plural_still_matches(self) -> None:
        self.set_odometer(61200)
        self.add_service("tyres - 4", "2026-11-01", 61200)
        row = self.due_for("tyres")
        self.assertEqual(row["last"]["service"], "tyres - 4")

    def test_due_soon_window(self) -> None:
        self.set_odometer(64500)
        self.add_service("oil change", "2026-11-01", 61500)
        row = self.due_for("oil change")
        self.assertEqual(row["miles_left"], 2000)
        self.assertEqual(row["status"], "ok")

        self.set_odometer(66000)
        row = self.due_for("oil change")
        self.assertEqual(row["miles_left"], 500)
        self.assertEqual(row["status"], "due soon")


class AddMonthsTest(unittest.TestCase):
    def test_simple_case(self) -> None:
        self.assertEqual(add_months(date(2026, 1, 15), 12), date(2027, 1, 15))

    def test_clamps_short_months(self) -> None:
        self.assertEqual(add_months(date(2026, 1, 31), 1), date(2026, 2, 28))

    def test_clamps_to_leap_february(self) -> None:
        self.assertEqual(add_months(date(2028, 1, 31), 1), date(2028, 2, 29))

    def test_crosses_the_year_boundary(self) -> None:
        self.assertEqual(add_months(date(2026, 11, 30), 3), date(2027, 2, 28))


if __name__ == "__main__":
    unittest.main()
