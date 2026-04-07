"""Tests for gpsink.serial_reader (mocked serial port)."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from gpsink.config import SerialConfig
from gpsink.serial_reader import SerialReader

# Sample sentences
VALID_GPRMC = "$GPRMC,123519.00,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*44"
VALID_GNRMC = "$GNRMC,123519.00,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*5A"
GPGGA_SENTENCE = "$GPGGA,123519.00,4807.038,N,01131.000,E,1,08,0.9,545.4,M,47.0,M,,*61"


class TestSerialReader:
    """Unit tests using a mocked pyserial.Serial."""

    @pytest.fixture
    def config(self) -> SerialConfig:
        return SerialConfig(port="COM99", baudrate=9600, timeout=0.1)

    def _make_mock_serial(self, lines: list[bytes], loop: bool = False):
        """Create a mock serial.Serial that yields *lines* then empty bytes."""
        mock_serial = MagicMock()
        mock_serial.is_open = True

        if loop:
            # Cycle through lines forever (for continuous reading tests)
            import itertools

            it = itertools.cycle(lines)
        else:
            it = iter(lines + [b""] * 50)  # padding so readline doesn't hang

        mock_serial.readline = MagicMock(side_effect=lambda: next(it, b""))
        mock_serial.close = MagicMock()
        return mock_serial

    @patch("gpsink.serial_reader.serial.Serial")
    def test_reader_delivers_fix_via_callback(self, mock_serial_cls, config):
        raw = (VALID_GPRMC + "\r\n").encode("ascii")
        mock_port = self._make_mock_serial([raw])
        mock_serial_cls.return_value = mock_port

        received: list = []
        reader = SerialReader(config, on_fix=lambda f: received.append(f))
        reader.start()
        time.sleep(0.3)
        reader.stop()

        assert len(received) >= 1
        assert received[0].latitude == pytest.approx(48.1173, abs=0.01)

    @patch("gpsink.serial_reader.serial.Serial")
    def test_reader_delivers_gnrmc_fix(self, mock_serial_cls, config):
        """$GNRMC sentences are parsed and delivered like $GPRMC."""
        raw = (VALID_GNRMC + "\r\n").encode("ascii")
        mock_port = self._make_mock_serial([raw])
        mock_serial_cls.return_value = mock_port

        received: list = []
        reader = SerialReader(config, on_fix=lambda f: received.append(f))
        reader.start()
        time.sleep(0.3)
        reader.stop()

        assert len(received) >= 1
        assert received[0].latitude == pytest.approx(48.1173, abs=0.01)

    @patch("gpsink.serial_reader.serial.Serial")
    def test_reader_ignores_non_rmc(self, mock_serial_cls, config):
        raw = (GPGGA_SENTENCE + "\r\n").encode("ascii")
        mock_port = self._make_mock_serial([raw])
        mock_serial_cls.return_value = mock_port

        received: list = []
        reader = SerialReader(config, on_fix=lambda f: received.append(f))
        reader.start()
        time.sleep(0.3)
        reader.stop()

        assert len(received) == 0

    @patch("gpsink.serial_reader.serial.Serial")
    def test_reader_handles_serial_open_error(self, mock_serial_cls, config):
        import serial as _serial

        mock_serial_cls.side_effect = _serial.SerialException("Port not found")

        errors: list = []
        reader = SerialReader(
            config,
            on_fix=lambda f: None,
            on_error=lambda e: errors.append(e),
            max_retries=0,  # no retries for this test
        )
        reader.start()
        time.sleep(0.3)
        reader.stop()

        assert len(errors) == 1
        assert "Port not found" in str(errors[0])

    @patch("gpsink.serial_reader.serial.Serial")
    def test_stop_terminates_thread(self, mock_serial_cls, config):
        raw = (VALID_GPRMC + "\r\n").encode("ascii")
        mock_port = self._make_mock_serial([raw], loop=True)
        mock_serial_cls.return_value = mock_port

        reader = SerialReader(config, on_fix=lambda f: None)
        reader.start()
        assert reader.is_running
        time.sleep(0.15)
        reader.stop()
        time.sleep(0.15)
        assert not reader.is_running

    @patch("gpsink.serial_reader.serial.Serial")
    def test_reader_multiple_fixes(self, mock_serial_cls, config):
        lines = [
            (VALID_GPRMC + "\r\n").encode("ascii"),
            (VALID_GPRMC + "\r\n").encode("ascii"),
            (VALID_GPRMC + "\r\n").encode("ascii"),
        ]
        mock_port = self._make_mock_serial(lines)
        mock_serial_cls.return_value = mock_port

        received: list = []
        reader = SerialReader(config, on_fix=lambda f: received.append(f))
        reader.start()
        time.sleep(0.3)
        reader.stop()

        assert len(received) >= 3


class TestSerialReaderReconnect:
    """Tests for serial port auto-reconnection."""

    @pytest.fixture
    def config(self) -> SerialConfig:
        return SerialConfig(port="COM99", baudrate=9600, timeout=0.1)

    @patch("gpsink.serial_reader.time.sleep")
    @patch("gpsink.serial_reader.serial.Serial")
    def test_reconnect_on_read_error(self, mock_serial_cls, mock_sleep, config):
        """Reader should reconnect when readline raises SerialException."""
        import serial as _serial

        # First port works, then readline raises, then reconnect succeeds
        mock_port1 = MagicMock()
        mock_port1.is_open = True

        call_count = 0

        def readline_side_effect():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return (VALID_GPRMC + "\r\n").encode("ascii")
            if call_count == 2:
                raise _serial.SerialException("USB disconnected")
            return b""

        mock_port1.readline = MagicMock(side_effect=readline_side_effect)
        mock_port1.close = MagicMock()

        mock_port2 = MagicMock()
        mock_port2.is_open = True
        mock_port2.readline = MagicMock(return_value=b"")
        mock_port2.close = MagicMock()

        mock_serial_cls.side_effect = [mock_port1, mock_port2]

        reconnect_events: list = []
        received: list = []

        reader = SerialReader(
            config,
            on_fix=lambda f: received.append(f),
            on_reconnect=lambda attempt, port: reconnect_events.append(attempt),
            max_retries=2,
            retry_base_delay=0.01,
        )
        reader.start()
        time.sleep(0.5)
        reader.stop()

        # Should have received the first fix before the error
        assert len(received) >= 1
        # Should have attempted reconnection
        assert len(reconnect_events) >= 1

    @patch("gpsink.serial_reader.time.sleep")
    @patch("gpsink.serial_reader.serial.Serial")
    def test_reconnect_on_initial_open_failure_then_success(
        self, mock_serial_cls, mock_sleep, config
    ):
        """Reader reconnects if initial open fails, then succeeds."""
        import serial as _serial

        mock_port = MagicMock()
        mock_port.is_open = True
        mock_port.readline = MagicMock(return_value=b"")
        mock_port.close = MagicMock()

        # First call fails, second succeeds
        mock_serial_cls.side_effect = [
            _serial.SerialException("Port busy"),
            mock_port,
        ]

        errors: list = []
        reconnect_events: list = []

        reader = SerialReader(
            config,
            on_fix=lambda f: None,
            on_error=lambda e: errors.append(e),
            on_reconnect=lambda attempt, port: reconnect_events.append(attempt),
            max_retries=3,
            retry_base_delay=0.01,
        )
        reader.start()
        time.sleep(0.5)
        reader.stop()

        # Should not have fired the final error callback (reconnect worked)
        assert len(errors) == 0
        # Should have reconnected
        assert len(reconnect_events) >= 1

    @patch("gpsink.serial_reader.time.sleep")
    @patch("gpsink.serial_reader.serial.Serial")
    def test_reconnect_exhausted_fires_error(self, mock_serial_cls, mock_sleep, config):
        """When all retries are exhausted, the on_error callback fires."""
        import serial as _serial

        mock_serial_cls.side_effect = _serial.SerialException("Port gone")

        errors: list = []
        reconnect_events: list = []

        reader = SerialReader(
            config,
            on_fix=lambda f: None,
            on_error=lambda e: errors.append(e),
            on_reconnect=lambda attempt, port: reconnect_events.append(attempt),
            max_retries=2,
            retry_base_delay=0.01,
        )
        reader.start()
        # Wait for the thread to finish naturally (all retries exhausted)
        assert reader._thread is not None
        reader._thread.join(timeout=5.0)

        assert len(errors) == 1
        assert len(reconnect_events) == 2  # tried twice
