"""Read NMEA sentences from a serial / COM port in a background thread."""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

import serial

from gpsink.config import SerialConfig
from gpsink.nmea_parser import GPSFix, parse_gprmc

log = logging.getLogger(__name__)


class SerialReader:
    """Continuously read NMEA sentences from a serial port.

    Parameters
    ----------
    config : SerialConfig
        Serial port settings.
    on_fix : callable(GPSFix) -> None
        Callback invoked on the reader thread for every parsed GPRMC fix.
    on_error : callable(Exception) -> None, optional
        Callback invoked when the serial port raises an error.
    """

    def __init__(
        self,
        config: SerialConfig,
        on_fix: Callable[[GPSFix], None],
        on_error: Optional[Callable[[Exception], None]] = None,
    ) -> None:
        self.config = config
        self.on_fix = on_fix
        self.on_error = on_error or (lambda e: None)
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
        log.info("Started serial reader on %s @ %d baud", self.config.port, self.config.baudrate)

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

    def _run(self) -> None:
        """Main loop executed on the reader thread."""
        try:
            self._serial = self._open_port()
        except serial.SerialException as exc:
            log.error("Could not open %s: %s", self.config.port, exc)
            self.on_error(exc)
            return

        try:
            while not self._stop_event.is_set():
                try:
                    raw_line = self._serial.readline()
                except serial.SerialException as exc:
                    log.error("Serial read error: %s", exc)
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
            if self._serial and self._serial.is_open:
                self._serial.close()
                log.debug("Serial port closed")
