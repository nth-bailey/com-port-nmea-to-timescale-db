"""TimescaleDB / PostGIS writer for GPS fix data."""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from typing import Optional

import psycopg2
import psycopg2.extensions
import psycopg2.extras

from gpsink.config import DatabaseConfig
from gpsink.nmea_parser import GPSFix

log = logging.getLogger(__name__)

# ------------------------------------------------------------------
# SQL templates
# ------------------------------------------------------------------

_CREATE_EXTENSION_POSTGIS = "CREATE EXTENSION IF NOT EXISTS postgis;"
_CREATE_EXTENSION_TIMESCALE = "CREATE EXTENSION IF NOT EXISTS timescaledb;"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS {table} (
    time         TIMESTAMPTZ      NOT NULL,
    geom         GEOMETRY(Point, 4326),
    latitude     DOUBLE PRECISION NOT NULL,
    longitude    DOUBLE PRECISION NOT NULL,
    speed_knots  DOUBLE PRECISION,
    course       DOUBLE PRECISION,
    status       CHAR(1),
    raw_sentence TEXT
);
"""

_CREATE_HYPERTABLE = """
SELECT create_hypertable('{table}', 'time', if_not_exists => TRUE);
"""

_INSERT_FIX = """
INSERT INTO {table} (time, geom, latitude, longitude, speed_knots, course, status, raw_sentence)
VALUES (%s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s, %s, %s, %s, %s);
"""


# ------------------------------------------------------------------
# Writer class
# ------------------------------------------------------------------


class GPSWriter:
    """Write `GPSFix` objects into TimescaleDB.

    The writer is safe to call from multiple threads — it serialises
    database access with an internal lock.

    Parameters
    ----------
    config : DatabaseConfig
        Connection settings.
    auto_provision : bool
        If *True*, call :meth:`provision` automatically on the first write.
    """

    def __init__(self, config: DatabaseConfig, *, auto_provision: bool = True) -> None:
        self.config = config
        self._conn: Optional[psycopg2.extensions.connection] = None
        self._lock = threading.Lock()
        self._provisioned = False
        self._auto_provision = auto_provision

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open (or re-open) the database connection."""
        with self._lock:
            if self._conn is not None and not self._conn.closed:
                return
            self._conn = psycopg2.connect(self.config.dsn)
            self._conn.autocommit = True
            log.info(
                "Connected to TimescaleDB at %s:%s/%s",
                self.config.host,
                self.config.port,
                self.config.dbname,
            )

    def close(self) -> None:
        """Close the database connection."""
        with self._lock:
            if self._conn is not None and not self._conn.closed:
                self._conn.close()
                log.info("Database connection closed")

    @contextmanager
    def _cursor(self):
        """Yield a cursor, reconnecting if necessary."""
        if self._conn is None or self._conn.closed:
            self.connect()

        assert self._conn is not None
        with self._conn.cursor() as cur:
            yield cur

    # ------------------------------------------------------------------
    # Schema provisioning
    # ------------------------------------------------------------------

    def provision(self) -> None:
        """Create extensions, tables, and hypertable if they don't exist."""
        table = self.config.table_name
        with self._lock:
            with self._cursor() as cur:
                cur.execute(_CREATE_EXTENSION_POSTGIS)
                cur.execute(_CREATE_EXTENSION_TIMESCALE)
                cur.execute(_CREATE_TABLE.format(table=table))
                cur.execute(_CREATE_HYPERTABLE.format(table=table))
            self._provisioned = True
            log.info("Provisioned table '%s' as TimescaleDB hypertable", table)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def write_fix(self, fix: GPSFix) -> None:
        """Insert a single GPS fix into the database.

        Parameters
        ----------
        fix : GPSFix
            Parsed GPRMC data to persist.
        """
        if self._auto_provision and not self._provisioned:
            self.provision()

        table = self.config.table_name
        with self._lock:
            with self._cursor() as cur:
                cur.execute(
                    _INSERT_FIX.format(table=table),
                    (
                        fix.timestamp,
                        fix.longitude,  # ST_MakePoint(x, y) = (lon, lat)
                        fix.latitude,
                        fix.latitude,
                        fix.longitude,
                        fix.speed_knots,
                        fix.course,
                        fix.status,
                        fix.raw,
                    ),
                )
        log.debug("Wrote fix @ %s to %s", fix.timestamp, table)

    def write_fixes(self, fixes: list[GPSFix]) -> int:
        """Batch-insert multiple fixes. Returns the count written."""
        if self._auto_provision and not self._provisioned:
            self.provision()

        table = self.config.table_name
        sql = _INSERT_FIX.format(table=table)
        rows = [
            (
                f.timestamp,
                f.longitude,
                f.latitude,
                f.latitude,
                f.longitude,
                f.speed_knots,
                f.course,
                f.status,
                f.raw,
            )
            for f in fixes
        ]

        with self._lock:
            with self._cursor() as cur:
                psycopg2.extras.execute_batch(cur, sql, rows, page_size=100)

        log.debug("Batch-wrote %d fixes to %s", len(rows), table)
        return len(rows)
