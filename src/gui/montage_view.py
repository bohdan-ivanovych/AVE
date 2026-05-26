"""Video montage view for creating video compilations."""

import customtkinter as ctk
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional
from datetime import datetime
import tkinter as tk
from tkinter import filedialog

from src.config import AppConfig
from src.services.logger import get_logger_service
from src.services.montage_service import MontageService, AudioSettings, AudioFitMode, MontageProgress

if TYPE_CHECKING:
    from src.gui.app import AVEApp


class VideoClipItem(ctk.CTkFrame):
    """UI component for a single video clip in the timeline."""
    
    def __init__(self, parent, video_path: Path, index: int, on_remove: callable, on_move_up: callable, on_move_down: callable, app):
        super().__init__(parent, fg_color=app.colors["card"], corner_radius=12, border_width=1, border_color=app.colors["border"])
        self.video_path = video_path
        self.index = index
        self.on_remove = on_remove
        self.on_move_up = on_move_up
        self.on_move_down = on_move_down
        self.app = app
        
        self._setup_ui()
        self._add_hover_effect()
    
    def _setup_ui(self):
        """Setup clip item UI."""
        self.pack_propagate(False)
        self.configure(height=80)
        
        # Info frame
        info_frame = ctk.CTkFrame(self, fg_color="transparent")
        info_frame.pack(side="left", fill="both", expand=True, padx=15, pady=10)
        
        # Index badge
        index_badge = ctk.CTkFrame(
            info_frame,
            fg_color=self.app.colors["accent"],
            corner_radius=8,
            width=32,
            height=32
        )
        index_badge.pack(side="left", padx=(0, 12))
        index_badge.pack_propagate(False)
        
        index_label = ctk.CTkLabel(
            index_badge,
            text=str(self.index + 1),
            font=("Segoe UI", 14, "bold"),
            text_color="#FFFFFF"
        )
        index_label.pack(expand=True)
        
        # File info
        file_info_frame = ctk.CTkFrame(info_frame, fg_color="transparent")
        file_info_frame.pack(side="left", fill="both", expand=True)
        
        filename = self.video_path.name
        if len(filename) > 40:
            filename = filename[:37] + "..."
        
        name_label = ctk.CTkLabel(
            file_info_frame,
            text=filename,
            font=(self.app.font_family, 14, "bold"),
            text_color=self.app.colors["text"],
            anchor="w"
        )
        name_label.pack(fill="x", pady=(0, 2))
        
        size_mb = self.video_path.stat().st_size / (1024 * 1024)
        size_text = f"{size_mb:.1f} MB"
        
        meta_label = ctk.CTkLabel(
            file_info_frame,
            text=size_text,
            font=(self.app.font_family_secondary, 11),
            text_color=self.app.colors["text_muted"],
            anchor="w"
        )
        meta_label.pack(fill="x")
        
        # Action buttons
        actions_frame = ctk.CTkFrame(self, fg_color="transparent")
        actions_frame.pack(side="right", padx=10, pady=10)
        
        # Move up button
        up_btn = ctk.CTkButton(
            actions_frame,
            text="↑",
            width=32,
            height=32,
            font=("Segoe UI", 14, "bold"),
            fg_color=self.app.colors["secondary"],
            hover_color=self.app.colors["secondary_hover"],
            corner_radius=8,
            command=self.on_move_up
        )
        up_btn.pack(pady=(0, 4))
        
        # Move down button
        down_btn = ctk.CTkButton(
            actions_frame,
            text="↓",
            width=32,
            height=32,
            font=("Segoe UI", 14, "bold"),
            fg_color=self.app.colors["secondary"],
            hover_color=self.app.colors["secondary_hover"],
            corner_radius=8,
            command=self.on_move_down
        )
        down_btn.pack(pady=(0, 4))
        
        # Remove button
        remove_btn = ctk.CTkButton(
            actions_frame,
            text="✕",
            width=32,
            height=32,
            font=("Segoe UI", 14, "bold"),
            fg_color=self.app.colors["error"],
            hover_color=self.app.colors["error_hover"],
            corner_radius=8,
            command=self.on_remove
        )
        remove_btn.pack()
    
    def _add_hover_effect(self):
        """Add hover effect to clip item."""
        def on_enter(e):
            self.configure(fg_color=self.app.colors["card_hover"], border_color=self.app.colors["border_light"])
        
        def on_leave(e):
            self.configure(fg_color=self.app.colors["card"], border_color=self.app.colors["border"])
        
        self.bind("<Enter>", on_enter)
        self.bind("<Leave>", on_leave)
    
    def update_index(self, new_index: int):
        """Update the index badge."""
        self.index = new_index
        # Find and update the index label
        for widget in self.winfo_children():
            if isinstance(widget, ctk.CTkFrame):
                for child in widget.winfo_children():
                    if isinstance(child, ctk.CTkFrame) and child.cget("width") == 32:
                        for label in child.winfo_children():
                            if isinstance(label, ctk.CTkLabel):
                                label.configure(text=str(new_index + 1))
                                break


class VideoMontageView(ctk.CTkFrame):
    """Video montage view with clip selection, ordering, and audio settings."""
    
    def __init__(self, parent, config: AppConfig, app: "AVEApp"):
        super().__init__(parent, fg_color=app.colors["bg"])
        self.config = config
        self.app = app
        self.logger = get_logger_service().get_logger("montage_view")
        
        # State
        self.selected_clips: List[Path] = []
        self.audio_path: Optional[Path] = None
        self.audio_settings = AudioSettings()
        self.montage_service = MontageService(config.montage_dir)
        self.is_rendering = False
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup montage view UI."""
        # Header
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.pack(pady=(30, 25), padx=40, fill="x")
        
        title = ctk.CTkLabel(
            header_frame,
            text="Video Montage",
            font=(self.app.font_family, 36, "bold"),
            text_color=self.app.colors["text"]
        )
        title.pack(side="left")
        
        subtitle = ctk.CTkLabel(
            header_frame,
            text="Combine video clips with custom audio",
            font=(self.app.font_family_secondary, 14),
            text_color=self.app.colors["text_secondary"]
        )
        subtitle.pack(side="left", padx=(15, 0))
        
        # Main content area
        content_frame = ctk.CTkFrame(self, fg_color="transparent")
        content_frame.pack(fill="both", expand=True, padx=40, pady=(0, 20))
        
        # Left panel - Video selection
        left_panel = ctk.CTkFrame(content_frame, fg_color=self.app.colors["card"], corner_radius=20)
        left_panel.pack(side="left", fill="both", expand=True, padx=(0, 10))
        
        # Video selection header
        video_header = ctk.CTkFrame(left_panel, fg_color="transparent")
        video_header.pack(fill="x", padx=25, pady=(25, 15))
        
        video_label = ctk.CTkLabel(
            video_header,
            text="🎬 Video Clips",
            font=(self.app.font_family, 20, "bold"),
            text_color=self.app.colors["text"]
        )
        video_label.pack(side="left")
        
        clip_count_label = ctk.CTkLabel(
            video_header,
            text="0 clips",
            font=(self.app.font_family_secondary, 12),
            text_color=self.app.colors["text_muted"]
        )
        clip_count_label.pack(side="right")
        self.clip_count_label = clip_count_label
        
        # Add videos button
        add_videos_btn = ctk.CTkButton(
            left_panel,
            text="+ Add Video Clips",
            font=(self.app.font_family, 14, "bold"),
            fg_color=self.app.colors["accent"],
            hover_color=self.app.colors["accent_hover"],
            height=44,
            corner_radius=12,
            command=self._select_videos
        )
        add_videos_btn.pack(fill="x", padx=25, pady=(0, 15))
        
        # Timeline/Selected clips panel
        timeline_frame = ctk.CTkFrame(
            left_panel,
            fg_color=self.app.colors["bg"],
            corner_radius=12
        )
        timeline_frame.pack(fill="both", expand=True, padx=25, pady=(0, 25))
        
        # Timeline header
        timeline_header = ctk.CTkFrame(timeline_frame, fg_color="transparent")
        timeline_header.pack(fill="x", padx=15, pady=(15, 10))
        
        timeline_label = ctk.CTkLabel(
            timeline_header,
            text="Timeline (drag to reorder)",
            font=(self.app.font_family_secondary, 11, "bold"),
            text_color=self.app.colors["text_muted"]
        )
        timeline_label.pack(side="left")
        
        # Clips scrollable area
        self.clips_scroll = ctk.CTkScrollableFrame(
            timeline_frame,
            fg_color="transparent",
            label_text=""
        )
        self.clips_scroll.pack(fill="both", expand=True, padx=10, pady=(0, 15))
        
        # Empty state for clips
        self.clips_empty_frame = ctk.CTkFrame(self.clips_scroll, fg_color="transparent")
        self.clips_empty_frame.pack(expand=True, pady=40)
        
        empty_icon = ctk.CTkLabel(
            self.clips_empty_frame,
            text="🎥",
            font=("Segoe UI", 48),
            text_color=self.app.colors["text_muted"]
        )
        empty_icon.pack()
        
        empty_text = ctk.CTkLabel(
            self.clips_empty_frame,
            text="No clips selected",
            font=(self.app.font_family, 16, "bold"),
            text_color=self.app.colors["text_secondary"]
        )
        empty_text.pack(pady=(10, 5))
        
        empty_hint = ctk.CTkLabel(
            self.clips_empty_frame,
            text="Click 'Add Video Clips' to start",
            font=(self.app.font_family_secondary, 12),
            text_color=self.app.colors["text_muted"]
        )
        empty_hint.pack()
        
        # Right panel - Audio settings
        right_panel = ctk.CTkFrame(content_frame, fg_color=self.app.colors["card"], corner_radius=20)
        right_panel.pack(side="right", fill="both", expand=True, padx=(10, 0))
        
        # Audio header
        audio_header = ctk.CTkFrame(right_panel, fg_color="transparent")
        audio_header.pack(fill="x", padx=25, pady=(25, 15))
        
        audio_label = ctk.CTkLabel(
            audio_header,
            text="🎵 Audio Settings",
            font=(self.app.font_family, 20, "bold"),
            text_color=self.app.colors["text"]
        )
        audio_label.pack(side="left")
        
        # Select audio button
        select_audio_btn = ctk.CTkButton(
            right_panel,
            text="Select Audio Track",
            font=(self.app.font_family, 14, "bold"),
            fg_color=self.app.colors["secondary"],
            hover_color=self.app.colors["secondary_hover"],
            height=44,
            corner_radius=12,
            command=self._select_audio
        )
        select_audio_btn.pack(fill="x", padx=25, pady=(0, 15))
        
        # Audio file display
        self.audio_file_frame = ctk.CTkFrame(right_panel, fg_color=self.app.colors["bg"], corner_radius=12)
        self.audio_file_frame.pack(fill="x", padx=25, pady=(0, 15))
        
        self.audio_file_label = ctk.CTkLabel(
            self.audio_file_frame,
            text="No audio selected",
            font=(self.app.font_family_secondary, 12),
            text_color=self.app.colors["text_muted"]
        )
        self.audio_file_label.pack(pady=12)
        
        # Audio settings
        settings_frame = ctk.CTkFrame(right_panel, fg_color="transparent")
        settings_frame.pack(fill="x", padx=25, pady=(0, 15))
        
        # Volume slider
        volume_label = ctk.CTkLabel(
            settings_frame,
            text="Volume",
            font=(self.app.font_family, 13, "bold"),
            text_color=self.app.colors["text"]
        )
        volume_label.pack(anchor="w", pady=(0, 8))
        
        self.volume_var = ctk.DoubleVar(value=1.0)
        volume_slider = ctk.CTkSlider(
            settings_frame,
            from_=0.0,
            to=2.0,
            number_of_steps=20,
            variable=self.volume_var,
            command=self._on_volume_change
        )
        volume_slider.pack(fill="x", pady=(0, 5))
        
        volume_value_label = ctk.CTkLabel(
            settings_frame,
            text="100%",
            font=(self.app.font_family_secondary, 11),
            text_color=self.app.colors["text_muted"]
        )
        volume_value_label.pack(anchor="w")
        self.volume_value_label = volume_value_label
        
        # Mute original audio
        self.mute_original_var = ctk.BooleanVar(value=True)
        mute_checkbox = ctk.CTkCheckBox(
            settings_frame,
            text="Mute original video audio",
            variable=self.mute_original_var,
            font=(self.app.font_family, 13),
            text_color=self.app.colors["text"],
            checkbox_width=20,
            checkbox_height=20,
            corner_radius=4,
            command=self._on_mute_change
        )
        mute_checkbox.pack(anchor="w", pady=(15, 0))
        
        # Audio fit mode
        fit_label = ctk.CTkLabel(
            settings_frame,
            text="Audio Fit Mode",
            font=(self.app.font_family, 13, "bold"),
            text_color=self.app.colors["text"]
        )
        fit_label.pack(anchor="w", pady=(20, 8))
        
        self.fit_mode_var = ctk.StringVar(value="trim")
        fit_menu = ctk.CTkOptionMenu(
            settings_frame,
            values=["Trim to video", "Loop to video", "Fit video to audio"],
            variable=self.fit_mode_var,
            command=self._on_fit_mode_change,
            font=(self.app.font_family_secondary, 12)
        )
        fit_menu.pack(fill="x")
        
        # Loop audio checkbox
        self.loop_audio_var = ctk.BooleanVar(value=False)
        loop_checkbox = ctk.CTkCheckBox(
            settings_frame,
            text="Loop audio if shorter",
            variable=self.loop_audio_var,
            font=(self.app.font_family, 13),
            text_color=self.app.colors["text"],
            checkbox_width=20,
            checkbox_height=20,
            corner_radius=4,
            command=self._on_loop_change
        )
        loop_checkbox.pack(anchor="w", pady=(15, 0))
        
        # Render button
        self.render_btn = ctk.CTkButton(
            right_panel,
            text="🎬 Auto Montage",
            font=(self.app.font_family, 16, "bold"),
            fg_color=self.app.colors["success"],
            hover_color=self.app.colors["success_hover"],
            height=52,
            corner_radius=14,
            command=self._start_render
        )
        self.render_btn.pack(fill="x", padx=25, pady=(20, 25))
        
        # Progress bar (hidden by default)
        self.progress_frame = ctk.CTkFrame(right_panel, fg_color="transparent")
        self.progress_frame.pack(fill="x", padx=25, pady=(0, 25))
        
        self.progress_label = ctk.CTkLabel(
            self.progress_frame,
            text="Ready",
            font=(self.app.font_family_secondary, 12),
            text_color=self.app.colors["text_muted"]
        )
        self.progress_label.pack(anchor="w", pady=(0, 8))
        
        self.progress_bar = ctk.CTkProgressBar(
            self.progress_frame,
            fg_color=self.app.colors["bg_tertiary"],
            progress_color=self.app.colors["accent"],
            corner_radius=8
        )
        self.progress_bar.pack(fill="x")
        self.progress_bar.set(0)
        self.progress_frame.pack_forget()
    
    def _select_videos(self):
        """Open file dialog to select video files."""
        if self.is_rendering:
            return
        
        filetypes = [
            ("Video files", "*.mp4 *.avi *.mov *.mkv *.webm"),
            ("All files", "*.*")
        ]
        
        files = filedialog.askopenfilenames(
            title="Select Video Clips",
            filetypes=filetypes
        )
        
        if files:
            for file in files:
                path = Path(file)
                if path not in self.selected_clips:
                    self.selected_clips.append(path)
            
            self._update_clips_ui()
    
    def _select_audio(self):
        """Open file dialog to select audio file."""
        if self.is_rendering:
            return
        
        filetypes = [
            ("Audio files", "*.mp3 *.wav *.aac *.ogg *.flac"),
            ("All files", "*.*")
        ]
        
        file = filedialog.askopenfilename(
            title="Select Audio Track",
            filetypes=filetypes
        )
        
        if file:
            self.audio_path = Path(file)
            self._update_audio_ui()
    
    def _update_clips_ui(self):
        """Update the clips timeline UI."""
        # Clear existing clips
        for widget in self.clips_scroll.winfo_children():
            if widget != self.clips_empty_frame:
                widget.destroy()
        
        # Update count
        self.clip_count_label.configure(text=f"{len(self.selected_clips)} clips")
        
        # Show/hide empty state
        if self.selected_clips:
            self.clips_empty_frame.pack_forget()
            
            # Create clip items
            for i, clip_path in enumerate(self.selected_clips):
                clip_item = VideoClipItem(
                    self.clips_scroll,
                    clip_path,
                    i,
                    lambda idx=i: self._remove_clip(idx),
                    lambda idx=i: self._move_clip_up(idx),
                    lambda idx=i: self._move_clip_down(idx),
                    self.app
                )
                clip_item.pack(fill="x", pady=5)
        else:
            self.clips_empty_frame.pack(expand=True, pady=40)
    
    def _remove_clip(self, index: int):
        """Remove a clip from the selection."""
        if 0 <= index < len(self.selected_clips):
            self.selected_clips.pop(index)
            self._update_clips_ui()
    
    def _move_clip_up(self, index: int):
        """Move a clip up in the order."""
        if index > 0:
            self.selected_clips[index], self.selected_clips[index - 1] = self.selected_clips[index - 1], self.selected_clips[index]
            self._update_clips_ui()
    
    def _move_clip_down(self, index: int):
        """Move a clip down in the order."""
        if index < len(self.selected_clips) - 1:
            self.selected_clips[index], self.selected_clips[index + 1] = self.selected_clips[index + 1], self.selected_clips[index]
            self._update_clips_ui()
    
    def _update_audio_ui(self):
        """Update the audio selection UI."""
        if self.audio_path:
            filename = self.audio_path.name
            if len(filename) > 35:
                filename = filename[:32] + "..."
            self.audio_file_label.configure(
                text=filename,
                text_color=self.app.colors["text"]
            )
        else:
            self.audio_file_label.configure(
                text="No audio selected",
                text_color=self.app.colors["text_muted"]
            )
    
    def _on_volume_change(self, value):
        """Handle volume slider change."""
        volume_percent = int(value * 100)
        self.volume_value_label.configure(text=f"{volume_percent}%")
        self.audio_settings.volume = value
    
    def _on_mute_change(self):
        """Handle mute checkbox change."""
        self.audio_settings.mute_original = self.mute_original_var.get()
    
    def _on_fit_mode_change(self, value):
        """Handle fit mode change."""
        mode_map = {
            "Trim to video": AudioFitMode.TRIM,
            "Loop to video": AudioFitMode.LOOP,
            "Fit video to audio": AudioFitMode.FIT
        }
        self.audio_settings.fit_mode = mode_map.get(value, AudioFitMode.TRIM)
    
    def _on_loop_change(self):
        """Handle loop checkbox change."""
        self.audio_settings.loop_audio = self.loop_audio_var.get()
    
    def _start_render(self):
        """Start the montage rendering process."""
        if self.is_rendering:
            return
        
        if not self.selected_clips:
            self.logger.warning("No clips selected for montage")
            return
        
        self.is_rendering = True
        self.render_btn.configure(
            text="⏳ Rendering...",
            fg_color=self.app.colors["secondary"],
            state="disabled"
        )
        
        # Show progress
        self.progress_frame.pack(fill="x", padx=25, pady=(0, 25))
        self.progress_bar.set(0)
        
        # Update audio settings
        self.audio_settings.audio_path = self.audio_path
        
        # Generate output filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"montage_{timestamp}.mp4"
        
        # Start rendering in background
        def render_thread():
            output_path = self.montage_service.create_montage(
                self.selected_clips,
                self.audio_settings,
                output_filename,
                self._on_render_progress
            )
            
            # Schedule UI update on main thread
            self.after(0, lambda: self._render_complete(output_path))
        
        import threading
        thread = threading.Thread(target=render_thread)
        thread.daemon = True
        thread.start()
    
    def _on_render_progress(self, progress: MontageProgress):
        """Handle render progress updates."""
        def update_ui():
            self.progress_label.configure(text=f"{progress.current_step} ({progress.percentage:.0f}%)")
            self.progress_bar.set(progress.percentage / 100)
        
        self.after(0, update_ui)
    
    def _render_complete(self, output_path: Optional[Path]):
        """Handle render completion."""
        self.is_rendering = False
        
        if output_path and output_path.exists():
            self.progress_label.configure(text="✓ Complete!", text_color=self.app.colors["success"])
            self.progress_bar.set(1.0)
            self.logger.info(f"Montage completed: {output_path}")
            
            # Show success message
            self.render_btn.configure(
                text="✓ Done",
                fg_color=self.app.colors["success"],
                state="normal"
            )
            
            # Reset after delay
            self.after(3000, self._reset_render_ui)
        else:
            self.progress_label.configure(text="✗ Failed", text_color=self.app.colors["error"])
            self.render_btn.configure(
                text="✗ Failed",
                fg_color=self.app.colors["error"],
                state="normal"
            )
            
            # Reset after delay
            self.after(3000, self._reset_render_ui)
    
    def _reset_render_ui(self):
        """Reset render UI to initial state."""
        self.render_btn.configure(
            text="🎬 Auto Montage",
            fg_color=self.app.colors["success"],
            state="normal"
        )
        self.progress_frame.pack_forget()
        self.progress_bar.set(0)
        self.progress_label.configure(text="Ready", text_color=self.app.colors["text_muted"])
    
    def on_view_shown(self):
        """Called when view is shown."""
        self.logger.debug("Montage view shown")
