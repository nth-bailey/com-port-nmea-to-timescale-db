"""Parse NMEA 0183 RMC and GGA sentences (any talker ID)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional

import pynmea2

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class GPSFix:
    """A single parsed GPS fix from an RMC or GGA sentence.

    Attributes
    ----------
    timestamp : datetime
        UTC date+time of the fix.
    latitude : float
        Decimal degrees (positive = North).
    longitude : float
        Decimal degrees (positive = East).
    speed_knots : float | None
        Speed over ground in knots.
    course : float | None
        Track angle in degrees True.
    status : str
        'A' = active / valid, 'V' = void.
    raw : str
        The original NMEA sentence.
    altitude : float | None
        Altitude above mean sea level in metres (from GGA).
    """

    timestamp: datetime
    latitude: float
    longitude: float
    speed_knots: Optional[float]
    course: Optional[float]
    status: str
    raw: str
    altitude: Optional[float] = None

    @property
    def is_valid(self) -> bool:
        """Return True when the receiver reports a valid fix."""
        return self.status == "A"

    @property
    def speed_kmh(self) -> Optional[float]:
        """Speed over ground converted to km/h."""
        return self.speed_knots * 1.852 if self.speed_knots is not None else None

    @property
    def speed_mph(self) -> Optional[float]:
        """Speed over ground converted to mph."""
        return self.speed_knots * 1.15078 if self.speed_knots is not None else None


def parse_rmc(sentence: str) -> Optional[GPSFix]:
    """Parse a single NMEA RMC sentence into a `GPSFix`.

    Accepts any talker ID — ``$GPRMC``, ``$GNRMC``, ``$GLRMC``, etc.

    Parameters
    ----------
    sentence : str
        A full NMEA sentence, e.g. ``$GNRMC,123519,...*47``.

    Returns
    -------
    GPSFix | None
        Parsed fix, or *None* if the sentence is not RMC or is malformed.
    """
    sentence = sentence.strip()
    if not sentence:
        return None

    try:
        msg = pynmea2.parse(sentence)
    except pynmea2.ParseError as exc:
        log.warning("NMEA parse error: %s — %r", exc, sentence)
        return None

    if not isinstance(msg, pynmea2.types.talker.RMC):
        return None

    # Build a full UTC datetime from the date + time fields.
    try:
        dt = datetime.combine(msg.datestamp, msg.timestamp, tzinfo=timezone.utc)
    except (TypeError, AttributeError):
        log.warning("Missing date/time in RMC sentence: %r", sentence)
        return None

    course = msg.true_course if msg.true_course else None
    # pynmea2 may return course as a string or float depending on version
    if course is not None:
        try:
            course = float(course)
        except (ValueError, TypeError):
            course = None

    return GPSFix(
        timestamp=dt,
        latitude=msg.latitude,
        longitude=msg.longitude,
        speed_knots=float(msg.spd_over_grnd) if msg.spd_over_grnd else 0.0,
        course=course,
        status=msg.status,
        raw=sentence,
    )


def parse_gga(sentence: str) -> Optional[GPSFix]:
    """Parse a single NMEA GGA sentence into a `GPSFix`.

    Accepts any talker ID — ``$GPGGA``, ``$GNGGA``, ``$GLGGA``, etc.

    GGA sentences carry altitude but **no date** field.  The parser
    combines today's UTC date with the GGA time-of-fix to build a full
    ``datetime``.

    Parameters
    ----------
    sentence : str
        A full NMEA sentence, e.g. ``$GPGGA,123519,...*61``.

    Returns
    -------
    GPSFix | None
        Parsed fix, or *None* if the sentence is not GGA or is malformed.
    """
    sentence = sentence.strip()
    if not sentence:
        return None

    try:
        msg = pynmea2.parse(sentence)
    except pynmea2.ParseError as exc:
        log.warning("NMEA parse error: %s — %r", exc, sentence)
        return None

    if not isinstance(msg, pynmea2.types.talker.GGA):
        return None

    # GGA has no date — use today's UTC date.
    try:
        dt = datetime.combine(date.today(), msg.timestamp, tzinfo=timezone.utc)
    except (TypeError, AttributeError):
        log.warning("Missing time in GGA sentence: %r", sentence)
        return None

    # Fix quality: 0 = invalid, ≥1 = some form of valid fix.
    try:
        gps_qual = int(msg.gps_qual)
    except (ValueError, TypeError):
        gps_qual = 0
    status = "A" if gps_qual >= 1 else "V"

    # Altitude above mean sea level (metres).
    try:
        altitude = float(msg.altitude) if msg.altitude else None
    except (ValueError, TypeError):
        altitude = None

    return GPSFix(
        timestamp=dt,
        latitude=msg.latitude,
        longitude=msg.longitude,
        speed_knots=None,  # GGA does not carry speed
        course=None,  # GGA does not carry course
        status=status,
        raw=sentence,
        altitude=altitude,
    )


def parse_nmea(sentence: str) -> Optional[GPSFix]:
    """Parse a single NMEA sentence (RMC or GGA) into a `GPSFix`.

    Tries RMC first, then GGA.  Returns *None* for unsupported or
    malformed sentences.
    """
    fix = parse_rmc(sentence)
    if fix is not None:
        return fix
    return parse_gga(sentence)


def parse_nmea_stream(lines: list[str]) -> list[GPSFix]:
    """Parse many NMEA lines, keeping only recognised fixes (RMC / GGA).

    Parameters
    ----------
    lines : list[str]
        Raw lines read from the serial port.

    Returns
    -------
    list[GPSFix]
        Successfully parsed fixes (may be empty).
    """
    fixes: list[GPSFix] = []
    for line in lines:
        fix = parse_nmea(line)
        if fix is not None:
            fixes.append(fix)
    return fixes


# Backward-compatible alias
parse_gprmc = parse_rmc
