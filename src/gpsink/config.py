"""Configuration dataclasses for serial port and database settings."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SerialConfig:
    """Settings for the COM / serial port connection."""

    port: str = "COM3"
    baudrate: int = 9600
    bytesize: int = 8  # 5, 6, 7, or 8
    parity: str = "N"  # N, E, O, M, S
    stopbits: float = 1  # 1, 1.5, 2
    timeout: float = 2.0  # read timeout in seconds
    rtscts: bool = False
    xonxoff: bool = False


@dataclass
class DatabaseConfig:
    """Connection parameters for TimescaleDB / PostGIS."""

    host: str = "localhost"
    port: int = 5432
    dbname: str = "gpsink"
    user: str = "postgres"
    password: str = "postgres"
    table_name: str = "gps_readings"

    @property
    def dsn(self) -> str:
        """Return a libpq-style connection string."""
        return (
            f"host={self.host} port={self.port} dbname={self.dbname} "
            f"user={self.user} password={self.password}"
        )


@dataclass
class AppConfig:
    """Top-level application configuration."""

    serial: SerialConfig = field(default_factory=SerialConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    source_label: str = "default"  # identifies the GPS entity / track
    source_uuid: str | None = None  # optional UUID for the GPS entity
