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
git clone git@github.com:jrbowlder/rig.git
cd rig
python3 -m rig --help
```

Add a vehicle, then list what is registered:

```sh
python3 -m rig add-vehicle --name Disco --year 1994 --make Land --model Rover --odo 187000
python3 -m rig vehicles
```

The database is a single SQLite file, `rig.db`, created automatically on first
run and ignored by git.
