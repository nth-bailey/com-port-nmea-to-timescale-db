"""Tests for gpsink.gui (mocked Tkinter — no display needed)."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest


class TestGUIConstruction:
    """Verify the GUI can be instantiated without a display by mocking Tk."""

    @patch("gpsink.gui.scrolledtext")
    @patch("gpsink.gui.ttk")
    @patch("gpsink.gui.tk")
    def test_gui_creates_without_error(self, mock_tk, mock_ttk, mock_st):
        mock_root = MagicMock()
        mock_tk.Tk.return_value = mock_root
        mock_tk.StringVar.return_value = MagicMock()

        from gpsink.gui import GpsinkGUI
        gui = GpsinkGUI()

        mock_root.title.assert_called_once()
        mock_root.geometry.assert_called_once()

    @patch("gpsink.gui.scrolledtext")
    @patch("gpsink.gui.ttk")
    @patch("gpsink.gui.tk")
    def test_gui_sets_window_title(self, mock_tk, mock_ttk, mock_st):
        mock_root = MagicMock()
        mock_tk.Tk.return_value = mock_root
        mock_tk.StringVar.return_value = MagicMock()

        from gpsink.gui import GpsinkGUI
        gui = GpsinkGUI()

        mock_root.title.assert_called_with("gpsink — GPS → TimescaleDB")

    @patch("gpsink.gui.scrolledtext")
    @patch("gpsink.gui.ttk")
    @patch("gpsink.gui.tk")
    def test_gui_close_protocol_set(self, mock_tk, mock_ttk, mock_st):
        mock_root = MagicMock()
        mock_tk.Tk.return_value = mock_root
        mock_tk.StringVar.return_value = MagicMock()

        from gpsink.gui import GpsinkGUI
        gui = GpsinkGUI()

        mock_root.protocol.assert_called_with("WM_DELETE_WINDOW", gui._on_close)

    @patch("gpsink.gui.scrolledtext")
    @patch("gpsink.gui.ttk")
    @patch("gpsink.gui.tk")
    def test_gui_sets_dark_background(self, mock_tk, mock_ttk, mock_st):
        mock_root = MagicMock()
        mock_tk.Tk.return_value = mock_root
        mock_tk.StringVar.return_value = MagicMock()

        from gpsink.gui import GpsinkGUI
        gui = GpsinkGUI()

        mock_root.configure.assert_called_with(bg="#1e1e2e")
