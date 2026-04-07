"""Tests for gpsink.db (mocked psycopg2)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from gpsink.config import DatabaseConfig
from gpsink.db import GPSWriter


class TestGPSWriter:
    """Unit tests with a fully mocked database connection."""

    @pytest.fixture
    def db_cfg(self) -> DatabaseConfig:
        return DatabaseConfig(
            host="127.0.0.1",
            port=5432,
            dbname="gpsink_test",
            user="testuser",
            password="testpass",
            table_name="gps_test",
        )

    @patch("gpsink.db.psycopg2.connect")
    def test_connect_uses_dsn(self, mock_connect, db_cfg):
        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_connect.return_value = mock_conn

        writer = GPSWriter(db_cfg, auto_provision=False)
        writer.connect()

        mock_connect.assert_called_once_with(db_cfg.dsn)
        assert mock_conn.autocommit is True

    @patch("gpsink.db.psycopg2.connect")
    def test_provision_creates_extensions_and_table(self, mock_connect, db_cfg):
        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_connect.return_value = mock_conn

        writer = GPSWriter(db_cfg, auto_provision=False)
        writer.connect()
        writer.provision()

        # Should have executed 4 statements: postgis ext, timescaledb ext, create table, create hypertable
        assert mock_cursor.execute.call_count == 4
        executed_sql = [c.args[0] for c in mock_cursor.execute.call_args_list]

        assert any("postgis" in s.lower() for s in executed_sql)
        assert any("timescaledb" in s.lower() for s in executed_sql)
        assert any("create table" in s.lower() for s in executed_sql)
        assert any("create_hypertable" in s.lower() for s in executed_sql)

    @patch("gpsink.db.psycopg2.connect")
    def test_write_fix_inserts_row(self, mock_connect, db_cfg, sample_fix):
        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_connect.return_value = mock_conn

        writer = GPSWriter(db_cfg, auto_provision=False)
        writer.connect()
        writer._provisioned = True  # skip provisioning
        writer.write_fix(sample_fix)

        mock_cursor.execute.assert_called_once()
        sql, params = mock_cursor.execute.call_args.args
        assert "INSERT INTO" in sql
        assert "ST_SetSRID" in sql
        assert params[0] == sample_fix.timestamp

    @patch("gpsink.db.psycopg2.extras.execute_batch")
    @patch("gpsink.db.psycopg2.connect")
    def test_write_fixes_batch(self, mock_connect, mock_exec_batch, db_cfg, sample_fix):
        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_connect.return_value = mock_conn

        writer = GPSWriter(db_cfg, auto_provision=False)
        writer.connect()
        writer._provisioned = True

        fixes = [sample_fix, sample_fix, sample_fix]
        count = writer.write_fixes(fixes)
        assert count == 3
        mock_exec_batch.assert_called_once()

    @patch("gpsink.db.psycopg2.connect")
    def test_close_closes_connection(self, mock_connect, db_cfg):
        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_connect.return_value = mock_conn

        writer = GPSWriter(db_cfg, auto_provision=False)
        writer.connect()
        writer.close()

        mock_conn.close.assert_called_once()

    @patch("gpsink.db.psycopg2.connect")
    def test_auto_provision_on_first_write(self, mock_connect, db_cfg, sample_fix):
        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_connect.return_value = mock_conn

        writer = GPSWriter(db_cfg, auto_provision=True)
        writer.connect()
        writer.write_fix(sample_fix)

        # Should have called provision (4 stmts) + 1 insert = 5
        assert mock_cursor.execute.call_count == 5

    def test_dsn_format(self, db_cfg):
        expected = "host=127.0.0.1 port=5432 dbname=gpsink_test user=testuser password=testpass"
        assert db_cfg.dsn == expected
