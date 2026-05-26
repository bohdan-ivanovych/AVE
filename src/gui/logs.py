"""Logs view component."""

import customtkinter as ctk
from tkinter import Text
import queue
from typing import TYPE_CHECKING

from src.config import AppConfig
from src.services.logger import get_logger_service
from utils import LOG_QUEUE as CORE_LOG_QUEUE

if TYPE_CHECKING:
    from src.gui.app import AVEApp


class LogsView(ctk.CTkFrame):
    """Logs view with real-time log display."""
    
    def __init__(self, parent, config: AppConfig, app: "AVEApp"):
        super().__init__(parent, fg_color=app.colors["bg"])
        self.config = config
        self.app = app
        self.logger = get_logger_service()
        self._paused = False
        
        self._setup_ui()
        self._start_log_polling()
    
    def _setup_ui(self):
        """Setup logs UI."""
        # Header with subtitle
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.pack(pady=(20, 15))
        
        header = ctk.CTkLabel(
            header_frame,
            text="Logs",
            font=("Segoe UI", 32, "bold"),
            text_color=self.app.colors["accent"]
        )
        header.pack()
        
        subtitle = ctk.CTkLabel(
            header_frame,
            text="Real-time application logs and debugging information",
            font=("Segoe UI", 13),
            text_color=self.app.colors["text_secondary"]
        )
        subtitle.pack(pady=(5, 0))
        
        # Actions
        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", padx=40, pady=(0, 8))
        clear_btn = ctk.CTkButton(actions, text="Clear", width=90, command=self._clear_logs, fg_color="#444444")
        clear_btn.pack(side="left", padx=4)
        copy_btn = ctk.CTkButton(actions, text="Copy All", width=100, command=self._copy_logs, fg_color="#564D4D")
        copy_btn.pack(side="left", padx=4)
        self.pause_btn = ctk.CTkButton(actions, text="Pause", width=100, command=self._toggle_pause, fg_color=self.app.colors["secondary"])
        self.pause_btn.pack(side="left", padx=4)

        # Log text area with better styling
        log_container = ctk.CTkFrame(self, fg_color=self.app.colors["card"], corner_radius=14, border_width=1, border_color=self.app.colors["border"])
        log_container.pack(fill="both", expand=True, padx=40, pady=12)
        
        # Text and scrollbar frame
        text_frame = ctk.CTkFrame(log_container, fg_color="transparent")
        text_frame.pack(fill="both", expand=True, padx=5, pady=5)
        
        self.log_text = Text(
            text_frame,
            width=120,
            height=40,
            bg="#1A1A1A",
            fg="#00FF00",
            font=("Consolas", 13),
            wrap="word",
            border=0,
            highlightthickness=0,
            insertbackground="#00FF00",
            selectbackground="#333333"
        )
        self.log_text.pack(side="left", fill="both", expand=True)
        
        # Scrollbar integrated with container
        scrollbar = ctk.CTkScrollbar(text_frame, command=self.log_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=scrollbar.set)
    
    def _start_log_polling(self):
        """Start polling for log updates."""
        self._update_logs()
    
    def _update_logs(self):
        """Update log display."""
        if self._paused:
            self.after(1000, self._update_logs)
            return
        # Read from old LOG_QUEUE (from core.py)
        try:
            logs = list(CORE_LOG_QUEUE.queue)
            if logs:
                content = "".join(logs[-500:])  # Last 500 lines
                self.log_text.delete("1.0", "end")
                self.log_text.insert("1.0", content)
                self.log_text.see("end")
        except Exception:
            pass
        
        # Also read from log file if available
        log_file = self.config.logs_dir / "app.log"
        if log_file.exists():
            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    # Show last 500 lines
                    content = "".join(lines[-500:])
                    if content:
                        self.log_text.delete("1.0", "end")
                        self.log_text.insert("1.0", content)
                        self.log_text.see("end")
            except Exception:
                pass
        
        # Schedule next update
        self.after(2000, self._update_logs)

    def _clear_logs(self):
        """Clear the log display."""
        try:
            self.log_text.delete("1.0", "end")
        except Exception:
            pass

    def _copy_logs(self):
        """Copy all logs to clipboard."""
        try:
            content = self.log_text.get("1.0", "end-1c")
            if not content:
                return
            self.clipboard_clear()
            self.clipboard_append(content)
            self.app.footer_label.configure(text="Logs copied to clipboard")
        except Exception:
            pass

    def _toggle_pause(self):
        """Pause/resume auto-refresh of logs."""
        self._paused = not self._paused
        try:
            self.pause_btn.configure(text="Resume" if self._paused else "Pause")
            self.app.footer_label.configure(text="Log auto-refresh paused" if self._paused else "Log auto-refresh resumed")
        except Exception:
            pass

