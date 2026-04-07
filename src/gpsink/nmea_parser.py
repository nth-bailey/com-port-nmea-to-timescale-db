"""Parse NMEA 0183 RMC sentences (any talker: $GPRMC, $GNRMC, $GLRMC, …)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import pynmea2

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class GPSFix:
    """A single parsed GPS fix from an RMC sentence.

    Attributes
    ----------
    timestamp : datetime
        UTC date+time of the fix.
    latitude : float
        Decimal degrees (positive = North).
    longitude : float
        Decimal degrees (positive = East).
    speed_knots : float
        Speed over ground in knots.
    course : float | None
        Track angle in degrees True.
    status : str
        'A' = active / valid, 'V' = void.
    raw : str
        The original NMEA sentence.
    """

    timestamp: datetime
    latitude: float
    longitude: float
    speed_knots: float
    course: Optional[float]
    status: str
    raw: str

    @property
    def is_valid(self) -> bool:
        """Return True when the receiver reports a valid fix."""
        return self.status == "A"

    @property
    def speed_kmh(self) -> float:
        """Speed over ground converted to km/h."""
        return self.speed_knots * 1.852

    @property
    def speed_mph(self) -> float:
        """Speed over ground converted to mph."""
        return self.speed_knots * 1.15078


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


def parse_nmea_stream(lines: list[str]) -> list[GPSFix]:
    """Parse many NMEA lines, keeping only valid RMC fixes.

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
        fix = parse_rmc(line)
        if fix is not None:
            fixes.append(fix)
    return fixes


# Backward-compatible alias
parse_gprmc = parse_rmc
