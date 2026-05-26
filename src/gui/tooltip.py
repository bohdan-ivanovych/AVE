"""Tooltip utility for CustomTkinter widgets."""

import customtkinter as ctk
import tkinter
from typing import Optional


class ToolTip:
    """Simple tooltip widget for CustomTkinter."""
    
    def __init__(self, widget, text: str, delay: int = 500):
        """
        Create a tooltip for a widget.
        
        Args:
            widget: The widget to attach tooltip to
            text: Tooltip text
            delay: Delay in milliseconds before showing tooltip
        """
        self.widget = widget
        self.text = text
        self.delay = delay
        self.tooltip_window: Optional[ctk.CTkToplevel] = None
        self.id: Optional[str] = None
        
        self.widget.bind("<Enter>", self._on_enter)
        self.widget.bind("<Leave>", self._on_leave)
        self.widget.bind("<ButtonPress>", self._on_leave)
    
    def _on_enter(self, event=None):
        """Schedule tooltip to appear."""
        self._schedule()
    
    def _on_leave(self, event=None):
        """Cancel tooltip and hide if shown."""
        self._unschedule()
        self._hide()
    
    def _schedule(self):
        """Schedule tooltip to appear after delay."""
        self._unschedule()
        self.id = self.widget.after(self.delay, self._show)
    
    def _unschedule(self):
        """Cancel scheduled tooltip."""
        if self.id:
            self.widget.after_cancel(self.id)
            self.id = None
    
    def _show(self):
        """Show the tooltip."""
        if self.tooltip_window:
            return
        
        # Check if widget still exists and is valid
        try:
            if not self.widget.winfo_exists():
                return
            # Try to get widget info to verify it's still valid
            _ = self.widget.winfo_width()
        except (AttributeError, RuntimeError, tkinter.TclError):
            # Widget was destroyed or is invalid
            return
        
        try:
            x, y, _, _ = self.widget.bbox("insert") if hasattr(self.widget, "bbox") else (0, 0, 0, 0)
            x += self.widget.winfo_rootx() + 25
            y += self.widget.winfo_rooty() + 20
            
            self.tooltip_window = ctk.CTkToplevel(self.widget)
            self.tooltip_window.wm_overrideredirect(True)
            self.tooltip_window.wm_geometry(f"+{x}+{y}")
            
            label = ctk.CTkLabel(
                self.tooltip_window,
                text=self.text,
                font=("Segoe UI", 12),
                fg_color="#2A2A2A",
                text_color="#FFFFFF",
                corner_radius=8,
                padx=12,
                pady=8
            )
            label.pack()
        except (AttributeError, RuntimeError, tkinter.TclError) as e:
            # Widget was destroyed during tooltip creation
            if self.tooltip_window:
                try:
                    self.tooltip_window.destroy()
                except:
                    pass
                self.tooltip_window = None
    
    def _hide(self):
        """Hide the tooltip."""
        if self.tooltip_window:
            try:
                if self.tooltip_window.winfo_exists():
                    self.tooltip_window.destroy()
            except (AttributeError, RuntimeError, tkinter.TclError):
                # Window already destroyed
                pass
            finally:
                self.tooltip_window = None


def create_tooltip(widget, text: str, delay: int = 500) -> ToolTip:
    """Create and return a tooltip for a widget."""
    return ToolTip(widget, text, delay)


