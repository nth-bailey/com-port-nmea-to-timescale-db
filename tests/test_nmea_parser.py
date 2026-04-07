"""Tests for gpsink.nmea_parser."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from gpsink.nmea_parser import GPSFix, parse_gprmc, parse_nmea_stream

# Sample NMEA sentences (duplicated from conftest for direct import)
VALID_GPRMC = "$GPRMC,123519.00,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*44"
VOID_GPRMC = "$GPRMC,123519.00,V,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*53"
GPGGA_SENTENCE = "$GPGGA,123519.00,4807.038,N,01131.000,E,1,08,0.9,545.4,M,47.0,M,,*61"
GARBAGE = "!!!NOT_NMEA!!!"


# ------------------------------------------------------------------
# parse_gprmc
# ------------------------------------------------------------------


class TestParseGprmc:
    """Unit tests for the single-sentence parser."""

    def test_valid_gprmc_returns_fix(self):
        fix = parse_gprmc(VALID_GPRMC)
        assert fix is not None
        assert isinstance(fix, GPSFix)

    def test_valid_fix_has_correct_timestamp(self):
        fix = parse_gprmc(VALID_GPRMC)
        assert fix is not None
        # 23-Mar-1994, 12:35:19 UTC
        assert fix.timestamp == datetime(1994, 3, 23, 12, 35, 19, tzinfo=timezone.utc)

    def test_valid_fix_latitude(self):
        fix = parse_gprmc(VALID_GPRMC)
        assert fix is not None
        # 48°07.038'N → ≈ 48.1173°
        assert fix.latitude == pytest.approx(48.1173, abs=0.001)

    def test_valid_fix_longitude(self):
        fix = parse_gprmc(VALID_GPRMC)
        assert fix is not None
        # 011°31.000'E → ≈ 11.5167°
        assert fix.longitude == pytest.approx(11.5167, abs=0.001)

    def test_valid_fix_speed(self):
        fix = parse_gprmc(VALID_GPRMC)
        assert fix is not None
        assert fix.speed_knots == pytest.approx(22.4)

    def test_valid_fix_course(self):
        fix = parse_gprmc(VALID_GPRMC)
        assert fix is not None
        assert fix.course == pytest.approx(84.4)

    def test_valid_fix_status_is_active(self):
        fix = parse_gprmc(VALID_GPRMC)
        assert fix is not None
        assert fix.status == "A"
        assert fix.is_valid is True

    def test_void_fix_status(self):
        fix = parse_gprmc(VOID_GPRMC)
        assert fix is not None
        assert fix.status == "V"
        assert fix.is_valid is False

    def test_non_rmc_returns_none(self):
        assert parse_gprmc(GPGGA_SENTENCE) is None

    def test_garbage_returns_none(self):
        assert parse_gprmc(GARBAGE) is None

    def test_empty_string_returns_none(self):
        assert parse_gprmc("") is None

    def test_whitespace_only_returns_none(self):
        assert parse_gprmc("   \n\t  ") is None

    def test_raw_field_preserved(self):
        fix = parse_gprmc(VALID_GPRMC)
        assert fix is not None
        assert fix.raw == VALID_GPRMC


# ------------------------------------------------------------------
# GPSFix properties
# ------------------------------------------------------------------


class TestGPSFixProperties:
    """Tests for computed properties on GPSFix."""

    def test_speed_kmh(self, sample_fix):
        assert sample_fix.speed_kmh == pytest.approx(22.4 * 1.852, rel=1e-3)

    def test_speed_mph(self, sample_fix):
        assert sample_fix.speed_mph == pytest.approx(22.4 * 1.15078, rel=1e-3)


# ------------------------------------------------------------------
# parse_nmea_stream
# ------------------------------------------------------------------


class TestParseNmeaStream:
    """Tests for batch parsing multiple lines."""

    def test_filters_only_gprmc(self):
        lines = [VALID_GPRMC, GPGGA_SENTENCE, VOID_GPRMC, GARBAGE]
        fixes = parse_nmea_stream(lines)
        assert len(fixes) == 2  # valid + void

    def test_empty_list(self):
        assert parse_nmea_stream([]) == []

    def test_all_garbage(self):
        assert parse_nmea_stream([GARBAGE, "", "random text"]) == []

    def test_preserves_order(self):
        lines = [VALID_GPRMC, VOID_GPRMC]
        fixes = parse_nmea_stream(lines)
        assert fixes[0].status == "A"
        assert fixes[1].status == "V"
