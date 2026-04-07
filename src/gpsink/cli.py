"""Command-line interface for gpsink."""

from __future__ import annotations

import logging
import signal
import threading

import click

from gpsink.config import DatabaseConfig, SerialConfig
from gpsink.db import GPSWriter
from gpsink.nmea_parser import GPSFix
from gpsink.serial_reader import SerialReader

log = logging.getLogger("gpsink")


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )


# ------------------------------------------------------------------
# CLI group
# ------------------------------------------------------------------


@click.group()
@click.version_option(package_name="gpsink")
def main() -> None:
    """gpsink — stream GPS NMEA data from a COM port into TimescaleDB."""


# ------------------------------------------------------------------
# `run` command — the main pipeline
# ------------------------------------------------------------------


@main.command()
@click.option(
    "--port", "-p", default="COM3", show_default=True, help="Serial / COM port name."
)
@click.option(
    "--baud", "-b", default=9600, show_default=True, type=int, help="Baud rate."
)
@click.option(
    "--bytesize",
    default=8,
    show_default=True,
    type=click.Choice(["5", "6", "7", "8"]),
    help="Data bits.",
)
@click.option(
    "--parity",
    default="N",
    show_default=True,
    type=click.Choice(["N", "E", "O", "M", "S"]),
    help="Parity.",
)
@click.option(
    "--stopbits",
    default="1",
    show_default=True,
    type=click.Choice(["1", "1.5", "2"]),
    help="Stop bits.",
)
@click.option(
    "--db-host", default="localhost", show_default=True, help="TimescaleDB host."
)
@click.option(
    "--db-port", default=5432, show_default=True, type=int, help="TimescaleDB port."
)
@click.option("--db-name", default="gpsink", show_default=True, help="Database name.")
@click.option("--db-user", default="postgres", show_default=True, help="Database user.")
@click.option(
    "--db-password", default="postgres", show_default=True, help="Database password."
)
@click.option(
    "--table", default="gps_readings", show_default=True, help="Target table name."
)
@click.option(
    "--no-db",
    is_flag=True,
    default=False,
    help="Run without connecting to TimescaleDB (serial-only / dry-run mode).",
)
@click.option(
    "--source-id",
    default="default",
    show_default=True,
    help="Label for this GPS source / entity (e.g. 'truck-1').",
)
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging.")
def run(
    port: str,
    baud: int,
    bytesize: str,
    parity: str,
    stopbits: str,
    db_host: str,
    db_port: int,
    db_name: str,
    db_user: str,
    db_password: str,
    table: str,
    no_db: bool,
    source_id: str,
    verbose: bool,
) -> None:
    """Start reading NMEA data and writing to TimescaleDB.

    Use --no-db to skip the database entirely and just verify the serial
    connection is healthy.
    """
    _setup_logging(verbose)

    serial_cfg = SerialConfig(
        port=port,
        baudrate=baud,
        bytesize=int(bytesize),
        parity=parity,
        stopbits=float(stopbits),
    )

    # ---- database (optional) -----------------------------------------
    writer = None
    if not no_db:
        db_cfg = DatabaseConfig(
            host=db_host,
            port=db_port,
            dbname=db_name,
            user=db_user,
            password=db_password,
            table_name=table,
        )
        writer = GPSWriter(
            db_cfg,
            source_id=source_id,
            on_reconnect=lambda attempt, info: click.echo(
                f"  ⟳  DB reconnect attempt {attempt} → {info}"
            ),
        )
        writer.connect()

    fix_count = 0
    count_lock = threading.Lock()

    def on_fix(fix: GPSFix) -> None:
        nonlocal fix_count
        if writer is not None:
            writer.write_fix(fix)
        with count_lock:
            fix_count += 1
        click.echo(
            f"[{fix.timestamp:%H:%M:%S}]  "
            f"lat={fix.latitude:+.6f}  lon={fix.longitude:+.6f}  "
            f"spd={fix.speed_knots:.1f}kn  "
            f"{'✓' if fix.is_valid else '✗'}"
        )

    def on_error(exc: Exception) -> None:
        click.secho(f"Serial error: {exc}", fg="red", err=True)

    def on_serial_reconnect(attempt: int, port_name: str) -> None:
        click.echo(f"  ⟳  Serial reconnect attempt {attempt} → {port_name}")

    reader = SerialReader(
        serial_cfg,
        on_fix=on_fix,
        on_error=on_error,
        on_reconnect=on_serial_reconnect,
    )

    stop = threading.Event()

    def _signal_handler(signum, frame):
        click.echo("\nShutting down…")
        stop.set()

    signal.signal(signal.SIGINT, _signal_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _signal_handler)

    if no_db:
        click.echo(
            f"gpsink  |  {serial_cfg.port} @ {serial_cfg.baudrate}  "
            f"(no database — serial-only mode)"
        )
    else:
        click.echo(
            f"gpsink  |  {serial_cfg.port} @ {serial_cfg.baudrate} → "
            f"{db_cfg.host}:{db_cfg.port}/{db_cfg.dbname}"
        )
    click.echo("Press Ctrl+C to stop.\n")

    reader.start()

    try:
        stop.wait()
    finally:
        reader.stop()
        if writer is not None:
            writer.close()
        click.echo(f"\nDone — {'logged' if no_db else 'wrote'} {fix_count} fixes.")


# ------------------------------------------------------------------
# `gui` command — launches the Tkinter GUI
# ------------------------------------------------------------------


@main.command()
def gui() -> None:
    """Launch the graphical interface."""
    from gpsink.gui import launch_gui  # lazy import to keep CLI snappy

    launch_gui()


# ------------------------------------------------------------------
# `provision` command — create the DB schema without streaming
# ------------------------------------------------------------------


@main.command()
@click.option("--db-host", default="localhost", show_default=True)
@click.option("--db-port", default=5432, show_default=True, type=int)
@click.option("--db-name", default="gpsink", show_default=True)
@click.option("--db-user", default="postgres", show_default=True)
@click.option("--db-password", default="postgres", show_default=True)
@click.option("--table", default="gps_readings", show_default=True)
def provision(db_host, db_port, db_name, db_user, db_password, table) -> None:
    """Create extensions, table, and hypertable in the database."""
    _setup_logging(False)
    db_cfg = DatabaseConfig(
        host=db_host,
        port=db_port,
        dbname=db_name,
        user=db_user,
        password=db_password,
        table_name=table,
    )
    writer = GPSWriter(db_cfg, auto_provision=False)
    writer.connect()
    writer.provision()
    writer.close()
    click.secho("✓ Database provisioned.", fg="green")


if __name__ == "__main__":
    main()
