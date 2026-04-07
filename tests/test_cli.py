"""Tests for gpsink.cli (Click commands)."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from gpsink.cli import main


class TestCLI:
    """Test the Click CLI interface."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_help(self, runner):
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "gpsink" in result.output.lower()

    def test_run_help(self, runner):
        result = runner.invoke(main, ["run", "--help"])
        assert result.exit_code == 0
        assert "--port" in result.output
        assert "--baud" in result.output
        assert "--db-host" in result.output

    def test_provision_help(self, runner):
        result = runner.invoke(main, ["provision", "--help"])
        assert result.exit_code == 0
        assert "--db-host" in result.output

    def test_gui_help(self, runner):
        result = runner.invoke(main, ["gui", "--help"])
        assert result.exit_code == 0

    @patch("gpsink.cli.GPSWriter")
    @patch("gpsink.cli.SerialReader")
    def test_run_starts_and_stops(self, mock_reader_cls, mock_writer_cls, runner):
        """Simulate a quick run that gets interrupted."""
        mock_writer = MagicMock()
        mock_writer_cls.return_value = mock_writer

        mock_reader = MagicMock()
        mock_reader_cls.return_value = mock_reader

        # Make stop.wait() return immediately by patching threading.Event
        with patch("gpsink.cli.threading.Event") as mock_event_cls:
            mock_event = MagicMock()
            mock_event.wait.return_value = None  # returns immediately
            mock_event_cls.return_value = mock_event

            result = runner.invoke(main, [
                "run",
                "--port", "COM99",
                "--baud", "9600",
                "--db-host", "localhost",
                "--db-name", "testdb",
            ])

        # Writer should have been connected and closed
        mock_writer.connect.assert_called_once()
        mock_writer.close.assert_called_once()

        # Reader should have been started and stopped
        mock_reader.start.assert_called_once()
        mock_reader.stop.assert_called_once()

    @patch("gpsink.cli.GPSWriter")
    def test_provision_command(self, mock_writer_cls, runner):
        mock_writer = MagicMock()
        mock_writer_cls.return_value = mock_writer

        result = runner.invoke(main, [
            "provision",
            "--db-host", "localhost",
            "--db-name", "testdb",
        ])

        assert result.exit_code == 0
        mock_writer.connect.assert_called_once()
        mock_writer.provision.assert_called_once()
        mock_writer.close.assert_called_once()
