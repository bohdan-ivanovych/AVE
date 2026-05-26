"""Qwen Video Generation view with image+prompt pairs."""

import customtkinter as ctk
import threading
import asyncio
from pathlib import Path
from typing import List, Optional, TYPE_CHECKING
from tkinter import messagebox, filedialog
from dataclasses import dataclass

from src.config import AppConfig
from src.services.logger import get_logger_service
from src.services.image_service import ImageService
from src.services.qwen_service import QwenService
from src.services.notifications import get_notification_service
from src.gui.tooltip import create_tooltip
from src.gui.clipboard_utils import setup_clipboard_support
from src.gui.error_handler import show_error, show_warning, show_info, safe_execute
from src.services.settings_service import get_settings_service
from core import PROFILES

if TYPE_CHECKING:
    from src.gui.app import AVEApp


@dataclass
class VideoPair:
    """Represents an image+prompt pair for video generation."""
    image: Path
    prompt: str
    enabled: bool = True


class QwenView(ctk.CTkFrame):
    """Qwen Video Generation view with pairing interface."""
    
    def __init__(self, parent, config: AppConfig, app: "AVEApp"):
        super().__init__(parent, fg_color=app.colors["bg"])
        self.config = config
        self.app = app
        self.logger = get_logger_service().get_logger("qwen_view")
        self.image_service = ImageService(config)
        self.qwen_service = QwenService(config)
        
        self.pairs: List[VideoPair] = []
        # Start from outpaint_dir since qwen typically uses outpainted images
        self._last_dir: Path = self.config.outpaint_dir if hasattr(self.config, 'outpaint_dir') and self.config.outpaint_dir.exists() else (self.config.assets_dir if hasattr(self.config, 'assets_dir') else Path('.'))
        
        # Load selected profiles from settings (defaults to all if not set)
        self.settings_service = get_settings_service()
        saved_profiles = self.settings_service.get_selected_profiles()
        available_profiles = self.settings_service.get_available_profiles()
        
        # Use selected profiles if set, otherwise use available profiles, otherwise use PROFILES
        if saved_profiles:
            self.selected_profiles: List[str] = saved_profiles
        elif available_profiles:
            self.selected_profiles: List[str] = available_profiles
        else:
            self.selected_profiles: List[str] = list(PROFILES) if PROFILES else []
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup Qwen video UI with modern design."""
        # Header with improved typography
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.pack(pady=(30, 20))
        
        # Main title with gradient effect
        title_container = ctk.CTkFrame(header_frame, fg_color="transparent")
        title_container.pack()
        
        header = ctk.CTkLabel(
            title_container,
            text="🎬 Qwen Video Generation",
            font=("Segoe UI", 36, "bold"),
            text_color="#9333EA"
        )
        header.pack()
        
        subtitle = ctk.CTkLabel(
            title_container,
            text="Create stunning videos from images with AI-powered generation",
            font=("Segoe UI", 14),
            text_color=self.app.colors["text_secondary"]
        )
        subtitle.pack(pady=(8, 0))
        
        # Pairs header with better styling
        pairs_header = ctk.CTkFrame(self, fg_color="transparent")
        pairs_header.pack(fill="x", padx=50, pady=(25, 10))
        
        header_left = ctk.CTkFrame(pairs_header, fg_color="transparent")
        header_left.pack(side="left", fill="x", expand=True)
        
        pairs_title = ctk.CTkLabel(
            header_left,
            text="📸 Image + Prompt Pairs",
            font=("Segoe UI", 20, "bold"),
            text_color=self.app.colors["text"]
        )
        pairs_title.pack(side="left")
        
        self.pairs_count_label = ctk.CTkLabel(
            header_left,
            text="0 pairs",
            font=("Segoe UI", 14),
            text_color=self.app.colors["text_secondary"]
        )
        self.pairs_count_label.pack(side="left", padx=(12, 0))
        
        # Scrollable pairs area with enhanced design
        scroll_frame = ctk.CTkScrollableFrame(
            self,
            fg_color=self.app.colors["card"],
            width=1200,
            height=520,
            corner_radius=16,
            border_width=1,
            border_color=self.app.colors["border"]
        )
        scroll_frame.pack(fill="both", expand=True, padx=50, pady=15)
        self.pairs_container = scroll_frame
        
        # Enable drag and drop
        self._setup_drag_drop()
        
        # Profile info (profiles are configured in Settings)
        profile_info_frame = ctk.CTkFrame(self, fg_color="transparent")
        profile_info_frame.pack(fill="x", padx=50, pady=(20, 15))
        
        self.profile_info_label = ctk.CTkLabel(
            profile_info_frame,
            text="",
            font=("Segoe UI", 13),
            text_color=self.app.colors["text_secondary"]
        )
        self.profile_info_label.pack(side="left")
        self._update_profile_info()
        
        settings_btn = ctk.CTkButton(
            profile_info_frame,
            text="⚙️ Open Settings",
            font=("Segoe UI", 12),
            fg_color=self.app.colors["secondary"],
            hover_color=self.app.colors["secondary_hover"],
            width=120,
            height=32,
            corner_radius=8,
            command=self._open_settings
        )
        settings_btn.pack(side="right")
        
        # Action buttons with improved layout
        action_frame = ctk.CTkFrame(self, fg_color="transparent")
        action_frame.pack(fill="x", padx=50, pady=(15, 25))
        
        # Left side: action buttons
        left_actions = ctk.CTkFrame(action_frame, fg_color="transparent")
        left_actions.pack(side="left")
        
        add_pair_btn = ctk.CTkButton(
            left_actions,
            text="➕ Add Pair",
            font=("Segoe UI", 16, "bold"),
            fg_color=self.app.colors["secondary"],
            hover_color=self.app.colors["secondary_hover"],
            width=160,
            height=52,
            corner_radius=10,
            command=self._add_pair
        )
        add_pair_btn.pack(side="left", padx=(0, 12))
        create_tooltip(add_pair_btn, "Add a new image+prompt pair")
        
        apply_prompt_btn = ctk.CTkButton(
            left_actions,
            text="📋 Apply to All",
            font=("Segoe UI", 15),
            fg_color=self.app.colors["secondary"],
            hover_color=self.app.colors["secondary_hover"],
            width=160,
            height=52,
            corner_radius=10,
            command=self._apply_prompt_to_all
        )
        apply_prompt_btn.pack(side="left", padx=(0, 20))
        create_tooltip(apply_prompt_btn, "Apply the same prompt to all pairs")
        
        # Progress section in the middle
        progress_frame = ctk.CTkFrame(action_frame, fg_color="transparent")
        progress_frame.pack(side="left", padx=30, expand=True)
        
        progress_top = ctk.CTkFrame(progress_frame, fg_color="transparent")
        progress_top.pack(fill="x", pady=(0, 8))
        
        self.status_indicator = ctk.CTkLabel(
            progress_top,
            text="●",
            font=("Segoe UI", 18),
            text_color=self.app.colors["text_secondary"]
        )
        self.status_indicator.pack(side="left", padx=(0, 10))
        
        self.progress_label = ctk.CTkLabel(
            progress_top,
            text="Ready",
            font=("Segoe UI", 15, "bold"),
            text_color=self.app.colors["text_secondary"]
        )
        self.progress_label.pack(side="left")
        
        self.progress_bar = ctk.CTkProgressBar(
            progress_frame,
            width=360,
            height=28,
            progress_color="#9333EA",
            corner_radius=14,
            fg_color=self.app.colors["card"]
        )
        self.progress_bar.pack(pady=(0, 6))
        self.progress_bar.set(0)
        
        self.task_counter = ctk.CTkLabel(
            progress_frame,
            text="0 tasks",
            font=("Segoe UI", 12),
            text_color=self.app.colors["text_muted"]
        )
        self.task_counter.pack()
        
        # Right side: main action button
        self.generate_btn = ctk.CTkButton(
            action_frame,
            text="🚀 Generate Videos",
            font=("Segoe UI", 20, "bold"),
            fg_color="#9333EA",
            hover_color="#A855F7",
            width=260,
            height=64,
            corner_radius=14,
            command=self._on_generate
        )
        self.generate_btn.pack(side="right")
        create_tooltip(self.generate_btn, "Generate all enabled video pairs")
    
    def _setup_drag_drop(self):
        """Setup drag and drop for images."""
        def on_drop(event):
            try:
                # Get dropped files
                files = self.tk.splitlist(event.data)
                for file in files:
                    if file.startswith('{') and file.endswith('}'):
                        file = file[1:-1]  # Remove braces
                    image_path = Path(file)
                    if image_path.exists():
                        is_valid, error = self.image_service.validate_image(image_path)
                        if is_valid:
                            pair = VideoPair(
                                image=image_path,
                                prompt="Create a dynamic video from this image"
                            )
                            self.pairs.append(pair)
                self._refresh_pairs()
            except Exception as e:
                self.logger.warning("Drag and drop error", error=str(e))
        
        # Bind drag and drop events
        self.pairs_container.bind("<Button-1>", lambda e: self.pairs_container.focus_set())
        try:
            # Windows drag and drop
            self.pairs_container.tk.call('package', 'require', 'tkdnd')
            self.pairs_container.tk.call('tkdnd::drop_target', 'register', self.pairs_container, 'DND_Files')
            self.pairs_container.bind('<<Drop:DND_Files>>', on_drop)
        except Exception:
            # Fallback if tkdnd not available
            pass
    
    def _add_pair(self):
        """Add a new image+prompt pair (or multiple pairs if multiple images selected)."""
        # Select images (can select multiple)
        files = filedialog.askopenfilenames(
            title="Select Image(s)",
            filetypes=[
                ("Image files", "*.jpg *.jpeg *.png *.webp"),
                ("All files", "*.*")
            ],
            initialdir=str(self._last_dir)
        )
        
        if not files:
            return
        
        # Validate and add all selected images
        added = 0
        invalid_files = []
        
        for file in files:
            image_path = Path(file)
            
            # Validate image
            is_valid, error = self.image_service.validate_image(image_path)
            if not is_valid:
                invalid_files.append(f"{image_path.name}: {error}")
                continue
            
            # Create pair with default prompt
            pair = VideoPair(
                image=image_path,
                prompt="Create a dynamic video from this image"
            )
            self.pairs.append(pair)
            added += 1
            
            # Update last dir
            try:
                self._last_dir = image_path.parent
            except Exception:
                pass
        
        if invalid_files:
            error_msg = "Some files were invalid:\n\n" + "\n".join(invalid_files[:5])
            if len(invalid_files) > 5:
                error_msg += f"\n... and {len(invalid_files) - 5} more"
            show_warning("Invalid Files", error_msg, logger=self.logger)
        
        if added > 0:
            self._refresh_pairs()
    
    def _refresh_pairs(self):
        """Refresh pairs display."""
        # Clear container
        for widget in self.pairs_container.winfo_children():
            widget.destroy()
        
        # Update count
        enabled_count = sum(1 for p in self.pairs if p.enabled)
        self.pairs_count_label.configure(
            text=f"{len(self.pairs)} pairs ({enabled_count} enabled)"
        )
        
        # Display pairs
        if not self.pairs:
            # Enhanced empty state
            empty_frame = ctk.CTkFrame(self.pairs_container, fg_color="transparent")
            empty_frame.pack(expand=True, pady=80)
            
            empty_icon = ctk.CTkLabel(
                empty_frame,
                text="🎬",
                font=("Segoe UI", 64),
                text_color=self.app.colors["text_muted"]
            )
            empty_icon.pack(pady=(0, 20))
            
            empty_label = ctk.CTkLabel(
                empty_frame,
                text="No pairs yet",
                font=("Segoe UI", 18, "bold"),
                text_color=self.app.colors["text"]
            )
            empty_label.pack(pady=(0, 8))
            
            empty_hint = ctk.CTkLabel(
                empty_frame,
                text="Click 'Add Pair' or drag and drop images to get started",
                font=("Segoe UI", 14),
                text_color=self.app.colors["text_secondary"]
            )
            empty_hint.pack()
        else:
            for idx, pair in enumerate(self.pairs):
                self._create_pair_widget(idx, pair)
    
    def _create_pair_widget(self, idx: int, pair: VideoPair):
        """Create widget for a video pair with enhanced design."""
        pair_frame = ctk.CTkFrame(
            self.pairs_container,
            fg_color=self.app.colors["card"],
            corner_radius=14,
            border_width=1,
            border_color=self.app.colors["border"]
        )
        pair_frame.pack(fill="x", padx=18, pady=12)
        
        # Top row: Image preview and controls
        top_row = ctk.CTkFrame(pair_frame, fg_color="transparent")
        top_row.pack(fill="x", padx=18, pady=15)
        
        # Enable checkbox
        enabled_var = ctk.BooleanVar(value=pair.enabled)
        enabled_check = ctk.CTkCheckBox(
            top_row,
            text="",
            variable=enabled_var,
            command=lambda v=enabled_var, i=idx: self._toggle_pair(i, v)
        )
        enabled_check.pack(side="left", padx=(0, 10))
        
        # Image preview (thumbnail) with better styling
        preview_container = ctk.CTkFrame(top_row, fg_color="transparent")
        preview_container.pack(side="left", padx=(0, 15))
        
        try:
            from PIL import Image
            from customtkinter import CTkImage
            img = Image.open(pair.image)
            img.thumbnail((120, 120), Image.LANCZOS)
            ctk_img = CTkImage(light_image=img, dark_image=img, size=(120, 120))
            
            preview_bg = ctk.CTkFrame(
                preview_container,
                fg_color=self.app.colors["bg"],
                corner_radius=10,
                width=120,
                height=120
            )
            preview_bg.pack()
            preview_bg.pack_propagate(False)
            
            img_label = ctk.CTkLabel(
                preview_bg,
                text="",
                image=ctk_img,
                width=120,
                height=120
            )
            img_label.image = ctk_img  # Keep reference
            img_label.pack(expand=True)
        except Exception:
            # Fallback if image can't be loaded
            preview_bg = ctk.CTkFrame(
                preview_container,
                fg_color=self.app.colors["bg"],
                corner_radius=10,
                width=120,
                height=120
            )
            preview_bg.pack()
            preview_bg.pack_propagate(False)
            
            img_label = ctk.CTkLabel(
                preview_bg,
                text="🖼️",
                font=("Segoe UI", 48),
                width=120,
                height=120
            )
            img_label.pack(expand=True)
        
        # Image info with better typography
        info_frame = ctk.CTkFrame(top_row, fg_color="transparent")
        info_frame.pack(side="left", fill="x", expand=True, padx=(0, 15))
        
        img_name_label = ctk.CTkLabel(
            info_frame,
            text=pair.image.name,
            font=("Segoe UI", 15, "bold"),
            text_color=self.app.colors["text"],
            anchor="w"
        )
        img_name_label.pack(anchor="w", pady=(0, 6))
        
        img_path_label = ctk.CTkLabel(
            info_frame,
            text=str(pair.image.parent),
            font=("Segoe UI", 12),
            text_color=self.app.colors["text_muted"],
            anchor="w"
        )
        img_path_label.pack(anchor="w")
        
        # Change image button
        change_img_btn = ctk.CTkButton(
            top_row,
            text="📁 Change",
            font=("Segoe UI", 13),
            fg_color=self.app.colors["secondary"],
            hover_color=self.app.colors["secondary_hover"],
            width=110,
            height=40,
            corner_radius=8,
            command=lambda i=idx: self._change_image(i)
        )
        change_img_btn.pack(side="right", padx=(0, 10))
        
        # Remove button
        remove_btn = ctk.CTkButton(
            top_row,
            text="🗑️",
            font=("Segoe UI", 16),
            fg_color="#E50914",
            hover_color="#F40612",
            width=50,
            height=50,
            corner_radius=10,
            command=lambda i=idx: self._remove_pair(i)
        )
        remove_btn.pack(side="right")
        
        # Prompt input with better styling
        prompt_frame = ctk.CTkFrame(pair_frame, fg_color="transparent")
        prompt_frame.pack(fill="x", padx=18, pady=(0, 15))
        
        prompt_label = ctk.CTkLabel(
            prompt_frame,
            text="Video Prompt:",
            font=("Segoe UI", 14, "bold"),
            text_color=self.app.colors["text"]
        )
        prompt_label.pack(anchor="w", pady=(0, 8))
        
        prompt_entry = ctk.CTkTextbox(
            prompt_frame,
            height=85,
            font=("Segoe UI", 13),
            fg_color=self.app.colors["bg"],
            border_width=1,
            border_color=self.app.colors["border"],
            corner_radius=8
        )
        prompt_entry.insert("1.0", pair.prompt)
        prompt_entry.pack(fill="x")
        # Setup full clipboard support (Ctrl+V, Ctrl+C, Ctrl+X, right-click menu)
        setup_clipboard_support(prompt_entry)
        
        # Store reference
        pair_frame.pair_data = pair
        pair_frame.prompt_widget = prompt_entry
    
    def _toggle_pair(self, idx: int, var: ctk.BooleanVar):
        """Toggle pair enabled state."""
        if idx < len(self.pairs):
            self.pairs[idx].enabled = var.get()
    
    def _change_image(self, idx: int):
        """Change image for a pair."""
        if idx >= len(self.pairs):
            return
        
        files = filedialog.askopenfilename(
            title="Select New Image",
            filetypes=[
                ("Image files", "*.jpg *.jpeg *.png *.webp"),
                ("All files", "*.*")
            ],
            initialdir=str(self._last_dir)
        )
        
        if files:
            image_path = Path(files)
            is_valid, error = self.image_service.validate_image(image_path)
            if is_valid:
                self.pairs[idx].image = image_path
                self._refresh_pairs()
            else:
                messagebox.showerror("Invalid Image", f"Image validation failed: {error}")
    
    def _remove_pair(self, idx: int):
        """Remove a pair."""
        if idx < len(self.pairs):
            self.pairs.pop(idx)
            self._refresh_pairs()
    
    def _update_profile_info(self):
        """Update profile info label."""
        # Reload profiles from settings
        saved_profiles = self.settings_service.get_selected_profiles()
        available_profiles = self.settings_service.get_available_profiles()
        
        # Use selected profiles if set, otherwise use available profiles, otherwise use PROFILES
        if saved_profiles:
            self.selected_profiles = saved_profiles
        elif available_profiles:
            self.selected_profiles = available_profiles
        else:
            self.selected_profiles = list(PROFILES) if PROFILES else []
        
        count = len(self.selected_profiles)
        if hasattr(self, 'profile_info_label'):
            self.profile_info_label.configure(
                text=f"📋 Using {count} profile(s) (configure in Settings)"
            )
    
    def _open_settings(self):
        """Open settings."""
        self.app._switch_view("settings")
    
    def on_view_shown(self):
        """Called when view is shown - refresh profile info."""
        self._update_profile_info()
    
    def _apply_prompt_to_all(self):
        """Apply prompt from first pair to all pairs with enhanced dialog."""
        from tkinter import Toplevel
        from src.gui.clipboard_utils import setup_clipboard_support
        
        if not self.pairs:
            messagebox.showinfo("No Pairs", "Please add at least one pair first.")
            return
        
        # Get prompt from first pair
        first_prompt = self.pairs[0].prompt if self.pairs else ""
        
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
            text=f"Enter the prompt to apply to all {len(self.pairs)} pair(s). You can paste text here (Ctrl+V).",
            font=("Segoe UI", 13),
            text_color=self.app.colors["text_secondary"],
            wraplength=650
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
            
            # Apply to all pairs
            updated = 0
            for widget in self.pairs_container.winfo_children():
                if hasattr(widget, 'pair_data') and hasattr(widget, 'prompt_widget'):
                    widget.prompt_widget.delete("1.0", "end")
                    widget.prompt_widget.insert("1.0", prompt_text)
                    widget.pair_data.prompt = prompt_text
                    updated += 1
            
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
    
    def _on_generate(self):
        """Handle generate button click."""
        # Collect enabled pairs with prompts
        enabled_pairs = []
        invalid_pairs = []
        
        for widget in self.pairs_container.winfo_children():
            if hasattr(widget, 'pair_data') and hasattr(widget, 'prompt_widget'):
                pair = widget.pair_data
                prompt = widget.prompt_widget.get("1.0", "end-1c").strip()
                
                if pair.enabled:
                    if not prompt:
                        invalid_pairs.append("Missing prompt")
                        continue
                    
                    is_valid, error = self.image_service.validate_image(pair.image)
                    if not is_valid:
                        invalid_pairs.append(f"Invalid image: {pair.image.name}")
                        continue
                    
                    pair.prompt = prompt
                    enabled_pairs.append(pair)
        
        if invalid_pairs:
            error_msg = "Some enabled pairs have issues:\n\n" + "\n".join(invalid_pairs[:5])
            if len(invalid_pairs) > 5:
                error_msg += f"\n... and {len(invalid_pairs) - 5} more"
            messagebox.showwarning("Validation Errors", error_msg)
        
        if not enabled_pairs:
            show_warning(
                "No Valid Pairs",
                "Please enable at least one pair with:\n"
                "• A valid prompt\n"
                "• A valid image",
                logger=self.logger
            )
            return
        
        # Get selected profiles
        profiles = self.selected_profiles
        if not profiles:
            show_warning(
                "No Profiles Selected",
                "Please select at least one Chrome profile to use.",
                logger=self.logger
            )
            return
        
        # Update progress
        if hasattr(self, 'progress_label'):
            self.progress_label.configure(
                text=f"Starting {len(enabled_pairs)} video generation(s)...",
                text_color="#9333EA"
            )
        if hasattr(self, 'status_indicator'):
            self.status_indicator.configure(text="●", text_color="#9333EA")
        if hasattr(self, 'task_counter'):
            self.task_counter.configure(text=f"{len(enabled_pairs)} videos queued")
        
        self.logger.info("Starting video generation", pair_count=len(enabled_pairs))
        
        # Disable generate button
        if hasattr(self, 'generate_btn'):
            self.generate_btn.configure(state="disabled", text="Processing…")
        
        # Run generation in background thread
        def run_generation_thread():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                # Prepare data
                image_paths = [p.image for p in enabled_pairs]
                prompts = [p.prompt for p in enabled_pairs]
                
                # Run batch video generation
                results = loop.run_until_complete(
                    self.qwen_service.batch_generate_videos(
                        image_paths,
                        prompts,
                        profiles,
                        self.config.qwen_dir
                    )
                )
                
                # Count results
                successful = sum(1 for p in results if p is not None)
                failed = len(results) - successful
                
                # Update UI
                msg = f"✅ Video generation complete: {successful}/{len(enabled_pairs)} succeeded"
                if failed > 0:
                    msg = f"⚠️ Video generation complete: {successful}/{len(enabled_pairs)} succeeded, {failed} failed"
                
                self.app.after(0, lambda: messagebox.showinfo("Video Generation Complete", msg, icon="info"))
                self.app.after(0, lambda: self._update_progress(successful, failed, len(enabled_pairs)))
                
                # Re-enable button
                if hasattr(self, 'generate_btn'):
                    self.app.after(0, lambda: self.generate_btn.configure(state="normal", text="🚀 Generate Videos"))
                
                # Send notification
                try:
                    notifier = get_notification_service()
                    notifier.notify("Video Generation Complete", msg, duration=6)
                except Exception:
                    pass
                
                loop.close()
                
            except Exception as e:
                self.logger.error("Video generation error", error=str(e), exc_info=True)
                self.app.after(0, lambda: messagebox.showerror(
                    "Video Generation Error",
                    f"An error occurred:\n{e}",
                    icon="error"
                ))
                if hasattr(self, 'generate_btn'):
                    self.app.after(0, lambda: self.generate_btn.configure(state="normal", text="🚀 Generate Videos"))
        
        thread = threading.Thread(target=run_generation_thread, daemon=True)
        thread.start()
    
    def _update_progress(self, finished: int, failed: int, total: int):
        """Update progress display."""
        if hasattr(self, 'progress_label'):
            if total == 0:
                self.progress_label.configure(text="Ready", text_color=self.app.colors["text_secondary"])
                if hasattr(self, 'status_indicator'):
                    self.status_indicator.configure(text="●", text_color=self.app.colors["text_secondary"])
            elif finished + failed < total:
                self.progress_label.configure(
                    text=f"Processing: {finished + failed}/{total}",
                    text_color="#9333EA"
                )
                if hasattr(self, 'status_indicator'):
                    self.status_indicator.configure(text="●", text_color="#9333EA")
            else:
                if failed == 0:
                    self.progress_label.configure(
                        text=f"✅ Complete: {finished}/{total}",
                        text_color=self.app.colors["success"]
                    )
                    if hasattr(self, 'status_indicator'):
                        self.status_indicator.configure(text="●", text_color=self.app.colors["success"])
                else:
                    self.progress_label.configure(
                        text=f"⚠️ Done: {finished}/{total} ({failed} failed)",
                        text_color=self.app.colors["warning"]
                    )
                    if hasattr(self, 'status_indicator'):
                        self.status_indicator.configure(text="●", text_color=self.app.colors["warning"])
        
        if hasattr(self, 'progress_bar') and total > 0:
            progress = (finished + failed) / total
            self.progress_bar.set(progress)
        
        if hasattr(self, 'task_counter'):
            self.task_counter.configure(text=f"{finished} succeeded, {failed} failed, {total - finished - failed} pending")
