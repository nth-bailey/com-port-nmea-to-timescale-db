"""Shared test fixtures for gpsink."""

from __future__ import annotations

import pytest

from gpsink.config import AppConfig, DatabaseConfig, SerialConfig
from gpsink.nmea_parser import GPSFix

# ---------------------------------------------------------------------------
# Example NMEA sentences  (RMC and GGA — any talker ID)
# ---------------------------------------------------------------------------

# GP talker — valid fix (status = A)
VALID_GPRMC = "$GPRMC,123519.00,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*44"

# GP talker — void fix (status = V)
VOID_GPRMC = "$GPRMC,123519.00,V,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*53"

# GN talker — valid fix (status = A)
VALID_GNRMC = "$GNRMC,123519.00,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*5A"

# GN talker — void fix (status = V)
VOID_GNRMC = "$GNRMC,123519.00,V,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*4D"

# GP talker — valid GGA (quality = 1, has altitude)
VALID_GPGGA = "$GPGGA,123519.00,4807.038,N,01131.000,E,1,08,0.9,545.4,M,47.0,M,,*61"

# GN talker — valid GGA (quality = 1, has altitude)
VALID_GNGGA = "$GNGGA,123519.00,4807.038,N,01131.000,E,1,08,0.9,545.4,M,47.0,M,,*7F"

# GP talker — void GGA (quality = 0, no valid fix)
VOID_GPGGA = "$GPGGA,123519.00,4807.038,N,01131.000,E,0,08,0.9,545.4,M,47.0,M,,*60"

# Non-RMC / non-GGA sentence (GSV)
GSV_SENTENCE = "$GPGSV,3,1,11,03,03,111,00,04,15,270,00,06,01,010,00,13,06,292,00*74"

# Garbage / malformed
GARBAGE = "!!!NOT_NMEA!!!"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def serial_config() -> SerialConfig:
    return SerialConfig(port="COM99", baudrate=9600)


@pytest.fixture
def db_config() -> DatabaseConfig:
    return DatabaseConfig(
        host="127.0.0.1",
        port=5432,
        dbname="gpsink_test",
        user="test_user",
        password="test_pass",
        table_name="gps_test",
    )


@pytest.fixture
def app_config(serial_config, db_config) -> AppConfig:
    return AppConfig(serial=serial_config, database=db_config)


@pytest.fixture
def sample_fix() -> GPSFix:
    """Return a pre-built GPSFix for tests that don't need parsing."""
    from datetime import datetime, timezone

    return GPSFix(
        timestamp=datetime(1994, 3, 23, 12, 35, 19, tzinfo=timezone.utc),
        latitude=48.1173,
        longitude=11.516666666666667,
        speed_knots=22.4,
        course=84.4,
        status="A",
        raw="$GPRMC,123519.00,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*44",
    )
