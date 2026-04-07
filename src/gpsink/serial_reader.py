"""Read NMEA sentences from a serial / COM port in a background thread."""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

import serial

from gpsink.config import SerialConfig
from gpsink.nmea_parser import GPSFix, parse_gprmc

log = logging.getLogger(__name__)

# Default reconnection settings
DEFAULT_MAX_RETRIES = 10
DEFAULT_RETRY_BASE_DELAY = 1.0  # seconds
DEFAULT_RETRY_MAX_DELAY = 30.0  # seconds


class SerialReader:
    """Continuously read NMEA sentences from a serial port.

    Automatically reconnects on transient serial errors using exponential
    backoff.  The retry behaviour is controlled by *max_retries*,
    *retry_base_delay*, and *retry_max_delay*.

    Parameters
    ----------
    config : SerialConfig
        Serial port settings.
    on_fix : callable(GPSFix) -> None
        Callback invoked on the reader thread for every parsed GPRMC fix.
    on_error : callable(Exception) -> None, optional
        Callback invoked when the serial port raises an unrecoverable error
        (i.e. all retries exhausted).
    on_reconnect : callable(int, str) -> None, optional
        Callback invoked on each reconnection attempt with ``(attempt, port)``.
    max_retries : int
        Maximum consecutive reconnection attempts before giving up.
    retry_base_delay : float
        Initial delay (seconds) between reconnection attempts.
    retry_max_delay : float
        Upper-bound delay (seconds) between reconnection attempts.
    """

    def __init__(
        self,
        config: SerialConfig,
        on_fix: Callable[[GPSFix], None],
        on_error: Optional[Callable[[Exception], None]] = None,
        on_reconnect: Optional[Callable[[int, str], None]] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_base_delay: float = DEFAULT_RETRY_BASE_DELAY,
        retry_max_delay: float = DEFAULT_RETRY_MAX_DELAY,
    ) -> None:
        self.config = config
        self.on_fix = on_fix
        self.on_error = on_error or (lambda e: None)
        self.on_reconnect = on_reconnect or (lambda attempt, port: None)
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay
        self.retry_max_delay = retry_max_delay
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._serial: Optional[serial.Serial] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Open the port and begin reading in a daemon thread."""
        if self._thread is not None and self._thread.is_alive():
            log.warning("Reader already running on %s", self.config.port)
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name=f"gpsink-reader-{self.config.port}",
            daemon=True,
        )
        self._thread.start()
        log.info(
            "Started serial reader on %s @ %d baud",
            self.config.port,
            self.config.baudrate,
        )

    def stop(self, timeout: float = 5.0) -> None:
        """Signal the reader thread to stop and wait for it to finish."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
        log.info("Stopped serial reader")

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _open_port(self) -> serial.Serial:
        """Create and return a configured `serial.Serial` instance."""
        cfg = self.config
        return serial.Serial(
            port=cfg.port,
            baudrate=cfg.baudrate,
            bytesize=cfg.bytesize,
            parity=cfg.parity,
            stopbits=cfg.stopbits,
            timeout=cfg.timeout,
            rtscts=cfg.rtscts,
            xonxoff=cfg.xonxoff,
        )

    def _close_port(self) -> None:
        """Safely close the serial port if open."""
        if self._serial and self._serial.is_open:
            try:
                self._serial.close()
            except Exception:
                pass
            log.debug("Serial port closed")

    def _reconnect(self) -> bool:
        """Try to re-open the serial port with exponential backoff.

        Returns *True* if the port was successfully re-opened, *False*
        if all retries were exhausted or a stop was requested.
        """
        self._close_port()

        for attempt in range(1, self.max_retries + 1):
            if self._stop_event.is_set():
                return False

            delay = min(
                self.retry_base_delay * (2 ** (attempt - 1)),
                self.retry_max_delay,
            )
            log.warning(
                "Reconnect attempt %d/%d for %s in %.1fs…",
                attempt,
                self.max_retries,
                self.config.port,
                delay,
            )
            self.on_reconnect(attempt, self.config.port)

            # Sleep in small increments so we can respond to stop quickly
            slept = 0.0
            while slept < delay:
                if self._stop_event.is_set():
                    return False
                time.sleep(min(0.25, delay - slept))
                slept += 0.25

            try:
                self._serial = self._open_port()
                log.info("Reconnected to %s on attempt %d", self.config.port, attempt)
                return True
            except serial.SerialException as exc:
                log.warning("Reconnect attempt %d failed: %s", attempt, exc)

        return False

    def _run(self) -> None:
        """Main loop executed on the reader thread."""
        try:
            self._serial = self._open_port()
        except serial.SerialException as exc:
            log.error("Could not open %s: %s", self.config.port, exc)
            # Try reconnecting before giving up entirely
            if not self._reconnect():
                self.on_error(exc)
                return

        assert self._serial is not None
        try:
            while not self._stop_event.is_set():
                try:
                    raw_line = self._serial.readline()
                except serial.SerialException as exc:
                    log.error("Serial read error: %s", exc)
                    if self._reconnect():
                        continue  # reconnected — resume reading
                    self.on_error(exc)
                    break

                if not raw_line:
                    continue  # timeout, no data

                try:
                    line = raw_line.decode("ascii", errors="ignore").strip()
                except UnicodeDecodeError:
                    continue

                if not line:
                    continue

                fix = parse_gprmc(line)
                if fix is not None:
                    try:
                        self.on_fix(fix)
                    except Exception as cb_exc:
                        log.error("on_fix callback error: %s", cb_exc)
        finally:
            self._close_port()
