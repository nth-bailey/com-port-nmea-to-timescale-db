"""Simple Tkinter GUI for configuring and running gpsink."""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from typing import Optional, Any

from gpsink.config import DatabaseConfig, SerialConfig
from gpsink.db import GPSWriter
from gpsink.nmea_parser import GPSFix
from gpsink.serial_reader import SerialReader

log = logging.getLogger(__name__)


class GpsinkGUI:
    """Tkinter application for gpsink."""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("gpsink — GPS → TimescaleDB")
        self.root.geometry("720x660")
        self.root.resizable(True, True)
        self.root.configure(bg="#1e1e2e")

        self._reader: Optional[SerialReader] = None
        self._writer: Optional[GPSWriter] = None
        self._fix_count = 0

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#1e1e2e")
        style.configure(
            "TLabel", background="#1e1e2e", foreground="#cdd6f4", font=("Segoe UI", 10)
        )
        style.configure(
            "Header.TLabel", font=("Segoe UI", 12, "bold"), foreground="#89b4fa"
        )
        style.configure("TEntry", fieldbackground="#313244", foreground="#cdd6f4")
        style.configure(
            "TButton",
            background="#89b4fa",
            foreground="#1e1e2e",
            font=("Segoe UI", 10, "bold"),
        )
        style.configure(
            "Stop.TButton",
            background="#f38ba8",
            foreground="#1e1e2e",
            font=("Segoe UI", 10, "bold"),
        )
        style.configure("TCombobox", fieldbackground="#313244", foreground="#cdd6f4")
        style.configure("TLabelframe", background="#1e1e2e", foreground="#a6adc8")
        style.configure(
            "TLabelframe.Label",
            background="#1e1e2e",
            foreground="#a6adc8",
            font=("Segoe UI", 10, "bold"),
        )
        style.configure(
            "Status.TLabel",
            background="#1e1e2e",
            foreground="#a6e3a1",
            font=("Segoe UI", 9),
        )
        style.configure(
            "TCheckbutton",
            background="#1e1e2e",
            foreground="#cdd6f4",
            font=("Segoe UI", 10),
        )

        self._build_ui()

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        pad: dict[str, Any] = dict(padx=8, pady=4)

        # ---- Serial settings ----
        serial_frame = ttk.LabelFrame(self.root, text="  📡  Serial / COM Port  ")
        serial_frame.pack(fill="x", **pad)

        row = ttk.Frame(serial_frame)
        row.pack(fill="x", **pad)

        ttk.Label(row, text="Port:").pack(side="left")
        self.port_var = tk.StringVar(value="COM3")
        ttk.Entry(row, textvariable=self.port_var, width=10).pack(side="left", padx=4)

        ttk.Label(row, text="Baud:").pack(side="left", padx=(12, 0))
        self.baud_var = tk.StringVar(value="9600")
        baud_cb = ttk.Combobox(
            row,
            textvariable=self.baud_var,
            width=8,
            values=["4800", "9600", "19200", "38400", "57600", "115200"],
        )
        baud_cb.pack(side="left", padx=4)

        ttk.Label(row, text="Data:").pack(side="left", padx=(12, 0))
        self.bytesize_var = tk.StringVar(value="8")
        ttk.Combobox(
            row, textvariable=self.bytesize_var, width=3, values=["5", "6", "7", "8"]
        ).pack(side="left", padx=4)

        ttk.Label(row, text="Parity:").pack(side="left", padx=(12, 0))
        self.parity_var = tk.StringVar(value="N")
        ttk.Combobox(
            row, textvariable=self.parity_var, width=3, values=["N", "E", "O", "M", "S"]
        ).pack(side="left", padx=4)

        ttk.Label(row, text="Stop:").pack(side="left", padx=(12, 0))
        self.stopbits_var = tk.StringVar(value="1")
        ttk.Combobox(
            row, textvariable=self.stopbits_var, width=4, values=["1", "1.5", "2"]
        ).pack(side="left", padx=4)

        # ---- Database settings ----
        db_frame = ttk.LabelFrame(self.root, text="  🗄️  TimescaleDB  ")
        db_frame.pack(fill="x", **pad)

        # Enable / disable database toggle
        db_toggle_row = ttk.Frame(db_frame)
        db_toggle_row.pack(fill="x", **pad)

        self.db_enabled_var = tk.BooleanVar(value=True)
        self.db_check = ttk.Checkbutton(
            db_toggle_row,
            text="Enable database connection",
            variable=self.db_enabled_var,
            command=self._on_db_toggle,
        )
        self.db_check.pack(side="left")

        ttk.Label(
            db_toggle_row,
            text="(uncheck to run serial-only / dry-run)",
            foreground="#6c7086",
            font=("Segoe UI", 8),
        ).pack(side="left", padx=(8, 0))

        row2 = ttk.Frame(db_frame)
        row2.pack(fill="x", **pad)

        ttk.Label(row2, text="Host:").pack(side="left")
        self.db_host_var = tk.StringVar(value="localhost")
        self._db_host_entry = ttk.Entry(row2, textvariable=self.db_host_var, width=16)
        self._db_host_entry.pack(side="left", padx=4)

        ttk.Label(row2, text="Port:").pack(side="left", padx=(12, 0))
        self.db_port_var = tk.StringVar(value="5432")
        self._db_port_entry = ttk.Entry(row2, textvariable=self.db_port_var, width=6)
        self._db_port_entry.pack(side="left", padx=4)

        ttk.Label(row2, text="DB:").pack(side="left", padx=(12, 0))
        self.db_name_var = tk.StringVar(value="gpsink")
        self._db_name_entry = ttk.Entry(row2, textvariable=self.db_name_var, width=12)
        self._db_name_entry.pack(side="left", padx=4)

        row3 = ttk.Frame(db_frame)
        row3.pack(fill="x", **pad)

        ttk.Label(row3, text="User:").pack(side="left")
        self.db_user_var = tk.StringVar(value="postgres")
        self._db_user_entry = ttk.Entry(row3, textvariable=self.db_user_var, width=12)
        self._db_user_entry.pack(side="left", padx=4)

        ttk.Label(row3, text="Password:").pack(side="left", padx=(12, 0))
        self.db_pass_var = tk.StringVar(value="postgres")
        self._db_pass_entry = ttk.Entry(
            row3, textvariable=self.db_pass_var, width=14, show="•"
        )
        self._db_pass_entry.pack(side="left", padx=4)

        ttk.Label(row3, text="Table:").pack(side="left", padx=(12, 0))
        self.table_var = tk.StringVar(value="gps_readings")
        self._db_table_entry = ttk.Entry(row3, textvariable=self.table_var, width=16)
        self._db_table_entry.pack(side="left", padx=4)

        # Store refs so we can enable/disable them
        self._db_widgets = [
            self._db_host_entry,
            self._db_port_entry,
            self._db_name_entry,
            self._db_user_entry,
            self._db_pass_entry,
            self._db_table_entry,
        ]

        # ---- Controls ----
        ctrl_frame = ttk.Frame(self.root)
        ctrl_frame.pack(fill="x", **pad)

        self.start_btn = ttk.Button(ctrl_frame, text="▶  Start", command=self._on_start)
        self.start_btn.pack(side="left", padx=4)

        self.stop_btn = ttk.Button(
            ctrl_frame, text="■  Stop", command=self._on_stop, style="Stop.TButton"
        )
        self.stop_btn.pack(side="left", padx=4)
        self.stop_btn.state(["disabled"])

        self.status_var = tk.StringVar(value="Idle")
        ttk.Label(ctrl_frame, textvariable=self.status_var, style="Status.TLabel").pack(
            side="right", padx=8
        )

        self.count_var = tk.StringVar(value="Fixes: 0")
        ttk.Label(ctrl_frame, textvariable=self.count_var, style="Status.TLabel").pack(
            side="right", padx=8
        )

        # ---- Log area ----
        log_frame = ttk.LabelFrame(self.root, text="  📜  Live Feed  ")
        log_frame.pack(fill="both", expand=True, **pad)

        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            height=14,
            bg="#181825",
            fg="#a6adc8",
            font=("Consolas", 9),
            insertbackground="#cdd6f4",
            relief="flat",
            state="disabled",
        )
        self.log_text.pack(fill="both", expand=True, padx=4, pady=4)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _log(self, text: str) -> None:
        """Append a line to the log widget (thread-safe via `after`)."""

        def _append():
            self.log_text.configure(state="normal")
            self.log_text.insert("end", text + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")

        self.root.after(0, _append)

    def _on_db_toggle(self) -> None:
        """Enable or disable the database entry widgets."""
        state = "!disabled" if self.db_enabled_var.get() else "disabled"
        for widget in self._db_widgets:
            widget.state([state])

    def _on_start(self) -> None:
        serial_cfg = SerialConfig(
            port=self.port_var.get(),
            baudrate=int(self.baud_var.get()),
            bytesize=int(self.bytesize_var.get()),
            parity=self.parity_var.get(),
            stopbits=float(self.stopbits_var.get()),
        )

        db_enabled = self.db_enabled_var.get()

        if db_enabled:
            db_cfg = DatabaseConfig(
                host=self.db_host_var.get(),
                port=int(self.db_port_var.get()),
                dbname=self.db_name_var.get(),
                user=self.db_user_var.get(),
                password=self.db_pass_var.get(),
                table_name=self.table_var.get(),
            )

            try:
                self._writer = GPSWriter(
                    db_cfg,
                    on_reconnect=lambda attempt, info: self._log(
                        f"  ⟳  DB reconnect attempt {attempt} → {info}"
                    ),
                )
                self._writer.connect()
            except Exception as exc:
                messagebox.showerror("Database Error", str(exc))
                return
        else:
            self._writer = None

        self._fix_count = 0

        def on_fix(fix: GPSFix) -> None:
            self._fix_count += 1
            self.root.after(0, lambda: self.count_var.set(f"Fixes: {self._fix_count}"))
            if self._writer is not None:
                try:
                    self._writer.write_fix(fix)
                except Exception as db_exc:
                    self._log(f"DB write error: {db_exc}")
            self._log(
                f"[{fix.timestamp:%H:%M:%S}]  "
                f"lat={fix.latitude:+.6f}  lon={fix.longitude:+.6f}  "
                f"spd={fix.speed_knots:.1f}kn  "
                f"{'✓' if fix.is_valid else '✗'}"
            )

        def on_error(exc: Exception) -> None:
            self._log(f"ERROR: {exc}")
            self.root.after(0, lambda: self.status_var.set("Error"))

        def on_serial_reconnect(attempt: int, port_name: str) -> None:
            self._log(f"  ⟳  Serial reconnect attempt {attempt} → {port_name}")
            self.root.after(
                0, lambda: self.status_var.set(f"Reconnecting ({attempt})…")
            )

        self._reader = SerialReader(
            serial_cfg,
            on_fix=on_fix,
            on_error=on_error,
            on_reconnect=on_serial_reconnect,
        )
        self._reader.start()

        mode = "serial-only" if not db_enabled else "streaming"
        self.status_var.set(f"{mode.title()} {serial_cfg.port}")
        self.start_btn.state(["disabled"])
        self.stop_btn.state(["!disabled"])

        if db_enabled:
            self._log(
                f"Started — {serial_cfg.port} @ {serial_cfg.baudrate} → "
                f"{db_cfg.host}:{db_cfg.port}/{db_cfg.dbname}"
            )
        else:
            self._log(
                f"Started — {serial_cfg.port} @ {serial_cfg.baudrate}  "
                f"(serial-only mode, no database)"
            )

    def _on_stop(self) -> None:
        if self._reader:
            self._reader.stop()
        if self._writer:
            self._writer.close()

        self.status_var.set("Stopped")
        self.start_btn.state(["!disabled"])
        self.stop_btn.state(["disabled"])
        db_label = "written" if self._writer is not None else "logged"
        self._log(f"Stopped — {self._fix_count} fixes {db_label}.")

    def _on_close(self) -> None:
        self._on_stop()
        self.root.destroy()

    def run(self) -> None:
        """Enter the Tk main loop."""
        self.root.mainloop()


def launch_gui() -> None:
    """Create and run the GUI (entry-point for CLI ``gpsink gui``)."""
    logging.basicConfig(level=logging.INFO)
    app = GpsinkGUI()
    app.run()


if __name__ == "__main__":
    launch_gui()
