# rig

Maintenance and cost tracking for a small fleet of vehicles, from the command line.

## What it is

`rig` keeps a record of what has been done to each vehicle and what it cost. You
log services as they happen, and `rig` works out what is due next, by mileage or
by date, whichever comes first.

Built for one household with a few cars, including a 1994 Land Rover Discovery
that needs considerably more attention than the rest of them.

## How to run it

Clone the repo and run it. There is nothing to install: `rig` uses only the
Python standard library, so Python 3.10 or newer is the only requirement.

```sh
git clone https://github.com/jrbowlder/rig.git
cd rig
python3 -m rig --help
```

Add a vehicle, then list what is registered:

```sh
python3 -m rig add-vehicle --name Disco --year 1994 --make Land --model Rover --odo 187000
python3 -m rig vehicles
```

Log work as it happens. A record can move the odometer forward, but never back:

```sh
python3 -m rig log --vehicle Disco --service "oil change" --odo 185900 --cost 68.40
python3 -m rig log --vehicle Disco --service "fuel pump" --cost 240 --notes "Bosch, from Rimmer"
```

Update the odometer on its own, and read the history back:

```sh
python3 -m rig odo --vehicle Forester --miles 61800
python3 -m rig history --vehicle Forester
```

Ask what needs doing. Each job is measured by mileage and by date, and it is
due at whichever limit arrives first:

```sh
python3 -m rig due
python3 -m rig due --vehicle Disco
```

Change an interval if your vehicle wants different numbers. Zero removes a
limit, so `--miles 0` leaves date-only:

```sh
python3 -m rig schedule --vehicle Disco
python3 -m rig interval --vehicle Disco --job "oil change" --miles 7500
```

Schedule something the defaults do not cover, and drop it again:

```sh
python3 -m rig job add --vehicle Disco --job "diff oil" --miles 30000 --months 36
python3 -m rig job remove --vehicle Disco --job "diff oil"
```

The default rules are shipped with the app: oil change every 5,000 miles or 12
months, air filter 15,000 or 24, brake fluid 30,000 or 24, tyres 30,000 or 60,
annual inspection every 12 months.

See what the fleet has cost, by vehicle and year, and get it out as a spreadsheet:

```sh
python3 -m rig spend
python3 -m rig spend --vehicle Disco --year 2026
python3 -m rig export --out rig.csv
```

The database is a single SQLite file, `rig.db`, created automatically on first
run and ignored by git. Money is stored as whole cents, so totals never pick up
rounding drift.

## Running the tests

The due engine and the command line have 25 tests covering both limits firing
independently, the exact limit, the due-soon window, month arithmetic across
short and leap months, keyword matching, and the CLI reading a read-only
database. They use a temporary database, so your real one is never touched.

```sh
python3 -m unittest discover -s tests
```
