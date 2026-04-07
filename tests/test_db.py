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


class TestGPSWriterReconnect:
    """Tests for database auto-reconnection."""

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

    @patch("gpsink.db.time.sleep")
    @patch("gpsink.db.psycopg2.connect")
    def test_write_fix_reconnects_on_operational_error(
        self, mock_connect, mock_sleep, db_cfg, sample_fix
    ):
        """write_fix should reconnect when the cursor raises OperationalError."""
        import psycopg2 as _pg

        # First connection works for connect()
        mock_conn1 = MagicMock()
        mock_conn1.closed = False
        mock_cursor1 = MagicMock()
        mock_cursor1.execute.side_effect = _pg.OperationalError("connection lost")
        mock_conn1.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor1)
        mock_conn1.cursor.return_value.__exit__ = MagicMock(return_value=False)

        # Second connection works for reconnect
        mock_conn2 = MagicMock()
        mock_conn2.closed = False
        mock_cursor2 = MagicMock()
        mock_conn2.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor2)
        mock_conn2.cursor.return_value.__exit__ = MagicMock(return_value=False)

        mock_connect.side_effect = [mock_conn1, mock_conn2]

        reconnect_events: list = []
        writer = GPSWriter(
            db_cfg,
            auto_provision=False,
            max_retries=3,
            retry_base_delay=0.01,
            on_reconnect=lambda attempt, info: reconnect_events.append(attempt),
        )
        writer.connect()
        writer._provisioned = True

        writer.write_fix(sample_fix)

        # Should have reconnected and then written via the new cursor
        assert len(reconnect_events) >= 1
        mock_cursor2.execute.assert_called_once()

    @patch("gpsink.db.time.sleep")
    @patch("gpsink.db.psycopg2.connect")
    def test_write_fix_raises_after_exhausted_retries(
        self, mock_connect, mock_sleep, db_cfg, sample_fix
    ):
        """write_fix raises when all reconnection attempts fail."""
        import psycopg2 as _pg

        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = _pg.OperationalError("connection lost")
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        # All reconnect attempts also fail
        mock_connect.side_effect = [mock_conn] + [
            _pg.OperationalError("still down")
        ] * 5

        writer = GPSWriter(
            db_cfg,
            auto_provision=False,
            max_retries=2,
            retry_base_delay=0.01,
        )
        writer.connect()
        writer._provisioned = True

        with pytest.raises(_pg.OperationalError):
            writer.write_fix(sample_fix)

    @patch("gpsink.db.time.sleep")
    @patch("gpsink.db.psycopg2.connect")
    def test_on_reconnect_callback_receives_attempt_number(
        self, mock_connect, mock_sleep, db_cfg, sample_fix
    ):
        """on_reconnect callback is called with the correct attempt number."""
        import psycopg2 as _pg

        mock_conn1 = MagicMock()
        mock_conn1.closed = False
        mock_cursor1 = MagicMock()
        mock_cursor1.execute.side_effect = _pg.OperationalError("gone")
        mock_conn1.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor1)
        mock_conn1.cursor.return_value.__exit__ = MagicMock(return_value=False)

        mock_conn2 = MagicMock()
        mock_conn2.closed = False
        mock_cursor2 = MagicMock()
        mock_conn2.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor2)
        mock_conn2.cursor.return_value.__exit__ = MagicMock(return_value=False)

        # First connect works, reconnect fails once, then succeeds
        mock_connect.side_effect = [
            mock_conn1,
            _pg.OperationalError("still down"),
            mock_conn2,
        ]

        events: list = []
        writer = GPSWriter(
            db_cfg,
            auto_provision=False,
            max_retries=3,
            retry_base_delay=0.01,
            on_reconnect=lambda attempt, info: events.append((attempt, info)),
        )
        writer.connect()
        writer._provisioned = True
        writer.write_fix(sample_fix)

        assert events[0][0] == 1
        assert events[1][0] == 2
        assert "gpsink_test" in events[0][1]
