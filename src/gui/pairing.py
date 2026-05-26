"""Pairing view with manual drag-and-drop support."""

import customtkinter as ctk
import threading
import queue
from pathlib import Path
from typing import List, Optional, TYPE_CHECKING
from tkinter import messagebox, Toplevel, filedialog

from src.config import AppConfig
from src.services.logger import get_logger_service
from src.services.image_service import ImageService
from src.services.history_service import get_history_service
from src.services.batch_template_service import get_batch_template_service
from core import run_one_generation, PROFILES, LOG_QUEUE as CORE_LOG_QUEUE
from src.services.settings_service import get_settings_service
from src.services.prompt_library_service import get_prompt_library_service
from src.services.notifications import get_notification_service
from src.dto import ImagePair, PairingMode
from src.gui.tooltip import create_tooltip
from src.gui.clipboard_utils import setup_clipboard_support
from src.exceptions import TemplateError
import time
import concurrent.futures
import asyncio
import json
import re
import random

# Optional import for process management
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

if TYPE_CHECKING:
    from src.gui.app import AVEApp


class PairingView(ctk.CTkFrame):
    """Pairing editor view with manual pairing support."""
    
    def __init__(self, parent, config: AppConfig, app: "AVEApp"):
        super().__init__(parent, fg_color=app.colors["bg"])
        self.config = config
        self.app = app
        self.logger = get_logger_service().get_logger("pairing")
        self.image_service = ImageService(config)
        
        self.pairs: List[ImagePair] = []
        self.pairing_mode = PairingMode.SEQUENTIAL
        self.history_service = get_history_service()
        # Remember last used directory for file dialogs
        self._last_dir: Path = self.config.assets_dir if hasattr(self.config, 'assets_dir') else Path('.')
        # Support 1-4 folders for pairing - start empty
        self._folders: List[Path] = []
        
        # Undo/redo stacks
        self._undo_stack: List[List[ImagePair]] = []
        self._redo_stack: List[List[ImagePair]] = []
        
        # Cancellation control
        self._cancellation_event: Optional[threading.Event] = None
        self._generation_thread: Optional[threading.Thread] = None
        self._executor: Optional[concurrent.futures.ThreadPoolExecutor] = None
        
        # Auto-save state
        self._auto_save_enabled = True
        self._auto_save_file = self.config.profiles_dir / "pairing_autosave.json"
        
        self._setup_ui()
        self._load_images()
        self._load_autosave()
    
    def apply_prompt_to_all(self, prompt_text: str) -> int:
        """Apply the given prompt to all currently displayed pair prompt boxes.
        Returns number of pairs updated.
        """
        updated = 0
        for widget in getattr(self, "pairs_container", []).winfo_children() if hasattr(self, "pairs_container") else []:
            if hasattr(widget, 'pair_data') and hasattr(widget, 'prompt_widget'):
                try:
                    widget.prompt_widget.delete("1.0", "end")
                    widget.prompt_widget.insert("1.0", prompt_text)
                    widget.pair_data.prompt = prompt_text
                    updated += 1
                except Exception:
                    continue
        # Visual hint on status
        try:
            if updated > 0 and hasattr(self, 'progress_label'):
                self.progress_label.configure(text=f"Applied prompt to {updated} pairs", text_color=self.app.colors["success"])
        except Exception:
            # Fallback if tkdnd not available
            pass
        return updated
    
    def _parse_placeholder_values(self, text: str) -> List[str]:
        """Parse placeholder values from text, respecting parentheses.
        
        Splits by newlines first, then by commas, but only splits on commas
        that are NOT inside parentheses.
        
        Args:
            text: Input text with values (newline or comma separated)
            
        Returns:
            List of parsed values
        """
        values = []
        
        # First split by newlines
        for line in text.split('\n'):
            line = line.strip()
            if not line:
                continue
            
            # Check if line contains commas
            if ',' not in line:
                # No commas, add as single value
                values.append(line)
            else:
                # Has commas - need to split carefully, respecting parentheses
                current_value = []
                paren_depth = 0
                i = 0
                
                while i < len(line):
                    char = line[i]
                    
                    if char == '(':
                        paren_depth += 1
                        current_value.append(char)
                    elif char == ')':
                        paren_depth -= 1
                        current_value.append(char)
                    elif char == ',' and paren_depth == 0:
                        # Comma at top level - split here
                        value_str = ''.join(current_value).strip()
                        if value_str:
                            values.append(value_str)
                        current_value = []
                    else:
                        current_value.append(char)
                    
                    i += 1
                
                # Add remaining value
                if current_value:
                    value_str = ''.join(current_value).strip()
                    if value_str:
                        values.append(value_str)
        
        return values
    
    def _show_placeholder_values_dialog(self, parent, placeholders: List[str]) -> Optional[dict]:
        """Show dialog to enter values for each placeholder.
        
        Args:
            parent: Parent window
            placeholders: List of placeholder names (without brackets)
            
        Returns:
            Dictionary mapping placeholder names to lists of values, or None if cancelled
        """
        # Remove duplicates while preserving order
        unique_placeholders = []
        seen = set()
        for p in placeholders:
            if p not in seen:
                unique_placeholders.append(p)
                seen.add(p)
        
        dialog = Toplevel(parent)
        dialog.title("Enter Placeholder Values")
        dialog.geometry("800x600")
        dialog.configure(bg=self.app.colors["bg"])
        dialog.transient(parent)
        dialog.grab_set()
        
        # Center the dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (800 // 2)
        y = (dialog.winfo_screenheight() // 2) - (600 // 2)
        dialog.geometry(f"800x600+{x}+{y}")
        
        # Header
        header_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        header_frame.pack(pady=(20, 15), padx=25, fill="x")
        
        title_label = ctk.CTkLabel(
            header_frame,
            text="📝 Enter Values for Placeholders",
            font=("Segoe UI", 20, "bold"),
            text_color=self.app.colors["accent"]
        )
        title_label.pack()
        
        desc_label = ctk.CTkLabel(
            header_frame,
            text=f"Enter values for each placeholder (one per line or comma-separated).\nChoose distribution mode: 1:1 (sequential, cycles if needed) or Random.",
            font=("Segoe UI", 12),
            text_color=self.app.colors["text_secondary"],
            wraplength=750,
            justify="left"
        )
        desc_label.pack(pady=(8, 0))
        
        # Distribution mode selector
        mode_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        mode_frame.pack(pady=(10, 0), fill="x")
        
        ctk.CTkLabel(
            mode_frame,
            text="Distribution Mode:",
            font=("Segoe UI", 13, "bold"),
            text_color=self.app.colors["text"]
        ).pack(side="left", padx=(0, 15))
        
        placeholder_mode_var = ctk.StringVar(value="sequential")
        sequential_radio = ctk.CTkRadioButton(
            mode_frame,
            text="1:1 Sequential (cycles if needed)",
            variable=placeholder_mode_var,
            value="sequential",
            font=("Segoe UI", 12)
        )
        sequential_radio.pack(side="left", padx=(0, 15))
        
        random_radio = ctk.CTkRadioButton(
            mode_frame,
            text="🎲 Random",
            variable=placeholder_mode_var,
            value="random",
            font=("Segoe UI", 12)
        )
        random_radio.pack(side="left")
        
        # Scrollable frame for placeholders
        scroll_frame = ctk.CTkScrollableFrame(dialog, fg_color=self.app.colors["card"], corner_radius=12)
        scroll_frame.pack(fill="both", expand=True, padx=25, pady=(0, 15))
        
        placeholder_widgets = {}
        
        for placeholder in unique_placeholders:
            # Frame for each placeholder
            placeholder_frame = ctk.CTkFrame(scroll_frame, fg_color="#2A2A2A", corner_radius=8)
            placeholder_frame.pack(fill="x", padx=10, pady=8)
            
            # Label
            label = ctk.CTkLabel(
                placeholder_frame,
                text=f"[{placeholder}]",
                font=("Segoe UI", 14, "bold"),
                text_color=self.app.colors["accent"]
            )
            label.pack(anchor="w", padx=15, pady=(12, 5))
            
            # Textbox for values
            values_textbox = ctk.CTkTextbox(
                placeholder_frame,
                height=80,
                fg_color="#1A1A1A",
                text_color=self.app.colors["text"],
                corner_radius=6,
                border_width=1,
                border_color=self.app.colors["border"],
                font=("Segoe UI", 12)
            )
            values_textbox.pack(fill="x", padx=15, pady=(0, 12))
            
            # Setup clipboard support
            setup_clipboard_support(values_textbox)
            
            placeholder_widgets[placeholder] = values_textbox
        
        # Buttons
        buttons_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        buttons_frame.pack(pady=(0, 20), padx=25, fill="x")
        
        result = None
        
        def apply_values():
            nonlocal result
            placeholder_values = {}
            
            for placeholder, textbox in placeholder_widgets.items():
                text = textbox.get("1.0", "end-1c").strip()
                if not text:
                    messagebox.showwarning(
                        "Empty Values",
                        f"Please enter at least one value for [{placeholder}]"
                    )
                    return
                
                # Parse values: split by newlines or commas (respecting parentheses)
                values = self._parse_placeholder_values(text)
                
                if not values:
                    messagebox.showwarning(
                        "Empty Values",
                        f"Please enter at least one value for [{placeholder}]"
                    )
                    return
                
                placeholder_values[placeholder] = values
            
            # Store mode with values
            result = {
                "values": placeholder_values,
                "mode": placeholder_mode_var.get()
            }
            dialog.destroy()
        
        def cancel():
            dialog.destroy()
        
        # Apply button
        apply_btn = ctk.CTkButton(
            buttons_frame,
            text="✅ Apply",
            font=("Segoe UI", 16, "bold"),
            fg_color=self.app.colors["accent"],
            hover_color=self.app.colors["accent_hover"],
            width=150,
            height=45,
            corner_radius=10,
            command=apply_values
        )
        apply_btn.pack(side="right", padx=(10, 0))
        
        # Cancel button
        cancel_btn = ctk.CTkButton(
            buttons_frame,
            text="Cancel",
            font=("Segoe UI", 14),
            fg_color=self.app.colors["secondary"],
            hover_color=self.app.colors["secondary_hover"],
            width=120,
            height=45,
            corner_radius=10,
            command=cancel
        )
        cancel_btn.pack(side="right")
        
        # Focus on first textbox
        if placeholder_widgets:
            first_textbox = list(placeholder_widgets.values())[0]
            first_textbox.focus_set()
        
        # Wait for dialog to close
        dialog.wait_window()
        
        return result
    
    def apply_prompt_to_all_with_placeholders(self, prompt_template: str, placeholder_data: dict) -> int:
        """Apply prompt template with placeholder values to all pairs.
        
        Args:
            prompt_template: Prompt template with [PLACEHOLDER] markers
            placeholder_data: Dictionary with "values" (dict of placeholder->list) and "mode" (sequential/random)
            
        Returns:
            Number of pairs updated
        """
        # Extract values and mode
        if isinstance(placeholder_data, dict) and "values" in placeholder_data:
            placeholder_values = placeholder_data["values"]
            mode = placeholder_data.get("mode", "random")
        else:
            # Backward compatibility - old format
            placeholder_values = placeholder_data
            mode = "random"
        
        updated = 0
        
        # Initialize sequential counters for each placeholder
        sequential_counters = {placeholder: 0 for placeholder in placeholder_values.keys()}
        
        # Get all pairs first
        pairs_widgets = []
        for widget in self.pairs_container.winfo_children():
            if hasattr(widget, 'pair_data') and hasattr(widget, 'prompt_widget'):
                pairs_widgets.append(widget)
        
        for pair_idx, widget in enumerate(pairs_widgets):
            try:
                # Start with template
                prompt = prompt_template
                
                # Replace each placeholder
                for placeholder, values in placeholder_values.items():
                    if not values:
                        continue
                    
                    # Select value based on mode
                    if mode == "sequential":
                        # 1:1 sequential - cycle through values
                        idx = sequential_counters[placeholder] % len(values)
                        selected_value = values[idx]
                        sequential_counters[placeholder] += 1
                    else:
                        # Random mode
                        selected_value = random.choice(values)
                    
                    # Replace ALL occurrences of [PLACEHOLDER] with the selected value
                    # Use regex to ensure exact match (avoid partial matches like [NAME] in [NAME2])
                    # Escape special regex characters in placeholder name only
                    escaped_placeholder = re.escape(placeholder)
                    # Replace [PLACEHOLDER] pattern exactly (case-sensitive)
                    # selected_value should be inserted as-is (not escaped)
                    pattern = r'\[' + escaped_placeholder + r'\]'
                    prompt = re.sub(pattern, selected_value, prompt)
                
                # Update widget
                widget.prompt_widget.delete("1.0", "end")
                widget.prompt_widget.insert("1.0", prompt)
                widget.pair_data.prompt = prompt
                updated += 1
            except Exception as e:
                self.logger.error("Failed to apply placeholder prompt", error=str(e), pair_index=pair_idx)
                continue
        
        # Visual hint on status
        try:
            if updated > 0 and hasattr(self, 'progress_label'):
                mode_text = "1:1 sequential" if mode == "sequential" else "random"
                self.progress_label.configure(
                    text=f"Applied prompt with placeholders ({mode_text}) to {updated} pairs",
                    text_color=self.app.colors["success"]
                )
        except Exception:
            pass
        
        return updated

    def _apply_prompt_to_all_ui(self):
        """UI handler for applying prompt to all pairs with enhanced dialog and placeholder support."""
        if not self.pairs:
            messagebox.showinfo("No Pairs", "Please create at least one pair first.")
            return
        
        # Get prompt from first pair that has a prompt
        first_prompt = ""
        for widget in self.pairs_container.winfo_children():
            if hasattr(widget, 'pair_data') and hasattr(widget, 'prompt_widget'):
                try:
                    first_prompt = widget.prompt_widget.get("1.0", "end-1c").strip()
                    if first_prompt:
                        break
                except Exception:
                    continue
        
        # Create custom dialog window
        dialog = Toplevel(self.app)
        dialog.title("Apply Prompt to All")
        dialog.geometry("700x500")
        dialog.configure(bg=self.app.colors["bg"])
        dialog.transient(self.app)
        dialog.grab_set()
        
        # Center the dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (700 // 2)
        y = (dialog.winfo_screenheight() // 2) - (500 // 2)
        dialog.geometry(f"700x500+{x}+{y}")
        
        # Header
        header_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        header_frame.pack(pady=(25, 15), padx=25, fill="x")
        
        title_label = ctk.CTkLabel(
            header_frame,
            text="📋 Apply Prompt to All Pairs",
            font=("Segoe UI", 22, "bold"),
            text_color=self.app.colors["accent"]
        )
        title_label.pack()
        
        desc_label = ctk.CTkLabel(
            header_frame,
            text=f"Enter the prompt to apply to all {len(self.pairs)} pair(s). You can paste text here (Ctrl+V).\nUse [PLACEHOLDER] for variables that will be randomly assigned.",
            font=("Segoe UI", 13),
            text_color=self.app.colors["text_secondary"],
            wraplength=650,
            justify="left"
        )
        desc_label.pack(pady=(8, 0))
        
        # Text area with full clipboard support
        text_frame = ctk.CTkFrame(dialog, fg_color=self.app.colors["card"], corner_radius=12)
        text_frame.pack(fill="both", expand=True, padx=25, pady=(0, 15))
        
        prompt_textbox = ctk.CTkTextbox(
            text_frame,
            width=650,
            height=300,
            fg_color="#1A1A1A",
            text_color=self.app.colors["text"],
            corner_radius=10,
            border_width=1,
            border_color=self.app.colors["border"],
            font=("Segoe UI", 13),
            wrap="word"
        )
        prompt_textbox.pack(fill="both", expand=True, padx=15, pady=15)
        
        # Insert initial prompt if available
        if first_prompt:
            prompt_textbox.insert("1.0", first_prompt)
        
        # Setup full clipboard support
        setup_clipboard_support(prompt_textbox)
        
        # Focus on textbox
        prompt_textbox.focus_set()
        prompt_textbox.mark_set("insert", "1.0")
        
        # Buttons
        buttons_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        buttons_frame.pack(pady=(0, 25), padx=25, fill="x")
        
        def apply_prompt():
            prompt_text = prompt_textbox.get("1.0", "end-1c").strip()
            if not prompt_text:
                messagebox.showwarning("Empty Prompt", "Please enter a prompt to apply.")
                return
            
            # Detect placeholders in square brackets
            placeholders = re.findall(r'\[([^\]]+)\]', prompt_text)
            
            if placeholders:
                # Show dialog to enter values for each placeholder
                placeholder_data = self._show_placeholder_values_dialog(dialog, placeholders)
                if placeholder_data is None:
                    return  # User cancelled
                
                # Apply prompts with values for each pair (sequential or random)
                updated = self.apply_prompt_to_all_with_placeholders(prompt_text, placeholder_data)
            else:
                # No placeholders, apply same prompt to all
                updated = self.apply_prompt_to_all(prompt_text)
            
            dialog.destroy()
            if updated > 0:
                messagebox.showinfo("Success", f"✅ Applied prompt to {updated} pair(s)!")
        
        def cancel():
            dialog.destroy()
        
        # Apply button
        apply_btn = ctk.CTkButton(
            buttons_frame,
            text="✅ Apply to All",
            font=("Segoe UI", 16, "bold"),
            fg_color=self.app.colors["accent"],
            hover_color=self.app.colors["accent_hover"],
            width=180,
            height=45,
            corner_radius=10,
            command=apply_prompt
        )
        apply_btn.pack(side="right", padx=(10, 0))
        
        # Cancel button
        cancel_btn = ctk.CTkButton(
            buttons_frame,
            text="Cancel",
            font=("Segoe UI", 14),
            fg_color=self.app.colors["secondary"],
            hover_color=self.app.colors["secondary_hover"],
            width=120,
            height=45,
            corner_radius=10,
            command=cancel
        )
        cancel_btn.pack(side="right")
        
        # Bind Enter key to apply (Ctrl+Enter)
        def on_ctrl_enter(event):
            apply_prompt()
        
        prompt_textbox.bind("<Control-Return>", on_ctrl_enter)
        
        # Bind Escape to cancel
        def on_escape(event):
            cancel()
        
        dialog.bind("<Escape>", on_escape)

    def _add_folder(self):
        """Add a new folder to the pairing list (max 4 folders)."""
        if len(self._folders) >= 4:
            messagebox.showinfo("Limit reached", "Максимум 4 папки для пейрингу.")
            return
        
        initial_dir = self._folders[-1] if self._folders and self._folders[-1].exists() else self._last_dir
        directory = filedialog.askdirectory(
            title=f"Оберіть папку {len(self._folders) + 1}",
            initialdir=str(initial_dir)
        )
        if not directory:
            return

        path = Path(directory)
        if not path.exists() or not path.is_dir():
            messagebox.showerror("Неправильна папка", "Вибрана папка недоступна або не існує.")
            return

        if path in self._folders:
            messagebox.showwarning("Папка вже додана", "Ця папка вже є в списку.")
            return

        self._folders.append(path)
        self._last_dir = path
        images_found = self.image_service.glob_images(path)
        if not images_found:
            messagebox.showwarning(
                "Немає зображень",
                "У вибраній папці немає підтримуваних зображень."
            )

        self.logger.info("Added folder", path=str(path), total_folders=len(self._folders))
        self._load_images()
        self._update_directory_labels()

    def _remove_folder(self, index: int):
        """Remove a folder from the pairing list."""
        if index < 0 or index >= len(self._folders):
            return
        
        if len(self._folders) <= 1:
            messagebox.showinfo("Мінімум 1 папка", "Потрібна принаймні одна папка для пейрингу.")
            return
        
        removed_path = self._folders.pop(index)
        self.logger.info("Removed folder", path=str(removed_path), total_folders=len(self._folders))
        self._load_images()
        self._update_directory_labels()

    def _update_directory_labels(self):
        """Refresh directory labels with currently selected paths - modern design."""
        # Clear existing folder widgets
        if hasattr(self, "folders_container"):
            for widget in self.folders_container.winfo_children():
                widget.destroy()
        
        # Recreate folder widgets with modern card design
        if hasattr(self, "folders_container"):
            for idx, folder_path in enumerate(self._folders):
                # Card-style folder row
                folder_card = ctk.CTkFrame(
                    self.folders_container,
                    fg_color=self.app.colors["bg"],
                    corner_radius=10,
                    border_width=1,
                    border_color=self.app.colors["border"]
                )
                folder_card.pack(fill="x", pady=6)
                
                folder_content = ctk.CTkFrame(folder_card, fg_color="transparent")
                folder_content.pack(fill="x", padx=12, pady=10)
                
                # Folder number badge
                badge = ctk.CTkLabel(
                    folder_content,
                    text=f"{idx + 1}",
                    font=(self.app.font_family, 12, "bold"),
                    text_color="#FFFFFF",
                    fg_color=self.app.colors["accent"],
                    corner_radius=12,
                    width=28,
                    height=28
                )
                badge.pack(side="left", padx=(0, 10))
                
                # Folder path
                folder_label = ctk.CTkLabel(
                    folder_content,
                    text=self._format_directory(folder_path),
                    font=(self.app.font_family_secondary, 13),
                    text_color=self.app.colors["text"],
                    anchor="w",
                    wraplength=200
                )
                folder_label.pack(side="left", fill="x", expand=True, padx=(0, 10))
                
                # Remove button
                remove_btn = ctk.CTkButton(
                    folder_content,
                    text="✕",
                    font=(self.app.font_family, 14, "bold"),
                    fg_color="#E50914",
                    hover_color="#F40612",
                    width=32,
                    height=32,
                    corner_radius=16,
                    command=lambda i=idx: self._remove_folder(i)
                )
                remove_btn.pack(side="right")
                create_tooltip(remove_btn, f"Remove folder {idx + 1}")

    @staticmethod
    def _format_directory(directory: Path) -> str:
        """Format path for display, keeping the ending if too long."""
        try:
            resolved = directory.expanduser()
        except Exception:
            resolved = directory
        text = str(resolved)
        max_len = 50  # Shorter for sidebar
        if len(text) <= max_len:
            return text
        return "…" + text[-(max_len - 1):]

    def _setup_ui(self):
        """Setup pairing UI - completely redesigned for modern UX with tabs."""
        # ========== TOP HEADER BAR ==========
        top_bar = ctk.CTkFrame(self, fg_color=self.app.colors["card"], height=80, corner_radius=0)
        top_bar.pack(fill="x", padx=0, pady=0)
        top_bar.pack_propagate(False)
        
        # Left: Title and stats
        header_left = ctk.CTkFrame(top_bar, fg_color="transparent")
        header_left.pack(side="left", fill="x", expand=True, padx=30, pady=15)
        
        title_row = ctk.CTkFrame(header_left, fg_color="transparent")
        title_row.pack(fill="x")
        
        # Tab buttons
        self.tab_var = ctk.StringVar(value="sora")
        tabs_frame = ctk.CTkFrame(title_row, fg_color="transparent")
        tabs_frame.pack(side="left")
        
        generate_tab = ctk.CTkButton(
            tabs_frame,
            text="🚀 Generate All Pairs",
            font=(self.app.font_family, 16, "bold"),
            fg_color="transparent",
            hover_color=self.app.colors["card_hover"],
            text_color=self.app.colors["text"],
            width=200,
            height=40,
            corner_radius=10,
            command=lambda: self._switch_tab("generate")
        )
        generate_tab.pack(side="left", padx=(0, 10))
        
        sora_tab = ctk.CTkButton(
            tabs_frame,
            text="🎬 Sora",
            font=(self.app.font_family, 16, "bold"),
            fg_color=self.app.colors["accent"],
            hover_color=self.app.colors["accent_hover"],
            text_color="#FFFFFF",
            width=150,
            height=40,
            corner_radius=10,
            command=lambda: self._switch_tab("sora")
        )
        sora_tab.pack(side="left")
        
        self.tab_buttons = {"generate": generate_tab, "sora": sora_tab}
        
        # Stats badges inline
        stats_inline = ctk.CTkFrame(title_row, fg_color="transparent")
        stats_inline.pack(side="left", padx=(20, 0))
        
        self.pairs_count_label = ctk.CTkLabel(
            stats_inline,
            text="0 pairs",
            font=(self.app.font_family_secondary, 13),
            text_color=self.app.colors["text_secondary"]
        )
        self.pairs_count_label.pack(side="left", padx=(0, 10))
        
        self.enabled_badge = ctk.CTkLabel(
            stats_inline,
            text="✓ 0",
            font=(self.app.font_family_secondary, 11, "bold"),
            text_color="#FFFFFF",
            fg_color=self.app.colors["success"],
            corner_radius=10,
            width=45,
            height=24
        )
        self.enabled_badge.pack(side="left", padx=3)
        
        self.disabled_badge = ctk.CTkLabel(
            stats_inline,
            text="✗ 0",
            font=(self.app.font_family_secondary, 11, "bold"),
            text_color="#FFFFFF",
            fg_color="#666666",
            corner_radius=10,
            width=45,
            height=24
        )
        self.disabled_badge.pack(side="left", padx=3)
        
        # Right: Quick actions
        header_right = ctk.CTkFrame(top_bar, fg_color="transparent")
        header_right.pack(side="right", padx=30, pady=15)
        
        # Search bar
        search_container = ctk.CTkFrame(header_right, fg_color=self.app.colors["bg"], corner_radius=20)
        search_container.pack(side="left", padx=(0, 15))
        
        self.search_entry = ctk.CTkEntry(
            search_container,
            placeholder_text="🔍 Search pairs...",
            width=250,
            height=36,
            font=(self.app.font_family_secondary, 13),
            border_width=0,
            corner_radius=20
        )
        self.search_entry.pack(padx=12, pady=6)
        self.search_entry.bind("<KeyRelease>", lambda e: self._on_search_change())
        
        # Filter dropdown
        self.filter_var = ctk.StringVar(value="all")
        filter_menu = ctk.CTkOptionMenu(
            header_right,
            values=["All", "Enabled", "Disabled"],
            variable=self.filter_var,
            command=lambda v: self._on_filter_change(),
            width=100,
            height=36,
            font=(self.app.font_family_secondary, 12),
            corner_radius=18
        )
        filter_menu.pack(side="left", padx=(0, 10))
        
        # Store original pairs for filtering
        self._all_pairs: List[ImagePair] = []
        
        # ========== LEFT SIDEBAR - SETTINGS ==========
        sidebar = ctk.CTkFrame(self, fg_color=self.app.colors["card"], width=300, corner_radius=0)
        sidebar.pack(side="left", fill="y", padx=0, pady=0)
        sidebar.pack_propagate(False)
        
        # Sidebar content with minimal padding
        sidebar_content = ctk.CTkScrollableFrame(sidebar, fg_color="transparent")
        sidebar_content.pack(fill="both", expand=True, padx=15, pady=10)
        
        # Mode selector
        mode_section = ctk.CTkFrame(sidebar_content, fg_color="transparent")
        mode_section.pack(fill="x", pady=(0, 4))
        
        ctk.CTkLabel(
            mode_section,
            text="Pairing Mode",
            font=(self.app.font_family, 14, "bold"),
            text_color=self.app.colors["text"]
        ).pack(anchor="w", pady=(0, 6))
        
        self.mode_var = ctk.StringVar(value="sequential")
        mode_options = [
            ("1:1 Sequential", "sequential"),
            ("🎲 Random", "random"),
            ("✋ Manual", "manual")
        ]
        
        for mode_text, mode_value in mode_options:
            btn = ctk.CTkRadioButton(
                mode_section,
                text=mode_text,
                variable=self.mode_var,
                value=mode_value,
                font=(self.app.font_family_secondary, 12),
                command=self._on_mode_change
            )
            btn.pack(anchor="w", pady=2)
        
        # Separator - minimal
        separator1 = ctk.CTkFrame(sidebar_content, fg_color=self.app.colors["border"], height=1)
        separator1.pack(fill="x", pady=6)
        
        # Directory selectors
        dirs_section = ctk.CTkFrame(sidebar_content, fg_color="transparent")
        dirs_section.pack(fill="x", pady=(0, 4))
        
        dirs_header = ctk.CTkFrame(dirs_section, fg_color="transparent")
        dirs_header.pack(fill="x", pady=(0, 6))
        
        ctk.CTkLabel(
            dirs_header,
            text="Image Folders",
            font=(self.app.font_family, 14, "bold"),
            text_color=self.app.colors["text"]
        ).pack(side="left")
        
        add_folder_btn = ctk.CTkButton(
            dirs_header,
            text="➕",
            font=("Segoe UI", 16),
            fg_color=self.app.colors["accent"],
            hover_color=self.app.colors["accent_hover"],
            width=36,
            height=36,
            corner_radius=18,
            command=self._add_folder
        )
        add_folder_btn.pack(side="right")
        create_tooltip(add_folder_btn, "Add folder (max 4)")
        
        # Container for folder rows
        self.folders_container = ctk.CTkFrame(dirs_section, fg_color="transparent")
        self.folders_container.pack(fill="x")
        
        # Separator - minimal
        separator2 = ctk.CTkFrame(sidebar_content, fg_color=self.app.colors["border"], height=1)
        separator2.pack(fill="x", pady=6)
        
        # Quick actions
        actions_section = ctk.CTkFrame(sidebar_content, fg_color="transparent")
        actions_section.pack(fill="x", pady=(0, 4))
        
        ctk.CTkLabel(
            actions_section,
            text="Quick Actions",
            font=(self.app.font_family, 14, "bold"),
            text_color=self.app.colors["text"]
        ).pack(anchor="w", pady=(0, 6))
        
        # Action buttons in grid
        action_buttons = [
            ("📋 Apply Prompt", self._apply_prompt_to_all_ui, self.app.colors["secondary"]),
            ("✓ Select All", self._batch_enable_all, "#16a34a"),
            ("✗ Deselect All", self._batch_disable_all, "#E50914"),
            ("➕ Add Pair", self._add_empty_pair, self.app.colors["accent"]),
            ("✋ Manual", self._show_manual_pairing, "#9333EA"),
        ]
        
        for i, (text, command, color) in enumerate(action_buttons):
            btn = ctk.CTkButton(
                actions_section,
                text=text,
                font=(self.app.font_family_secondary, 12),
                fg_color=color,
                hover_color=color if color == self.app.colors["accent"] else None,
                height=34,
                corner_radius=8,
                command=command
            )
            btn.pack(fill="x", pady=1.5)
        
        # Separator - minimal
        separator3 = ctk.CTkFrame(sidebar_content, fg_color=self.app.colors["border"], height=1)
        separator3.pack(fill="x", pady=6)
        
        # File operations
        file_section = ctk.CTkFrame(sidebar_content, fg_color="transparent")
        file_section.pack(fill="x")
        
        ctk.CTkLabel(
            file_section,
            text="Templates & Files",
            font=(self.app.font_family, 14, "bold"),
            text_color=self.app.colors["text"]
        ).pack(anchor="w", pady=(0, 6))
        
        file_buttons = [
            ("💾 Save Template", self._save_as_template),
            ("📂 Load Template", self._load_template),
            ("📤 Export", self._export_pairs),
            ("📥 Import", self._import_pairs),
        ]
        
        for text, command in file_buttons:
            btn = ctk.CTkButton(
                file_section,
                text=text,
                font=(self.app.font_family_secondary, 12),
                fg_color=self.app.colors["secondary"],
                hover_color=self.app.colors["secondary_hover"],
                height=30,
                corner_radius=8,
                command=command
            )
            btn.pack(fill="x", pady=1.5)
        
        # ========== MAIN CONTENT AREA ==========
        main_content = ctk.CTkFrame(self, fg_color="transparent")
        main_content.pack(side="right", fill="both", expand=True, padx=0, pady=0)
        
        # Tab content containers
        self.tab_containers = {}
        
        # Generate All Pairs tab
        generate_container = ctk.CTkFrame(main_content, fg_color=self.app.colors["bg"])
        self.tab_containers["generate"] = generate_container
        
        # Sora tab (pairing)
        sora_container = ctk.CTkFrame(main_content, fg_color=self.app.colors["bg"])
        self.tab_containers["sora"] = sora_container
        
        # Scrollable pairs area for Sora tab - minimal padding
        scroll_frame = ctk.CTkScrollableFrame(
            sora_container,
            fg_color=self.app.colors["bg"],
            corner_radius=0,
            border_width=0
        )
        scroll_frame.pack(fill="both", expand=True, padx=5, pady=5)
        self.pairs_container = scroll_frame
        
        # Generate tab content (placeholder for now)
        generate_content = ctk.CTkFrame(generate_container, fg_color="transparent")
        generate_content.pack(expand=True, fill="both", padx=20, pady=20)
        
        generate_label = ctk.CTkLabel(
            generate_content,
            text="🚀 Generate All Pairs\n\nThis tab will show generation controls and progress.",
            font=(self.app.font_family, 18),
            text_color=self.app.colors["text_secondary"],
            justify="center"
        )
        generate_label.pack(expand=True)
        
        # Show initial tab
        self._switch_tab("sora")
        
        # ========== FIXED BOTTOM PANEL ==========
        bottom_panel = ctk.CTkFrame(main_content, fg_color=self.app.colors["card"], height=90, corner_radius=0)
        bottom_panel.pack(side="bottom", fill="x", padx=0, pady=0)
        bottom_panel.pack_propagate(False)
        
        # Main controls row
        controls_row = ctk.CTkFrame(bottom_panel, fg_color="transparent")
        controls_row.pack(fill="x", padx=30, pady=15)
        
        # Left: Generate button
        self.generate_btn = ctk.CTkButton(
            controls_row,
            text="🚀 GENERATE ALL PAIRS",
            font=(self.app.font_family, 20, "bold"),
            fg_color=self.app.colors["accent"],
            hover_color=self.app.colors["accent_hover"],
            width=280,
            height=60,
            corner_radius=16,
            command=self._on_generate
        )
        self.generate_btn.pack(side="left", padx=(0, 15))
        
        self.cancel_btn = ctk.CTkButton(
            controls_row,
            text="⏹ Cancel",
            font=(self.app.font_family, 16, "bold"),
            fg_color="#E50914",
            hover_color="#F40612",
            width=120,
            height=60,
            corner_radius=16,
            command=self._on_cancel,
            state="disabled"
        )
        self.cancel_btn.pack(side="left", padx=(0, 30))
        
        # Center: Progress info
        progress_section = ctk.CTkFrame(controls_row, fg_color="transparent")
        progress_section.pack(side="left", expand=True, fill="x", padx=20)
        
        self.progress_label = ctk.CTkLabel(
            progress_section,
            text="Ready",
            font=(self.app.font_family_secondary, 14, "bold"),
            text_color=self.app.colors["text"]
        )
        self.progress_label.pack(side="left", padx=(0, 15))
        
        self.task_counter = ctk.CTkLabel(
            progress_section,
            text="0 tasks",
            font=(self.app.font_family_secondary, 13),
            text_color=self.app.colors["text_secondary"]
        )
        self.task_counter.pack(side="left", padx=(0, 15))
        
        self.progress_bar = ctk.CTkProgressBar(
            progress_section,
            width=250,
            height=24,
            progress_color=self.app.colors["accent"],
            corner_radius=12,
            fg_color=self.app.colors["bg"]
        )
        self.progress_bar.pack(side="left")
        self.progress_bar.set(0)
        
        # Right: Undo/Redo
        undo_redo_section = ctk.CTkFrame(controls_row, fg_color="transparent")
        undo_redo_section.pack(side="right")
        
        undo_btn = ctk.CTkButton(
            undo_redo_section,
            text="↶ Undo",
            font=(self.app.font_family_secondary, 12),
            fg_color=self.app.colors["secondary"],
            hover_color=self.app.colors["secondary_hover"],
            width=80,
            height=40,
            corner_radius=10,
            command=self._undo
        )
        undo_btn.pack(side="left", padx=5)
        
        redo_btn = ctk.CTkButton(
            undo_redo_section,
            text="↷ Redo",
            font=(self.app.font_family_secondary, 12),
            fg_color=self.app.colors["secondary"],
            hover_color=self.app.colors["secondary_hover"],
            width=80,
            height=40,
            corner_radius=10,
            command=self._redo
        )
        redo_btn.pack(side="left", padx=5)

        self._update_directory_labels()
        
        # Setup keyboard shortcuts
        self._setup_keyboard_shortcuts()
    
    def _setup_keyboard_shortcuts(self):
        """Setup keyboard shortcuts for common operations.
        
        Note: Uses bind on the main app window since bind_all is not supported
        in CustomTkinter.
        """
        # Bind to main app window for global shortcuts
        # Ctrl+S: Save template
        self.app.bind("<Control-s>", lambda e: self._save_as_template())
        # Ctrl+O: Load template
        self.app.bind("<Control-o>", lambda e: self._load_template())
        # Ctrl+Z: Undo
        self.app.bind("<Control-z>", lambda e: self._undo())
        # Ctrl+Y: Redo
        self.app.bind("<Control-y>", lambda e: self._redo())
        # Ctrl+C: Cancel (when generation is running) - only if cancel button is enabled
        def handle_cancel(e):
            if hasattr(self, 'cancel_btn') and self.cancel_btn.cget("state") == "normal":
                self._on_cancel()
        self.app.bind("<Control-c>", handle_cancel)
        # Ctrl+A: Apply prompt to all (only when pairs exist and not in text widget)
        def handle_apply_all(e):
            # Check if focus is in a text widget (don't override Ctrl+A for text selection)
            try:
                focus_widget = self.app.focus_get()
                if focus_widget:
                    # Check if it's a text widget by checking widget class
                    widget_class = focus_widget.winfo_class()
                    if widget_class in ('Text', 'Entry'):
                        # Let text widget handle Ctrl+A for selection
                        return
            except Exception:
                pass
            if self.pairs:
                self._apply_prompt_to_all_ui()
                return "break"  # Prevent default behavior
        self.app.bind("<Control-a>", handle_apply_all)
        # Ctrl+F: Focus search
        def handle_search_focus(e):
            if hasattr(self, 'search_entry'):
                self.search_entry.focus_set()
                return "break"  # Prevent default behavior
        self.app.bind("<Control-f>", handle_search_focus)
        # Escape: Close dialogs or clear search
        self.app.bind("<Escape>", lambda e: self._handle_escape())
        # Ctrl+E: Enable all pairs
        self.app.bind("<Control-e>", lambda e: self._batch_enable_all())
        # Ctrl+D: Disable all pairs
        self.app.bind("<Control-d>", lambda e: self._batch_disable_all())
        # Ctrl+T: Toggle all pairs
        self.app.bind("<Control-t>", lambda e: self._batch_toggle_all())
    
    def _handle_escape(self):
        """Handle Escape key press - close any open dialogs or clear search."""
        # Close any open dialogs
        for widget in self.app.winfo_children():
            if isinstance(widget, Toplevel):
                widget.destroy()
                return
        
        # Clear search if focused
        if hasattr(self, 'search_entry') and self.search_entry.focus_get() == self.search_entry:
            self.search_entry.delete(0, "end")
            self._on_search_change()

    def _load_images(self):
        """Load available images from all folders."""
        self.folder_images = []
        for folder in self._folders:
            images = self.image_service.glob_images(folder)
            self.folder_images.append(images)
        self._update_directory_labels()
        self._refresh_pairs()
    
    def _switch_tab(self, tab_name: str):
        """Switch between tabs (generate/sora)."""
        self.tab_var.set(tab_name)
        
        # Update tab button styles
        for name, btn in self.tab_buttons.items():
            if name == tab_name:
                btn.configure(
                    fg_color=self.app.colors["accent"],
                    text_color="#FFFFFF"
                )
            else:
                btn.configure(
                    fg_color="transparent",
                    text_color=self.app.colors["text"]
                )
        
        # Show/hide tab containers
        for name, container in self.tab_containers.items():
            if name == tab_name:
                container.pack(fill="both", expand=True)
            else:
                container.pack_forget()
    
    def _on_mode_change(self):
        """Handle pairing mode change."""
        self._save_state_for_undo()
        mode_str = self.mode_var.get()
        if mode_str == "sequential":
            self.pairing_mode = PairingMode.SEQUENTIAL
        elif mode_str == "random":
            self.pairing_mode = PairingMode.RANDOM
        else:
            self.pairing_mode = PairingMode.MANUAL
        
        self._refresh_pairs()
    
    def _on_search_change(self):
        """Handle search text change."""
        self._refresh_pairs()
    
    def _on_filter_change(self):
        """Handle filter change."""
        self._refresh_pairs()
    
    def _refresh_pairs(self):
        """Refresh pairs display with search and filter applied."""
        # Store all pairs before filtering
        # Don't regenerate if we're loading a template or if we're in manual mode with existing pairs
        if not hasattr(self, '_is_loading_template'):
            self._is_loading_template = False
        
        if not self._is_loading_template and (not hasattr(self, '_all_pairs') or self.pairing_mode != PairingMode.MANUAL):
            # Generate pairs based on mode
            self._generate_pairs_by_mode()
        
        # Apply search and filter
        filtered_pairs = self._apply_filters(self._all_pairs)
        
        # Clear container
        for widget in self.pairs_container.winfo_children():
            widget.destroy()
        
        # Update pairs to filtered list for display
        self.pairs = filtered_pairs
        
        # Update pairs count and statistics
        if hasattr(self, 'pairs_count_label'):
            enabled_count = sum(1 for p in filtered_pairs if p.enabled)
            disabled_count = len(filtered_pairs) - enabled_count
            total_count = len(self._all_pairs)
            filtered_count = len(filtered_pairs)
            
            if filtered_count < total_count:
                self.pairs_count_label.configure(
                    text=f"{filtered_count}/{total_count} pairs"
                )
            else:
                self.pairs_count_label.configure(
                    text=f"{total_count} pairs"
                )
            
            # Update badges
            if hasattr(self, 'enabled_badge'):
                self.enabled_badge.configure(text=f"✓ {enabled_count}")
            if hasattr(self, 'disabled_badge'):
                self.disabled_badge.configure(text=f"✗ {disabled_count}")
        
        # Display pairs
        if not filtered_pairs:
            # Empty state
            empty_frame = ctk.CTkFrame(self.pairs_container, fg_color="transparent")
            empty_frame.pack(expand=True, pady=50)
            
            empty_icon = ctk.CTkLabel(
                empty_frame,
                text="🖼️",
                font=("Segoe UI", 48),
                text_color=self.app.colors["text_muted"]
            )
            empty_icon.pack()
            
            if hasattr(self, 'search_entry') and self.search_entry.get().strip():
                empty_label = ctk.CTkLabel(
                    empty_frame,
                    text="No pairs match your search",
                    font=("Segoe UI", 18, "bold"),
                    text_color=self.app.colors["text_secondary"]
                )
                empty_label.pack(pady=(10, 5))
            else:
                empty_label = ctk.CTkLabel(
                    empty_frame,
                    text="No pairs yet",
                    font=("Segoe UI", 18, "bold"),
                    text_color=self.app.colors["text_secondary"]
                )
                empty_label.pack(pady=(10, 5))
                
                hint_label = ctk.CTkLabel(
                    empty_frame,
                    text="Select a pairing mode or use Manual Pairing to create pairs",
                    font=("Segoe UI", 13),
                    text_color=self.app.colors["text_muted"]
                )
                hint_label.pack()
        else:
            # Optimized: Batch create widgets with staggered rendering for better performance
            def create_pairs_batch(start_idx=0, batch_size=15):
                """Create pairs in batches to avoid UI freezing."""
                end_idx = min(start_idx + batch_size, len(filtered_pairs))
                for idx in range(start_idx, end_idx):
                    self._create_pair_widget(idx, filtered_pairs[idx])
                
                # Schedule next batch if there are more pairs
                if end_idx < len(filtered_pairs):
                    self.after(10, lambda: create_pairs_batch(end_idx, batch_size))
            
            # Start batch creation for better performance
            if len(filtered_pairs) > 20:
                create_pairs_batch(0, 15)  # Create 15 pairs at a time for large lists
            else:
                # For small lists, create all at once
                for idx, pair in enumerate(filtered_pairs):
                    self._create_pair_widget(idx, pair)
    
    def _generate_pairs_by_mode(self):
        """Generate pairs based on current mode."""
        if self.pairing_mode == PairingMode.SEQUENTIAL:
            if not self.folder_images or not any(self.folder_images):
                self._all_pairs = []
            else:
                # Get the maximum length across all folders
                max_len = max(len(images) for images in self.folder_images) if self.folder_images else 0
                self._all_pairs = []
                for i in range(max_len):
                    pair_images = []
                    for folder_imgs in self.folder_images:
                        if i < len(folder_imgs):
                            pair_images.append(folder_imgs[i])
                    if pair_images:  # Only create pair if at least one image
                        self._all_pairs.append(ImagePair(images=pair_images, prompt="", enabled=True))
        elif self.pairing_mode == PairingMode.RANDOM:
            import random
            if not self.folder_images or not any(self.folder_images):
                self._all_pairs = []
            else:
                # Get the maximum length across all folders
                max_len = max(len(images) for images in self.folder_images) if self.folder_images else 0
                # Shuffle each folder's images
                shuffled_folders = []
                for folder_imgs in self.folder_images:
                    shuffled = folder_imgs[:]
                    random.shuffle(shuffled)
                    shuffled_folders.append(shuffled)
                
                self._all_pairs = []
                for i in range(max_len):
                    pair_images = []
                    for shuffled_imgs in shuffled_folders:
                        if i < len(shuffled_imgs):
                            pair_images.append(shuffled_imgs[i])
                    if pair_images:  # Only create pair if at least one image
                        self._all_pairs.append(ImagePair(images=pair_images, prompt="", enabled=True))
        else:
            # Manual mode: keep existing pairs
            self._all_pairs = self.pairs.copy() if self.pairs else []
    
    def _apply_filters(self, pairs: List[ImagePair]) -> List[ImagePair]:
        """Apply search and filter to pairs.
        
        Args:
            pairs: List of pairs to filter
            
        Returns:
            Filtered list of pairs
        """
        filtered = pairs
        
        # Apply search filter
        if hasattr(self, 'search_entry'):
            search_text = self.search_entry.get().strip().lower()
            if search_text:
                filtered = []
                for pair in pairs:
                    # Search in image names
                    image_names = " ".join([img.stem.lower() for img in pair.images])
                    # Search in prompt
                    prompt_text = pair.prompt.lower()
                    if search_text in image_names or search_text in prompt_text:
                        filtered.append(pair)
        
        # Apply enabled/disabled filter
        if hasattr(self, 'filter_var'):
            filter_value = self.filter_var.get()
            if filter_value == "enabled":
                filtered = [p for p in filtered if p.enabled]
            elif filter_value == "disabled":
                filtered = [p for p in filtered if not p.enabled]
        
        return filtered
    
    def _save_state_for_undo(self):
        """Save current state for undo."""
        # Deep copy pairs
        import copy
        state = copy.deepcopy(self.pairs)
        self._undo_stack.append(state)
        # Clear redo stack when new action
        self._redo_stack.clear()
        # Limit undo stack size
        if len(self._undo_stack) > 20:
            self._undo_stack.pop(0)
        
        # Auto-save state
        if self._auto_save_enabled:
            self._save_autosave()
    
    def _save_autosave(self):
        """Auto-save current state to file."""
        try:
            # Sync prompts from UI before saving
            pairs_to_save = []
            for widget in getattr(self, "pairs_container", []).winfo_children():
                if hasattr(widget, 'pair_data') and hasattr(widget, 'prompt_widget'):
                    pair = widget.pair_data
                    try:
                        prompt = widget.prompt_widget.get("1.0", "end-1c").strip()
                        pair.prompt = prompt
                    except Exception:
                        pass
                    pairs_to_save.append(pair)
            
            if not pairs_to_save:
                pairs_to_save = self.pairs
            
            autosave_data = {
                "version": "1.0",
                "pairing_mode": self.pairing_mode.value if hasattr(self.pairing_mode, 'value') else str(self.pairing_mode),
                "pairs": []
            }
            
            for pair in pairs_to_save:
                pair_data = {
                    "images": [str(img) for img in pair.images],
                    "prompt": pair.prompt,
                    "enabled": pair.enabled
                }
                autosave_data["pairs"].append(pair_data)
            
            self._auto_save_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._auto_save_file, 'w', encoding='utf-8') as f:
                json.dump(autosave_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logger.warning("Failed to auto-save", error=str(e))
    
    def _load_autosave(self):
        """Load auto-saved state if available."""
        if not self._auto_save_file.exists():
            return
        
        try:
            with open(self._auto_save_file, 'r', encoding='utf-8') as f:
                autosave_data = json.load(f)
            
            if not isinstance(autosave_data, dict) or "pairs" not in autosave_data:
                return
            
            # Ask user if they want to restore
            if not messagebox.askyesno(
                "Auto-save Found",
                "An auto-saved state was found.\n\n"
                "Would you like to restore it?",
                icon="question"
            ):
                return
            
            imported_pairs = []
            for pair_data in autosave_data["pairs"]:
                try:
                    if "images" not in pair_data or not isinstance(pair_data["images"], list):
                        continue
                    
                    image_paths = []
                    for img_path_str in pair_data["images"]:
                        img_path = Path(img_path_str)
                        is_valid, error = self.image_service.validate_image(img_path)
                        if is_valid:
                            image_paths.append(img_path)
                    
                    if not image_paths:
                        continue
                    
                    pair = ImagePair(
                        images=image_paths,
                        prompt=pair_data.get("prompt", ""),
                        enabled=pair_data.get("enabled", True)
                    )
                    imported_pairs.append(pair)
                except Exception:
                    continue
            
            if imported_pairs:
                self.pairs = imported_pairs
                self._all_pairs = imported_pairs.copy()
                
                # Set mode if specified
                if "pairing_mode" in autosave_data:
                    mode_str = autosave_data["pairing_mode"]
                    if mode_str == "sequential":
                        self.mode_var.set("sequential")
                        self.pairing_mode = PairingMode.SEQUENTIAL
                    elif mode_str == "random":
                        self.mode_var.set("random")
                        self.pairing_mode = PairingMode.RANDOM
                    else:
                        self.mode_var.set("manual")
                        self.pairing_mode = PairingMode.MANUAL
                
                self._refresh_pairs()
                messagebox.showinfo("Restored", f"✅ Restored {len(imported_pairs)} pair(s) from auto-save!")
        except Exception as e:
            self.logger.warning("Failed to load auto-save", error=str(e))
    
    def _undo(self):
        """Undo last action."""
        if not self._undo_stack:
            return
        
        # Save current state to redo
        import copy
        self._redo_stack.append(copy.deepcopy(self.pairs))
        
        # Restore previous state
        self.pairs = self._undo_stack.pop()
        self._refresh_pairs()
    
    def _redo(self):
        """Redo last undone action."""
        if not self._redo_stack:
            return
        
        # Save current state to undo
        import copy
        self._undo_stack.append(copy.deepcopy(self.pairs))
        
        # Restore redo state
        self.pairs = self._redo_stack.pop()
        self._refresh_pairs()
    
    def _batch_enable_all(self):
        """Enable all pairs."""
        if not self.pairs:
            return
        self._save_state_for_undo()
        for pair in self.pairs:
            pair.enabled = True
        # Update UI checkboxes
        for widget in self.pairs_container.winfo_children():
            if hasattr(widget, 'pair_data'):
                for child in widget.winfo_children():
                    if isinstance(child, ctk.CTkCheckBox):
                        child.select()
        self._refresh_pairs()
        if hasattr(self, 'progress_label'):
            self.progress_label.configure(
                text=f"✅ Enabled all {len(self.pairs)} pair(s)",
                text_color=self.app.colors["success"]
            )
            self.after(2000, lambda: self.progress_label.configure(
                text="Ready",
                text_color=self.app.colors["text_secondary"]
            ))
    
    def _batch_disable_all(self):
        """Disable all pairs."""
        if not self.pairs:
            return
        self._save_state_for_undo()
        for pair in self.pairs:
            pair.enabled = False
        # Update UI checkboxes
        for widget in self.pairs_container.winfo_children():
            if hasattr(widget, 'pair_data'):
                for child in widget.winfo_children():
                    if isinstance(child, ctk.CTkCheckBox):
                        child.deselect()
        self._refresh_pairs()
        if hasattr(self, 'progress_label'):
            self.progress_label.configure(
                text=f"✗ Disabled all {len(self.pairs)} pair(s)",
                text_color=self.app.colors["warning"]
            )
            self.after(2000, lambda: self.progress_label.configure(
                text="Ready",
                text_color=self.app.colors["text_secondary"]
            ))
    
    def _batch_toggle_all(self):
        """Toggle all pairs (enable disabled, disable enabled)."""
        if not self.pairs:
            return
        self._save_state_for_undo()
        # Count enabled pairs
        enabled_count = sum(1 for p in self.pairs if p.enabled)
        # If more than half are enabled, disable all; otherwise enable all
        if enabled_count > len(self.pairs) / 2:
            for pair in self.pairs:
                pair.enabled = False
            action = "disabled"
        else:
            for pair in self.pairs:
                pair.enabled = True
            action = "enabled"
        # Update UI checkboxes
        for widget in self.pairs_container.winfo_children():
            if hasattr(widget, 'pair_data'):
                for child in widget.winfo_children():
                    if isinstance(child, ctk.CTkCheckBox):
                        if action == "enabled":
                            child.select()
                        else:
                            child.deselect()
        self._refresh_pairs()
        if hasattr(self, 'progress_label'):
            self.progress_label.configure(
                text=f"🔄 Toggled all pairs ({action})",
                text_color=self.app.colors["accent"]
            )
            self.after(2000, lambda: self.progress_label.configure(
                text="Ready",
                text_color=self.app.colors["text_secondary"]
            ))

    def _reset_pair_statuses(self):
        """Clear status flags for all pairs."""
        for pair in self.pairs:
            pair.last_status = None

    def _get_pair_status_style(self, status: Optional[str]) -> tuple[str, str, str, str]:
        """Return border color, label text, text color, and badge bg for a status."""
        border_default = self.app.colors["border"]
        success_color = "#16a34a"  # Green for success
        warning_color = self.app.colors.get("warning", "#f59e0b")
        accent_color = self.app.colors.get("accent", "#4A90E2")
        danger_color = "#dc2626"  # Red for failed - more visible

        mapping = {
            None: (border_default, "", self.app.colors["text_secondary"], "transparent"),
            "queued": (accent_color, "Queued", accent_color, "#141f2c"),
            "running": (accent_color, "Running…", accent_color, "#141f2c"),
            "success": (success_color, "Completed", success_color, "#10251b"),
            "failed": (danger_color, "Failed", danger_color, "#2b0f14"),
            "cancelled": (warning_color, "Cancelled", warning_color, "#2a2113"),
        }
        return mapping.get(status, mapping[None])

    def _mark_pair_status(self, pair_index: Optional[int], status: Optional[str]):
        """Update stored status and refresh the UI styling for a pair."""
        if pair_index is None or pair_index < 0 or pair_index >= len(self.pairs):
            return
        pair = self.pairs[pair_index]
        pair.last_status = status
        self._refresh_pair_visual(pair)

    def _refresh_pair_visual(self, pair: ImagePair):
        """Apply border/status badge colors for a pair if the widget exists."""
        if not hasattr(self, "pairs_container"):
            return
        border_color, status_text, text_color, badge_bg = self._get_pair_status_style(pair.last_status)
        # Use thicker border for success/failed to make it more visible
        border_width = 3 if pair.last_status in ("success", "failed") else 1
        for widget in self.pairs_container.winfo_children():
            if getattr(widget, "pair_data", None) is pair:
                try:
                    widget.configure(border_color=border_color, border_width=border_width)
                except Exception:
                    pass
                status_label = getattr(widget, "status_label", None)
                if status_label:
                    if status_text:
                        status_label.configure(
                            text=status_text,
                            text_color=text_color,
                            fg_color=badge_bg
                        )
                    else:
                        status_label.configure(
                            text="",
                            text_color=self.app.colors["text_secondary"],
                            fg_color="transparent"
                        )
                break

    def _build_pair_title(self, pair: ImagePair) -> str:
        """Compose a friendly label for a pair using character/cake names."""
        try:
            return build_pair_label(pair.images)
        except Exception:
            fallback = " + ".join(img.stem for img in pair.images[:2] if img)
            return fallback or "Untitled Pair"
    
    def _create_pair_widget(self, idx: int, pair: ImagePair):
        """Create UI widget for a pair."""
        border_color, status_text, status_fg, badge_bg = self._get_pair_status_style(pair.last_status)
        # Use thicker border for success/failed to make it more visible
        border_width = 3 if pair.last_status in ("success", "failed") else 1
        pair_frame = ctk.CTkFrame(
            self.pairs_container,
            fg_color=self.app.colors["card"],
            corner_radius=12,
            border_width=border_width,
            border_color=border_color
        )
        pair_frame.pack(fill="x", padx=8, pady=6)
        
        # Add enhanced hover effect
        def make_pair_hover(f):
            def on_enter(e):
                f.configure(
                    fg_color=self.app.colors["card_hover"],
                    border_color=self.app.colors["border_light"]
                )
            def on_leave(e):
                f.configure(
                    fg_color=self.app.colors["card"],
                    border_color=self.app.colors["border"]
                )
            f.bind("<Enter>", on_enter)
            f.bind("<Leave>", on_leave)
        
        make_pair_hover(pair_frame)

        # Header with pair title + status badge
        header_frame = ctk.CTkFrame(pair_frame, fg_color="transparent")
        header_frame.pack(fill="x", padx=18, pady=(12, 0))

        title_label = ctk.CTkLabel(
            header_frame,
            text=self._build_pair_title(pair),
            font=("Segoe UI", 16, "bold"),
            text_color=self.app.colors["text"],
            anchor="w"
        )
        title_label.pack(side="left", expand=True)

        status_label = ctk.CTkLabel(
            header_frame,
            text=status_text,
            font=("Segoe UI", 12, "bold"),
            text_color=status_fg,
            fg_color=badge_bg,
            corner_radius=999,
            padx=10,
            pady=4
        )
        status_label.pack(side="right")

        # Main content row
        content_frame = ctk.CTkFrame(pair_frame, fg_color="transparent")
        content_frame.pack(fill="x", padx=10, pady=8)
        
        # Checkbox
        enabled_var = ctk.BooleanVar(value=pair.enabled)
        checkbox = ctk.CTkCheckBox(
            content_frame,
            text="",
            variable=enabled_var,
            command=lambda i=idx, v=enabled_var: self._toggle_pair(i, v)
        )
        checkbox.pack(side="left", padx=10)
        create_tooltip(checkbox, "Enable/disable this pair for generation")
        
        # Image previews
        for img_path in pair.images[:4]:  # Max 4 images
            self._create_image_preview(content_frame, img_path, pair_index=idx)

        # Refs badge if more than 2 images
        if len(pair.images) > 2:
            refs_badge = ctk.CTkLabel(
                content_frame,
                text=f"+{len(pair.images) - 2} refs",
                font=("Segoe UI", 12, "bold"),
                text_color="#FFFFFF",
                fg_color=self.app.colors["accent"],
                corner_radius=10
            )
            refs_badge.pack(side="left", padx=6)
        
        # Reference controls (add up to 4 images total)
        controls_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
        controls_frame.pack(side="left", padx=8)

        add_refs_btn = ctk.CTkButton(
            controls_frame,
            text="➕ Add refs",
            font=("Segoe UI", 12),
            fg_color=self.app.colors["secondary"],
            hover_color=self.app.colors["secondary_hover"],
            command=lambda i=idx: self._add_refs_to_pair(i)
        )
        add_refs_btn.pack(pady=4, padx=2)
        create_tooltip(add_refs_btn, f"Add reference images (up to 4 total)\nCurrent: {len(pair.images)}/4")

        clear_refs_btn = ctk.CTkButton(
            controls_frame,
            text="🧹 Clear refs",
            font=("Segoe UI", 12),
            fg_color="#444444",
            hover_color="#555555",
            command=lambda i=idx: self._clear_refs_from_pair(i)
        )
        clear_refs_btn.pack(pady=4, padx=2)
        create_tooltip(clear_refs_btn, "Remove all reference images\n(keeps first 2 images)")

        # Drag-and-drop dropzone to add refs (if TkinterDnD2 available)
        try:
            from tkinterdnd2 import DND_FILES  # type: ignore
            drop_zone = ctk.CTkFrame(
                content_frame,
                fg_color="#222222",
                width=140,
                height=70,
                corner_radius=8,
                border_width=1,
                border_color=self.app.colors["border"]
            )
            drop_zone.pack(side="left", padx=8)
            drop_zone.pack_propagate(False)

            dz_label = ctk.CTkLabel(
                drop_zone,
                text="Drop refs\nhere",
                font=("Segoe UI", 12),
                text_color=self.app.colors["text_secondary"]
            )
            dz_label.pack(expand=True)
            create_tooltip(drop_zone, "Drop 1-2 images to add as refs")

            def on_drop(event, i=idx):
                data = (event.data or "").strip()
                if not data:
                    return
                candidates = [Path(p.strip("{}")) for p in data.split()]
                remaining = max(0, 4 - len(self.pairs[i].images))
                if remaining <= 0:
                    messagebox.showinfo("Limit reached", "This pair already has 4 images.")
                    return
                to_add: list[Path] = []
                invalid: list[str] = []
                for p in candidates[:remaining]:
                    ok, err = self.image_service.validate_image(p)
                    if ok:
                        to_add.append(p)
                    else:
                        invalid.append(f"{p.name}: {err}")
                if invalid:
                    msg = "Some files were invalid:\n\n" + "\n".join(invalid[:5])
                    if len(invalid) > 5:
                        msg += f"\n... and {len(invalid) - 5} more"
                    messagebox.showwarning("Invalid Files", msg)
                if not to_add:
                    return
                self._save_state_for_undo()
                self.mode_var.set("manual")
                self.pairing_mode = PairingMode.MANUAL
                self.pairs[i].images.extend(to_add)
                try:
                    self._last_dir = to_add[-1].parent
                except Exception:
                    pass
                self._refresh_pairs()

            drop_zone.drop_target_register(DND_FILES)
            drop_zone.dnd_bind('<<Drop>>', on_drop)
        except Exception:
            pass

        # Prompt field with better styling
        prompt_entry = ctk.CTkTextbox(
            pair_frame,
            width=460,
            height=75,
            fg_color="#1A1A1A",
            text_color=self.app.colors["text"],
            corner_radius=10,
            border_width=1,
            border_color=self.app.colors["border"],
            font=("Segoe UI", 13)
        )
        prompt_entry.insert("1.0", pair.prompt)
        prompt_entry.pack(fill="x", padx=15, pady=(0, 12))
        # Setup full clipboard support (Ctrl+V, Ctrl+C, Ctrl+X, right-click menu)
        setup_clipboard_support(prompt_entry)
        
        # Sync prompt changes back to pair_data
        def sync_prompt(event=None):
            try:
                prompt_text = prompt_entry.get("1.0", "end-1c").strip()
                pair.prompt = prompt_text
            except Exception:
                pass
        
        # Bind to text changes (on key release and focus out)
        prompt_entry.bind("<KeyRelease>", sync_prompt)
        prompt_entry.bind("<FocusOut>", sync_prompt)
        
        # Context menu for pair frame (right-click)
        try:
            import tkinter as tk
            pair_menu = tk.Menu(pair_frame, tearoff=0)
            
            # Copy prompt
            pair_menu.add_command(
                label="📋 Copy Prompt",
                command=lambda p=pair.prompt: self._copy_to_clipboard(p)
            )
            
            # Copy prompt to all
            pair_menu.add_command(
                label="📋 Copy Prompt to All",
                command=lambda p=pair.prompt: self._copy_prompt_to_all(p)
            )
            
            pair_menu.add_separator()
            
            # Enable/Disable
            if pair.enabled:
                pair_menu.add_command(
                    label="✗ Disable",
                    command=lambda i=idx: self._toggle_pair_direct(i, False)
                )
            else:
                pair_menu.add_command(
                    label="✓ Enable",
                    command=lambda i=idx: self._toggle_pair_direct(i, True)
                )
            
            pair_menu.add_separator()
            
            # Duplicate pair
            pair_menu.add_command(
                label="📋 Duplicate",
                command=lambda i=idx: self._duplicate_pair(i)
            )
            
            # Delete pair
            pair_menu.add_command(
                label="🗑️ Delete",
                command=lambda i=idx: self._delete_pair(i)
            )
            
            def show_pair_menu(event):
                try:
                    pair_menu.tk_popup(event.x_root, event.y_root)
                finally:
                    pair_menu.grab_release()
            
            pair_frame.bind("<Button-3>", show_pair_menu)
        except Exception:
            pass
        
        # Store reference
        pair_frame.pair_data = pair
        pair_frame.prompt_widget = prompt_entry
        pair_frame.status_label = status_label
    
    def _add_refs_to_pair(self, idx: int):
        """Append up to 4 total images to a pair via file dialog."""
        if idx >= len(self.pairs):
            return
        pair = self.pairs[idx]
        remaining = max(0, 4 - len(pair.images))
        if remaining == 0:
            messagebox.showinfo("Limit reached", "This pair already has 4 images.")
            return
        filetypes = [("Images", "*.png *.jpg *.jpeg *.webp"), ("All Files", "*.*")]
        selected = filedialog.askopenfilenames(
            title=f"Select up to {remaining} reference image(s)",
            initialdir=str(self._last_dir),
            filetypes=filetypes
        )
        if not selected:
            return
        
        # Validate images before adding
        to_add = []
        invalid_files = []
        for p in selected[:remaining]:
            path = Path(p)
            is_valid, error = self.image_service.validate_image(path)
            if is_valid:
                to_add.append(path)
            else:
                invalid_files.append(f"{path.name}: {error}")
        
        if invalid_files:
            error_msg = "Some files were invalid:\n\n" + "\n".join(invalid_files[:5])
            if len(invalid_files) > 5:
                error_msg += f"\n... and {len(invalid_files) - 5} more"
            messagebox.showwarning("Invalid Files", error_msg)
        
        if not to_add:
            return
        
        self._save_state_for_undo()
        # Switch to manual mode so refs are preserved on refresh
        self.mode_var.set("manual")
        self.pairing_mode = PairingMode.MANUAL
        pair.images.extend(to_add)
        # Update last dir
        try:
            self._last_dir = to_add[-1].parent
        except Exception:
            pass
        self._refresh_pairs()
    
    def _clear_refs_from_pair(self, idx: int):
        """Keep the first two images (if present) and clear additional refs beyond 2."""
        if idx >= len(self.pairs):
            return
        pair = self.pairs[idx]
        if len(pair.images) <= 2:
            # Nothing extra to clear
            messagebox.showinfo("No refs to clear", "This pair has no additional reference images to clear.")
            return
        
        # Ask for confirmation
        if not messagebox.askyesno(
            "Clear Reference Images",
            f"Remove {len(pair.images) - 2} reference image(s)?\nThe first 2 images will be kept.",
            icon="question"
        ):
            return
        
        self._save_state_for_undo()
        # Switch to manual mode so changes persist
        self.mode_var.set("manual")
        self.pairing_mode = PairingMode.MANUAL
        pair.images = pair.images[:2]
        self._refresh_pairs()

    def _remove_image_from_pair(self, idx: int, image_path: Path):
        """Remove a specific image from a pair."""
        if idx >= len(self.pairs):
            return
        pair = self.pairs[idx]
        if image_path not in pair.images:
            return
        
        # Prevent removing the last image (at least 1 image required)
        if len(pair.images) <= 1:
            messagebox.showwarning(
                "Cannot Remove",
                "A pair must have at least 1 image. Cannot remove the last image.",
                icon="warning"
            )
            return
        
        self._save_state_for_undo()
        self.mode_var.set("manual")
        self.pairing_mode = PairingMode.MANUAL
        pair.images = [p for p in pair.images if p != image_path]
        self._refresh_pairs()

    def _replace_image_in_pair(self, idx: int, image_path: Path):
        """Replace a specific image in a pair via file dialog."""
        if idx >= len(self.pairs):
            return
        pair = self.pairs[idx]
        if image_path not in pair.images:
            return
        filetypes = [("Images", "*.png *.jpg *.jpeg *.webp"), ("All Files", "*.*")]
        new_path = filedialog.askopenfilename(
            title="Select replacement image",
            initialdir=str(image_path.parent if image_path.parent.exists() else self._last_dir),
            filetypes=filetypes
        )
        if not new_path:
            return
        self._replace_image_in_pair_with_path(idx, image_path, Path(new_path))

    def _replace_image_in_pair_with_path(self, idx: int, old_path: Path, new_path: Path):
        """Replace image using an explicit new path (used by DnD or dialog)."""
        if idx >= len(self.pairs):
            return
        if new_path.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'}:
            messagebox.showwarning("Unsupported", "Please choose a PNG/JPG/JPEG/WEBP image.")
            return
        pair = self.pairs[idx]
        if old_path not in pair.images:
            return
        self._save_state_for_undo()
        self.mode_var.set("manual")
        self.pairing_mode = PairingMode.MANUAL
        pair.images = [new_path if p == old_path else p for p in pair.images]
        try:
            self._last_dir = new_path.parent
        except Exception:
            pass
        self._refresh_pairs()
    
    def _create_image_preview(self, parent, img_path: Path, pair_index: int):
        """Create image preview widget with better styling and context actions.
        If TkinterDnD is available, allow dropping a file to replace this image.
        """
        try:
            from PIL import Image
            from customtkinter import CTkImage
            
            # Create a frame for the image with border - make it slightly larger to fit delete button
            img_frame = ctk.CTkFrame(
                parent,
                fg_color="transparent",
                width=85,
                height=85
            )
            img_frame.pack(side="left", padx=8)
            img_frame.pack_propagate(False)
            
            # Check if image exists
            if not img_path.exists():
                # Show placeholder for missing image
                placeholder_label = ctk.CTkLabel(
                    img_frame,
                    text="❌\nMissing",
                    font=("Segoe UI", 10),
                    text_color=self.app.colors["text_secondary"],
                    width=75,
                    height=75,
                    corner_radius=8
                )
                placeholder_label.pack(padx=3, pady=3)
                create_tooltip(placeholder_label, f"Image not found:\n{img_path}")
                return
            
            pil_img = Image.open(img_path).resize((75, 75), Image.LANCZOS)
            ctk_img = CTkImage(light_image=pil_img, dark_image=pil_img, size=(75, 75))
            
            img_label = ctk.CTkLabel(
                img_frame, 
                image=ctk_img, 
                text="",
                corner_radius=8
            )
            img_label.image = ctk_img
            img_label.pack(padx=3, pady=3)
            
            # Add visible delete button (×) - similar to manual_pairing.py
            remove_btn = ctk.CTkButton(
                img_frame,
                text="×",
                width=24,
                height=24,
                font=("Arial", 16, "bold"),
                fg_color=self.app.colors["error"],
                hover_color=self.app.colors["error_hover"],
                corner_radius=12,
                command=lambda p=img_path, i=pair_index: self._remove_image_from_pair(i, p)
            )
            remove_btn.place(x=59, y=2)
            create_tooltip(remove_btn, f"Remove this image\n{img_path.name}")
            
            # Add enhanced hover effect
            def make_img_hover():
                def on_enter(e):
                    img_frame.configure(fg_color=self.app.colors["border_light"]) 
                def on_leave(e):
                    img_frame.configure(fg_color="transparent")
                img_frame.bind("<Enter>", on_enter)
                img_frame.bind("<Leave>", on_leave)
            
            make_img_hover()

            # Left-click to replace (quick UX) - but not on the delete button
            def handle_click(e):
                # Check if click was on the delete button
                if e.widget == remove_btn or e.widget.winfo_parent() == str(remove_btn):
                    return
                self._replace_image_in_pair(pair_index, img_path)
            img_frame.bind("<Button-1>", handle_click)
            img_label.bind("<Button-1>", handle_click)

            # Context menu (right-click) for remove/replace
            try:
                import tkinter as tk
                menu = tk.Menu(img_frame, tearoff=0)
                menu.add_command(label="Remove", command=lambda p=img_path, i=pair_index: self._remove_image_from_pair(i, p))
                menu.add_command(label="Replace...", command=lambda p=img_path, i=pair_index: self._replace_image_in_pair(i, p))
                def show_menu(event, m=menu):
                    m.tk_popup(event.x_root, event.y_root)
                img_frame.bind("<Button-3>", show_menu)
                img_label.bind("<Button-3>", show_menu)
            except Exception:
                pass

            # Optional drag-and-drop support via TkinterDnD2 (if installed)
            try:
                from tkinterdnd2 import DND_FILES  # type: ignore
                def drop_replace(event, i=pair_index, old=img_path):
                    data = (event.data or "").strip()
                    if not data:
                        return
                    # TkinterDnD wraps Windows paths in braces when spaces exist
                    candidates = [p.strip("{}") for p in data.split()]
                    if not candidates:
                        return
                    newp = Path(candidates[0])
                    if newp.exists():
                        self._replace_image_in_pair_with_path(i, old, newp)
                img_frame.drop_target_register(DND_FILES)
                img_frame.dnd_bind('<<Drop>>', drop_replace)
            except Exception:
                pass
        except Exception as e:
            self.logger.warning("Failed to load image preview", error=str(e), path=str(img_path))
    
    def _toggle_pair(self, idx: int, var: ctk.BooleanVar):
        """Toggle pair enabled state."""
        if idx < len(self.pairs):
            self._save_state_for_undo()
            self.pairs[idx].enabled = var.get()
    
    def _toggle_pair_direct(self, idx: int, enabled: bool):
        """Toggle pair enabled state directly."""
        if idx < len(self.pairs):
            self._save_state_for_undo()
            self.pairs[idx].enabled = enabled
            self._refresh_pairs()
    
    def _copy_to_clipboard(self, text: str):
        """Copy text to clipboard."""
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            if hasattr(self, 'progress_label'):
                self.progress_label.configure(
                    text="📋 Copied to clipboard",
                    text_color=self.app.colors["success"]
                )
                self.after(2000, lambda: self.progress_label.configure(
                    text="Ready",
                    text_color=self.app.colors["text_secondary"]
                ))
        except Exception:
            pass
    
    def _copy_prompt_to_all(self, prompt: str):
        """Copy prompt from one pair to all others."""
        if not prompt:
            messagebox.showwarning("Empty Prompt", "The selected pair has no prompt to copy.")
            return
        
        updated = self.apply_prompt_to_all(prompt)
        if updated > 0:
            messagebox.showinfo("Success", f"✅ Copied prompt to {updated} pair(s)!")
    
    def _duplicate_pair(self, idx: int):
        """Duplicate a pair."""
        if idx >= len(self.pairs):
            return
        
        self._save_state_for_undo()
        import copy
        original_pair = self.pairs[idx]
        duplicated_pair = copy.deepcopy(original_pair)
        duplicated_pair.prompt = f"{original_pair.prompt} (copy)" if original_pair.prompt else ""
        
        # Insert after current pair
        self.pairs.insert(idx + 1, duplicated_pair)
        self._all_pairs.insert(idx + 1, duplicated_pair)
        self._refresh_pairs()
        
        if hasattr(self, 'progress_label'):
            self.progress_label.configure(
                text=f"📋 Duplicated pair #{idx + 1}",
                text_color=self.app.colors["success"]
            )
            self.after(2000, lambda: self.progress_label.configure(
                text="Ready",
                text_color=self.app.colors["text_secondary"]
            ))
    
    def _delete_pair(self, idx: int):
        """Delete a pair."""
        if idx >= len(self.pairs):
            return
        
        if not messagebox.askyesno(
            "Confirm Delete",
            f"Are you sure you want to delete pair #{idx + 1}?",
            icon="warning"
        ):
            return
        
        self._save_state_for_undo()
        self.pairs.pop(idx)
        if idx < len(self._all_pairs):
            self._all_pairs.pop(idx)
        self._refresh_pairs()
        
        if hasattr(self, 'progress_label'):
            self.progress_label.configure(
                text=f"🗑️ Deleted pair #{idx + 1}",
                text_color=self.app.colors["warning"]
            )
            self.after(2000, lambda: self.progress_label.configure(
                text="Ready",
                text_color=self.app.colors["text_secondary"]
            ))
    
    def _add_empty_pair(self):
        """Add a new empty pair to the list."""
        self._save_state_for_undo()
        
        # Ensure we're in manual mode
        self.mode_var.set("manual")
        self.pairing_mode = PairingMode.MANUAL
        
        # Create empty pair
        empty_pair = ImagePair(
            images=[],
            prompt="",
            enabled=True
        )
        
        # Add to lists
        if not hasattr(self, '_all_pairs'):
            self._all_pairs = []
        self._all_pairs.append(empty_pair)
        self.pairs = self._all_pairs.copy()
        
        # Refresh display
        self._refresh_pairs()
        
        # Scroll to the new pair
        self.after(100, lambda: self._scroll_to_pair(len(self.pairs) - 1))
        
        self.logger.info("Empty pair added", total_pairs=len(self.pairs))
    
    def _scroll_to_pair(self, idx: int):
        """Scroll to a specific pair in the list."""
        try:
            # Get all pair widgets
            widgets = self.pairs_container.winfo_children()
            if idx < len(widgets):
                widget = widgets[idx]
                # Scroll the widget into view
                self.pairs_container.update_idletasks()
                widget.update_idletasks()
                # Try to scroll to the widget
                try:
                    # Get the scrollable frame parent
                    scrollable = self.pairs_container
                    if hasattr(scrollable, '_parent_canvas'):
                        canvas = scrollable._parent_canvas
                        bbox = canvas.bbox("all")
                        if bbox:
                            widget_y = widget.winfo_y()
                            canvas.yview_moveto(widget_y / (bbox[3] - bbox[1]))
                except Exception:
                    pass
        except Exception as e:
            self.logger.debug("Failed to scroll to pair", error=str(e), index=idx)
    
    def _show_manual_pairing(self):
        """Show manual pairing dialog."""
        from src.gui.manual_pairing import ManualPairingEditor
        
        dialog = Toplevel(self.app)
        dialog.title("Manual Pairing")
        dialog.geometry("700x400")
        dialog.configure(bg="#0F0F0F")
        
        editor = ManualPairingEditor(
            dialog,
            self.config,
            self.image_service,
            on_pair_added=self._on_manual_pair_added
        )
        editor.pack(fill="both", expand=True, padx=20, pady=20)
    
    def _on_manual_pair_added(self, pair: ImagePair):
        """Handle manual pair addition."""
        self._save_state_for_undo()
        if not hasattr(self, '_all_pairs'):
            self._all_pairs = []
        self._all_pairs.append(pair)
        self.pairs = self._all_pairs.copy()
        
        # Ensure we're in manual mode when adding pairs manually
        self.mode_var.set("manual")
        self.pairing_mode = PairingMode.MANUAL
        
        self._refresh_pairs()
        
        # Close the manual pairing dialog (find the Toplevel that contains ManualPairingEditor)
        from src.gui.manual_pairing import ManualPairingEditor
        for widget in self.app.winfo_children():
            if isinstance(widget, Toplevel):
                # Check if this toplevel contains ManualPairingEditor
                for child in widget.winfo_children():
                    if isinstance(child, ManualPairingEditor):
                        widget.destroy()
                        return
    
    def _on_generate(self):
        """Handle generate button click."""
        # Collect enabled pairs with prompts
        enabled_pairs = []
        invalid_pairs = []
        
        for widget in self.pairs_container.winfo_children():
            if hasattr(widget, 'pair_data') and hasattr(widget, 'prompt_widget'):
                pair = widget.pair_data
                prompt = widget.prompt_widget.get("1.0", "end-1c").strip()
                
                # Validate pair
                if pair.enabled:
                    if not prompt:
                        invalid_pairs.append("Missing prompt")
                        continue
                    if len(pair.images) < 1:
                        invalid_pairs.append("No images")
                        continue
                    
                    # Validate all images
                    all_valid = True
                    for img_path in pair.images:
                        is_valid, error = self.image_service.validate_image(img_path)
                        if not is_valid:
                            invalid_pairs.append(f"Invalid image: {img_path.name}")
                            all_valid = False
                            break
                    
                    if all_valid:
                        pair.prompt = prompt
                        enabled_pairs.append(pair)
        
        if invalid_pairs:
            error_msg = "Some enabled pairs have issues:\n\n" + "\n".join(invalid_pairs[:5])
            if len(invalid_pairs) > 5:
                error_msg += f"\n... and {len(invalid_pairs) - 5} more"
            messagebox.showwarning("Validation Errors", error_msg)
        
        if not enabled_pairs:
            messagebox.showwarning(
                "No Valid Pairs", 
                "Please enable at least one pair with:\n"
                "• A valid prompt\n"
                "• At least 1 valid image\n"
                "• All images must exist and be valid format",
                icon="warning"
            )
            return
        
        # Get profiles from settings (or use all if not set)
        try:
            settings_service = get_settings_service()
            saved_profiles = settings_service.get_selected_profiles()
            available_profiles = settings_service.get_available_profiles()
            
            # Use selected profiles if set, otherwise use available profiles, otherwise use PROFILES
            if saved_profiles:
                profiles = saved_profiles
            elif available_profiles:
                profiles = available_profiles
            else:
                profiles = list(PROFILES) if PROFILES else []
            
            if not profiles:
                messagebox.showerror(
                    "Configuration Error", 
                    "No Chrome profiles selected!\nPlease select profiles in Settings.",
                    icon="error"
                )
                return
        except Exception as e:
            self.logger.error("Failed to get profiles", error=str(e))
            messagebox.showerror(
                "Error", 
                f"Failed to load Chrome profiles: {e}",
                icon="error"
            )
            return

        pair_positions = {id(p): idx for idx, p in enumerate(self.pairs)}
        self._reset_pair_statuses()
        for pair in enabled_pairs:
            pair_idx = pair_positions.get(id(pair))
            if pair_idx is not None:
                self.pairs[pair_idx].last_status = "queued"
        self._refresh_pairs()
        
        # Update progress label and status
        if hasattr(self, 'progress_label'):
            self.progress_label.configure(
                text=f"Starting {len(enabled_pairs)} task(s)...",
                text_color=self.app.colors["accent"]
            )
        if hasattr(self, 'status_indicator'):
            self.status_indicator.configure(text="●", text_color=self.app.colors["accent"])
        if hasattr(self, 'task_counter'):
            self.task_counter.configure(text=f"{len(enabled_pairs)} tasks queued")
        
        self.logger.info("Starting generation", pair_count=len(enabled_pairs))
        
        # Save state for undo
        self._save_state_for_undo()
        
        # Initialize cancellation event
        self._cancellation_event = threading.Event()
        self._cancellation_event.clear()
        
        # Disable generate button, enable cancel button
        if hasattr(self, 'generate_btn'):
            try:
                self.generate_btn.configure(state="disabled", text="Processing…")
            except Exception:
                pass
        if hasattr(self, 'cancel_btn'):
            try:
                self.cancel_btn.configure(state="normal")
            except Exception:
                pass

        # Run generation in background thread
        import uuid
        job_id = str(uuid.uuid4())[:8]
        job_start_time = time.time()
        
        def run_generation_thread():
            self.logger.info("Generation thread started", total_tasks=len(enabled_pairs))
            finished = 0
            failed = 0
            cancelled = 0
            total = len(enabled_pairs)
            
            # Auto-save prompts to library
            try:
                lib = get_prompt_library_service()
                for p in enabled_pairs:
                    if p.prompt and not self._cancellation_event.is_set():
                        lib.add_prompt(p.prompt)
            except Exception as e:
                self.logger.warning("Failed to auto-save prompts", error=str(e))
            
            def safe_log_insert_mt(msg):
                """Safely insert log message from background thread."""
                try:
                    # Use queue instead of direct app.after to avoid threading issues
                    if CORE_LOG_QUEUE:
                        CORE_LOG_QUEUE.put(f"{msg}\n")
                    # Also log to logger
                    self.logger.info("Generation log", message=msg.strip())
                except Exception as e:
                    # Fallback to logger only
                    self.logger.info("Generation log", message=msg.strip(), error=str(e))
            
            def single_task(task_idx, pair_obj: ImagePair):
                nonlocal finished, failed, cancelled, total
                # Check cancellation before starting
                if self._cancellation_event.is_set():
                    return "cancelled"
                
                profile = profiles[task_idx % len(profiles)]
                image_paths = pair_obj.images
                prompt_text = pair_obj.prompt
                pair_idx = pair_positions.get(id(pair_obj), -1)
                # Create a descriptive task name from image stems
                image_names = " + ".join([img.stem for img in image_paths])
                safe_log_insert_mt(f"\n===== TASK {task_idx+1}/{total}: {image_names} =====\n")
                
                try:
                    # Check cancellation before generation
                    if self._cancellation_event.is_set():
                        safe_log_insert_mt(f"Task {task_idx+1} cancelled before start")
                        if pair_idx is not None and pair_idx >= 0:
                            self.app.after(0, lambda idx=pair_idx: self._mark_pair_status(idx, "cancelled"))
                        return "cancelled"
                    if pair_idx is not None and pair_idx >= 0:
                        self.app.after(0, lambda idx=pair_idx: self._mark_pair_status(idx, "running"))
                    run_one_generation(task_idx+1, profile, image_paths, None, prompt_text, CORE_LOG_QUEUE)
                    
                    # Check cancellation after generation
                    if self._cancellation_event.is_set():
                        safe_log_insert_mt(f"Task {task_idx+1} marked as cancelled after completion")
                        if pair_idx is not None and pair_idx >= 0:
                            self.app.after(0, lambda idx=pair_idx: self._mark_pair_status(idx, "cancelled"))
                        return "cancelled"
                    
                    finished += 1
                    if pair_idx is not None and pair_idx >= 0:
                        self.app.after(0, lambda idx=pair_idx: self._mark_pair_status(idx, "success"))
                    return "completed"
                except Exception as e:
                    if self._cancellation_event.is_set():
                        safe_log_insert_mt(f"Task {task_idx+1} cancelled due to cancellation request")
                        if pair_idx is not None and pair_idx >= 0:
                            self.app.after(0, lambda idx=pair_idx: self._mark_pair_status(idx, "cancelled"))
                        return "cancelled"
                    safe_log_insert_mt(f"FATAL: {e}")
                    failed += 1
                    if pair_idx is not None and pair_idx >= 0:
                        self.app.after(0, lambda idx=pair_idx: self._mark_pair_status(idx, "failed"))
                    return "failed"
                finally:
                    # Use explicit parameters to avoid closure issues
                    fin_val = finished
                    fail_val = failed
                    canc_val = cancelled
                    tot_val = total
                    self.app.after(0, lambda f=fin_val, fa=fail_val, c=canc_val, t=tot_val: 
                                  self._update_progress(f, fa, c, t))
            
            # Use semaphore to limit concurrent browser launches (waves)
            # Get from settings first, fallback to config
            from src.services.settings_service import get_settings_service
            settings_service = get_settings_service()
            # Use max_concurrent_browser_launches for wave size (browsers per wave)
            max_launches = settings_service.get_max_concurrent_browser_launches() or getattr(self.config, "max_concurrent_browser_launches", 2)
            browser_launch_semaphore = threading.Semaphore(max_launches)
            
            # Get wave delay setting
            wave_delay_ms = settings_service.get_delay_setting("wave_delay_ms", 5000)
            wave_delay_seconds = wave_delay_ms / 1000.0
            
            # Track last launch time per profile to add small delay between same-profile launches
            import time
            profile_last_launch = {profile: 0 for profile in profiles}
            profile_launch_lock = threading.Lock()
            
            # Track wave completion - when all browsers in a wave finish Create click
            wave_completion_lock = threading.Lock()
            wave_completion_count = {}  # wave_num -> count of browsers that completed Create click
            wave_completion_events = {}  # wave_num -> Event to signal wave completion
            
            def mark_wave_completion(wave_num: int):
                """Mark that one browser in a wave has completed (Create click or error)."""
                with wave_completion_lock:
                    if wave_num not in wave_completion_count:
                        wave_completion_count[wave_num] = 0
                        wave_completion_events[wave_num] = threading.Event()
                    wave_completion_count[wave_num] += 1
                    
                    # If all browsers in this wave completed, signal the event
                    if wave_completion_count[wave_num] >= max_launches:
                        wave_completion_events[wave_num].set()
                        safe_log_insert_mt(f"\n✅ Wave {wave_num + 1} completed ({wave_completion_count[wave_num]}/{max_launches} browsers finished)\n")
            
            def single_task_with_semaphore(task_idx, pair_obj: ImagePair, total_tasks: int):
                """Wrapper that limits concurrent browser launches and releases semaphore after Create click."""
                nonlocal finished, failed, cancelled
                # Calculate which wave this task belongs to
                wave_num = task_idx // max_launches
                
                # Acquire semaphore before launching browser (limits to max_launches at a time)
                browser_launch_semaphore.acquire()
                semaphore_released = False
                
                # Wait for previous wave to complete if this is not the first wave
                if wave_num > 0:
                    with wave_completion_lock:
                        if wave_num not in wave_completion_events:
                            wave_completion_events[wave_num] = threading.Event()
                        prev_wave_event = wave_completion_events.get(wave_num - 1)
                    
                    if prev_wave_event:
                        safe_log_insert_mt(f"\n⏸️  Waiting for wave {wave_num} to complete before starting wave {wave_num + 1}...\n")
                        prev_wave_event.wait()  # Wait for previous wave to complete
                        safe_log_insert_mt(f"✓ Wave {wave_num} completed, starting wave {wave_num + 1} after {wave_delay_seconds:.1f}s delay...\n")
                        time.sleep(wave_delay_seconds)
                try:
                    # Run generation but release semaphore early (after Create click, before notification wait)
                    # We'll modify run_one_generation to accept a callback for early release
                    # For now, we'll use a wrapper that monitors when Create is clicked
                    profile = profiles[task_idx % len(profiles)]
                    image_paths = pair_obj.images
                    prompt_text = pair_obj.prompt
                    pair_idx = pair_positions.get(id(pair_obj), -1)
                    image_names = " + ".join([img.stem for img in image_paths])
                    safe_log_insert_mt(f"\n===== TASK {task_idx+1}/{total_tasks}: {image_names} =====\n")
                    
                    if self._cancellation_event.is_set():
                        safe_log_insert_mt(f"Task {task_idx+1} cancelled before start")
                        if pair_idx is not None and pair_idx >= 0:
                            self.app.after(0, lambda idx=pair_idx: self._mark_pair_status(idx, "cancelled"))
                        # Release semaphore and mark wave completion if cancelled after acquiring semaphore
                        if not semaphore_released:
                            browser_launch_semaphore.release()
                            semaphore_released = True
                            mark_wave_completion(wave_num)
                        return "cancelled"
                    
                    if pair_idx is not None and pair_idx >= 0:
                        self.app.after(0, lambda idx=pair_idx: self._mark_pair_status(idx, "running"))
                    
                    # Import here to avoid circular imports
                    from playwright.sync_api import sync_playwright
                    import os
                    from src.config import get_config
                    from src.utils.path_utils import sanitize_path
                    from core import SORA_URL, OUTPUTS_DIR, get_core_config, log_worker, handle_error, wait_for_sora_img_notification, _collect_top_tile_sources, describe_media_name
                    from datetime import datetime
                    import requests
                    
                    config = get_config()
                    playwright = None
                    ctx = None
                    page = None
                    
                    def log(msg):
                        log_worker(task_idx+1, msg)
                        if CORE_LOG_QUEUE:
                            CORE_LOG_QUEUE.put(f"[W{task_idx+1}] {msg}\n")
                    
                    try:
                        # Add small delay if same profile was launched recently (prevents conflicts)
                        with profile_launch_lock:
                            last_launch = profile_last_launch.get(profile, 0)
                            current_time = time.time()
                            if last_launch > 0 and (current_time - last_launch) < 2.0:
                                delay = 2.0 - (current_time - last_launch)
                                log(f"Waiting {delay:.1f}s before launching (profile in use)...")
                                time.sleep(delay)
                            profile_last_launch[profile] = time.time()
                        
                        # CRITICAL: Start playwright INSIDE try block and ensure it's kept alive
                        # The playwright instance must stay alive for the entire duration of browser usage
                        playwright = sync_playwright().start()
                        # Store reference to prevent garbage collection
                        _playwright_ref = playwright
                        profile_name_safe = os.path.basename(profile)
                        
                        # Get browser channel to determine profile path
                        browser_channel = getattr(config, "browser_channel", "chrome") or "chrome"
                        
                        # Use Edge profiles if using Edge, otherwise Chrome profiles
                        if browser_channel == "msedge" or "edge" in browser_channel.lower():
                            # Try Edge profile path first
                            edge_base_path = getattr(config, "edge_base", None)
                            if edge_base_path:
                                edge_base = sanitize_path(edge_base_path)
                            else:
                                edge_base = Path(os.path.expanduser("~")) / "AppData" / "Local" / "Microsoft" / "Edge" / "User Data"
                            
                            if edge_base.exists():
                                chrome_base = edge_base
                                log(f"Using Edge profiles from: {chrome_base}")
                            else:
                                # Fallback to Chrome profiles (Edge can use Chrome profiles)
                                chrome_base = sanitize_path(config.chrome_base)
                                log(f"Edge profiles not found at {edge_base}, using Chrome profiles: {chrome_base}")
                        else:
                            chrome_base = sanitize_path(config.chrome_base)
                        
                        profile_path = chrome_base / profile_name_safe
                        
                        if not profile_path.exists():
                            log(f"ERROR: Profile path not found: {profile_path}")
                            return "failed"
                        
                        log("Launching browser...")
                        core_config = get_core_config()
                        
                        # Clean up any existing browser processes (Chrome/Edge) using this profile BEFORE first attempt
                        if PSUTIL_AVAILABLE:
                            try:
                                profile_str = str(profile_path)
                                killed_count = 0
                                log(f"Checking for existing browser processes ({browser_channel}) using this profile...")
                                for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                                    try:
                                        proc_name = proc.info['name'] or ''
                                        # Check for Chrome or Edge processes
                                        if ('chrome' in proc_name.lower() or 'msedge' in proc_name.lower() or 'edge' in proc_name.lower()):
                                            cmdline = proc.info.get('cmdline', [])
                                            if cmdline and any(profile_str in str(arg) for arg in cmdline):
                                                log(f"Found existing browser process using profile: PID {proc.info['pid']}, killing...")
                                                try:
                                                    proc.terminate()  # Try graceful termination first
                                                    time.sleep(0.5)
                                                    if proc.is_running():
                                                        proc.kill()  # Force kill if still running
                                                except (psutil.NoSuchProcess, psutil.AccessDenied):
                                                    pass
                                                killed_count += 1
                                                time.sleep(0.3)
                                    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                                        pass
                                if killed_count > 0:
                                    log(f"Killed {killed_count} existing browser process(es), waiting for cleanup...")
                                    time.sleep(2)  # Wait for processes to fully terminate and profile to unlock
                            except Exception as kill_err:
                                log(f"Warning: Could not check/kill existing processes: {kill_err}")
                        
                        # Retry logic for browser launch with better error handling
                        ctx = None
                        max_launch_retries = 3
                        for launch_retry in range(max_launch_retries):
                            try:
                                # Add delay between retries
                                if launch_retry > 0:
                                    wait_time = launch_retry * 3
                                    log(f"Retrying browser launch (attempt {launch_retry + 1}/{max_launch_retries}) after {wait_time}s...")
                                    time.sleep(wait_time)
                                    
                                    # Kill processes again on retry
                                    if PSUTIL_AVAILABLE:
                                        try:
                                            profile_str = str(profile_path)
                                            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                                                try:
                                                    proc_name = proc.info['name'] or ''
                                                    # Check for Chrome or Edge processes
                                                    if ('chrome' in proc_name.lower() or 'msedge' in proc_name.lower() or 'edge' in proc_name.lower()):
                                                        cmdline = proc.info.get('cmdline', [])
                                                        if cmdline and any(profile_str in str(arg) for arg in cmdline):
                                                            log(f"Killing browser process on retry: PID {proc.info['pid']}")
                                                            try:
                                                                proc.terminate()
                                                                time.sleep(0.5)
                                                                if proc.is_running():
                                                                    proc.kill()
                                                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                                                pass
                                                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                                                    pass
                                            time.sleep(2)
                                        except Exception:
                                            pass
                                
                                log(f"Launching browser (attempt {launch_retry + 1}/{max_launch_retries})...")
                                
                                # CRITICAL FIX: Check if profile is locked by another process BEFORE launch
                                # Chrome locks the profile with a lockfile, and if it exists, launch will fail
                                import os
                                lock_file = profile_path / "SingletonLock"
                                lock_cookie = profile_path / "SingletonCookie"
                                if lock_file.exists() or lock_cookie.exists():
                                    log(f"Profile lock detected, waiting for unlock...")
                                    # Wait for lock to be released (max 10 seconds)
                                    for wait_attempt in range(20):
                                        time.sleep(0.5)
                                        if not lock_file.exists() and not lock_cookie.exists():
                                            break
                                    if lock_file.exists() or lock_cookie.exists():
                                        # Force remove lock files if they're stale
                                        try:
                                            if lock_file.exists():
                                                os.remove(str(lock_file))
                                            if lock_cookie.exists():
                                                os.remove(str(lock_cookie))
                                            log("Removed stale lock files")
                                            time.sleep(1)
                                        except Exception as lock_err:
                                            log(f"Could not remove lock files: {lock_err}")
                                
                                # CRITICAL: launch_persistent_context can raise exception even if browser starts
                                # The issue is that Chrome closes immediately if profile is locked or has errors
                                # We need to ensure profile is completely free before launch
                                ctx = None
                                
                                # Final check: ensure no browser processes (Chrome/Edge) are using this profile
                                if PSUTIL_AVAILABLE:
                                    try:
                                        profile_str = str(profile_path)
                                        found_processes = []
                                        # Check for both Chrome and Edge processes
                                        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                                            try:
                                                proc_name = proc.info['name'] or ''
                                                # Check for Chrome or Edge processes
                                                if ('chrome' in proc_name.lower() or 'msedge' in proc_name.lower() or 'edge' in proc_name.lower()):
                                                    cmdline = proc.info.get('cmdline', [])
                                                    if cmdline and any(profile_str in str(arg) for arg in cmdline):
                                                        found_processes.append(proc.info['pid'])
                                            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                                                pass
                                        if found_processes:
                                            log(f"WARNING: Found {len(found_processes)} browser process(es) using profile: {found_processes}")
                                            # Kill them to free the profile
                                            for pid in found_processes:
                                                try:
                                                    proc = psutil.Process(pid)
                                                    proc.terminate()
                                                    time.sleep(0.3)
                                                    if proc.is_running():
                                                        proc.kill()
                                                except (psutil.NoSuchProcess, psutil.AccessDenied):
                                                    pass
                                            time.sleep(2)  # Wait for processes to fully terminate
                                    except Exception:
                                        pass
                                
                                try:
                                    log(f"Launching {browser_channel} browser...")
                                    ctx = playwright.chromium.launch_persistent_context(
                                        user_data_dir=str(profile_path),
                                        headless=False,
                                        channel=browser_channel,  # Use Edge instead of Chrome
                                        args=[
                                            "--disable-blink-features=AutomationControlled",
                                            "--disable-dev-shm-usage",
                                            "--no-sandbox",
                                            "--disable-setuid-sandbox",
                                            "--disable-background-networking",  # Prevent background processes
                                            "--disable-sync",  # Disable sync to reduce conflicts
                                        ],
                                        ignore_default_args=["--enable-automation"],
                                        timeout=core_config.browser_timeout,
                                        accept_downloads=True
                                    )
                                except Exception as launch_exc:
                                    # Browser might have started but closed immediately
                                    error_str = str(launch_exc)
                                    log(f"Launch exception: {error_str}")
                                    # Clean up any partial context
                                    if ctx:
                                        try:
                                            ctx.close()
                                        except:
                                            pass
                                        ctx = None
                                    raise  # Re-raise to trigger retry
                                
                                # Verify context is actually created and valid
                                if ctx is None:
                                    raise RuntimeError("Context is None after launch")
                                
                                # CRITICAL: Immediately check if browser is still connected
                                # If it closed during launch, ctx.browser might be None or disconnected
                                try:
                                    if ctx.browser is None:
                                        raise RuntimeError("Browser is None - browser closed during launch")
                                    if not ctx.browser.is_connected():
                                        raise RuntimeError("Browser disconnected immediately after launch")
                                except AttributeError:
                                    # ctx.browser might not exist if browser closed
                                    raise RuntimeError("Browser attribute missing - browser closed during launch")
                                
                                # CRITICAL: Create a page immediately to keep browser alive
                                # Without a page, Playwright may close the browser
                                try:
                                    test_page = ctx.new_page()
                                    if test_page is None:
                                        raise RuntimeError("Failed to create initial page")
                                except Exception as page_err:
                                    # If we can't create a page, browser might have closed
                                    error_str = str(page_err)
                                    if "Target page, context or browser has been closed" in error_str:
                                        raise RuntimeError("Browser closed before page creation")
                                    raise
                                
                                # Wait for browser to fully initialize
                                time.sleep(1.0)  # Reduced wait time - we already have a page
                                
                                # Verify browser is still connected after wait
                                if ctx.browser is None or not ctx.browser.is_connected():
                                    raise RuntimeError("Browser disconnected after initialization wait")
                                
                                # Verify we can still access pages
                                if len(ctx.pages) == 0:
                                    raise RuntimeError("No pages in context after creation")
                                
                                # Close test page - we'll create a new one for actual work
                                try:
                                    if not test_page.is_closed():
                                        test_page.close()
                                except Exception:
                                    pass
                                
                                log("✓ Browser launched successfully")
                                break
                                
                            except Exception as launch_err:
                                error_msg = str(launch_err)
                                log(f"Browser launch failed (attempt {launch_retry + 1}/{max_launch_retries}): {error_msg}")
                                
                                # Clean up failed context
                                if ctx:
                                    try:
                                        ctx.close()
                                    except:
                                        pass
                                    ctx = None
                                
                                if launch_retry == max_launch_retries - 1:
                                    log(f"FATAL: Failed to launch browser after {max_launch_retries} attempts")
                                    return "failed"
                        
                        if ctx is None:
                            log("FATAL: Could not create browser context")
                            return "failed"
                        
                        # Create page and verify it's working
                        try:
                            # Verify browser is still connected before creating page
                            if ctx.browser and not ctx.browser.is_connected():
                                raise RuntimeError("Browser disconnected before page creation")
                            
                            page = ctx.new_page()
                            # Verify page is created
                            if page is None:
                                raise RuntimeError("Page is None after creation")
                            
                            # Small delay to let page initialize
                            time.sleep(0.5)
                            
                            # Verify page is still valid
                            if page.is_closed():
                                raise RuntimeError("Page was closed immediately after creation")
                            
                            log("✓ Page created and verified")
                        except Exception as page_err:
                            log(f"FATAL: Failed to create page: {page_err}")
                            try:
                                ctx.close()
                            except:
                                pass
                            return "failed"
                        
                        log("Navigating to Sora...")
                        
                        # Verify browser is still connected before navigation
                        try:
                            if ctx.browser and not ctx.browser.is_connected():
                                log("ERROR: Browser disconnected before navigation")
                                return "failed"
                        except Exception as check_err:
                            log(f"Warning: Could not verify browser connection: {check_err}")
                        
                        for nav_attempt in range(core_config.navigation_retries):
                            try:
                                # Verify page is still valid
                                if page.is_closed():
                                    log("ERROR: Page was closed before navigation")
                                    return "failed"
                                
                                page.goto(SORA_URL, wait_until="domcontentloaded", timeout=core_config.navigation_timeout)
                                
                                # Verify browser is still connected after navigation
                                if ctx.browser and not ctx.browser.is_connected():
                                    log("ERROR: Browser disconnected during navigation")
                                    if nav_attempt < core_config.navigation_retries - 1:
                                        log(f"Retrying navigation (attempt {nav_attempt + 2}/{core_config.navigation_retries})...")
                                        time.sleep(2)
                                        continue
                                    else:
                                        return "failed"
                                
                                page.wait_for_load_state("domcontentloaded", timeout=5000)
                                page.wait_for_timeout(core_config.scroll_delay)
                                
                                # Final verification after navigation
                                if page.is_closed():
                                    raise RuntimeError("Page was closed after navigation")
                                if ctx.browser and not ctx.browser.is_connected():
                                    raise RuntimeError("Browser disconnected after navigation")
                                
                                log("✓ Navigation successful")
                                break
                            except Exception as e:
                                error_msg = str(e)
                                if "Target page, context or browser has been closed" in error_msg:
                                    log(f"ERROR: Browser/context closed during navigation: {error_msg}")
                                    return "failed"
                                if nav_attempt < core_config.navigation_retries - 1:
                                    log(f"Navigation failed (attempt {nav_attempt + 1}/{core_config.navigation_retries}): {error_msg}, retrying...")
                                    time.sleep(2)
                                else:
                                    log(f"Navigation failed (final attempt): {error_msg}")
                                    return "failed"
                        
                        if "login" in page.url.lower() or "auth" in page.url.lower():
                            log("ERROR: Not logged in! Run Login Mode first.")
                            return "failed"
                        
                        try:
                            page.evaluate("window.scrollTo(0, 0)")
                            page.wait_for_timeout(core_config.scroll_delay)
                            log("✓ Page loaded")
                        except Exception as e:
                            log(f"Scroll warning: {e}")
                        
                        # Upload images
                        for idx, img_path in enumerate(image_paths, 1):
                            img_name = Path(img_path).stem
                            log(f"Uploading image {idx}/{len(image_paths)}: {img_name}")
                            try:
                                file_input = page.locator('input[type="file"]').first
                                abs_path = Path(img_path).resolve()
                                if not abs_path.exists():
                                    log(f"ERROR: Image path does not exist: {abs_path}")
                                    return "failed"
                                file_input.set_input_files(str(abs_path))
                                log(f"✓ Image {idx} uploaded")
                                delay = core_config.upload_delay if idx < len(image_paths) else core_config.upload_delay_last
                                page.wait_for_timeout(delay)
                            except Exception as e:
                                log(f"ERROR uploading image {idx}: {e}")
                                return "failed"
                        
                        # Wait for Create button
                        log("Waiting for Create button (max 60 sec)...")
                        button_ready = False
                        for attempt in range(60):
                            try:
                                disabled = page.evaluate("""
                                    () => {
                                        const btn = Array.from(document.querySelectorAll('button'))
                                            .find(b => b.textContent.includes('Remix') || b.textContent.includes('Create'));
                                        return btn ? btn.getAttribute('data-disabled') : 'notfound';
                                    }
                                """)
                                if disabled == 'false':
                                    log("✓ Button ready!")
                                    button_ready = True
                                    break
                                if (attempt + 1) % 10 == 0:
                                    log(f"Waiting... {attempt + 1}/60")
                                time.sleep(1)
                            except Exception as e:
                                log(f"Button poll error: {e}")
                                time.sleep(1)
                        
                        if not button_ready:
                            log("ERROR: Button never became ready")
                            return "failed"
                        
                        log("Waiting for files to fully process...")
                        page.wait_for_timeout(800)
                        
                        # Set prompt and click Create
                        log("Clicking Create...")
                        create_clicked = False
                        for attempt in range(20):
                            try:
                                set_result = page.evaluate(
                                    """
                                    (prompt) => {
                                        const textarea = document.querySelector('textarea[placeholder*="Describe"]');
                                        if (!textarea) return {success: false, error: "notextarea"};
                                        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
                                        nativeInputValueSetter.call(textarea, prompt);
                                        textarea.dispatchEvent(new Event('input', { bubbles: true }));
                                        textarea.dispatchEvent(new Event('change', { bubbles: true }));
                                        const actualValue = textarea.value;
                                        return {success: true, promptLength: actualValue.length, isSet: actualValue === prompt || actualValue.length === prompt.length};
                                    }
                                    """,
                                    prompt_text
                                )
                                
                                if not set_result.get('success') or not set_result.get('isSet'):
                                    log(f"Failed to set prompt: {set_result.get('error', 'not set')}")
                                    time.sleep(0.5)
                                    continue
                                
                                time.sleep(0.3)
                                
                                click_result = page.evaluate(
                                    """
                                    () => {
                                        const buttons = Array.from(document.querySelectorAll('button'));
                                        const createBtn = buttons.find(b => b.textContent.includes('Remix') || b.textContent.includes('Create'));
                                        if (!createBtn) return {found: false};
                                        const disabled = createBtn.getAttribute('data-disabled');
                                        if (disabled === 'false') {
                                            createBtn.click();
                                            return {found: true, clicked: true};
                                        }
                                        return {found: true, clicked: false, disabled: disabled};
                                    }
                                    """
                                )
                                
                                if click_result.get('clicked'):
                                    log(f"✓ Prompt set ({set_result.get('promptLength')} chars) + clicked!")
                                    create_clicked = True
                                    page.wait_for_timeout(core_config.create_click_delay)
                                    break
                                
                                if not click_result.get('found'):
                                    log(f"Create button not found, attempt {attempt + 1}/20")
                                    time.sleep(0.5)
                                    continue
                                
                                if (attempt + 1) % 5 == 0:
                                    log(f"Waiting... {attempt + 1}/20 (disabled={click_result.get('disabled')})")
                                time.sleep(1)
                            except Exception as e:
                                log(f"Prompt injection error: {e}")
                                time.sleep(1)
                        
                        if not create_clicked:
                            log("ERROR: Could not click Create button")
                            return "failed"
                        
                        # RELEASE SEMAPHORE HERE - allow next browsers to start
                        browser_launch_semaphore.release()
                        semaphore_released = True
                        
                        # Mark wave completion after successful Create click
                        mark_wave_completion(wave_num)
                        
                        # Now wait for notification and download in background (doesn't block other browsers)
                        log("Waiting for Sora image notification...")
                        baseline_sources = _collect_top_tile_sources(page)
                        notified = wait_for_sora_img_notification(page, timeout=core_config.notification_timeout_seconds, baseline_sources=baseline_sources)
                        if not notified:
                            log("WARNING: Sora notification not detected (fallback to tile polling)")
                        else:
                            log("✓ Sora image notification detected, proceeding to download")
                        
                        # Download variants
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        downloaded = 0
                        try:
                            page.evaluate("window.scrollTo(0, 0)")
                            page.wait_for_timeout(300)
                            tiles = page.locator('div.group\\/tile')
                            total = tiles.count()
                            max_variants = getattr(core_config, 'max_variants_per_task', 2)
                            log(f"Found {total} total tiles, taking top {max_variants}")
                            for idx in range(min(max_variants, total)):
                                try:
                                    tile = tiles.nth(idx)
                                    log(f"Downloading variant {idx + 1}...")
                                    tile.scroll_into_view_if_needed()
                                    page.wait_for_timeout(200)
                                    tile.hover()
                                    page.wait_for_timeout(300)
                                    
                                    img = tile.locator('img, video').first
                                    img.wait_for(state="visible", timeout=5000)
                                    img_url = img.get_attribute('src')
                                    if not img_url:
                                        img_url = img.evaluate("el => el.currentSrc || el.src || el.querySelector('source')?.src")
                                    
                                    if img_url and not img_url.startswith('data:'):
                                        try:
                                            response = requests.get(img_url, timeout=core_config.download_timeout // 1000, stream=True)
                                            response.raise_for_status()
                                            char_names = [describe_media_name(img).replace(" · ", "_").replace(" ", "_") for img in image_paths[:2]]
                                            name_part = "_".join(char_names[:2]) if char_names else "_".join([img.stem for img in image_paths[:2]])
                                            filename = f"{timestamp}_W{task_idx+1}_{name_part}_v{idx + 1}.webp"
                                            save_path = OUTPUTS_DIR / filename
                                            with open(save_path, 'wb') as f:
                                                for chunk in response.iter_content(chunk_size=8192):
                                                    f.write(chunk)
                                            log(f"✓ Downloaded: {filename}")
                                            downloaded += 1
                                        except Exception as url_err:
                                            log(f"URL download failed: {url_err}")
                                            img_url = None
                                    
                                    if not img_url or img_url.startswith('data:'):
                                        try:
                                            with page.expect_download(timeout=core_config.download_timeout) as download_info:
                                                img.click(button="right")
                                                page.wait_for_timeout(300)
                                                page.keyboard.press("v")
                                                page.wait_for_timeout(500)
                                            download = download_info.value
                                            char_names = [describe_media_name(img).replace(" · ", "_").replace(" ", "_") for img in image_paths[:2]]
                                            name_part = "_".join(char_names[:2]) if char_names else "_".join([img.stem for img in image_paths[:2]])
                                            filename = f"{timestamp}_W{task_idx+1}_{name_part}_v{idx + 1}.webp"
                                            save_path = OUTPUTS_DIR / filename
                                            download.save_as(save_path)
                                            log(f"✓ Downloaded (right click): {filename}")
                                            downloaded += 1
                                        except Exception as right_click_err:
                                            log(f"Right click also failed: {right_click_err}")
                                    
                                    page.wait_for_timeout(200)
                                except Exception as e:
                                    log(f"ERROR downloading variant {idx + 1}: {e}")
                                    continue
                            
                            if downloaded > 0:
                                log(f"✅ Completed! {downloaded}/{max_variants} variants downloaded")
                            else:
                                log("WARNING: No variants downloaded")
                        except Exception as e:
                            log(f"Download error: {e}")
                        
                        if downloaded > 0:
                            finished += 1
                            if pair_idx is not None and pair_idx >= 0:
                                self.app.after(0, lambda idx=pair_idx: self._mark_pair_status(idx, "success"))
                            return "completed"
                        else:
                            failed += 1
                            if pair_idx is not None and pair_idx >= 0:
                                self.app.after(0, lambda idx=pair_idx: self._mark_pair_status(idx, "failed"))
                            return "failed"
                            
                    except Exception as e:
                        if self._cancellation_event.is_set():
                            safe_log_insert_mt(f"Task {task_idx+1} cancelled due to cancellation request")
                            if pair_idx is not None and pair_idx >= 0:
                                self.app.after(0, lambda idx=pair_idx: self._mark_pair_status(idx, "cancelled"))
                            return "cancelled"
                        safe_log_insert_mt(f"FATAL: {e}")
                        failed += 1
                        if pair_idx is not None and pair_idx >= 0:
                            self.app.after(0, lambda idx=pair_idx: self._mark_pair_status(idx, "failed"))
                        return "failed"
                    finally:
                        # Use explicit parameters to avoid closure issues
                        fin_val = finished
                        fail_val = failed
                        canc_val = cancelled
                        tot_val = total
                        self.app.after(0, lambda f=fin_val, fa=fail_val, c=canc_val, t=tot_val: 
                                      self._update_progress(f, fa, c, t))
                        # CRITICAL: Close context FIRST, then stop playwright
                        # This ensures browser is properly closed before playwright cleanup
                        if ctx:
                            try:
                                # Close all pages first
                                for p in list(ctx.pages):
                                    try:
                                        if not p.is_closed():
                                            p.close()
                                    except Exception as page_err:
                                        self.logger.debug("Failed to close page", error=str(page_err))
                                # Close context - this will close the browser
                                ctx.close()
                                # Wait a bit for context to fully close
                                time.sleep(0.5)
                            except Exception as ctx_err:
                                self.logger.debug("Failed to close context", error=str(ctx_err))
                        # Only stop playwright AFTER context is closed
                        # This prevents playwright from forcefully closing active contexts
                        if playwright:
                            try:
                                # Small delay to ensure context cleanup completed
                                time.sleep(0.3)
                                playwright.stop()
                            except Exception as pw_err:
                                self.logger.debug("Failed to stop playwright", error=str(pw_err))
                except Exception as e:
                    # Make sure to release semaphore even on error
                    if not semaphore_released:
                        try:
                            browser_launch_semaphore.release()
                            semaphore_released = True
                            # Mark wave completion even on error
                            mark_wave_completion(wave_num)
                        except:
                            pass
                    
                    import traceback
                    error_trace = traceback.format_exc()
                    safe_log_insert_mt(f"FATAL ERROR in task {task_idx+1}: {e}\n{error_trace}")
                    
                    if self._cancellation_event.is_set():
                        safe_log_insert_mt(f"Task {task_idx+1} cancelled")
                        pair_idx_val = pair_positions.get(id(pair_obj), -1)
                        if pair_idx_val is not None and pair_idx_val >= 0:
                            try:
                                self.app.after(0, lambda idx=pair_idx_val: self._mark_pair_status(idx, "cancelled"))
                            except:
                                pass
                        return "cancelled"
                    
                    failed += 1
                    pair_idx_val = pair_positions.get(id(pair_obj), -1)
                    if pair_idx_val is not None and pair_idx_val >= 0:
                        try:
                            self.app.after(0, lambda idx=pair_idx_val: self._mark_pair_status(idx, "failed"))
                        except:
                            pass
                    return "failed"
                finally:
                    # Ensure semaphore is always released
                    if not semaphore_released:
                        try:
                            browser_launch_semaphore.release()
                            # Mark wave completion if not already marked
                            mark_wave_completion(wave_num)
                        except:
                            pass
            
            try:
                # Parallel execution with thread pool (bounded by config)
                # But browser launches are limited by semaphore (2 at a time)
                browser_cap = getattr(self.config, "max_parallel_browsers", self.config.max_concurrent_tasks)
                max_workers = max(1, min(self.config.max_concurrent_tasks, browser_cap, len(enabled_pairs)))
                def task_wrapper(task_idx: int, pair: ImagePair):
                    try:
                        if len(pair.images) < 1:
                            return "skipped"
                        # Check cancellation before submitting
                        if self._cancellation_event.is_set():
                            return "cancelled"
                        return single_task_with_semaphore(task_idx, pair, total)
                    except Exception as e:
                        import traceback
                        error_trace = traceback.format_exc()
                        safe_log_insert_mt(f"CRITICAL ERROR in task_wrapper {task_idx+1}: {e}\n{error_trace}")
                        nonlocal failed
                        failed += 1
                        return "failed"

                with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                    self._executor = executor
                    futures = []
                    for idx, pair in enumerate(enabled_pairs):
                        # Check cancellation before submitting new tasks
                        if self._cancellation_event.is_set():
                            break
                        futures.append(executor.submit(task_wrapper, idx, pair))
                    
                    # Wait for all tasks to complete or cancellation
                    for f in concurrent.futures.as_completed(futures):
                        if self._cancellation_event.is_set():
                            # Cancel remaining futures
                            for future in futures:
                                if not future.done():
                                    future.cancel()
                            # Count remaining as cancelled
                            remaining = sum(1 for fut in futures if not fut.done())
                            cancelled += remaining
                            break
                        
                        try:
                            result = f.result(timeout=300)  # 5 minutes timeout per task
                            if result == "cancelled":
                                cancelled += 1
                            elif result == "failed":
                                # Already counted inside task
                                pass
                            elif result == "skipped":
                                # Don't count skipped
                                pass
                        except concurrent.futures.TimeoutError:
                            self.logger.error("Task timeout - task took too long")
                            failed += 1
                        except concurrent.futures.CancelledError:
                            cancelled += 1
                        except Exception as e:
                            import traceback
                            error_trace = traceback.format_exc()
                            self.logger.error("Task exception in result handler", error=str(e), traceback=error_trace)
                            # Only count as failed if not already counted
                            failed += 1
                    
                    self._executor = None
                
                # Calculate duration
                duration = time.time() - job_start_time
                
                # Save to history
                self.history_service.add_entry(
                    job_id=job_id,
                    task_count=total,
                    completed=finished,
                    failed=failed,
                    duration_seconds=duration,
                    pairing_mode=self.pairing_mode.value if hasattr(self.pairing_mode, 'value') else str(self.pairing_mode),
                    output_dir=str(self.config.outputs_dir)
                )
                
                # Show completion with better messaging
                if self._cancellation_event.is_set():
                    msg = f"⏹ Cancelled: {finished}/{total} completed, {cancelled} cancelled"
                    if failed > 0:
                        msg += f", {failed} failed"
                    title = "Generation Cancelled"
                elif failed == 0 and cancelled == 0:
                    msg = f"✅ Success! All {finished} task(s) completed successfully!"
                    title = "Generation Complete"
                else:
                    msg = f"⚠️ Completed: {finished}/{total} succeeded"
                    if failed > 0:
                        msg += f", {failed} failed"
                    if cancelled > 0:
                        msg += f", {cancelled} cancelled"
                    title = "Generation Completed"
                
                # Use explicit values to avoid closure issues
                title_val = title
                msg_val = msg
                fin_val = finished
                fail_val = failed
                canc_val = cancelled
                tot_val = total
                
                # Update UI safely using queue
                def update_ui_safely():
                    try:
                        messagebox.showinfo(title_val, msg_val, icon="info")
                    except Exception as e:
                        self.logger.warning("Failed to show message", error=str(e))
                    
                    try:
                        self._update_progress(fin_val, fail_val, canc_val, tot_val)
                    except Exception as e:
                        self.logger.warning("Failed to update progress", error=str(e))
                    
                    # Re-enable generate button, disable cancel button
                    if hasattr(self, 'generate_btn'):
                        try:
                            self.generate_btn.configure(state="normal", text="🚀 Generate")
                        except Exception as e:
                            self.logger.warning("Failed to update generate button", error=str(e))
                    if hasattr(self, 'cancel_btn'):
                        try:
                            self.cancel_btn.configure(state="disabled")
                        except Exception as e:
                            self.logger.warning("Failed to update cancel button", error=str(e))
                
                try:
                    self.app.after_idle(update_ui_safely)
                except AttributeError:
                    # Fallback if after_idle doesn't exist (older tkinter)
                    try:
                        self.app.after(0, update_ui_safely)
                    except Exception as e:
                        self.logger.error("Failed to schedule UI update", error=str(e))
                except Exception as e:
                    self.logger.error("Failed to schedule UI update", error=str(e))
                    # Try direct call as last resort
                    try:
                        update_ui_safely()
                    except:
                        pass
                
                # Windows toast (best-effort)
                try:
                    notifier = get_notification_service()
                    notifier.notify(title_val, msg_val, duration=6)
                except Exception:
                    pass
                
            except Exception as e:
                import traceback
                error_trace = traceback.format_exc()
                self.logger.error("Critical error in run_generation_thread", error=str(e), traceback=error_trace)
                # At least try to update progress directly
                try:
                    self._update_progress(0, total, 0, total)  # Mark all as failed
                except:
                    pass
                # Try to re-enable button
                try:
                    if hasattr(self, 'generate_btn'):
                        self.app.after(0, lambda: self.generate_btn.configure(state="normal", text="🚀 Generate"))
                    if hasattr(self, 'cancel_btn'):
                        self.app.after(0, lambda: self.cancel_btn.configure(state="disabled"))
                except:
                    pass
        
        # Start generation thread
        self._generation_thread = threading.Thread(target=run_generation_thread, daemon=True)
        self._generation_thread.start()
    
    def _on_cancel(self):
        """Handle cancel button click."""
        if not self._cancellation_event or not self._generation_thread:
            return
        
        if not self._generation_thread.is_alive():
            return
        
        # Confirm cancellation
        if not messagebox.askyesno(
            "Cancel Generation",
            "Are you sure you want to cancel the current generation?\n\n"
            "Tasks that have already started will complete, but pending tasks will be cancelled.",
            icon="question"
        ):
            return
        
        # Set cancellation flag
        self._cancellation_event.set()
        
        # Update UI
        if hasattr(self, 'progress_label'):
            self.progress_label.configure(
                text="Cancelling...",
                text_color=self.app.colors["warning"]
            )
        if hasattr(self, 'status_indicator'):
            self.status_indicator.configure(text="●", text_color=self.app.colors["warning"])
        
        self.logger.info("Cancellation requested by user")
    
    def _update_progress(self, finished: int, failed: int, cancelled: int, total: int):
        """Update progress display with status indicators.
        
        Args:
            finished: Number of completed tasks
            failed: Number of failed tasks
            cancelled: Number of cancelled tasks
            total: Total number of tasks
        """
        if hasattr(self, 'progress_label'):
            if total == 0:
                self.progress_label.configure(text="Ready", text_color=self.app.colors["text_secondary"])
                if hasattr(self, 'status_indicator'):
                    self.status_indicator.configure(text="●", text_color=self.app.colors["text_secondary"])
            elif cancelled > 0 or (self._cancellation_event and self._cancellation_event.is_set()):
                self.progress_label.configure(
                    text=f"⏹ Cancelling: {finished}/{total} completed",
                    text_color=self.app.colors["warning"]
                )
                if hasattr(self, 'status_indicator'):
                    self.status_indicator.configure(text="●", text_color=self.app.colors["warning"])
            elif finished + failed + cancelled < total:
                self.progress_label.configure(
                    text=f"Processing: {finished + failed + cancelled}/{total}",
                    text_color=self.app.colors["accent"]
                )
                if hasattr(self, 'status_indicator'):
                    self.status_indicator.configure(text="●", text_color=self.app.colors["accent"])
            else:
                if failed == 0 and cancelled == 0:
                    self.progress_label.configure(
                        text=f"✅ Complete: {finished}/{total}",
                        text_color=self.app.colors["success"]
                    )
                    if hasattr(self, 'status_indicator'):
                        self.status_indicator.configure(text="●", text_color=self.app.colors["success"])
                else:
                    parts = []
                    if finished > 0:
                        parts.append(f"{finished} succeeded")
                    if failed > 0:
                        parts.append(f"{failed} failed")
                    if cancelled > 0:
                        parts.append(f"{cancelled} cancelled")
                    status_text = f"⚠️ Done: {', '.join(parts)}"
                    self.progress_label.configure(
                        text=status_text,
                        text_color=self.app.colors["warning"]
                    )
                    if hasattr(self, 'status_indicator'):
                        self.status_indicator.configure(text="●", text_color=self.app.colors["warning"])
        
        if hasattr(self, 'progress_bar') and total > 0:
            progress = (finished + failed + cancelled) / total
            self.progress_bar.set(progress)
        
        if hasattr(self, 'task_counter'):
            parts = []
            if finished > 0:
                parts.append(f"{finished} succeeded")
            if failed > 0:
                parts.append(f"{failed} failed")
            if cancelled > 0:
                parts.append(f"{cancelled} cancelled")
            pending = total - finished - failed - cancelled
            if pending > 0:
                parts.append(f"{pending} pending")
            self.task_counter.configure(text=", ".join(parts) if parts else "0 tasks")
    
    def _safe_log_insert(self, msg: str):
        """Safely insert log message."""
        # Logs are handled by core.py LOG_QUEUE
        pass
    
    def _save_as_template(self):
        """Save current pairing configuration as template with enhanced dialog."""
        if not self.pairs:
            messagebox.showinfo("No Pairs", "Please create at least one pair before saving a template.")
            return
        
        # Create enhanced save dialog
        dialog = Toplevel(self.app)
        dialog.title("💾 Save Template")
        dialog.geometry("600x400")
        dialog.configure(bg=self.app.colors["bg"])
        dialog.transient(self.app)
        dialog.grab_set()
        
        # Center the dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (600 // 2)
        y = (dialog.winfo_screenheight() // 2) - (400 // 2)
        dialog.geometry(f"600x400+{x}+{y}")
        
        # Header
        header_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        header_frame.pack(pady=(25, 15), padx=25, fill="x")
        
        title_label = ctk.CTkLabel(
            header_frame,
            text="💾 Save Template",
            font=("Segoe UI", 22, "bold"),
            text_color=self.app.colors["accent"]
        )
        title_label.pack()
        
        desc_label = ctk.CTkLabel(
            header_frame,
            text=f"Save current configuration as a template ({len(self.pairs)} pair(s))",
            font=("Segoe UI", 13),
            text_color=self.app.colors["text_secondary"]
        )
        desc_label.pack(pady=(8, 0))
        
        # Form frame
        form_frame = ctk.CTkFrame(dialog, fg_color=self.app.colors["card"], corner_radius=12)
        form_frame.pack(fill="both", expand=True, padx=25, pady=(0, 15))
        
        # Name field
        name_frame = ctk.CTkFrame(form_frame, fg_color="transparent")
        name_frame.pack(fill="x", padx=20, pady=(20, 10))
        
        name_label = ctk.CTkLabel(
            name_frame,
            text="Template Name *",
            font=("Segoe UI", 13, "bold"),
            text_color=self.app.colors["text"]
        )
        name_label.pack(anchor="w", pady=(0, 5))
        
        name_entry = ctk.CTkEntry(
            name_frame,
            placeholder_text="Enter template name...",
            height=40,
            font=("Segoe UI", 13),
            fg_color=self.app.colors["bg"],
            border_color=self.app.colors["border"]
        )
        name_entry.pack(fill="x")
        name_entry.focus_set()
        setup_clipboard_support(name_entry)
        
        # Notes field
        notes_frame = ctk.CTkFrame(form_frame, fg_color="transparent")
        notes_frame.pack(fill="both", expand=True, padx=20, pady=(10, 20))
        
        notes_label = ctk.CTkLabel(
            notes_frame,
            text="Notes (optional)",
            font=("Segoe UI", 13, "bold"),
            text_color=self.app.colors["text"]
        )
        notes_label.pack(anchor="w", pady=(0, 5))
        
        notes_textbox = ctk.CTkTextbox(
            notes_frame,
            height=100,
            font=("Segoe UI", 12),
            fg_color=self.app.colors["bg"],
            border_color=self.app.colors["border"],
            wrap="word"
        )
        notes_textbox.pack(fill="both", expand=True)
        setup_clipboard_support(notes_textbox)
        
        # Buttons
        buttons_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        buttons_frame.pack(pady=(0, 25), padx=25, fill="x")
        
        def save_template():
            name = name_entry.get().strip()
            if not name:
                messagebox.showwarning("Invalid Name", "Please enter a template name.")
                return
            
            notes = notes_textbox.get("1.0", "end-1c").strip()
            
            try:
                # Sync prompts from UI widgets to pairs before saving
                pairs_to_save = []
                for widget in self.pairs_container.winfo_children():
                    if hasattr(widget, 'pair_data') and hasattr(widget, 'prompt_widget'):
                        pair = widget.pair_data
                        prompt = widget.prompt_widget.get("1.0", "end-1c").strip()
                        from copy import deepcopy
                        pair_copy = deepcopy(pair)
                        pair_copy.prompt = prompt
                        pairs_to_save.append(pair_copy)
                
                if not pairs_to_save:
                    pairs_to_save = self.pairs
                
                template_service = get_batch_template_service()
                pairing_mode_str = self.pairing_mode.value if hasattr(self.pairing_mode, 'value') else str(self.pairing_mode)
                template = template_service.create_template(
                    name=name,
                    image_pairs=pairs_to_save,
                    pairing_mode=pairing_mode_str,
                    notes=notes
                )
                dialog.destroy()
                messagebox.showinfo("Success", f"✅ Template '{name}' saved!\n{len(pairs_to_save)} pair(s) saved.")
                self.logger.info("Template saved", template_id=template.template_id, name=name, pair_count=len(pairs_to_save))
            except Exception as e:
                self.logger.error("Failed to save template", error=str(e))
                messagebox.showerror("Error", f"Failed to save template:\n{str(e)}")
        
        save_btn = ctk.CTkButton(
            buttons_frame,
            text="💾 Save",
            font=("Segoe UI", 16, "bold"),
            fg_color=self.app.colors["accent"],
            hover_color=self.app.colors["accent_hover"],
            width=150,
            height=45,
            corner_radius=10,
            command=save_template
        )
        save_btn.pack(side="right", padx=(10, 0))
        
        cancel_btn = ctk.CTkButton(
            buttons_frame,
            text="Cancel",
            font=("Segoe UI", 14),
            fg_color=self.app.colors["secondary"],
            hover_color=self.app.colors["secondary_hover"],
            width=120,
            height=45,
            corner_radius=10,
            command=dialog.destroy
        )
        cancel_btn.pack(side="left")
        
        # Bind Enter to save
        dialog.bind("<Return>", lambda e: save_template())
        dialog.bind("<Escape>", lambda e: dialog.destroy())
    
    def _load_template(self):
        """Load a saved template with enhanced UI - search, filter, preview, and more."""
        template_service = get_batch_template_service()
        all_templates = template_service.get_all_templates()
        
        if not all_templates:
            messagebox.showinfo("No Templates", "No saved templates found.\n\nCreate a template by saving your current pairing configuration.")
            return
        
        dialog = Toplevel(self.app)
        dialog.title("📂 Template Manager")
        dialog.geometry("900x700")
        dialog.configure(bg=self.app.colors["bg"])
        dialog.transient(self.app)
        dialog.grab_set()
        
        # Center the dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (900 // 2)
        y = (dialog.winfo_screenheight() // 2) - (700 // 2)
        dialog.geometry(f"900x700+{x}+{y}")
        
        # Header with search and filters
        header_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        header_frame.pack(pady=(20, 15), padx=25, fill="x")
        
        title_label = ctk.CTkLabel(
            header_frame,
            text="📂 Template Manager",
            font=("Segoe UI", 24, "bold"),
            text_color=self.app.colors["accent"]
        )
        title_label.pack(side="left")
        
        count_label = ctk.CTkLabel(
            header_frame,
            text=f"({len(all_templates)} templates)",
            font=("Segoe UI", 13),
            text_color=self.app.colors["text_secondary"]
        )
        count_label.pack(side="left", padx=(10, 0))
        
        # Search and filter bar
        search_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        search_frame.pack(fill="x", padx=25, pady=(0, 15))
        
        search_entry = ctk.CTkEntry(
            search_frame,
            placeholder_text="🔍 Search templates by name, notes, or mode...",
            height=40,
            font=("Segoe UI", 13),
            fg_color=self.app.colors["card"],
            border_color=self.app.colors["border"]
        )
        search_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        setup_clipboard_support(search_entry)
        
        # Sort dropdown
        sort_var = ctk.StringVar(value="Newest First")
        sort_menu = ctk.CTkOptionMenu(
            search_frame,
            values=["Newest First", "Oldest First", "Name (A-Z)", "Name (Z-A)", "Most Pairs", "Fewest Pairs"],
            variable=sort_var,
            width=150,
            height=40,
            font=("Segoe UI", 12),
            fg_color=self.app.colors["card"],
            button_color=self.app.colors["accent"]
        )
        sort_menu.pack(side="right")
        
        # Scrollable list frame
        list_frame = ctk.CTkScrollableFrame(
            dialog,
            fg_color=self.app.colors["card"],
            corner_radius=12,
            border_width=1,
            border_color=self.app.colors["border"]
        )
        list_frame.pack(fill="both", expand=True, padx=25, pady=(0, 15))
        
        # Template selection variable
        selected_template = [None]
        template_cards = {}  # Store card widgets for highlighting
        
        def filter_and_sort_templates():
            """Filter and sort templates based on search and sort criteria."""
            query = search_entry.get().lower().strip()
            sort_value = sort_var.get()
            
            # Filter templates
            filtered = all_templates
            if query:
                filtered = [
                    t for t in all_templates
                    if query in t.name.lower()
                    or (t.notes and query in t.notes.lower())
                    or query in t.pairing_mode.lower()
                ]
            
            # Sort templates
            if sort_value == "Newest First":
                # Convert ISO string to datetime for proper sorting
                from datetime import datetime
                filtered = sorted(
                    filtered, 
                    key=lambda t: datetime.fromisoformat(t.created_at.replace('Z', '+00:00')) if isinstance(t.created_at, str) and 'T' in t.created_at else (datetime.fromisoformat(t.created_at) if isinstance(t.created_at, str) else datetime.min),
                    reverse=True
                )
            elif sort_value == "Oldest First":
                # Convert ISO string to datetime for proper sorting
                from datetime import datetime
                filtered = sorted(
                    filtered, 
                    key=lambda t: datetime.fromisoformat(t.created_at.replace('Z', '+00:00')) if isinstance(t.created_at, str) and 'T' in t.created_at else (datetime.fromisoformat(t.created_at) if isinstance(t.created_at, str) else datetime.min)
                )
            elif sort_value == "Name (A-Z)":
                filtered = sorted(filtered, key=lambda t: t.name.lower())
            elif sort_value == "Name (Z-A)":
                filtered = sorted(filtered, key=lambda t: t.name.lower(), reverse=True)
            elif sort_value == "Most Pairs":
                filtered = sorted(filtered, key=lambda t: len(t.image_pairs), reverse=True)
            elif sort_value == "Fewest Pairs":
                filtered = sorted(filtered, key=lambda t: len(t.image_pairs))
            
            # Update count
            count_label.configure(text=f"({len(filtered)} of {len(all_templates)} templates)")
            
            # Clear existing cards
            for widget in list_frame.winfo_children():
                widget.destroy()
            template_cards.clear()
            
            # Create template cards
            for template in filtered:
                template_card = ctk.CTkFrame(
                    list_frame,
                    fg_color=self.app.colors["card"],
                    corner_radius=12,
                    border_width=2,
                    border_color=self.app.colors["border"]
                )
                template_card.pack(fill="x", padx=10, pady=8)
                template_cards[template.template_id] = template_card
                
                # Main content frame
                content_frame = ctk.CTkFrame(template_card, fg_color="transparent")
                content_frame.pack(fill="x", padx=15, pady=12)
                
                # Left side: Info
                left_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
                left_frame.pack(side="left", fill="both", expand=True)
                
                # Template name
                name_label = ctk.CTkLabel(
                    left_frame,
                    text=template.name,
                    font=("Segoe UI", 18, "bold"),
                    text_color=self.app.colors["text"],
                    anchor="w"
                )
                name_label.pack(anchor="w", pady=(0, 8))
                
                # Metadata row
                meta_frame = ctk.CTkFrame(left_frame, fg_color="transparent")
                meta_frame.pack(fill="x", pady=(0, 6))
                
                pair_count = len(template.image_pairs)
                created_date = template.created_at[:10] if len(template.created_at) >= 10 else template.created_at
                mode_display = template.pairing_mode.capitalize()
                
                # Pair count badge
                pair_badge = ctk.CTkLabel(
                    meta_frame,
                    text=f"📸 {pair_count} pair{'s' if pair_count != 1 else ''}",
                    font=("Segoe UI", 11, "bold"),
                    text_color="#FFFFFF",
                    fg_color=self.app.colors["accent"],
                    corner_radius=6,
                    width=100,
                    height=24
                )
                pair_badge.pack(side="left", padx=(0, 8))
                
                # Mode badge
                mode_badge = ctk.CTkLabel(
                    meta_frame,
                    text=f"🎯 {mode_display}",
                    font=("Segoe UI", 11),
                    text_color=self.app.colors["text_secondary"],
                    fg_color=self.app.colors["bg"],
                    corner_radius=6,
                    width=100,
                    height=24
                )
                mode_badge.pack(side="left", padx=(0, 8))
                
                # Date badge
                date_badge = ctk.CTkLabel(
                    meta_frame,
                    text=f"📅 {created_date}",
                    font=("Segoe UI", 11),
                    text_color=self.app.colors["text_secondary"],
                    fg_color=self.app.colors["bg"],
                    corner_radius=6,
                    width=100,
                    height=24
                )
                date_badge.pack(side="left")
                
                # Notes preview
                if template.notes:
                    notes_preview = template.notes[:80] + "..." if len(template.notes) > 80 else template.notes
                    notes_label = ctk.CTkLabel(
                        left_frame,
                        text=f"📝 {notes_preview}",
                        font=("Segoe UI", 11),
                        text_color=self.app.colors["text_secondary"],
                        anchor="w",
                        wraplength=500
                    )
                    notes_label.pack(anchor="w", pady=(4, 0))
                
                # Right side: Actions
                actions_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
                actions_frame.pack(side="right", padx=(15, 0))
                
                def select_template(t):
                    # Reset all borders
                    for card in template_cards.values():
                        card.configure(border_color=self.app.colors["border"])
                    # Highlight selected
                    template_cards[t.template_id].configure(border_color=self.app.colors["accent"])
                    selected_template[0] = t
                
                # Select button (main action)
                select_btn = ctk.CTkButton(
                    actions_frame,
                    text="✓ Load",
                    font=("Segoe UI", 13, "bold"),
                    fg_color=self.app.colors["accent"],
                    hover_color=self.app.colors["accent_hover"],
                    width=100,
                    height=36,
                    corner_radius=8,
                    command=lambda t=template: select_template(t)
                )
                select_btn.pack(pady=(0, 6))
                
                # Preview button
                def preview_template(t):
                    preview_dialog = Toplevel(dialog)
                    preview_dialog.title(f"Preview: {t.name}")
                    preview_dialog.geometry("500x400")
                    preview_dialog.configure(bg=self.app.colors["bg"])
                    preview_dialog.transient(dialog)
                    
                    preview_frame = ctk.CTkScrollableFrame(preview_dialog, fg_color=self.app.colors["card"])
                    preview_frame.pack(fill="both", expand=True, padx=20, pady=20)
                    
                    # Template details
                    ctk.CTkLabel(
                        preview_frame,
                        text=t.name,
                        font=("Segoe UI", 20, "bold"),
                        text_color=self.app.colors["accent"]
                    ).pack(anchor="w", pady=(0, 10))
                    
                    info_text = f"Pairs: {len(t.image_pairs)}\nMode: {t.pairing_mode.capitalize()}\nCreated: {t.created_at[:10] if len(t.created_at) >= 10 else t.created_at}"
                    if t.notes:
                        info_text += f"\n\nNotes:\n{t.notes}"
                    
                    ctk.CTkLabel(
                        preview_frame,
                        text=info_text,
                        font=("Segoe UI", 12),
                        text_color=self.app.colors["text"],
                        anchor="w",
                        justify="left",
                        wraplength=450
                    ).pack(anchor="w", fill="x")
                    
                    ctk.CTkButton(
                        preview_dialog,
                        text="Close",
                        command=preview_dialog.destroy
                    ).pack(pady=10)
                
                preview_btn = ctk.CTkButton(
                    actions_frame,
                    text="👁️ Preview",
                    font=("Segoe UI", 11),
                    fg_color=self.app.colors["secondary"],
                    hover_color=self.app.colors["secondary_hover"],
                    width=100,
                    height=32,
                    corner_radius=8,
                    command=lambda t=template: preview_template(t)
                )
                preview_btn.pack()
            
            # Update selected template highlight if one was selected
            if selected_template[0] and selected_template[0].template_id in template_cards:
                template_cards[selected_template[0].template_id].configure(border_color=self.app.colors["accent"])
        
        # Bind search and sort
        search_entry.bind("<KeyRelease>", lambda e: filter_and_sort_templates())
        sort_var.trace("w", lambda *args: filter_and_sort_templates())
        
        # Initial render
        filter_and_sort_templates()
        
        # Buttons frame
        buttons_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        buttons_frame.pack(pady=(0, 20), padx=25, fill="x")
        
        def load_selected():
            if not selected_template[0]:
                messagebox.showwarning("No Selection", "Please select a template first!")
                return
            
            template = selected_template[0]
            try:
                pairs, mode = template_service.load_template_to_pairs(template.template_id)
                self._save_state_for_undo()
                
                # Set mode first
                if mode == "sequential":
                    self.mode_var.set("sequential")
                    self.pairing_mode = PairingMode.SEQUENTIAL
                elif mode == "random":
                    self.mode_var.set("random")
                    self.pairing_mode = PairingMode.RANDOM
                else:
                    self.mode_var.set("manual")
                    self.pairing_mode = PairingMode.MANUAL
                
                # Set pairs after mode - this ensures loaded pairs are preserved
                self.pairs = pairs
                self._all_pairs = pairs.copy()
                
                # Force refresh without regeneration by temporarily marking as loaded
                self._is_loading_template = True
                self._refresh_pairs()
                self._is_loading_template = False
                dialog.destroy()
                messagebox.showinfo("Success", f"✅ Template '{template.name}' loaded!\n{len(pairs)} pair(s) ready.")
                self.logger.info("Template loaded", template_id=template.template_id, name=template.name, pair_count=len(pairs))
            except Exception as e:
                self.logger.error("Failed to load template", error=str(e), template_id=template.template_id)
                messagebox.showerror("Error", f"Failed to load template:\n{str(e)}")
        
        def delete_selected():
            if not selected_template[0]:
                messagebox.showwarning("No Selection", "Please select a template to delete!")
                return
            
            template = selected_template[0]
            if not messagebox.askyesno(
                "Confirm Delete",
                f"Are you sure you want to delete template '{template.name}'?\n\nThis action cannot be undone.",
                icon="warning"
            ):
                return
            
            try:
                if template_service.delete_template(template.template_id):
                    # Refresh templates
                    all_templates[:] = template_service.get_all_templates()
                    selected_template[0] = None
                    filter_and_sort_templates()
                    messagebox.showinfo("Success", f"Template '{template.name}' deleted.")
                    self.logger.info("Template deleted", template_id=template.template_id, name=template.name)
                else:
                    messagebox.showerror("Error", "Failed to delete template.")
            except Exception as e:
                self.logger.error("Failed to delete template", error=str(e))
                messagebox.showerror("Error", f"Failed to delete template:\n{str(e)}")
        
        # Load button
        load_btn = ctk.CTkButton(
            buttons_frame,
            text="✅ Load Template",
            font=("Segoe UI", 16, "bold"),
            fg_color=self.app.colors["accent"],
            hover_color=self.app.colors["accent_hover"],
            width=180,
            height=45,
            corner_radius=10,
            command=load_selected
        )
        load_btn.pack(side="right", padx=(10, 0))
        
        # Delete button
        delete_btn = ctk.CTkButton(
            buttons_frame,
            text="🗑️ Delete",
            font=("Segoe UI", 14),
            fg_color="#E50914",
            hover_color="#F40612",
            width=120,
            height=45,
            corner_radius=10,
            command=delete_selected
        )
        delete_btn.pack(side="right", padx=(0, 10))
        
        # Cancel button
        cancel_btn = ctk.CTkButton(
            buttons_frame,
            text="Cancel",
            font=("Segoe UI", 14),
            fg_color=self.app.colors["secondary"],
            hover_color=self.app.colors["secondary_hover"],
            width=120,
            height=45,
            corner_radius=10,
            command=dialog.destroy
        )
        cancel_btn.pack(side="left")
        
        # Bind Enter key to load
        dialog.bind("<Return>", lambda e: load_selected())
        dialog.bind("<Escape>", lambda e: dialog.destroy())
        dialog.bind("<Control-f>", lambda e: search_entry.focus_set())
    
    def _export_pairs(self):
        """Export current pairs to JSON file."""
        if not self.pairs:
            messagebox.showinfo("No Pairs", "No pairs to export.")
            return
        
        filepath = filedialog.asksaveasfilename(
            title="Export Pairs",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialdir=str(self._last_dir)
        )
        
        if not filepath:
            return
        
        try:
            export_data = {
                "version": "1.0",
                "pairing_mode": self.pairing_mode.value if hasattr(self.pairing_mode, 'value') else str(self.pairing_mode),
                "pairs": []
            }
            
            # Collect current prompts from UI
            for widget in self.pairs_container.winfo_children():
                if hasattr(widget, 'pair_data') and hasattr(widget, 'prompt_widget'):
                    pair = widget.pair_data
                    prompt = widget.prompt_widget.get("1.0", "end-1c").strip()
                    
                    pair_data = {
                        "images": [str(img) for img in pair.images],
                        "prompt": prompt,
                        "enabled": pair.enabled
                    }
                    export_data["pairs"].append(pair_data)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            
            self._last_dir = Path(filepath).parent
            messagebox.showinfo("Success", f"Exported {len(export_data['pairs'])} pair(s) to:\n{filepath}")
            self.logger.info("Pairs exported", filepath=filepath, count=len(export_data['pairs']))
            
        except Exception as e:
            self.logger.error("Export failed", error=str(e))
            messagebox.showerror("Export Error", f"Failed to export pairs:\n{str(e)}")
    
    def _import_pairs(self):
        """Import pairs from JSON file."""
        filepath = filedialog.askopenfilename(
            title="Import Pairs",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialdir=str(self._last_dir)
        )
        
        if not filepath:
            return
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                import_data = json.load(f)
            
            # Validate structure
            if not isinstance(import_data, dict) or "pairs" not in import_data:
                raise TemplateError("Invalid file format: missing 'pairs' key")
            
            imported_pairs = []
            errors = []
            
            for idx, pair_data in enumerate(import_data["pairs"]):
                try:
                    # Validate required fields
                    if "images" not in pair_data or not isinstance(pair_data["images"], list):
                        errors.append(f"Pair {idx+1}: missing or invalid 'images' field")
                        continue
                    
                    # Convert image paths to Path objects and validate
                    image_paths = []
                    for img_path_str in pair_data["images"]:
                        img_path = Path(img_path_str)
                        is_valid, error = self.image_service.validate_image(img_path)
                        if not is_valid:
                            errors.append(f"Pair {idx+1}, image {img_path.name}: {error}")
                            continue
                        image_paths.append(img_path)
                    
                    if not image_paths:
                        errors.append(f"Pair {idx+1}: no valid images")
                        continue
                    
                    # Create ImagePair
                    pair = ImagePair(
                        images=image_paths,
                        prompt=pair_data.get("prompt", ""),
                        enabled=pair_data.get("enabled", True)
                    )
                    imported_pairs.append(pair)
                    
                except Exception as e:
                    errors.append(f"Pair {idx+1}: {str(e)}")
            
            if errors:
                error_msg = f"Some pairs had errors:\n\n" + "\n".join(errors[:10])
                if len(errors) > 10:
                    error_msg += f"\n... and {len(errors) - 10} more errors"
                messagebox.showwarning("Import Warnings", error_msg)
            
            if not imported_pairs:
                messagebox.showwarning("Import Failed", "No valid pairs could be imported.")
                return
            
            # Ask user how to import
            import_mode = messagebox.askyesno(
                "Import Mode",
                f"Import {len(imported_pairs)} pair(s)?\n\n"
                "Yes: Replace current pairs\n"
                "No: Append to current pairs"
            )
            
            self._save_state_for_undo()
            
            if import_mode:
                # Replace
                self.pairs = imported_pairs
                # Set mode if specified
                if "pairing_mode" in import_data:
                    mode_str = import_data["pairing_mode"]
                    if mode_str == "sequential":
                        self.mode_var.set("sequential")
                        self.pairing_mode = PairingMode.SEQUENTIAL
                    elif mode_str == "random":
                        self.mode_var.set("random")
                        self.pairing_mode = PairingMode.RANDOM
                    else:
                        self.mode_var.set("manual")
                        self.pairing_mode = PairingMode.MANUAL
            else:
                # Append
                self.pairs.extend(imported_pairs)
                # Switch to manual mode when appending
                self.mode_var.set("manual")
                self.pairing_mode = PairingMode.MANUAL
            
            self._refresh_pairs()
            self._last_dir = Path(filepath).parent
            
            msg = f"Successfully imported {len(imported_pairs)} pair(s)!"
            if errors:
                msg += f"\n({len(errors)} error(s) encountered)"
            messagebox.showinfo("Import Success", msg)
            self.logger.info("Pairs imported", filepath=filepath, count=len(imported_pairs), errors=len(errors))
            
        except json.JSONDecodeError as e:
            messagebox.showerror("Import Error", f"Invalid JSON file:\n{str(e)}")
        except TemplateError as e:
            messagebox.showerror("Import Error", str(e))
        except Exception as e:
            self.logger.error("Import failed", error=str(e))
            messagebox.showerror("Import Error", f"Failed to import pairs:\n{str(e)}")
