"""Clipboard utilities for CustomTkinter text widgets and tkinter Text."""

import tkinter as tk
from typing import Union
import customtkinter as ctk


def setup_clipboard_support(widget: Union[ctk.CTkTextbox, ctk.CTkEntry, tk.Text]):
    """
    Setup full clipboard support (Ctrl+V, Ctrl+C, Ctrl+X, Ctrl+A) 
    and context menu (right-click) for text widgets.
    
    Args:
        widget: CTkTextbox, CTkEntry, or tk.Text widget
    """
    # Handle tkinter Text widget directly
    if isinstance(widget, tk.Text):
        _setup_tk_text_clipboard(widget)
        return
    
    # Get the underlying tkinter widget for CustomTkinter widgets
    tk_widget = widget._textbox if isinstance(widget, ctk.CTkTextbox) else widget._entry
    
    # Bind keyboard shortcuts - use default parameter to avoid closure issues
    widget.bind("<Control-v>", lambda e=None, w=widget: _paste(w, e))
    widget.bind("<Control-c>", lambda e=None, w=widget: _copy(w, e))
    widget.bind("<Control-x>", lambda e=None, w=widget: _cut(w, e))
    widget.bind("<Control-a>", lambda e=None, w=widget: _select_all(w, e))
    
    # Bind right-click for context menu
    widget.bind("<Button-3>", lambda e=None, w=widget: _show_context_menu(w, e))
    widget.bind("<Button-2>", lambda e=None, w=widget: _show_context_menu(w, e))  # Middle button on some systems
    
    # Also bind to the underlying tk widget for better compatibility
    if isinstance(widget, ctk.CTkTextbox):
        tk_widget.bind("<Control-v>", lambda e=None, w=widget: _paste(w, e))
        tk_widget.bind("<Control-c>", lambda e=None, w=widget: _copy(w, e))
        tk_widget.bind("<Control-x>", lambda e=None, w=widget: _cut(w, e))
        tk_widget.bind("<Control-a>", lambda e=None, w=widget: _select_all(w, e))
        tk_widget.bind("<Button-3>", lambda e=None, w=widget: _show_context_menu(w, e))
    else:
        tk_widget.bind("<Control-v>", lambda e=None, w=widget: _paste(w, e))
        tk_widget.bind("<Control-c>", lambda e=None, w=widget: _copy(w, e))
        tk_widget.bind("<Control-x>", lambda e=None, w=widget: _cut(w, e))
        tk_widget.bind("<Control-a>", lambda e=None, w=widget: _select_all(w, e))
        tk_widget.bind("<Button-3>", lambda e=None, w=widget: _show_context_menu(w, e))


def _paste(widget: Union[ctk.CTkTextbox, ctk.CTkEntry, tk.Text], event=None):
    """Paste from clipboard."""
    try:
        clipboard_text = widget.clipboard_get()
        if isinstance(widget, tk.Text):
            # Delete selected text if any
            try:
                widget.delete("sel.first", "sel.last")
            except tk.TclError:
                pass
            # Insert at cursor
            widget.insert("insert", clipboard_text)
        elif isinstance(widget, ctk.CTkTextbox):
            # Delete selected text if any
            try:
                widget.delete("sel.first", "sel.last")
            except tk.TclError:
                pass
            # Insert at cursor
            widget.insert("insert", clipboard_text)
        else:  # CTkEntry
            # Delete selected text if any
            try:
                widget.delete("sel.first", "sel.last")
            except tk.TclError:
                pass
            # Insert at cursor
            widget.insert("insert", clipboard_text)
    except tk.TclError:
        # Clipboard might be empty or not text
        pass
    return "break"


def _copy(widget: Union[ctk.CTkTextbox, ctk.CTkEntry, tk.Text], event=None):
    """Copy selected text to clipboard."""
    try:
        if isinstance(widget, tk.Text):
            text = widget.get("sel.first", "sel.last")
        elif isinstance(widget, ctk.CTkTextbox):
            text = widget.get("sel.first", "sel.last")
        else:  # CTkEntry
            text = widget.get()
            # Get selected portion
            try:
                sel_start = widget.index("sel.first")
                sel_end = widget.index("sel.last")
                text = text[sel_start:sel_end]
            except tk.TclError:
                # No selection, copy all
                pass
        
        if text:
            widget.clipboard_clear()
            widget.clipboard_append(text)
    except tk.TclError:
        pass
    return "break"


def _cut(widget: Union[ctk.CTkTextbox, ctk.CTkEntry, tk.Text], event=None):
    """Cut selected text to clipboard."""
    try:
        if isinstance(widget, tk.Text):
            text = widget.get("sel.first", "sel.last")
            if text:
                widget.clipboard_clear()
                widget.clipboard_append(text)
                widget.delete("sel.first", "sel.last")
        elif isinstance(widget, ctk.CTkTextbox):
            text = widget.get("sel.first", "sel.last")
            if text:
                widget.clipboard_clear()
                widget.clipboard_append(text)
                widget.delete("sel.first", "sel.last")
        else:  # CTkEntry
            try:
                sel_start = widget.index("sel.first")
                sel_end = widget.index("sel.last")
                text = widget.get()[sel_start:sel_end]
                if text:
                    widget.clipboard_clear()
                    widget.clipboard_append(text)
                    widget.delete("sel.first", "sel.last")
            except tk.TclError:
                # No selection
                pass
    except tk.TclError:
        pass
    return "break"


def _select_all(widget: Union[ctk.CTkTextbox, ctk.CTkEntry, tk.Text], event=None):
    """Select all text."""
    try:
        if isinstance(widget, tk.Text):
            widget.tag_add("sel", "1.0", "end")
        elif isinstance(widget, ctk.CTkTextbox):
            widget.tag_add("sel", "1.0", "end")
        else:  # CTkEntry
            widget.select_range(0, tk.END)
    except tk.TclError:
        pass
    return "break"


def _show_context_menu(widget: Union[ctk.CTkTextbox, ctk.CTkEntry, tk.Text], event=None):
    """Show context menu on right-click."""
    # If no event provided, try to get widget position
    if event is None:
        try:
            # Get widget position
            widget.update_idletasks()
            x = widget.winfo_rootx() + widget.winfo_width() // 2
            y = widget.winfo_rooty() + widget.winfo_height() // 2
        except:
            # Fallback to cursor position
            try:
                x = widget.winfo_pointerx()
                y = widget.winfo_pointery()
            except:
                return
    else:
        try:
            x = event.x_root
            y = event.y_root
        except AttributeError:
            # Event doesn't have x_root/y_root, try to get from widget
            try:
                widget.update_idletasks()
                x = widget.winfo_rootx() + widget.winfo_width() // 2
                y = widget.winfo_rooty() + widget.winfo_height() // 2
            except:
                return
    
    menu = tk.Menu(widget, tearoff=0)
    
    # Check if there's selected text
    has_selection = False
    try:
        if isinstance(widget, tk.Text):
            has_selection = bool(widget.get("sel.first", "sel.last"))
        elif isinstance(widget, ctk.CTkTextbox):
            has_selection = bool(widget.get("sel.first", "sel.last"))
        else:  # CTkEntry
            try:
                widget.index("sel.first")
                has_selection = True
            except tk.TclError:
                has_selection = False
    except tk.TclError:
        has_selection = False
    
    # Check if clipboard has text
    has_clipboard = False
    try:
        clipboard_text = widget.clipboard_get()
        has_clipboard = bool(clipboard_text.strip())
    except tk.TclError:
        has_clipboard = False
    
    # Cut (only if selection exists)
    menu.add_command(
        label="Cut",
        command=lambda w=widget: _cut(w, None),
        state="normal" if has_selection else "disabled"
    )
    
    # Copy (only if selection exists)
    menu.add_command(
        label="Copy",
        command=lambda w=widget: _copy(w, None),
        state="normal" if has_selection else "disabled"
    )
    
    # Paste (only if clipboard has text)
    menu.add_command(
        label="Paste",
        command=lambda w=widget: _paste(w, None),
        state="normal" if has_clipboard else "disabled"
    )
    
    menu.add_separator()
    
    # Select All
    menu.add_command(
        label="Select All",
        command=lambda w=widget: _select_all(w, None)
    )
    
    try:
        menu.tk_popup(x, y)
    finally:
        menu.grab_release()


def _setup_tk_text_clipboard(text_widget: tk.Text):
    """Setup clipboard support for tkinter Text widget."""
    text_widget.bind("<Control-v>", lambda e=None, w=text_widget: _paste(w, e))
    text_widget.bind("<Control-c>", lambda e=None, w=text_widget: _copy(w, e))
    text_widget.bind("<Control-x>", lambda e=None, w=text_widget: _cut(w, e))
    text_widget.bind("<Control-a>", lambda e=None, w=text_widget: _select_all(w, e))
    text_widget.bind("<Button-3>", lambda e=None, w=text_widget: _show_context_menu(w, e))
    text_widget.bind("<Button-2>", lambda e=None, w=text_widget: _show_context_menu(w, e))

