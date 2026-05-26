"""Dashboard view component."""

import customtkinter as ctk
from pathlib import Path
from typing import TYPE_CHECKING

from src.config import AppConfig
from src.services.logger import get_logger_service
from src.services.image_service import ImageService
from src.services.history_service import get_history_service

if TYPE_CHECKING:
    from src.gui.app import AVEApp


class DashboardView(ctk.CTkFrame):
    """Dashboard view with stats and quick actions."""
    
    def __init__(self, parent, config: AppConfig, app: "AVEApp"):
        super().__init__(parent, fg_color=app.colors["bg"])
        self.config = config
        self.app = app
        self.logger = get_logger_service().get_logger("dashboard")
        self.image_service = ImageService(config)
        self.history_service = get_history_service()
        
        self._setup_ui()
        self._load_stats()
        self._load_history()
        
        # Refresh stats periodically (every 10 seconds)
        self.after(10000, self._refresh_periodic)
    
    def _setup_ui(self):
        """Setup dashboard UI."""
        # Header with subtitle
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.pack(pady=(30, 25))
        
        header = ctk.CTkLabel(
            header_frame,
            text="Dashboard",
            font=(self.app.font_family, 36, "bold"),
            text_color=self.app.colors["text"]
        )
        header.pack()
        
        subtitle = ctk.CTkLabel(
            header_frame,
            text="Overview & Quick Actions",
            font=(self.app.font_family_secondary, 14),
            text_color=self.app.colors["text_secondary"]
        )
        subtitle.pack(pady=(8, 0))
        
        # Stats cards with improved design
        stats_frame = ctk.CTkFrame(self, fg_color=self.app.colors["bg"])
        stats_frame.pack(fill="x", padx=40, pady=20)
        
        self.stats_cards = {}
        stats = [
            ("Profiles", "profiles"),
            ("Subjects", "subjects"),
            ("References", "references"),
            ("Outputs", "outputs")
        ]
        
        for i, (label, key) in enumerate(stats):
            card = ctk.CTkFrame(
                stats_frame, 
                fg_color=self.app.colors["card"], 
                width=240, 
                height=160,
                corner_radius=20,  # More rounded like Apple
                border_width=0,  # No border for cleaner look
                border_color=self.app.colors["border"]
            )
            card.grid(row=0, column=i, padx=10, pady=10)
            card.grid_propagate(False)
            
            # Add smooth Apple-like hover effect
            def make_card_hover(c, k=key):
                from src.gui.animation_utils import animate_color_transition
                
                def on_enter(e):
                    animate_color_transition(
                        c,
                        self.app.colors["card"],
                        self.app.colors["card_hover"],
                        duration_ms=200,
                        steps=10
                    )
                def on_leave(e):
                    animate_color_transition(
                        c,
                        self.app.colors["card_hover"],
                        self.app.colors["card"],
                        duration_ms=200,
                        steps=10
                    )
                c.bind("<Enter>", on_enter)
                c.bind("<Leave>", on_leave)
            
            make_card_hover(card)
            
            # Icon for each stat with better styling
            icon_map = {
                "profiles": "👤",
                "subjects": "🎭",
                "references": "🖼️",
                "outputs": "✨"
            }
            icon = icon_map.get(key, "📊")
            
            # Icon container
            icon_frame = ctk.CTkFrame(card, fg_color="transparent")
            icon_frame.pack(pady=(18, 8))
            
            icon_label = ctk.CTkLabel(
                icon_frame,
                text=icon,
                font=("Segoe UI", 32)
            )
            icon_label.pack()
            
            value_label = ctk.CTkLabel(
                card,
                text="0",
                font=(self.app.font_family, 48, "bold"),  # Larger, bold
                text_color=self.app.colors["text"]
            )
            value_label.pack(pady=(0, 8))
            
            name_label = ctk.CTkLabel(
                card,
                text=label,
                font=(self.app.font_family_secondary, 15, "normal"),
                text_color=self.app.colors["text_secondary"]
            )
            name_label.pack()
            
            self.stats_cards[key] = value_label
        
        # Quick actions with status - improved design
        actions_frame = ctk.CTkFrame(self, fg_color=self.app.colors["card"], corner_radius=20, border_width=0, border_color=self.app.colors["border"])
        actions_frame.pack(fill="both", expand=True, padx=40, pady=20)
        
        # Header with icon
        actions_header = ctk.CTkFrame(actions_frame, fg_color="transparent")
        actions_header.pack(fill="x", padx=25, pady=(25, 15))
        
        actions_label = ctk.CTkLabel(
            actions_header,
            text="⚡ Quick Actions",
            font=(self.app.font_family, 24, "bold"),
            text_color=self.app.colors["text"]
        )
        actions_label.pack(side="left")
        
        # Status badge with better styling
        status_frame = ctk.CTkFrame(actions_header, fg_color="transparent")
        status_frame.pack(side="right")
        
        status_dot = ctk.CTkLabel(
            status_frame,
            text="●",
            font=("Segoe UI", 14),
            text_color=self.app.colors["success"]
        )
        status_dot.pack(side="left", padx=(0, 6))
        
        status_badge = ctk.CTkLabel(
            status_frame,
            text="Ready",
            font=("Segoe UI", 13, "bold"),
            text_color=self.app.colors["success"]
        )
        status_badge.pack(side="left")
        
        buttons_frame = ctk.CTkFrame(actions_frame, fg_color="transparent")
        buttons_frame.pack(pady=(0, 15))
        
        pairing_btn = ctk.CTkButton(
            buttons_frame,
            text="🚀 Pairing",
            font=(self.app.font_family, 16, "bold"),
            fg_color=self.app.colors["accent"],
            hover_color=self.app.colors["accent_hover"],
            width=180,
            height=56,  # Slightly taller like Apple buttons
            corner_radius=14,  # More rounded
            border_width=0,
            command=lambda: self.app._switch_view("pairing")
        )
        pairing_btn.pack(side="left", padx=10)
        
        qwen_btn = ctk.CTkButton(
            buttons_frame,
            text="🎬 Qwen Video",
            font=("Segoe UI", 16, "bold"),
            fg_color="#9333EA",
            hover_color="#A855F7",
            width=180,
            height=55,
            corner_radius=12,
            command=lambda: self.app._switch_view("qwen")
        )
        qwen_btn.pack(side="left", padx=10)
        
        outpaint_btn = ctk.CTkButton(
            buttons_frame,
            text="🖼️ Outpaint",
            font=("Segoe UI", 16, "bold"),
            fg_color="#4A90E2",
            hover_color="#5BA0F2",
            width=180,
            height=55,
            corner_radius=12,
            command=lambda: self.app._switch_view("outpaint")
        )
        outpaint_btn.pack(side="left", padx=10)
        
        logs_btn = ctk.CTkButton(
            buttons_frame,
            text="📋 Logs",
            font=("Segoe UI", 16, "bold"),
            fg_color=self.app.colors["secondary"],
            hover_color=self.app.colors["secondary_hover"],
            width=180,
            height=55,
            corner_radius=12,
            command=lambda: self.app._switch_view("logs")
        )
        logs_btn.pack(side="left", padx=10)
        
        # History section - improved design
        history_frame = ctk.CTkFrame(self, fg_color=self.app.colors["card"], corner_radius=20, border_width=0, border_color=self.app.colors["border"])
        history_frame.pack(fill="both", expand=True, padx=40, pady=20)
        
        # History header
        history_header = ctk.CTkFrame(history_frame, fg_color="transparent")
        history_header.pack(fill="x", padx=25, pady=(25, 15))
        
        history_label = ctk.CTkLabel(
            history_header,
            text="📜 Recent History",
            font=(self.app.font_family, 24, "bold"),
            text_color=self.app.colors["text"]
        )
        history_label.pack(side="left")
        
        # Refresh button with better styling
        refresh_btn = ctk.CTkButton(
            history_header,
            text="🔄 Refresh",
            width=110,
            height=36,
            font=("Segoe UI", 13, "bold"),
            fg_color=self.app.colors["secondary"],
            hover_color=self.app.colors["secondary_hover"],
            corner_radius=8,
            command=self._load_history
        )
        refresh_btn.pack(side="right")
        
        # History scrollable
        self.history_scroll = ctk.CTkScrollableFrame(
            history_frame,
            fg_color=self.app.colors["bg"],
            width=1000,
            height=300
        )
        self.history_scroll.pack(fill="both", expand=True, padx=10, pady=10)
    
    def _load_stats(self):
        """Load and display statistics."""
        try:
            # Count profiles
            profiles = len(self.config.default_profiles)
            self.stats_cards["profiles"].configure(text=str(profiles))
            
            # Count subjects
            subjects = self.image_service.glob_images(self.config.subjects_dir)
            self.stats_cards["subjects"].configure(text=str(len(subjects)))
            
            # Count references
            references = self.image_service.glob_images(self.config.references_dir)
            self.stats_cards["references"].configure(text=str(len(references)))
            
            # Count outputs
            if self.config.outputs_dir.exists():
                outputs = list(self.config.outputs_dir.glob("*.webp"))
                self.stats_cards["outputs"].configure(text=str(len(outputs)))
            else:
                self.stats_cards["outputs"].configure(text="0")
                
        except Exception as e:
            self.logger.error("Failed to load stats", error=str(e))
    
    def _load_history(self):
        """Load and display recent history."""
        try:
            # Clear existing
            for widget in self.history_scroll.winfo_children():
                widget.destroy()
            
            # Get recent history
            history = self.history_service.get_history(limit=10)
            
            if not history:
                # Better empty state
                empty_frame = ctk.CTkFrame(self.history_scroll, fg_color="transparent")
                empty_frame.pack(expand=True, pady=40)
                
                empty_icon = ctk.CTkLabel(
                    empty_frame,
                    text="📊",
                    font=("Segoe UI", 48),
                    text_color=self.app.colors["text_muted"]
                )
                empty_icon.pack()
                
                no_history_label = ctk.CTkLabel(
                    empty_frame,
                    text="No history yet",
                    font=("Segoe UI", 18, "bold"),
                    text_color=self.app.colors["text_secondary"]
                )
                no_history_label.pack(pady=(10, 5))
                
                hint_label = ctk.CTkLabel(
                    empty_frame,
                    text="Start generating images to see your history here",
                    font=("Segoe UI", 13),
                    text_color=self.app.colors["text_muted"]
                )
                hint_label.pack()
                return
            
            # Display history entries
            for entry in history:
                self._create_history_entry(entry)
                
        except Exception as e:
            self.logger.error("Failed to load history", error=str(e))
    
    def _create_history_entry(self, entry):
        """Create UI widget for a history entry."""
        from datetime import datetime
        
        entry_frame = ctk.CTkFrame(
            self.history_scroll,
            fg_color=self.app.colors["card"],
            height=75,
            corner_radius=10,
            border_width=1,
            border_color=self.app.colors["border"]
        )
        entry_frame.pack(fill="x", padx=8, pady=7)
        
        # Add enhanced hover effect
        def make_entry_hover(f):
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
        
        make_entry_hover(entry_frame)
        
        # Parse timestamp
        try:
            dt = datetime.fromisoformat(entry.timestamp)
            time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        except:
            time_str = entry.timestamp
        
        # Info
        info_frame = ctk.CTkFrame(entry_frame, fg_color="transparent")
        info_frame.pack(side="left", fill="both", expand=True, padx=15, pady=10)
        
        time_label = ctk.CTkLabel(
            info_frame,
            text=time_str,
            font=("Segoe UI", 12, "bold"),
            text_color=self.app.colors["text"]
        )
        time_label.pack(anchor="w")
        
        # Better formatted stats
        stats_parts = []
        if entry.completed > 0:
            stats_parts.append(f"✅ {entry.completed} succeeded")
        if entry.failed > 0:
            stats_parts.append(f"❌ {entry.failed} failed")
        if entry.task_count > 0:
            stats_parts.append(f"📊 {entry.task_count} total")
        
        stats_text = " | ".join(stats_parts) if stats_parts else "No tasks"
        stats_text += f" | ⏱️ {entry.duration_seconds:.1f}s"
        
        stats_label = ctk.CTkLabel(
            info_frame,
            text=stats_text,
            font=("Segoe UI", 11),
            text_color=self.app.colors["text_secondary"]
        )
        stats_label.pack(anchor="w")
        
        # Success rate indicator with badge styling
        if entry.task_count > 0:
            success_rate = (entry.completed / entry.task_count) * 100
            color = self.app.colors["success"] if success_rate >= 80 else self.app.colors["warning"] if success_rate >= 50 else self.app.colors["error"]
            
            # Badge frame
            badge_frame = ctk.CTkFrame(
                entry_frame,
                fg_color=color,
                corner_radius=12,
                width=60,
                height=30
            )
            badge_frame.pack(side="right", padx=18, pady=10)
            badge_frame.pack_propagate(False)
            
            rate_label = ctk.CTkLabel(
                badge_frame,
                text=f"{success_rate:.0f}%",
                font=("Segoe UI", 13, "bold"),
                text_color="#FFFFFF"
            )
            rate_label.pack(expand=True)
    
    def _refresh_periodic(self):
        """Periodically refresh stats and history."""
        self._load_stats()
        self._load_history()
        # Refresh every 10 seconds
        self.after(10000, self._refresh_periodic)

