"""Command line interface for rig."""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .db import connect, db_path
from .schedule import compute_due, describe_left, seed_schedule


def parse_money(text: str) -> int:
    """Turn '65.42' or '$1,240' into an integer number of cents."""
    cleaned = text.strip().replace("$", "").replace(",", "")
    try:
        return int((Decimal(cleaned) * 100).to_integral_value())
    except (InvalidOperation, ValueError, OverflowError):
        # OverflowError is not theoretical: Decimal('Infinity') converts to a
        # Decimal happily and only fails at int(), so it needs naming here.
        raise argparse.ArgumentTypeError(f"not a valid amount: {text!r}")


def format_money(cents: int) -> str:
    """Turn 6542 back into '$65.42' using whole-number arithmetic only."""
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100:,}.{cents % 100:02d}"


def format_dollars(cents: int) -> str:
    """The same number without the dollar sign, for CSV output."""
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}{cents // 100}.{cents % 100:02d}"


def render_table(
    headers: list[str], rows: list[list[str]], right: set[int] | None = None
) -> list[str]:
    """Lay out a table whose columns are as wide as their widest cell.

    Hardcoded widths look fine until a vehicle is called "Range Rover Classic",
    at which point the columns run together.
    """
    right = right or set()
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(str(cell)))

    def line(cells: list[str]) -> str:
        parts = []
        for index, cell in enumerate(cells):
            text = str(cell)
            parts.append(
                text.rjust(widths[index])
                if index in right
                else text.ljust(widths[index])
            )
        return "  ".join(parts).rstrip()

    separator = "-" * (sum(widths) + 2 * (len(widths) - 1))
    return [line(headers), separator] + [line(row) for row in rows]


def lookup_vehicle(conn: sqlite3.Connection, ref: str) -> sqlite3.Row:
    """Find one vehicle by name or by '#id', or stop with a helpful message."""
    ref = ref.strip()
    if ref.startswith("#") and ref[1:].isdigit():
        row = conn.execute(
            "SELECT * FROM vehicles WHERE id = ?", (int(ref[1:]),)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM vehicles WHERE lower(name) = lower(?)", (ref,)
        ).fetchone()

    if row is None:
        names = [
            r["name"] for r in conn.execute("SELECT name FROM vehicles ORDER BY name")
        ]
        known = ", ".join(names) if names else "none registered yet"
        raise SystemExit(f"No vehicle matches {ref!r}. Known vehicles: {known}")
    return row


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

    # The rules belong to the vehicle, so they are created with it. That is what
    # lets `due` and `schedule` stay read-only.
    new_id = cur.lastrowid
    if new_id is None:
        conn.close()
        raise SystemExit("Could not read the new vehicle's id back.")
    seed_schedule(conn, new_id)

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

    table = []
    for row in rows:
        description = " ".join(
            str(part) for part in (row["year"], row["make"], row["model"]) if part
        )
        table.append(
            [f"#{row['id']}", row["name"], f"{row['odometer']:,} mi", description]
        )

    for line in render_table(["#", "Name", "Odometer", "Description"], table, {0, 2}):
        print(line)
    return 0


def cmd_log(args: argparse.Namespace) -> int:
    conn = connect()
    vehicle = lookup_vehicle(conn, args.vehicle)

    service_date = args.date or date.today().isoformat()
    try:
        datetime.strptime(service_date, "%Y-%m-%d")
    except ValueError:
        conn.close()
        raise SystemExit(f"Date must be YYYY-MM-DD, got {service_date!r}")

    if args.odo is not None and args.odo < 0:
        conn.close()
        raise SystemExit("Odometer cannot be negative.")

    conn.execute(
        """
        INSERT INTO services (vehicle_id, service, service_date, odometer, cost_cents, notes)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            vehicle["id"],
            args.service,
            service_date,
            args.odo,
            args.cost,
            args.notes,
        ),
    )

    # A service record is also evidence of mileage, so it can move the
    # vehicle's odometer forward. It never moves it backwards.
    moved = args.odo is not None and args.odo > vehicle["odometer"]
    if moved:
        conn.execute(
            "UPDATE vehicles SET odometer = ?, odometer_updated = ? WHERE id = ?",
            (args.odo, date.today().isoformat(), vehicle["id"]),
        )

    conn.commit()
    conn.close()

    print(
        f"Logged {args.service!r} on {vehicle['name']} "
        f"({service_date}, {format_money(args.cost)})"
    )
    if moved:
        print(f"  odometer now {args.odo:,} mi")
    elif args.odo is not None and args.odo < vehicle["odometer"]:
        print(
            f"  note: {args.odo:,} mi is below the recorded {vehicle['odometer']:,} mi"
        )
    return 0


def cmd_odo(args: argparse.Namespace) -> int:
    conn = connect()
    vehicle = lookup_vehicle(conn, args.vehicle)

    if args.miles < vehicle["odometer"] and not args.force:
        conn.close()
        raise SystemExit(
            f"{vehicle['name']} is already at {vehicle['odometer']:,} mi. "
            "Use --force if the reading really went down."
        )

    conn.execute(
        "UPDATE vehicles SET odometer = ?, odometer_updated = ? WHERE id = ?",
        (args.miles, date.today().isoformat(), vehicle["id"]),
    )
    conn.commit()
    conn.close()
    print(f"{vehicle['name']}: {vehicle['odometer']:,} mi -> {args.miles:,} mi")
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    conn = connect()
    vehicle = lookup_vehicle(conn, args.vehicle)
    rows = conn.execute(
        """
        SELECT * FROM services
        WHERE vehicle_id = ?
        ORDER BY service_date DESC, id DESC
        """,
        (vehicle["id"],),
    ).fetchall()
    conn.close()

    if not rows:
        print(f"No service records for {vehicle['name']} yet.")
        return 0

    table = []
    for row in rows:
        odo = f"{row['odometer']:,} mi" if row["odometer"] is not None else "-"
        table.append(
            [row["service_date"], odo, row["service"], format_money(row["cost_cents"])]
        )

    for line in render_table(["Date", "Mileage", "Service", "Cost"], table, {1, 3}):
        print(line)

    notes = [row["notes"] for row in rows if row["notes"]]
    if notes:
        print()
        for note in notes:
            print(f"  note: {note}")

    total = sum(row["cost_cents"] for row in rows)
    record_word = "record" if len(rows) == 1 else "records"
    print()
    print(f"{len(rows)} {record_word}, total {format_money(total)}")
    return 0


def cmd_due(args: argparse.Namespace) -> int:
    conn = connect()
    if args.vehicle:
        vehicles = [lookup_vehicle(conn, args.vehicle)]
    else:
        vehicles = conn.execute("SELECT * FROM vehicles ORDER BY name").fetchall()

    if not vehicles:
        conn.close()
        print("No vehicles registered yet.")
        return 0

    for vehicle in vehicles:
        results = compute_due(conn, vehicle)
        print(f"\n{vehicle['name']}  ({vehicle['odometer']:,} mi)")

        table = []
        for row in results:
            last = row["last"]
            if last is None:
                last_text = "never recorded"
            elif last["odometer"] is None:
                last_text = last["service_date"]
            else:
                last_text = f"{last['service_date']} @ {last['odometer']:,}"

            next_miles = (
                f"{row['due_odo']:,} mi" if row["due_odo"] is not None else "-"
            )
            next_date = (
                row["due_date"].isoformat() if row["due_date"] is not None else "-"
            )
            status = (
                "never recorded, treat as due"
                if row["status"] == "never"
                else describe_left(row["miles_left"], row["days_left"])
            )
            table.append([row["job"], last_text, next_miles, next_date, status])

        for line in render_table(
            ["Job", "Last done", "Next miles", "Next date", "Status"], table
        ):
            print(line)

        urgent = [
            r for r in results if r["status"] in ("overdue", "never", "due soon")
        ]
        if urgent:
            print(f"\n  {len(urgent)} of {len(results)} jobs need attention")
        else:
            print(f"\n  all {len(results)} jobs fine")

    conn.close()
    return 0


def cmd_schedule(args: argparse.Namespace) -> int:
    conn = connect()
    vehicle = lookup_vehicle(conn, args.vehicle)
    rows = conn.execute(
        "SELECT * FROM schedule WHERE vehicle_id = ? ORDER BY job", (vehicle["id"],)
    ).fetchall()
    conn.close()

    print(f"{vehicle['name']}: schedule rules")
    table = [
        [
            row["job"],
            f"{row['interval_miles']:,}" if row["interval_miles"] else "-",
            str(row["interval_months"]) if row["interval_months"] else "-",
        ]
        for row in rows
    ]
    for line in render_table(["Job", "Every miles", "Every months"], table, {1, 2}):
        print(line)
    return 0


def cmd_interval(args: argparse.Namespace) -> int:
    if args.miles is None and args.months is None:
        raise SystemExit("Give --miles, --months, or both. Zero removes that limit.")

    conn = connect()
    vehicle = lookup_vehicle(conn, args.vehicle)

    row = conn.execute(
        "SELECT * FROM schedule WHERE vehicle_id = ? AND lower(job) = lower(?)",
        (vehicle["id"], args.job),
    ).fetchone()
    if row is None:
        jobs = [
            r["job"]
            for r in conn.execute(
                "SELECT job FROM schedule WHERE vehicle_id = ? ORDER BY job",
                (vehicle["id"],),
            )
        ]
        conn.close()
        raise SystemExit(
            f"No job {args.job!r}. Jobs on {vehicle['name']}: {', '.join(jobs)}. "
            "Add one with: rig job add"
        )

    miles = row["interval_miles"] if args.miles is None else (args.miles or None)
    months = row["interval_months"] if args.months is None else (args.months or None)

    conn.execute(
        "UPDATE schedule SET interval_miles = ?, interval_months = ? "
        "WHERE vehicle_id = ? AND job = ?",
        (miles, months, vehicle["id"], row["job"]),
    )
    conn.commit()
    conn.close()

    def show(m: int | None, mo: int | None) -> str:
        return f"{m if m else '-'} mi / {mo if mo else '-'} mo"

    print(
        f"{vehicle['name']} {row['job']}: "
        f"{show(row['interval_miles'], row['interval_months'])} -> {show(miles, months)}"
    )
    return 0


def cmd_job_add(args: argparse.Namespace) -> int:
    if args.miles is None and args.months is None:
        raise SystemExit("Give --miles, --months, or both.")
    if args.miles is not None and args.miles <= 0:
        raise SystemExit("--miles must be more than zero for a new job.")
    if args.months is not None and args.months <= 0:
        raise SystemExit("--months must be more than zero for a new job.")

    job = args.job.strip()
    if not job:
        raise SystemExit("Job needs a name.")

    conn = connect()
    vehicle = lookup_vehicle(conn, args.vehicle)

    existing = conn.execute(
        "SELECT job FROM schedule WHERE vehicle_id = ? AND lower(job) = lower(?)",
        (vehicle["id"], job),
    ).fetchone()
    if existing is not None:
        conn.close()
        raise SystemExit(
            f"{vehicle['name']} already has {existing['job']!r}. "
            "Use interval to change it."
        )

    conn.execute(
        """
        INSERT INTO schedule (vehicle_id, job, interval_miles, interval_months)
        VALUES (?, ?, ?, ?)
        """,
        (vehicle["id"], job, args.miles, args.months),
    )
    conn.commit()
    conn.close()

    miles = args.miles if args.miles else "-"
    months = args.months if args.months else "-"
    print(f"Added {job!r} to {vehicle['name']}: {miles} mi / {months} mo")
    return 0


def cmd_job_remove(args: argparse.Namespace) -> int:
    conn = connect()
    vehicle = lookup_vehicle(conn, args.vehicle)
    row = conn.execute(
        "SELECT job FROM schedule WHERE vehicle_id = ? AND lower(job) = lower(?)",
        (vehicle["id"], args.job.strip()),
    ).fetchone()
    if row is None:
        conn.close()
        raise SystemExit(f"{vehicle['name']} has no job {args.job!r}.")

    conn.execute(
        "DELETE FROM schedule WHERE vehicle_id = ? AND job = ?",
        (vehicle["id"], row["job"]),
    )
    conn.commit()
    conn.close()
    print(f"Removed {row['job']!r} from {vehicle['name']}")
    return 0


def cmd_spend(args: argparse.Namespace) -> int:
    conn = connect()

    where = []
    params: list[object] = []
    if args.vehicle:
        where.append("v.id = ?")
        params.append(lookup_vehicle(conn, args.vehicle)["id"])
    if args.year is not None:
        where.append("substr(s.service_date, 1, 4) = ?")
        params.append(str(args.year))

    clause = f"WHERE {' AND '.join(where)}" if where else ""
    rows = conn.execute(
        f"""
        SELECT v.name AS vehicle,
               substr(s.service_date, 1, 4) AS year,
               COUNT(*) AS records,
               SUM(s.cost_cents) AS cost
        FROM services s
        JOIN vehicles v ON v.id = s.vehicle_id
        {clause}
        GROUP BY v.name, year
        ORDER BY v.name, year
        """,
        params,
    ).fetchall()
    conn.close()

    if not rows:
        print("No service records match that.")
        return 0

    table = [
        [row["vehicle"], row["year"], str(row["records"]), format_money(row["cost"])]
        for row in rows
    ]
    total_cost = sum(row["cost"] for row in rows)
    total_records = sum(row["records"] for row in rows)
    table.append(["Total", "", str(total_records), format_money(total_cost)])

    for line in render_table(["Vehicle", "Year", "Records", "Cost"], table, {2, 3}):
        print(line)
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    target = Path(args.out).expanduser().resolve()
    if target == db_path().resolve():
        raise SystemExit("That is the database file. Pick a different name for the CSV.")

    conn = connect()
    rows = conn.execute(
        """
        SELECT v.name AS vehicle, s.service_date, s.service, s.odometer,
               s.cost_cents, s.notes
        FROM services s
        JOIN vehicles v ON v.id = s.vehicle_id
        ORDER BY v.name, s.service_date
        """
    ).fetchall()
    conn.close()

    with open(target, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["vehicle", "date", "service", "odometer", "cost", "notes"])
        for row in rows:
            writer.writerow(
                [
                    row["vehicle"],
                    row["service_date"],
                    row["service"],
                    row["odometer"] if row["odometer"] is not None else "",
                    format_dollars(row["cost_cents"]),
                    row["notes"] or "",
                ]
            )

    print(f"Wrote {len(rows)} records to {target}")
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

    log = subparsers.add_parser("log", help="Record a service")
    log.add_argument("--vehicle", required=True, help="Vehicle name or #id")
    log.add_argument("--service", required=True, help='What was done, e.g. "oil change"')
    log.add_argument("--date", help="Date of the work, YYYY-MM-DD (default today)")
    log.add_argument("--odo", type=int, help="Odometer when the work was done")
    log.add_argument("--cost", type=parse_money, default=0, help="Cost in dollars")
    log.add_argument("--notes")
    log.set_defaults(func=cmd_log)

    odo = subparsers.add_parser("odo", help="Update a vehicle's odometer")
    odo.add_argument("--vehicle", required=True, help="Vehicle name or #id")
    odo.add_argument("--miles", type=int, required=True)
    odo.add_argument("--force", action="store_true", help="Allow a lower reading")
    odo.set_defaults(func=cmd_odo)

    history = subparsers.add_parser("history", help="Show service records")
    history.add_argument("--vehicle", required=True, help="Vehicle name or #id")
    history.set_defaults(func=cmd_history)

    due = subparsers.add_parser("due", help="Show what is due or overdue")
    due.add_argument("--vehicle", help="Vehicle name or #id (default: all)")
    due.set_defaults(func=cmd_due)

    schedule = subparsers.add_parser("schedule", help="Show a vehicle's interval rules")
    schedule.add_argument("--vehicle", required=True, help="Vehicle name or #id")
    schedule.set_defaults(func=cmd_schedule)

    interval = subparsers.add_parser("interval", help="Change a job's interval")
    interval.add_argument("--vehicle", required=True, help="Vehicle name or #id")
    interval.add_argument("--job", required=True, help='Job name, e.g. "oil change"')
    interval.add_argument("--miles", type=int, help="Miles interval, 0 for none")
    interval.add_argument("--months", type=int, help="Months interval, 0 for none")
    interval.set_defaults(func=cmd_interval)

    job = subparsers.add_parser("job", help="Add or remove a scheduled job")
    job_subparsers = job.add_subparsers(dest="job_command", required=True)

    job_add = job_subparsers.add_parser("add", help="Schedule a new job")
    job_add.add_argument("--vehicle", required=True, help="Vehicle name or #id")
    job_add.add_argument("--job", required=True, help='Job name, e.g. "diff oil"')
    job_add.add_argument("--miles", type=int, help="Miles interval")
    job_add.add_argument("--months", type=int, help="Months interval")
    job_add.set_defaults(func=cmd_job_add)

    job_remove = job_subparsers.add_parser("remove", help="Stop scheduling a job")
    job_remove.add_argument("--vehicle", required=True, help="Vehicle name or #id")
    job_remove.add_argument("--job", required=True, help="Job name")
    job_remove.set_defaults(func=cmd_job_remove)

    spend = subparsers.add_parser("spend", help="Totals by vehicle and year")
    spend.add_argument("--vehicle", help="Vehicle name or #id (default: all)")
    spend.add_argument("--year", type=int, help="Only this year")
    spend.set_defaults(func=cmd_spend)

    export = subparsers.add_parser("export", help="Write all records to a CSV file")
    export.add_argument("--out", required=True, help="Path to write, e.g. rig.csv")
    export.set_defaults(func=cmd_export)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
