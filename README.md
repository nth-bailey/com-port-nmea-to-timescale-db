# 📡 gpsink

Stream NMEA GPS data from a COM port radio dongle into [TimescaleDB](https://www.timescale.com/) with [PostGIS](https://postgis.net/).

Built for ≥1 Hz radio GPS data sources transmitting RMC sentences (`$GNRMC`, `$GPRMC`, `$GLRMC`, …).

## Features

- **Serial / COM port reader** — configurable baud rate, parity, stop bits, flow control
- **NMEA parser** — extracts lat/lon/speed/course from any `$xxRMC` sentence (e.g. `$GNRMC`) via `pynmea2`
- **TimescaleDB writer** — auto-provisions a hypertable with a PostGIS `geometry(Point, 4326)` column
- **Optional database** — run in serial-only mode (`--no-db`) to verify COM port connectivity before involving the DB
- **Auto-reconnect** — both serial port and database connections automatically retry with exponential backoff on transient failures (e.g. USB hiccup, network outage)
- **CLI** — fully configurable via command-line flags
- **GUI** — simple Tkinter interface with database on/off toggle for configuring and monitoring the stream

## Quick Start

```bash
# Install with uv
uv sync --extra dev

# Run the CLI
uv run gpsink run --port COM3 --baud 9600 --db-host localhost --db-name gpsink

# Run serial-only mode (no database — just verify COM port)
uv run gpsink run --port COM3 --no-db

# Launch the GUI
uv run gpsink gui

# Provision the database schema only
uv run gpsink provision --db-host localhost --db-name gpsink
```

## CLI Reference

```
gpsink run [OPTIONS]      Start reading NMEA data and writing to TimescaleDB
gpsink gui                Launch the graphical interface
gpsink provision          Create extensions, table, and hypertable
```

### `gpsink run` Options

| Flag           | Default     | Description              |
|----------------|-------------|--------------------------|
| `--port / -p`  | `COM3`      | Serial / COM port name   |
| `--baud / -b`  | `9600`      | Baud rate                |
| `--bytesize`   | `8`         | Data bits (5-8)          |
| `--parity`     | `N`         | Parity (N/E/O/M/S)       |
| `--stopbits`   | `1`         | Stop bits (1/1.5/2)      |
| `--db-host`    | `localhost` | TimescaleDB host         |
| `--db-port`    | `5432`      | TimescaleDB port         |
| `--db-name`    | `gpsink`    | Database name            |
| `--db-user`    | `postgres`  | Database user            |
| `--db-password`| `postgres`  | Database password        |
| `--table`      | `gps_readings` | Target table name     |
| `--source-id`  | `default`   | Label for this GPS source / entity (e.g. `truck-1`) |
| `--no-db`      | off         | Skip database — serial-only / dry-run mode |
| `-v`           | off         | Enable debug logging     |

### Auto-Reconnect

Both the serial port reader and the database writer will automatically attempt to reconnect when the connection is lost (e.g. USB cable briefly unplugged, network outage). Reconnection uses **exponential backoff** (1s → 2s → 4s → … up to 30s), with up to 10 retries by default. Reconnection events are logged to the console/GUI live feed.

## GUI Reference

![alt text](gui.png)

## Database Schema

```sql
CREATE TABLE gps_readings (
    time         TIMESTAMPTZ      NOT NULL,  -- UTC timestamp of the fix
    source_id    TEXT             NOT NULL,  -- User-defined entity / track label
    geom         GEOMETRY(Point, 4326),      -- WGS 84 point (lon, lat) in decimal degrees
    latitude     DOUBLE PRECISION NOT NULL,  -- Decimal degrees; positive = North, negative = South
    longitude    DOUBLE PRECISION NOT NULL,  -- Decimal degrees; positive = East, negative = West
    speed_knots  DOUBLE PRECISION,           -- Speed over ground in knots (1 kt ≈ 1.852 km/h)
    course       DOUBLE PRECISION,           -- Track angle in degrees true (0–360°)
    status       CHAR(1),                    -- 'A' = active/valid fix, 'V' = void/invalid
    raw_sentence TEXT                         -- Original NMEA sentence verbatim
);
-- Automatically converted to a TimescaleDB hypertable
```

> **NMEA → DB conversion:** Raw RMC sentences encode position as `DDDMM.MMMM` with `N`/`S`/`E`/`W` indicators (e.g. `4807.038,N` = 48°07.038′ N). The parser ([pynmea2](https://github.com/Knio/pynmea2)) converts these to **signed decimal degrees** before insertion (e.g. `48.1173`, with South/West as negative). The `geom` column stores the same coordinates as a PostGIS `Point(longitude, latitude)` in SRID 4326 (WGS 84).

> **Multi-entity tracking:** Use `--source-id` (CLI) or the Source ID field (GUI) to label each GPS stream. Run multiple gpsink instances against the same table with different source IDs to track separate vehicles, drones, etc. Query by `WHERE source_id = 'truck-1'`.

## Development

```bash
# Install dev dependencies
uv sync --extra dev

# Run tests
uv run pytest

# Run with coverage
uv run pytest --cov=gpsink --cov-report=term-missing
```

## Project Structure

```
├── src/gpsink/
│   ├── __init__.py        # Package version
│   ├── config.py          # Dataclass configs for serial & DB
│   ├── nmea_parser.py     # RMC sentence parser → GPSFix
│   ├── serial_reader.py   # Threaded COM port reader
│   ├── db.py              # TimescaleDB/PostGIS writer
│   ├── cli.py             # Click CLI (run / gui / provision)
│   └── gui.py             # Tkinter GUI
├── tests/
│   ├── conftest.py        # Shared fixtures & sample sentences
│   ├── test_config.py
│   ├── test_nmea_parser.py
│   ├── test_serial_reader.py
│   ├── test_db.py
│   ├── test_cli.py
│   └── test_gui.py
└── pyproject.toml         # PEP 621 project config (uv/hatchling)
```

## License

MIT
