"""Main GUI application with async integration."""

import asyncio
import threading
from pathlib import Path
from typing import Optional
import customtkinter as ctk

from src.config import AppConfig
from src.services.logger import get_logger_service
from src.gui.dashboard import DashboardView
from src.gui.pairing import PairingView
from src.gui.settings import SettingsView
from src.gui.logs import LogsView
from src.gui.tooltip import create_tooltip
from src.gui.animation_utils import add_apple_hover_effect, add_apple_press_effect


class AVEApp(ctk.CTk):
    """Main application window with premium dark mode design."""
    
    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config
        self.logger = get_logger_service().get_logger("gui")
        
        # Remove any default padding that creates gaps
        try:
            # Configure main window to have no padding
            self.grid_columnconfigure(0, weight=0)
            self.grid_columnconfigure(1, weight=1)
        except:
            pass
        
        # Setup async event loop in background thread
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._setup_async_loop()
        
        # UI Configuration - Apple-inspired
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        
        # Use SF Pro-like font if available, fallback to Segoe UI
        self.font_family = "SF Pro Display" if self._font_available("SF Pro Display") else "Segoe UI"
        self.font_family_secondary = "SF Pro Text" if self._font_available("SF Pro Text") else "Segoe UI"
        
        self.title("Autonomous Video Engine - AVE")
        self.geometry("1600x1000")  # Larger default size for better usability
        self.minsize(1400, 800)  # Increased minimum window size
        
        # Enable smooth scrolling and interactions
        self.configure(cursor="arrow")
        
        # Remove any default padding that might create gaps
        try:
            self.configure(padx=0, pady=0)
        except:
            pass
        
        # Apple-inspired color scheme - Premium, elegant, minimal
        self.colors = {
            # Backgrounds - Apple's dark mode palette
            "bg": "#000000",  # Pure black like macOS
            "bg_secondary": "#1C1C1E",  # iOS dark gray
            "bg_tertiary": "#2C2C2E",  # Lighter tertiary
            "card": "#1C1C1E",  # Card background
            "card_hover": "#2C2C2E",  # Hover state - subtle
            "card_active": "#3A3A3C",  # Active/pressed state
            "card_elevated": "#2C2C2E",  # Elevated card
            "card_glass": "#1C1C1E80",  # Glass morphism effect
            
            # Accent - Apple's system blue
            "accent": "#007AFF",  # iOS system blue
            "accent_hover": "#0051D5",  # Darker blue on hover
            "accent_light": "#5AC8FA",  # Light blue
            "accent_pressed": "#0040AA",  # Pressed state
            "accent_gradient_start": "#007AFF",
            "accent_gradient_end": "#0051D5",
            
            # Secondary colors
            "secondary": "#48484A",  # Gray
            "secondary_hover": "#636366",  # Lighter gray
            "secondary_pressed": "#3A3A3C",
            
            # Status colors - Apple style
            "success": "#34C759",  # iOS green
            "success_hover": "#30D158",  # Brighter green
            "success_light": "#66FF88",
            "warning": "#FF9500",  # iOS orange
            "warning_hover": "#FFB340",  # Brighter orange
            "error": "#FF3B30",  # iOS red
            "error_hover": "#FF6961",  # Softer red
            
            # Text - Apple's text hierarchy
            "text": "#FFFFFF",  # Primary text
            "text_secondary": "#EBEBF5",  # Secondary text (iOS style)
            "text_tertiary": "#EBEBF599",  # Tertiary text
            "text_muted": "#8E8E93",  # Muted text
            "text_disabled": "#3A3A3C",  # Disabled text
            
            # Borders - Subtle and minimal
            "border": "#38383A",  # Primary border
            "border_light": "#48484A",  # Lighter border
            "border_highlight": "#636366",  # Highlighted border
            "border_separator": "#38383A",  # Separator lines
            
            # Shadows - Soft and subtle like Apple
            "shadow": "#00000040",  # Standard shadow
            "shadow_light": "#00000020",  # Light shadow
            "shadow_medium": "#00000060",  # Medium shadow
            "shadow_heavy": "#00000080",  # Heavy shadow
            "shadow_colored": "#007AFF20",  # Colored shadow for accent
            
            # Gradients
            "gradient_start": "#1C1C1E",
            "gradient_end": "#000000",
            "gradient_accent_start": "#007AFF",
            "gradient_accent_end": "#0051D5",
            
            # Effects
            "glow": "#007AFF15",  # Subtle glow effect
            "overlay": "#00000080",  # Overlay for modals
            "blur": "#1C1C1E80",  # Blur effect color
            
            # Interactive states
            "hover_overlay": "#FFFFFF08",  # Subtle white overlay on hover
            "pressed_overlay": "#00000015",  # Dark overlay on press
        }
        
        self._setup_layout()
        self._setup_nav_tooltips()
        self._show_dashboard()
        
        # Handle window close
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
    
    def _setup_async_loop(self):
        """Setup async event loop in background thread."""
        def run_loop():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.loop.run_forever()
        
        thread = threading.Thread(target=run_loop, daemon=True)
        thread.start()
        
        # Wait for loop to be ready
        while self.loop is None:
            threading.Event().wait(0.1)
    
    def run_async(self, coro):
        """Run async coroutine from sync context."""
        if self.loop:
            future = asyncio.run_coroutine_threadsafe(coro, self.loop)
            return future.result(timeout=30)
        return None
    
    def _setup_layout(self):
        """Setup main layout with sidebar and content area."""
        # Use grid for precise control - no gaps between sidebar and content
        self.grid_columnconfigure(0, weight=0, minsize=280)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)  # Footer row
        
        # Sidebar with subtle border - wider for better readability
        self.sidebar = ctk.CTkFrame(
            self,
            width=280,  # Increased width for better text visibility
            fg_color=self.colors["card"],
            corner_radius=0,
            border_width=0
        )
        # Use grid for zero gap
        self.sidebar.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        
        # Logo/Title with gradient effect
        title_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        title_frame.pack(pady=(35, 25))
        
        # Icon/Logo with better styling
        icon_frame = ctk.CTkFrame(title_frame, fg_color="transparent")
        icon_frame.pack()
        
        icon_label = ctk.CTkLabel(
            icon_frame,
            text="🎬",
            font=("Segoe UI", 42),
            width=60,
            height=60
        )
        icon_label.pack()
        
        title = ctk.CTkLabel(
            title_frame,
            text="AVE Studio",
            font=(self.font_family, 34, "bold"),
            text_color=self.colors["accent"]
        )
        title.pack(pady=(8, 0))
        
        subtitle = ctk.CTkLabel(
            title_frame,
            text="Autonomous Engine",
            font=(self.font_family_secondary, 12),
            text_color=self.colors["text_secondary"]
        )
        subtitle.pack(pady=(2, 0))
        
        # Version badge with better styling
        version_frame = ctk.CTkFrame(
            title_frame,
            fg_color=self.colors["accent"],
            corner_radius=10,
            width=50,
            height=20
        )
        version_frame.pack(pady=(8, 0))
        version_frame.pack_propagate(False)
        
        version_badge = ctk.CTkLabel(
            version_frame,
            text="v2.0",
            font=(self.font_family_secondary, 10, "bold"),
            text_color="#FFFFFF"
        )
        version_badge.pack(expand=True)
        
        # Navigation buttons - organized by sections
        self.nav_buttons = {}
        
        # Main section
        main_section_label = ctk.CTkLabel(
            self.sidebar,
            text="MAIN",
            font=(self.font_family_secondary, 10, "bold"),
            text_color=self.colors["text_muted"]
        )
        main_section_label.pack(pady=(15, 8), padx=20, anchor="w")
        
        main_nav_items = [
            ("🏠 Dashboard", "dashboard"),
            ("🤝 Pairing", "pairing"),
        ]
        
        for text, view_name in main_nav_items:
            btn = ctk.CTkButton(
                self.sidebar,
                text=text,
                font=(self.font_family, 16, "normal"),  # Apple uses normal weight, not bold
                fg_color="transparent",
                text_color=self.colors["text"],
                hover_color=self.colors["card_hover"],
                anchor="w",
                height=52,
                corner_radius=12,  # More rounded like Apple
                border_width=0,
                command=lambda v=view_name: self._switch_view(v)
            )
            btn.pack(fill="x", padx=12, pady=4)
            self.nav_buttons[view_name] = btn
            
            # Add smooth Apple-like hover animation effect
            def make_hover_effect(button, name):
                from src.gui.animation_utils import animate_color_transition
                
                def on_enter(e):
                    if name != self.current_view:
                        animate_color_transition(
                            button,
                            "transparent",
                            self.colors["card_hover"],
                            duration_ms=150,
                            steps=8
                        )
                def on_leave(e):
                    if name != self.current_view:
                        animate_color_transition(
                            button,
                            self.colors["card_hover"],
                            "transparent",
                            duration_ms=150,
                            steps=8
                        )
                button.bind("<Enter>", on_enter)
                button.bind("<Leave>", on_leave)
                add_apple_press_effect(button, self.colors)
            
            make_hover_effect(btn, view_name)
        
        # Tools section
        tools_separator = ctk.CTkFrame(
            self.sidebar,
            fg_color=self.colors["border"],
            height=1
        )
        tools_separator.pack(fill="x", padx=20, pady=(15, 8))
        
        tools_section_label = ctk.CTkLabel(
            self.sidebar,
            text="TOOLS",
            font=(self.font_family_secondary, 10, "bold"),
            text_color=self.colors["text_muted"]
        )
        tools_section_label.pack(pady=(0, 8), padx=20, anchor="w")
        
        tools_nav_items = [
            ("🎬 Qwen Video", "qwen"),
            ("🖌️ Outpaint", "outpaint"),
            ("🎞️ Video Montage", "montage"),
        ]
        
        for text, view_name in tools_nav_items:
            btn = ctk.CTkButton(
                self.sidebar,
                text=text,
                font=(self.font_family, 16, "normal"),
                fg_color="transparent",
                text_color=self.colors["text"],
                hover_color=self.colors["card_hover"],
                anchor="w",
                height=52,
                corner_radius=12,
                border_width=0,
                command=lambda v=view_name: self._switch_view(v)
            )
            btn.pack(fill="x", padx=12, pady=4)
            self.nav_buttons[view_name] = btn
            make_hover_effect(btn, view_name)
        
        # Utilities section
        utils_separator = ctk.CTkFrame(
            self.sidebar,
            fg_color=self.colors["border"],
            height=1
        )
        utils_separator.pack(fill="x", padx=20, pady=(15, 8))
        
        utils_section_label = ctk.CTkLabel(
            self.sidebar,
            text="UTILITIES",
            font=(self.font_family_secondary, 10, "bold"),
            text_color=self.colors["text_muted"]
        )
        utils_section_label.pack(pady=(0, 8), padx=20, anchor="w")
        
        utils_nav_items = [
            ("🔐 Login Mode", "login"),
            ("🧾 Prompt Library", "prompt_library"),
            ("📜 Logs", "logs"),
        ]
        
        for text, view_name in utils_nav_items:
            btn = ctk.CTkButton(
                self.sidebar,
                text=text,
                font=(self.font_family, 16, "normal"),
                fg_color="transparent",
                text_color=self.colors["text"],
                hover_color=self.colors["card_hover"],
                anchor="w",
                height=52,
                corner_radius=12,
                border_width=0,
                command=lambda v=view_name: self._switch_view(v)
            )
            btn.pack(fill="x", padx=12, pady=4)
            self.nav_buttons[view_name] = btn
            make_hover_effect(btn, view_name)
        
        # Settings section
        settings_separator = ctk.CTkFrame(
            self.sidebar,
            fg_color=self.colors["border"],
            height=1
        )
        settings_separator.pack(fill="x", padx=20, pady=(15, 8))
        
        settings_btn = ctk.CTkButton(
            self.sidebar,
            text="⚙️ Settings",
            font=(self.font_family, 16, "normal"),
            fg_color="transparent",
            text_color=self.colors["text"],
            hover_color=self.colors["card_hover"],
            anchor="w",
            height=52,
            corner_radius=12,
            border_width=0,
            command=lambda: self._switch_view("settings")
        )
        settings_btn.pack(fill="x", padx=12, pady=4)
        self.nav_buttons["settings"] = settings_btn
        make_hover_effect(settings_btn, "settings")
        
        # Sidebar quick settings - more compact and organized
        quick_settings_separator = ctk.CTkFrame(
            self.sidebar,
            fg_color=self.colors["border"],
            height=1
        )
        quick_settings_separator.pack(fill="x", padx=20, pady=(20, 15), side="bottom")
        
        self.quick_settings = ctk.CTkFrame(
            self.sidebar,
            fg_color="transparent"
        )
        self.quick_settings.pack(side="bottom", fill="x", padx=12, pady=(0, 20))

        # Compact appearance control
        appearance_frame = ctk.CTkFrame(self.quick_settings, fg_color="transparent")
        appearance_frame.pack(fill="x", pady=(0, 8))
        
        ctk.CTkLabel(
            appearance_frame,
            text="Theme",
            font=(self.font_family_secondary, 11),
            text_color=self.colors["text_muted"]
        ).pack(side="left")
        
        self.appearance_var = ctk.StringVar(value="Dark")
        appearance_menu = ctk.CTkOptionMenu(
            appearance_frame,
            values=["Dark", "Light", "System"],
            variable=self.appearance_var,
            command=self._change_appearance_mode,
            width=80,
            height=28,
            font=(self.font_family_secondary, 11)
        )
        appearance_menu.pack(side="right")

        # Compact scale control
        scale_frame = ctk.CTkFrame(self.quick_settings, fg_color="transparent")
        scale_frame.pack(fill="x")
        
        ctk.CTkLabel(
            scale_frame,
            text="Scale",
            font=(self.font_family_secondary, 11),
            text_color=self.colors["text_muted"]
        ).pack(side="left")

        self.scaling_var = ctk.StringVar(value="100%")
        scale_menu = ctk.CTkOptionMenu(
            scale_frame,
            values=["80%", "90%", "100%", "110%", "120%"],
            variable=self.scaling_var,
            command=self._change_scaling,
            width=80,
            height=28,
            font=(self.font_family_secondary, 11)
        )
        scale_menu.pack(side="right")
        
        # Content area - no gap between sidebar and content
        self.content = ctk.CTkFrame(
            self,
            fg_color=self.colors["bg"],
            corner_radius=0,
            border_width=0
        )
        # Use grid for precise positioning with zero gap
        self.content.grid(row=0, column=1, sticky="nsew", padx=0, pady=0)
        
        # Footer (optional, can be shown in some views)
        self.footer = ctk.CTkFrame(
            self,
            fg_color=self.colors["card"],
            height=35,
            corner_radius=0,
            border_width=0
        )
        # Footer spans both columns using grid
        self.footer.grid(row=1, column=0, columnspan=2, sticky="ew", padx=0, pady=0)
        
        # Status indicator dot
        self.status_dot = ctk.CTkLabel(
            self.footer,
            text="●",
            font=("Segoe UI", 12),
            text_color=self.colors["success"]
        )
        self.status_dot.pack(side="left", padx=(15, 8), pady=0)
        
        self.footer_label = ctk.CTkLabel(
            self.footer,
            text="Ready • Use the sidebar to navigate",
            font=("Segoe UI", 11),
            text_color=self.colors["text_secondary"]
        )
        self.footer_label.pack(side="left", padx=0, pady=0)
        
        # Current view
        self.current_view = None
        self.views = {}
    
    def _switch_view(self, view_name: str):
        """Switch to a different view."""
        # Clear content
        for widget in self.content.winfo_children():
            widget.pack_forget()
        
        # Update button states with smooth transitions
        for name, btn in self.nav_buttons.items():
            if name == view_name:
                btn.configure(
                    fg_color=self.colors["accent"],
                    text_color="#FFFFFF",
                    font=(self.font_family, 16, "bold"),  # Bold for active
                    hover_color=self.colors["accent_hover"]
                )
            else:
                btn.configure(
                    fg_color="transparent",
                    text_color=self.colors["text"],
                    font=(self.font_family, 16, "normal"),
                    hover_color=self.colors["card_hover"]
                )
        
        # Show view
        if view_name not in self.views:
            self.views[view_name] = self._create_view(view_name)
        
        view = self.views[view_name]
        view.pack(fill="both", expand=True, padx=0, pady=0)
        self.current_view = view_name

        # Call on_view_shown if method exists (for refreshing data)
        if hasattr(view, 'on_view_shown'):
            try:
                view.on_view_shown()
            except Exception as e:
                self.logger.warning("Error calling on_view_shown", view=view_name, error=str(e))

        # Update footer context
        try:
            self.footer_label.configure(
                text=f"View: {view_name.capitalize()} • Use on-screen buttons to act"
            )
        except Exception:
            pass
    
    def _create_view(self, view_name: str):
        """Create a view component."""
        if view_name == "dashboard":
            return DashboardView(self.content, self.config, self)
        elif view_name == "pairing":
            return PairingView(self.content, self.config, self)
        elif view_name == "qwen":
            from src.gui.qwen_view import QwenView
            return QwenView(self.content, self.config, self)
        elif view_name == "outpaint":
            from src.gui.outpaint_view import OutpaintView
            return OutpaintView(self.content, self.config, self)
        elif view_name == "montage":
            from src.gui.montage_view import VideoMontageView
            return VideoMontageView(self.content, self.config, self)
        elif view_name == "login":
            from src.gui.login import LoginView
            return LoginView(self.content, self.config, self)
        elif view_name == "settings":
            return SettingsView(self.content, self.config, self)
        elif view_name == "logs":
            return LogsView(self.content, self.config, self)
        elif view_name == "prompt_library":
            from src.gui.prompt_library_view import PromptLibraryView
            return PromptLibraryView(self.content, self.config, self)
        else:
            frame = ctk.CTkFrame(self.content, fg_color=self.colors["bg"])
            return frame
    
    def _show_dashboard(self):
        """Show dashboard view on startup."""
        self._switch_view("dashboard")
    
    def on_closing(self):
        """Handle window close event."""
        if self.loop:
            # Schedule loop shutdown
            self.loop.call_soon_threadsafe(self.loop.stop)
        self.destroy()
    
    def _setup_nav_tooltips(self):
        """Attach helpful tooltips to navigation buttons."""
        try:
            tooltip_map = {
                "dashboard": "Overview and quick access to recent activity",
                "pairing": "Manage image pairs and launch tasks",
                "qwen": "Prepare videos based on uploaded assets",
                "outpaint": "Extend images with creative outpainting tools",
                "montage": "Combine video clips with custom audio",
                "login": "Handle authentication flows and cookies",
                "prompt_library": "Store and reuse your custom prompts",
                "settings": "Adjust application preferences",
                "logs": "Inspect recent automation logs",
            }
            for name, btn in self.nav_buttons.items():
                tip = tooltip_map.get(name, name.capitalize())
                create_tooltip(btn, tip, delay=400)
        except Exception:
            pass

    def _change_appearance_mode(self, mode: str):
        """Switch application appearance mode."""
        ctk.set_appearance_mode(mode.lower())

    def _change_scaling(self, value: str):
        """Adjust global widget scaling."""
        try:
            scaling = int(value.replace("%", "")) / 100
        except ValueError:
            scaling = 1.0
        ctk.set_widget_scaling(scaling)
    
    def _font_available(self, font_name: str) -> bool:
        """Check if a font is available on the system."""
        try:
            import tkinter.font as tkfont
            fonts = tkfont.families()
            return font_name in fonts
        except:
            return False
    
    def run(self):
        """Start the GUI main loop."""
        self.mainloop()

