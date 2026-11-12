"""Command line interface for rig."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date

from .db import connect


def cmd_add_vehicle(args: argparse.Namespace) -> int:
    conn = connect()
    try:
        cur = conn.execute(
            """
            INSERT INTO vehicles (name, year, make, model, odometer, odometer_updated)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                args.name,
                args.year,
                args.make,
                args.model,
                args.odo,
                date.today().isoformat(),
            ),
        )
    except sqlite3.IntegrityError:
        print(f"A vehicle named {args.name!r} already exists.", file=sys.stderr)
        conn.close()
        return 1

    conn.commit()
    conn.close()
    print(f"Added vehicle #{cur.lastrowid}: {args.name}")
    return 0


def cmd_vehicles(args: argparse.Namespace) -> int:
    conn = connect()
    rows = conn.execute("SELECT * FROM vehicles ORDER BY name").fetchall()
    conn.close()

    if not rows:
        print("No vehicles yet. Add one with: python3 -m rig add-vehicle --name ...")
        return 0

    for row in rows:
        description = " ".join(
            str(part) for part in (row["year"], row["make"], row["model"]) if part
        )
        print(
            f"#{row['id']:<3} {row['name']:<14} {row['odometer']:>7} mi   {description}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rig",
        description="Maintenance and cost tracking for a small fleet.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_vehicle = subparsers.add_parser("add-vehicle", help="Register a vehicle")
    add_vehicle.add_argument("--name", required=True, help="Short name, e.g. Disco")
    add_vehicle.add_argument("--year", type=int)
    add_vehicle.add_argument("--make")
    add_vehicle.add_argument("--model")
    add_vehicle.add_argument(
        "--odo", type=int, default=0, help="Current odometer in miles"
    )
    add_vehicle.set_defaults(func=cmd_add_vehicle)

    vehicles = subparsers.add_parser("vehicles", help="List registered vehicles")
    vehicles.set_defaults(func=cmd_vehicles)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
