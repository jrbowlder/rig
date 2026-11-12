"""Tests for the command line layer.

Run from the repo root:  python3 -m unittest discover -s tests
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from rig.cli import main
from rig.db import db_path


class CliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.environ["RIG_DB"] = str(Path(self.tmp.name) / "test.db")
        self.addCleanup(os.environ.pop, "RIG_DB", None)

    def run_cli(self, *args: str) -> tuple[int, str]:
        """Run the CLI as if from the shell, capturing what it prints."""
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(out):
            try:
                code = main(list(args))
            except SystemExit as exit_request:
                # SystemExit carries either an exit code or a message. The
                # message goes to stderr in a real shell, with code 1.
                raw = exit_request.code
                if isinstance(raw, int) or raw is None:
                    code = int(raw or 0)
                else:
                    print(raw, file=sys.stderr)
                    code = 1
        return code, out.getvalue()

    def add_vehicle(self, name: str = "Disco", odo: int = 1000) -> None:
        code, _ = self.run_cli("add-vehicle", "--name", name, "--odo", str(odo))
        self.assertEqual(code, 0)

    def test_add_and_list_a_vehicle(self) -> None:
        self.add_vehicle("Range Rover Classic", 187000)
        code, output = self.run_cli("vehicles")
        self.assertEqual(code, 0)
        self.assertIn("Range Rover Classic", output)
        self.assertIn("187,000 mi", output)

    def test_duplicate_vehicle_is_refused_with_exit_1(self) -> None:
        self.add_vehicle("Disco")
        code, output = self.run_cli("add-vehicle", "--name", "Disco")
        self.assertEqual(code, 1)
        self.assertIn("already exists", output)

    def test_log_then_due_shows_the_job_as_done(self) -> None:
        self.add_vehicle(odo=10000)
        code, _ = self.run_cli(
            "log",
            "--vehicle",
            "Disco",
            "--service",
            "oil change",
            "--date",
            "2026-11-01",
            "--odo",
            "10000",
            "--cost",
            "68.40",
        )
        self.assertEqual(code, 0)

        code, output = self.run_cli("due")
        self.assertEqual(code, 0)
        oil_line = next(line for line in output.splitlines() if "oil change" in line)
        self.assertIn("2026-11-01", oil_line)
        self.assertNotIn("never recorded", oil_line)

    def test_coil_pack_does_not_satisfy_the_oil_change(self) -> None:
        self.add_vehicle(odo=20000)
        self.run_cli(
            "log",
            "--vehicle",
            "Disco",
            "--service",
            "coil pack replaced",
            "--date",
            "2026-11-01",
            "--odo",
            "20000",
        )
        code, output = self.run_cli("due")
        self.assertEqual(code, 0)
        oil_line = next(line for line in output.splitlines() if "oil change" in line)
        self.assertIn("never recorded", oil_line)

    def test_infinite_cost_is_rejected_not_crashed(self) -> None:
        self.add_vehicle()
        code, output = self.run_cli(
            "log", "--vehicle", "Disco", "--service", "x", "--cost", "Infinity"
        )
        self.assertEqual(code, 2)
        self.assertIn("not a valid amount", output)
        self.assertNotIn("Traceback", output)

    def test_spend_total_matches_the_records(self) -> None:
        self.add_vehicle()
        for cost in ("68.40", "1240", "145"):
            self.run_cli(
                "log", "--vehicle", "Disco", "--service", "job", "--cost", cost
            )
        code, output = self.run_cli("spend")
        self.assertEqual(code, 0)
        self.assertIn("$1,453.40", output)
        self.assertIn("3", output)

    def test_export_refuses_to_overwrite_the_database(self) -> None:
        self.add_vehicle()
        code, output = self.run_cli("export", "--out", str(db_path()))
        self.assertNotEqual(code, 0)
        self.assertIn("database", output.lower())
        self.assertTrue(db_path().exists())

    def test_job_add_schedules_a_new_job(self) -> None:
        self.add_vehicle()
        code, output = self.run_cli(
            "job", "add", "--vehicle", "Disco", "--job", "diff oil", "--miles", "30000"
        )
        self.assertEqual(code, 0)
        self.assertIn("diff oil", output)

        code, output = self.run_cli("due")
        self.assertEqual(code, 0)
        self.assertIn("diff oil", output)

    def test_job_add_refuses_a_duplicate(self) -> None:
        self.add_vehicle()
        self.run_cli(
            "job", "add", "--vehicle", "Disco", "--job", "diff oil", "--miles", "30000"
        )
        code, output = self.run_cli(
            "job", "add", "--vehicle", "Disco", "--job", "diff oil", "--miles", "40000"
        )
        self.assertNotEqual(code, 0)
        self.assertIn("already has", output)

    def test_due_runs_against_a_read_only_database(self) -> None:
        """`due` used to write rules and died with 'readonly database'."""
        self.add_vehicle(odo=10000)
        self.run_cli(
            "log", "--vehicle", "Disco", "--service", "oil change", "--odo", "10000"
        )
        path = db_path()
        os.chmod(path, 0o444)
        self.addCleanup(os.chmod, path, 0o644)

        code, output = self.run_cli("due")
        self.assertEqual(code, 0)
        self.assertIn("oil change", output)
        self.assertNotIn("readonly", output)


if __name__ == "__main__":
    unittest.main()
