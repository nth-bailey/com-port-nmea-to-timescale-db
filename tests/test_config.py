"""Tests for gpsink.config."""

from __future__ import annotations


from gpsink.config import AppConfig, DatabaseConfig, SerialConfig


class TestSerialConfig:
    def test_defaults(self):
        cfg = SerialConfig()
        assert cfg.port == "COM3"
        assert cfg.baudrate == 9600
        assert cfg.bytesize == 8
        assert cfg.parity == "N"
        assert cfg.stopbits == 1
        assert cfg.timeout == 2.0

    def test_custom_values(self):
        cfg = SerialConfig(port="COM7", baudrate=115200, parity="E")
        assert cfg.port == "COM7"
        assert cfg.baudrate == 115200
        assert cfg.parity == "E"


class TestDatabaseConfig:
    def test_defaults(self):
        cfg = DatabaseConfig()
        assert cfg.host == "localhost"
        assert cfg.port == 5432
        assert cfg.dbname == "gpsink"

    def test_dsn(self):
        cfg = DatabaseConfig(
            host="db.example.com",
            port=5433,
            dbname="mydb",
            user="admin",
            password="secret",
        )
        assert (
            cfg.dsn
            == "host=db.example.com port=5433 dbname=mydb user=admin password=secret"
        )

    def test_table_name_default(self):
        cfg = DatabaseConfig()
        assert cfg.table_name == "gps_readings"


class TestAppConfig:
    def test_default_creates_sub_configs(self):
        cfg = AppConfig()
        assert isinstance(cfg.serial, SerialConfig)
        assert isinstance(cfg.database, DatabaseConfig)

    def test_custom_sub_configs(self):
        serial = SerialConfig(port="COM10")
        db = DatabaseConfig(dbname="custom_db")
        cfg = AppConfig(serial=serial, database=db)
        assert cfg.serial.port == "COM10"
        assert cfg.database.dbname == "custom_db"
