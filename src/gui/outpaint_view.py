"""Outpaint view with image selection interface."""

import customtkinter as ctk
import threading
import asyncio
from pathlib import Path
from typing import List, TYPE_CHECKING, Optional, Dict, Tuple
from tkinter import messagebox, filedialog

from src.config import AppConfig
from src.services.logger import get_logger_service
from src.services.image_service import ImageService
from src.services.outpaint_service import OutpaintService
from src.services.notifications import get_notification_service
from src.gui.tooltip import create_tooltip
from src.gui.clipboard_utils import setup_clipboard_support
from src.gui.error_handler import show_error, show_warning, show_info, safe_execute
from src.services.settings_service import get_settings_service
from core import PROFILES
from src.utils.name_utils import describe_media_name

if TYPE_CHECKING:
    from src.gui.app import AVEApp


class OutpaintView(ctk.CTkFrame):
    """Outpaint view with image selection interface."""
    
    def __init__(self, parent, config: AppConfig, app: "AVEApp"):
        super().__init__(parent, fg_color=app.colors["bg"])
        self.config = config
        self.app = app
        self.logger = get_logger_service().get_logger("outpaint_view")
        self.image_service = ImageService(config)
        self.outpaint_service = OutpaintService(config)
        
        self.selected_images: List[Path] = []
        self._image_status: Dict[Tuple[int, Path], str] = {}
        # Start from outputs_dir since we're selecting images for outpaint
        self._last_dir: Path = self.config.outputs_dir if hasattr(self.config, 'outputs_dir') and self.config.outputs_dir.exists() else (self.config.assets_dir if hasattr(self.config, 'assets_dir') else Path('.'))
        
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
        """Setup Outpaint UI with modern design."""
        # Header with improved typography
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.pack(pady=(30, 20))
        
        # Main title with gradient effect
        title_container = ctk.CTkFrame(header_frame, fg_color="transparent")
        title_container.pack()
        
        header = ctk.CTkLabel(
            title_container,
            text="🖼️ Batch Outpaint",
            font=("Segoe UI", 36, "bold"),
            text_color="#4A90E2"
        )
        header.pack()
        
        subtitle = ctk.CTkLabel(
            title_container,
            text="Transform images to 9:16 aspect ratio using AI-powered outpainting",
            font=("Segoe UI", 14),
            text_color=self.app.colors["text_secondary"]
        )
        subtitle.pack(pady=(8, 0))
        
        # Images header with better styling
        images_header = ctk.CTkFrame(self, fg_color="transparent")
        images_header.pack(fill="x", padx=50, pady=(25, 10))
        
        header_left = ctk.CTkFrame(images_header, fg_color="transparent")
        header_left.pack(side="left", fill="x", expand=True)
        
        images_title = ctk.CTkLabel(
            header_left,
            text="📸 Selected Images",
            font=("Segoe UI", 20, "bold"),
            text_color=self.app.colors["text"]
        )
        images_title.pack(side="left")
        
        self.images_count_label = ctk.CTkLabel(
            header_left,
            text="0 images",
            font=("Segoe UI", 14),
            text_color=self.app.colors["text_secondary"]
        )
        self.images_count_label.pack(side="left", padx=(12, 0))
        
        # Scrollable images area with enhanced design
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
        self.images_container = scroll_frame
        
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
        
        add_images_btn = ctk.CTkButton(
            left_actions,
            text="➕ Add Images",
            font=("Segoe UI", 16, "bold"),
            fg_color=self.app.colors["secondary"],
            hover_color=self.app.colors["secondary_hover"],
            width=160,
            height=52,
            corner_radius=10,
            command=self._add_images
        )
        add_images_btn.pack(side="left", padx=(0, 12))
        create_tooltip(add_images_btn, "Add images to outpaint")
        
        clear_btn = ctk.CTkButton(
            left_actions,
            text="🗑️ Clear All",
            font=("Segoe UI", 16, "bold"),
            fg_color="#E50914",
            hover_color="#F40612",
            width=140,
            height=52,
            corner_radius=10,
            command=self._clear_all
        )
        clear_btn.pack(side="left", padx=(0, 20))
        create_tooltip(clear_btn, "Clear all selected images")
        
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
            progress_color="#4A90E2",
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
            text="🚀 Start Outpaint",
            font=("Segoe UI", 20, "bold"),
            fg_color="#4A90E2",
            hover_color="#5BA0F2",
            width=260,
            height=64,
            corner_radius=14,
            command=self._on_generate
        )
        self.generate_btn.pack(side="right")
        create_tooltip(self.generate_btn, "Start batch outpaint for all images")
    
    def _setup_drag_drop(self):
        """Setup drag and drop for images."""
        def on_drop(event):
            try:
                # Get dropped files
                files = self.tk.splitlist(event.data)
                added = 0
                for file in files:
                    if file.startswith('{') and file.endswith('}'):
                        file = file[1:-1]  # Remove braces
                    image_path = Path(file)
                    if image_path.exists():
                        is_valid, error = self.image_service.validate_image(image_path)
                        if is_valid:
                            if image_path not in self.selected_images:
                                self.selected_images.append(image_path)
                                added += 1
                if added > 0:
                    self._image_status.clear()
                    self._refresh_images()
            except Exception as e:
                self.logger.warning("Drag and drop error", error=str(e))
        
        # Bind drag and drop events
        self.images_container.bind("<Button-1>", lambda e: self.images_container.focus_set())
        try:
            # Windows drag and drop
            self.images_container.tk.call('package', 'require', 'tkdnd')
            self.images_container.tk.call('tkdnd::drop_target', 'register', self.images_container, 'DND_Files')
            self.images_container.bind('<<Drop:DND_Files>>', on_drop)
        except Exception:
            # Fallback if tkdnd not available
            pass
    
    def _add_images(self):
        """Add images to the list."""
        files = filedialog.askopenfilenames(
            title="Select Images for Outpaint",
            filetypes=[
                ("Image files", "*.jpg *.jpeg *.png *.webp"),
                ("All files", "*.*")
            ],
            initialdir=str(self._last_dir)
        )
        
        if not files:
            return
        
        # Validate and add images
        added = 0
        invalid_files = []
        
        for file in files:
            image_path = Path(file)
            is_valid, error = self.image_service.validate_image(image_path)
            if is_valid:
                if image_path not in self.selected_images:
                    self.selected_images.append(image_path)
                    added += 1
            else:
                invalid_files.append(f"{image_path.name}: {error}")
        
        if invalid_files:
            error_msg = "Some files were invalid:\n\n" + "\n".join(invalid_files[:5])
            if len(invalid_files) > 5:
                error_msg += f"\n... and {len(invalid_files) - 5} more"
            show_warning("Invalid Files", error_msg, logger=self.logger)
        
        if added > 0:
            # Update last dir
            try:
                self._last_dir = Path(files[-1]).parent
            except Exception:
                pass
            self._image_status.clear()
            self._refresh_images()
    
    def _clear_all(self):
        """Clear all selected images."""
        if self.selected_images:
            confirm = messagebox.askyesno(
                "Clear All",
                f"Remove all {len(self.selected_images)} selected images?",
                icon="question"
            )
            if confirm:
                self.selected_images.clear()
                self._image_status.clear()
                self._refresh_images()
    
    def _get_image_status_style(self, status: Optional[str]) -> tuple[str, str, str, str]:
        """Return border color, label text, label color, and badge background."""
        border_default = self.app.colors["border"]
        success_color = self.app.colors.get("success", "#16a34a")
        warning_color = self.app.colors.get("warning", "#f59e0b")
        accent_color = self.app.colors.get("accent", "#4A90E2")
        danger_color = "#E50914"

        mapping = {
            None: (border_default, "", self.app.colors["text_secondary"], "transparent"),
            "queued": (accent_color, "Queued", accent_color, "#141f2c"),
            "success": (success_color, "Completed", success_color, "#10251b"),
            "failed": (danger_color, "Failed", danger_color, "#2b0f14"),
        }
        return mapping.get(status, mapping[None])
    
    def _refresh_images(self):
        """Refresh images display."""
        # Clear container
        for widget in self.images_container.winfo_children():
            widget.destroy()
        
        # Update count
        self.images_count_label.configure(text=f"{len(self.selected_images)} images")
        
        # Display images
        if not self.selected_images:
            # Enhanced empty state
            empty_frame = ctk.CTkFrame(self.images_container, fg_color="transparent")
            empty_frame.pack(expand=True, pady=80)
            
            empty_icon = ctk.CTkLabel(
                empty_frame,
                text="📁",
                font=("Segoe UI", 64),
                text_color=self.app.colors["text_muted"]
            )
            empty_icon.pack(pady=(0, 20))
            
            empty_label = ctk.CTkLabel(
                empty_frame,
                text="No images selected",
                font=("Segoe UI", 18, "bold"),
                text_color=self.app.colors["text"]
            )
            empty_label.pack(pady=(0, 8))
            
            empty_hint = ctk.CTkLabel(
                empty_frame,
                text="Click 'Add Images' or drag and drop files here",
                font=("Segoe UI", 14),
                text_color=self.app.colors["text_secondary"]
            )
            empty_hint.pack()
        else:
            for idx, image_path in enumerate(self.selected_images):
                self._create_image_widget(idx, image_path)
    
    def _create_image_widget(self, idx: int, image_path: Path):
        """Create widget for an image with enhanced design."""
        status = self._image_status.get((idx, image_path))
        border_color, status_text, status_fg, status_bg = self._get_image_status_style(status)
        img_frame = ctk.CTkFrame(
            self.images_container,
            fg_color=self.app.colors["card"],
            corner_radius=14,
            border_width=1,
            border_color=border_color
        )
        img_frame.pack(fill="x", padx=18, pady=12)
        
        content_frame = ctk.CTkFrame(img_frame, fg_color="transparent")
        content_frame.pack(fill="x", padx=18, pady=15)
        
        # Image preview with better styling
        preview_container = ctk.CTkFrame(content_frame, fg_color="transparent")
        preview_container.pack(side="left", padx=(0, 15))
        
        try:
            from PIL import Image
            from customtkinter import CTkImage
            img = Image.open(image_path)
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
        info_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
        info_frame.pack(side="left", fill="x", expand=True, padx=(0, 15))
        
        img_name_label = ctk.CTkLabel(
            info_frame,
            text=describe_media_name(image_path),
            font=("Segoe UI", 15, "bold"),
            text_color=self.app.colors["text"],
            anchor="w"
        )
        img_name_label.pack(anchor="w", pady=(0, 6))
        
        img_path_label = ctk.CTkLabel(
            info_frame,
            text=str(image_path.parent),
            font=("Segoe UI", 12),
            text_color=self.app.colors["text_muted"],
            anchor="w"
        )
        img_path_label.pack(anchor="w")

        if status_text:
            status_label = ctk.CTkLabel(
                info_frame,
                text=status_text,
                font=("Segoe UI", 12, "bold"),
                text_color=status_fg,
                fg_color=status_bg,
                corner_radius=999,
                padx=10,
                pady=4
            )
            status_label.pack(anchor="w", pady=(8, 0))
        
        # Remove button with better styling
        remove_btn = ctk.CTkButton(
            content_frame,
            text="🗑️",
            font=("Segoe UI", 16),
            fg_color="#E50914",
            hover_color="#F40612",
            width=50,
            height=50,
            corner_radius=10,
            command=lambda i=idx: self._remove_image(i)
        )
        remove_btn.pack(side="right")
    
    def _remove_image(self, idx: int):
        """Remove an image from the list."""
        if idx < len(self.selected_images):
            self.selected_images.pop(idx)
            self._image_status.clear()
            self._refresh_images()
    
    def _apply_outpaint_results(self, images_snapshot: List[Tuple[int, Path]], results: List[Optional[Path]]):
        """Apply outpaint results to update image statuses."""
        try:
            # Update status for each image based on results
            for (idx, image_path), result_path in zip(images_snapshot, results):
                if result_path is not None and result_path.exists():
                    self._image_status[(idx, image_path)] = "success"
                else:
                    self._image_status[(idx, image_path)] = "failed"
            
            # Refresh display to show updated statuses
            self._refresh_images()
        except Exception as e:
            self.logger.error("Failed to apply outpaint results", error=str(e), exc_info=True)
    
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
    
    def _on_generate(self):
        """Handle generate button click."""
        if not self.selected_images:
            show_warning("No Images", "Please select at least one image to outpaint.", logger=self.logger)
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
        
        # Confirm action
        confirm = messagebox.askyesno(
            "Batch Outpaint",
            f"This will open {len(self.selected_images)} browser window(s) (one per image).\n"
            f"Each image will be outpainted to 9:16 aspect ratio.\n\n"
            f"Continue?",
            icon="question"
        )
        
        if not confirm:
            return
        
        images_snapshot = list(enumerate(self.selected_images))
        image_list = [img for _, img in images_snapshot]
        self._image_status = {(idx, path): "queued" for idx, path in images_snapshot}
        self._refresh_images()
        
        # Update progress
        if hasattr(self, 'progress_label'):
            self.progress_label.configure(
                text=f"Starting batch outpaint: {len(self.selected_images)} image(s)...",
                text_color="#4A90E2"
            )
        if hasattr(self, 'status_indicator'):
            self.status_indicator.configure(text="●", text_color="#4A90E2")
        if hasattr(self, 'task_counter'):
            self.task_counter.configure(text=f"{len(self.selected_images)} images queued")
        
        self.logger.info("Starting batch outpaint", image_count=len(self.selected_images))
        
        # Disable generate button
        if hasattr(self, 'generate_btn'):
            self.generate_btn.configure(state="disabled", text="Processing…")
        
        # Run outpaint in background thread
        def run_outpaint_thread():
            loop = None
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                # Run batch outpaint
                results = loop.run_until_complete(
                    self.outpaint_service.batch_outpaint(
                        image_list,
                        profiles,
                        self.config.outpaint_dir
                    )
                )
                
                # Count results
                successful = sum(1 for p in results if p is not None)
                failed = len(results) - successful
                
                # Update UI
                msg = f"✅ Outpaint complete: {successful}/{len(self.selected_images)} succeeded"
                if failed > 0:
                    msg = f"⚠️ Outpaint complete: {successful}/{len(self.selected_images)} succeeded, {failed} failed"
                
                self.app.after(0, lambda: messagebox.showinfo("Outpaint Complete", msg, icon="info"))
                self.app.after(0, lambda: self._update_progress(successful, failed, len(image_list)))
                self.app.after(0, lambda snaps=images_snapshot, res=results: self._apply_outpaint_results(snaps, res))
                
                # Re-enable button
                if hasattr(self, 'generate_btn'):
                    self.app.after(0, lambda: self.generate_btn.configure(state="normal", text="🚀 Start Outpaint"))
                
                # Send notification
                try:
                    notifier = get_notification_service()
                    notifier.notify("Batch Outpaint Complete", msg, duration=6)
                except Exception:
                    pass
                
            except Exception as e:
                self.logger.error("Batch outpaint error", error=str(e), exc_info=True)
                self.app.after(0, lambda: messagebox.showerror(
                    "Outpaint Error",
                    f"An error occurred:\n{e}",
                    icon="error"
                ))
                if hasattr(self, 'generate_btn'):
                    self.app.after(0, lambda: self.generate_btn.configure(state="normal", text="🚀 Start Outpaint"))
            finally:
                # Always close the event loop
                if loop:
                    try:
                        # Cancel any pending tasks
                        pending = asyncio.all_tasks(loop)
                        for task in pending:
                            task.cancel()
                        # Wait for cancellations
                        if pending:
                            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                    except Exception:
                        pass
                    try:
                        loop.close()
                    except Exception:
                        pass
        
        thread = threading.Thread(target=run_outpaint_thread, daemon=True)
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
                    text_color="#4A90E2"
                )
                if hasattr(self, 'status_indicator'):
                    self.status_indicator.configure(text="●", text_color="#4A90E2")
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
