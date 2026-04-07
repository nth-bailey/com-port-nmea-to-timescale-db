"""TimescaleDB / PostGIS writer for GPS fix data."""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from collections.abc import Callable
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

# Default reconnection settings
DEFAULT_MAX_RETRIES = 10
DEFAULT_RETRY_BASE_DELAY = 1.0  # seconds
DEFAULT_RETRY_MAX_DELAY = 30.0  # seconds


# ------------------------------------------------------------------
# Writer class
# ------------------------------------------------------------------


class GPSWriter:
    """Write `GPSFix` objects into TimescaleDB.

    The writer is safe to call from multiple threads — it serialises
    database access with an internal lock.

    Supports automatic reconnection on transient database errors
    (network glitches, server restarts, etc.) using exponential backoff.

    Parameters
    ----------
    config : DatabaseConfig
        Connection settings.
    auto_provision : bool
        If *True*, call :meth:`provision` automatically on the first write.
    max_retries : int
        Maximum consecutive reconnection attempts before raising.
    retry_base_delay : float
        Initial delay (seconds) between reconnection attempts.
    retry_max_delay : float
        Upper-bound delay (seconds) between reconnection attempts.
    on_reconnect : callable(int, str) -> None, optional
        Callback invoked on each reconnection attempt with
        ``(attempt, dsn_summary)``.
    """

    def __init__(
        self,
        config: DatabaseConfig,
        *,
        auto_provision: bool = True,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_base_delay: float = DEFAULT_RETRY_BASE_DELAY,
        retry_max_delay: float = DEFAULT_RETRY_MAX_DELAY,
        on_reconnect: Optional[Callable[[int, str], None]] = None,
    ) -> None:
        self.config = config
        self._conn: Optional[psycopg2.extensions.connection] = None
        self._lock = threading.Lock()
        self._provisioned = False
        self._auto_provision = auto_provision
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay
        self.retry_max_delay = retry_max_delay
        self.on_reconnect = on_reconnect or (lambda attempt, info: None)

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

    def _reconnect_unlocked(self) -> bool:
        """Attempt to reconnect with exponential backoff.

        Must be called while ``self._lock`` is **not** held.
        Returns *True* on success, *False* if all retries are exhausted.
        """
        # Close the stale connection
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

        dsn_summary = f"{self.config.host}:{self.config.port}/{self.config.dbname}"

        for attempt in range(1, self.max_retries + 1):
            delay = min(
                self.retry_base_delay * (2 ** (attempt - 1)),
                self.retry_max_delay,
            )
            log.warning(
                "DB reconnect attempt %d/%d for %s in %.1fs…",
                attempt,
                self.max_retries,
                dsn_summary,
                delay,
            )
            self.on_reconnect(attempt, dsn_summary)
            time.sleep(delay)

            try:
                self._conn = psycopg2.connect(self.config.dsn)
                self._conn.autocommit = True
                log.info("Reconnected to %s on attempt %d", dsn_summary, attempt)
                return True
            except psycopg2.OperationalError as exc:
                log.warning("DB reconnect attempt %d failed: %s", attempt, exc)

        return False

    @contextmanager
    def _cursor(self):
        """Yield a cursor, reconnecting if necessary."""
        if self._conn is None or self._conn.closed:
            self.connect()

        assert self._conn is not None
        with self._conn.cursor() as cur:
            yield cur

    @contextmanager
    def _resilient_cursor(self):
        """Yield a cursor, retrying the entire operation on transient errors.

        This is used by write methods so that a momentary network blip
        does not permanently kill the ingestion pipeline.
        """
        try:
            with self._cursor() as cur:
                yield cur
        except (psycopg2.OperationalError, psycopg2.InterfaceError) as exc:
            log.error("Database error during operation: %s — attempting reconnect", exc)
            if self._reconnect_unlocked():
                # Re-yield a new cursor after successful reconnection.
                # The caller will need to re-execute their SQL, so we raise
                # a dedicated sentinel to signal the retry.
                raise _RetryAfterReconnect() from exc
            raise  # all retries exhausted, propagate the original error

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

        Automatically retries on transient connection errors.

        Parameters
        ----------
        fix : GPSFix
            Parsed GPRMC data to persist.
        """
        if self._auto_provision and not self._provisioned:
            self.provision()

        table = self.config.table_name
        params = (
            fix.timestamp,
            fix.longitude,  # ST_MakePoint(x, y) = (lon, lat)
            fix.latitude,
            fix.latitude,
            fix.longitude,
            fix.speed_knots,
            fix.course,
            fix.status,
            fix.raw,
        )

        for _attempt in range(2):  # at most one retry after reconnect
            with self._lock:
                try:
                    with self._cursor() as cur:
                        cur.execute(_INSERT_FIX.format(table=table), params)
                    break  # success
                except (psycopg2.OperationalError, psycopg2.InterfaceError) as exc:
                    log.error("DB write error: %s — attempting reconnect", exc)
                    if not self._reconnect_unlocked():
                        raise

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

        for _attempt in range(2):
            with self._lock:
                try:
                    with self._cursor() as cur:
                        psycopg2.extras.execute_batch(cur, sql, rows, page_size=100)
                    break
                except (psycopg2.OperationalError, psycopg2.InterfaceError) as exc:
                    log.error("DB batch-write error: %s — attempting reconnect", exc)
                    if not self._reconnect_unlocked():
                        raise

        log.debug("Batch-wrote %d fixes to %s", len(rows), table)
        return len(rows)


class _RetryAfterReconnect(Exception):
    """Internal sentinel — never escapes the module."""
