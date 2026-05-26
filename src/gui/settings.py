"""Settings view component with full functionality."""

import customtkinter as ctk
from pathlib import Path
from typing import TYPE_CHECKING, List
from tkinter import messagebox, filedialog

from src.config import AppConfig
from src.gui.clipboard_utils import setup_clipboard_support
from src.gui.profile_selector import ProfileSelector
from src.gui.error_handler import show_info, show_error
from src.services.settings_service import get_settings_service
from src.services.logger import get_logger_service
from core import PROFILES

if TYPE_CHECKING:
    from src.gui.app import AVEApp


class SettingsView(ctk.CTkFrame):
    """Enhanced Settings view with full functionality."""
    
    def __init__(self, parent, config: AppConfig, app: "AVEApp"):
        super().__init__(parent, fg_color=app.colors["bg"])
        self.config = config
        self.app = app
        self.logger = get_logger_service().get_logger("settings")
        self.settings_service = get_settings_service()
        
        # Load saved settings
        self._ui_scale_var = ctk.DoubleVar(value=self.settings_service.get_ui_scale())
        self._appearance_var = ctk.StringVar(value=self.settings_service.get_appearance_mode().capitalize())
        
        # Load browser settings (with fallback to config)
        self._max_concurrent_launches_var = ctk.IntVar(value=self.settings_service.get_max_concurrent_browser_launches() or self.config.max_concurrent_browser_launches)
        self._max_parallel_browsers_var = ctk.IntVar(value=self.settings_service.get_max_parallel_browsers() or self.config.max_parallel_browsers)
        self._browser_launch_delay_var = ctk.IntVar(value=self.settings_service.get_delay_setting("browser_launch_delay_ms", self.config.browser_launch_delay_ms))
        self._browser_stagger_delay_var = ctk.IntVar(value=self.settings_service.get_delay_setting("browser_stagger_delay_ms", self.config.browser_stagger_delay_ms))
        self._wave_delay_var = ctk.IntVar(value=self.settings_service.get_delay_setting("wave_delay_ms", 5000))
        self._qwen_browser_delay_var = ctk.IntVar(value=self.settings_service.get_delay_setting("qwen_browser_delay_ms", 2000))
        
        # Load timeout settings
        self._browser_timeout_var = ctk.IntVar(value=self.settings_service.get_timeout_setting("browser_timeout", self.config.browser_timeout) // 1000)
        self._navigation_timeout_var = ctk.IntVar(value=self.settings_service.get_timeout_setting("navigation_timeout", self.config.navigation_timeout) // 1000)
        self._button_wait_var = ctk.IntVar(value=self.settings_service.get_timeout_setting("button_wait_seconds", self.config.button_wait_seconds))
        self._notification_timeout_var = ctk.IntVar(value=self.settings_service.get_timeout_setting("notification_timeout_seconds", self.config.notification_timeout_seconds))
        
        # Load upload settings
        self._upload_delay_var = ctk.IntVar(value=self.settings_service.get_delay_setting("upload_delay", self.config.upload_delay))
        self._upload_delay_last_var = ctk.IntVar(value=self.settings_service.get_delay_setting("upload_delay_last", self.config.upload_delay_last))
        self._create_click_delay_var = ctk.IntVar(value=self.settings_service.get_delay_setting("create_click_delay", self.config.create_click_delay))
        
        # Load batch settings
        self._max_concurrent_tasks_var = ctk.IntVar(value=self.settings_service.get_batch_setting("max_concurrent_tasks", self.config.max_concurrent_tasks))
        self._max_variants_var = ctk.IntVar(value=self.settings_service.get_batch_setting("max_variants_per_task", self.config.max_variants_per_task))
        self._semaphore_limit_var = ctk.IntVar(value=self.settings_service.get_batch_setting("semaphore_limit", self.config.semaphore_limit))
        
        # Other delays
        self._scroll_delay_var = ctk.IntVar(value=self.settings_service.get_delay_setting("scroll_delay", self.config.scroll_delay))
        self._download_timeout_var = ctk.IntVar(value=self.settings_service.get_timeout_setting("download_timeout", self.config.download_timeout) // 1000)
        self._navigation_retries_var = ctk.IntVar(value=self.settings_service.get_batch_setting("navigation_retries", self.config.navigation_retries))
        
        # Load saved profiles
        saved_profiles = self.settings_service.get_selected_profiles()
        saved_available = self.settings_service.get_available_profiles()
        
        # Use saved available profiles, or fall back to PROFILES from core, or config default_profiles
        if saved_available:
            self._available_profiles: List[str] = saved_available
        elif PROFILES:
            self._available_profiles: List[str] = list(PROFILES)
        else:
            self._available_profiles: List[str] = list(self.config.default_profiles)
        
        # Use saved selected profiles, or default to all available
        if saved_profiles:
            # Filter to only include profiles that are still available
            self._selected_profiles: List[str] = [p for p in saved_profiles if p in self._available_profiles]
        else:
            self._selected_profiles: List[str] = list(self._available_profiles)
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup enhanced settings UI."""
        # Header with improved typography
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.pack(pady=(30, 25))
        
        header = ctk.CTkLabel(
            header_frame,
            text="⚙️ Settings",
            font=("Segoe UI", 36, "bold"),
            text_color=self.app.colors["accent"]
        )
        header.pack()
        
        subtitle = ctk.CTkLabel(
            header_frame,
            text="Configure application preferences and behavior",
            font=("Segoe UI", 14),
            text_color=self.app.colors["text_secondary"]
        )
        subtitle.pack(pady=(8, 0))
        
        # Settings container
        settings_container = ctk.CTkScrollableFrame(
            self,
            fg_color=self.app.colors["bg"],
            width=1100
        )
        settings_container.pack(fill="both", expand=True, padx=50, pady=20)
        
        # Chrome Profiles Section
        profiles_frame = ctk.CTkFrame(
            settings_container,
            fg_color=self.app.colors["card"],
            corner_radius=14,
            border_width=1,
            border_color=self.app.colors["border"]
        )
        profiles_frame.pack(fill="x", pady=12)
        
        profiles_title = ctk.CTkLabel(
            profiles_frame,
            text="👤 Chrome Profiles",
            font=("Segoe UI", 22, "bold"),
            text_color=self.app.colors["text"]
        )
        profiles_title.pack(anchor="w", padx=25, pady=(25, 10))
        
        profiles_desc = ctk.CTkLabel(
            profiles_frame,
            text="Select which Chrome profiles to use for all operations (Pairing, Outpaint, Qwen)",
            font=("Segoe UI", 13),
            text_color=self.app.colors["text_secondary"]
        )
        profiles_desc.pack(anchor="w", padx=25, pady=(0, 15))
        
        profile_container = ctk.CTkFrame(profiles_frame, fg_color="transparent")
        profile_container.pack(fill="x", padx=25, pady=(0, 25))
        
        self.profile_selector = ProfileSelector(
            profile_container,
            available_profiles=self._available_profiles,
            selected_profiles=self._selected_profiles,
            on_change=self._on_profiles_changed,
            on_profiles_updated=self._on_profiles_list_updated,
            colors=self.app.colors,
            chrome_base=self.config.chrome_base
        )
        self.profile_selector.pack(fill="both", expand=True, padx=0, pady=0)
        
        # General Settings Section
        general_frame = ctk.CTkFrame(
            settings_container,
            fg_color=self.app.colors["card"],
            corner_radius=14,
            border_width=1,
            border_color=self.app.colors["border"]
        )
        general_frame.pack(fill="x", pady=12)
        
        section_title = ctk.CTkLabel(
            general_frame,
            text="⚙️ General Settings",
            font=("Segoe UI", 22, "bold"),
            text_color=self.app.colors["text"]
        )
        section_title.pack(anchor="w", padx=25, pady=(25, 15))

        # Appearance mode
        appearance_row = ctk.CTkFrame(general_frame, fg_color="transparent")
        appearance_row.pack(fill="x", padx=25, pady=10)
        
        appearance_label = ctk.CTkLabel(
            appearance_row,
            text="Appearance:",
            font=("Segoe UI", 15),
            text_color=self.app.colors["text"]
        )
        appearance_label.pack(side="left")
        
        appearance_menu = ctk.CTkOptionMenu(
            appearance_row,
            values=["Dark", "Light", "System"],
            variable=self._appearance_var,
            command=self._on_appearance_change,
            width=150
        )
        appearance_menu.pack(side="left", padx=15)

        # UI scaling
        scaling_row = ctk.CTkFrame(general_frame, fg_color="transparent")
        scaling_row.pack(fill="x", padx=25, pady=10)
        
        scaling_label = ctk.CTkLabel(
            scaling_row,
            text="UI Scale:",
            font=("Segoe UI", 15),
            text_color=self.app.colors["text"]
        )
        scaling_label.pack(side="left")
        
        scaling_slider = ctk.CTkSlider(
            scaling_row,
            from_=0.8,
            to=1.4,
            number_of_steps=12,
            variable=self._ui_scale_var,
            command=lambda v: self._on_scale_change(float(v)),
            width=200
        )
        scaling_slider.pack(side="left", padx=15)
        
        self._scale_value_label = ctk.CTkLabel(
            scaling_row,
            text=f"{int(self._ui_scale_var.get() * 100)}%",
            font=("Segoe UI", 13),
            text_color=self.app.colors["text_secondary"],
            width=50
        )
        self._scale_value_label.pack(side="left", padx=6)
        
        # Chrome Profile Path
        profile_path_row = ctk.CTkFrame(general_frame, fg_color="transparent")
        profile_path_row.pack(fill="x", padx=25, pady=10)
        
        profile_path_label = ctk.CTkLabel(
            profile_path_row,
            text="Chrome Profile Path:",
            font=("Segoe UI", 15),
            text_color=self.app.colors["text"]
        )
        profile_path_label.pack(anchor="w", pady=(0, 8))
        
        profile_path_entry_frame = ctk.CTkFrame(profile_path_row, fg_color="transparent")
        profile_path_entry_frame.pack(fill="x")
        
        self.profile_path_entry = ctk.CTkEntry(
            profile_path_entry_frame,
            width=600,
            font=("Segoe UI", 12)
        )
        self.profile_path_entry.insert(0, str(self.config.chrome_base))
        self.profile_path_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        setup_clipboard_support(self.profile_path_entry)
        
        browse_profile_btn = ctk.CTkButton(
            profile_path_entry_frame,
            text="Browse",
            width=100,
            height=32,
            command=self._browse_chrome_path
        )
        browse_profile_btn.pack(side="left")
        
        # Sora URL
        url_row = ctk.CTkFrame(general_frame, fg_color="transparent")
        url_row.pack(fill="x", padx=25, pady=10)
        
        url_label = ctk.CTkLabel(
            url_row,
            text="Sora URL:",
            font=("Segoe UI", 15),
            text_color=self.app.colors["text"]
        )
        url_label.pack(anchor="w", pady=(0, 8))
        
        self.url_entry = ctk.CTkEntry(
            url_row,
            width=600,
            font=("Segoe UI", 12)
        )
        setup_clipboard_support(self.url_entry)
        self.url_entry.insert(0, self.config.sora_url)
        self.url_entry.pack(anchor="w", fill="x")
        
        general_frame.pack(pady=(0, 12))
        
        # Browser Settings Section
        browser_frame = ctk.CTkFrame(
            settings_container,
            fg_color=self.app.colors["card"],
            corner_radius=14,
            border_width=1,
            border_color=self.app.colors["border"]
        )
        browser_frame.pack(fill="x", pady=12)
        
        browser_title = ctk.CTkLabel(
            browser_frame,
            text="🌐 Browser Settings",
            font=("Segoe UI", 22, "bold"),
            text_color=self.app.colors["text"]
        )
        browser_title.pack(anchor="w", padx=25, pady=(25, 15))
        
        # Max Concurrent Browser Launches (Browsers per wave)
        launches_row = ctk.CTkFrame(browser_frame, fg_color="transparent")
        launches_row.pack(fill="x", padx=25, pady=10)
        
        launches_label = ctk.CTkLabel(
            launches_row,
            text="Browsers per Wave:",
            font=("Segoe UI", 14),
            text_color=self.app.colors["text"],
            width=200
        )
        launches_label.pack(side="left")
        
        launches_entry = ctk.CTkEntry(
            launches_row,
            textvariable=self._max_concurrent_launches_var,
            width=100,
            font=("Segoe UI", 13)
        )
        launches_entry.pack(side="left", padx=10)
        
        launches_desc = ctk.CTkLabel(
            launches_row,
            text="(How many browsers launch simultaneously)",
            font=("Segoe UI", 11),
            text_color=self.app.colors["text_muted"]
        )
        launches_desc.pack(side="left", padx=10)
        
        # Max Parallel Browsers
        parallel_row = ctk.CTkFrame(browser_frame, fg_color="transparent")
        parallel_row.pack(fill="x", padx=25, pady=10)
        
        parallel_label = ctk.CTkLabel(
            parallel_row,
            text="Max Parallel Browsers:",
            font=("Segoe UI", 14),
            text_color=self.app.colors["text"],
            width=200
        )
        parallel_label.pack(side="left")
        
        parallel_entry = ctk.CTkEntry(
            parallel_row,
            textvariable=self._max_parallel_browsers_var,
            width=100,
            font=("Segoe UI", 13)
        )
        parallel_entry.pack(side="left", padx=10)
        
        parallel_desc = ctk.CTkLabel(
            parallel_row,
            text="(Maximum browsers open at once)",
            font=("Segoe UI", 11),
            text_color=self.app.colors["text_muted"]
        )
        parallel_desc.pack(side="left", padx=10)
        
        # Browser Launch Delay
        launch_delay_row = ctk.CTkFrame(browser_frame, fg_color="transparent")
        launch_delay_row.pack(fill="x", padx=25, pady=10)
        
        launch_delay_label = ctk.CTkLabel(
            launch_delay_row,
            text="Browser Launch Delay (ms):",
            font=("Segoe UI", 14),
            text_color=self.app.colors["text"],
            width=200
        )
        launch_delay_label.pack(side="left")
        
        launch_delay_entry = ctk.CTkEntry(
            launch_delay_row,
            textvariable=self._browser_launch_delay_var,
            width=100,
            font=("Segoe UI", 13)
        )
        launch_delay_entry.pack(side="left", padx=10)
        
        # Browser Stagger Delay
        stagger_delay_row = ctk.CTkFrame(browser_frame, fg_color="transparent")
        stagger_delay_row.pack(fill="x", padx=25, pady=10)
        
        stagger_delay_label = ctk.CTkLabel(
            stagger_delay_row,
            text="Browser Stagger Delay (ms):",
            font=("Segoe UI", 14),
            text_color=self.app.colors["text"],
            width=200
        )
        stagger_delay_label.pack(side="left")
        
        stagger_delay_entry = ctk.CTkEntry(
            stagger_delay_row,
            textvariable=self._browser_stagger_delay_var,
            width=100,
            font=("Segoe UI", 13)
        )
        stagger_delay_entry.pack(side="left", padx=10)
        
        # Wave Delay (delay between waves)
        wave_delay_row = ctk.CTkFrame(browser_frame, fg_color="transparent")
        wave_delay_row.pack(fill="x", padx=25, pady=10)
        
        wave_delay_label = ctk.CTkLabel(
            wave_delay_row,
            text="Wave Delay (ms):",
            font=("Segoe UI", 14),
            text_color=self.app.colors["text"],
            width=200
        )
        wave_delay_label.pack(side="left")
        
        wave_delay_entry = ctk.CTkEntry(
            wave_delay_row,
            textvariable=self._wave_delay_var,
            width=100,
            font=("Segoe UI", 13)
        )
        wave_delay_entry.pack(side="left", padx=10)
        
        wave_delay_desc = ctk.CTkLabel(
            wave_delay_row,
            text="(Delay before starting next wave, to allow first wave to load)",
            font=("Segoe UI", 11),
            text_color=self.app.colors["text_muted"]
        )
        wave_delay_desc.pack(side="left", padx=10)
        
        # Qwen Browser Delay (delay between Qwen browser launches)
        qwen_delay_row = ctk.CTkFrame(browser_frame, fg_color="transparent")
        qwen_delay_row.pack(fill="x", padx=25, pady=10)
        
        qwen_delay_label = ctk.CTkLabel(
            qwen_delay_row,
            text="Qwen Browser Delay (ms):",
            font=("Segoe UI", 14),
            text_color=self.app.colors["text"],
            width=200
        )
        qwen_delay_label.pack(side="left")
        
        qwen_delay_entry = ctk.CTkEntry(
            qwen_delay_row,
            textvariable=self._qwen_browser_delay_var,
            width=100,
            font=("Segoe UI", 13)
        )
        qwen_delay_entry.pack(side="left", padx=10)
        
        qwen_delay_desc = ctk.CTkLabel(
            qwen_delay_row,
            text="(Large delay between Qwen browser launches for stability)",
            font=("Segoe UI", 11),
            text_color=self.app.colors["text_muted"]
        )
        qwen_delay_desc.pack(side="left", padx=10)
        
        # Timeout Settings Section
        timeout_frame = ctk.CTkFrame(
            settings_container,
            fg_color=self.app.colors["card"],
            corner_radius=14,
            border_width=1,
            border_color=self.app.colors["border"]
        )
        timeout_frame.pack(fill="x", pady=12)
        
        timeout_title = ctk.CTkLabel(
            timeout_frame,
            text="⏱️ Timeout Settings",
            font=("Segoe UI", 22, "bold"),
            text_color=self.app.colors["text"]
        )
        timeout_title.pack(anchor="w", padx=25, pady=(25, 15))
        
        # Browser Timeout
        browser_timeout_row = ctk.CTkFrame(timeout_frame, fg_color="transparent")
        browser_timeout_row.pack(fill="x", padx=25, pady=8)
        
        browser_timeout_label = ctk.CTkLabel(
            browser_timeout_row,
            text="Browser Timeout (seconds):",
            font=("Segoe UI", 13),
            text_color=self.app.colors["text"],
            width=200
        )
        browser_timeout_label.pack(side="left")
        
        browser_timeout_entry = ctk.CTkEntry(
            browser_timeout_row,
            textvariable=self._browser_timeout_var,
            width=100,
            font=("Segoe UI", 13)
        )
        browser_timeout_entry.pack(side="left", padx=10)
        
        # Navigation Timeout
        nav_timeout_row = ctk.CTkFrame(timeout_frame, fg_color="transparent")
        nav_timeout_row.pack(fill="x", padx=25, pady=8)
        
        nav_timeout_label = ctk.CTkLabel(
            nav_timeout_row,
            text="Navigation Timeout (seconds):",
            font=("Segoe UI", 13),
            text_color=self.app.colors["text"],
            width=200
        )
        nav_timeout_label.pack(side="left")
        
        nav_timeout_entry = ctk.CTkEntry(
            nav_timeout_row,
            textvariable=self._navigation_timeout_var,
            width=100,
            font=("Segoe UI", 13)
        )
        nav_timeout_entry.pack(side="left", padx=10)
        
        # Button Wait
        button_wait_row = ctk.CTkFrame(timeout_frame, fg_color="transparent")
        button_wait_row.pack(fill="x", padx=25, pady=8)
        
        button_wait_label = ctk.CTkLabel(
            button_wait_row,
            text="Create Button Wait (seconds):",
            font=("Segoe UI", 13),
            text_color=self.app.colors["text"],
            width=200
        )
        button_wait_label.pack(side="left")
        
        button_wait_entry = ctk.CTkEntry(
            button_wait_row,
            textvariable=self._button_wait_var,
            width=100,
            font=("Segoe UI", 13)
        )
        button_wait_entry.pack(side="left", padx=10)
        
        # Notification Timeout
        notif_timeout_row = ctk.CTkFrame(timeout_frame, fg_color="transparent")
        notif_timeout_row.pack(fill="x", padx=25, pady=8)
        
        notif_timeout_label = ctk.CTkLabel(
            notif_timeout_row,
            text="Notification Timeout (seconds):",
            font=("Segoe UI", 13),
            text_color=self.app.colors["text"],
            width=200
        )
        notif_timeout_label.pack(side="left")
        
        notif_timeout_entry = ctk.CTkEntry(
            notif_timeout_row,
            textvariable=self._notification_timeout_var,
            width=100,
            font=("Segoe UI", 13)
        )
        notif_timeout_entry.pack(side="left", padx=10)
        
        # Upload Settings Section
        upload_frame = ctk.CTkFrame(
            settings_container,
            fg_color=self.app.colors["card"],
            corner_radius=14,
            border_width=1,
            border_color=self.app.colors["border"]
        )
        upload_frame.pack(fill="x", pady=12)
        
        upload_title = ctk.CTkLabel(
            upload_frame,
            text="📤 Upload Settings",
            font=("Segoe UI", 22, "bold"),
            text_color=self.app.colors["text"]
        )
        upload_title.pack(anchor="w", padx=25, pady=(25, 15))
        
        # Upload Delay
        upload_delay_row = ctk.CTkFrame(upload_frame, fg_color="transparent")
        upload_delay_row.pack(fill="x", padx=25, pady=8)
        
        upload_delay_label = ctk.CTkLabel(
            upload_delay_row,
            text="Upload Delay (ms):",
            font=("Segoe UI", 13),
            text_color=self.app.colors["text"],
            width=200
        )
        upload_delay_label.pack(side="left")
        
        upload_delay_entry = ctk.CTkEntry(
            upload_delay_row,
            textvariable=self._upload_delay_var,
            width=100,
            font=("Segoe UI", 13)
        )
        upload_delay_entry.pack(side="left", padx=10)
        
        # Upload Delay Last
        upload_delay_last_row = ctk.CTkFrame(upload_frame, fg_color="transparent")
        upload_delay_last_row.pack(fill="x", padx=25, pady=8)
        
        upload_delay_last_label = ctk.CTkLabel(
            upload_delay_last_row,
            text="Last Upload Delay (ms):",
            font=("Segoe UI", 13),
            text_color=self.app.colors["text"],
            width=200
        )
        upload_delay_last_label.pack(side="left")
        
        upload_delay_last_entry = ctk.CTkEntry(
            upload_delay_last_row,
            textvariable=self._upload_delay_last_var,
            width=100,
            font=("Segoe UI", 13)
        )
        upload_delay_last_entry.pack(side="left", padx=10)
        
        # Create Click Delay
        create_click_delay_row = ctk.CTkFrame(upload_frame, fg_color="transparent")
        create_click_delay_row.pack(fill="x", padx=25, pady=8)
        
        create_click_delay_label = ctk.CTkLabel(
            create_click_delay_row,
            text="Create Click Delay (ms):",
            font=("Segoe UI", 13),
            text_color=self.app.colors["text"],
            width=200
        )
        create_click_delay_label.pack(side="left")
        
        create_click_delay_entry = ctk.CTkEntry(
            create_click_delay_row,
            textvariable=self._create_click_delay_var,
            width=100,
            font=("Segoe UI", 13)
        )
        create_click_delay_entry.pack(side="left", padx=10)
        
        # Batch Settings Section
        batch_frame = ctk.CTkFrame(
            settings_container,
            fg_color=self.app.colors["card"],
            corner_radius=14,
            border_width=1,
            border_color=self.app.colors["border"]
        )
        batch_frame.pack(fill="x", pady=12)
        
        batch_title = ctk.CTkLabel(
            batch_frame,
            text="📦 Batch Processing",
            font=("Segoe UI", 22, "bold"),
            text_color=self.app.colors["text"]
        )
        batch_title.pack(anchor="w", padx=25, pady=(25, 15))
        
        # Max Concurrent Tasks
        concurrent_row = ctk.CTkFrame(batch_frame, fg_color="transparent")
        concurrent_row.pack(fill="x", padx=25, pady=10)
        
        concurrent_label = ctk.CTkLabel(
            concurrent_row,
            text="Max Concurrent Tasks:",
            font=("Segoe UI", 14),
            text_color=self.app.colors["text"],
            width=200
        )
        concurrent_label.pack(side="left")
        
        concurrent_entry = ctk.CTkEntry(
            concurrent_row,
            textvariable=self._max_concurrent_tasks_var,
            width=100,
            font=("Segoe UI", 13)
        )
        concurrent_entry.pack(side="left", padx=10)
        
        # Max Variants
        variants_row = ctk.CTkFrame(batch_frame, fg_color="transparent")
        variants_row.pack(fill="x", padx=25, pady=10)
        
        variants_label = ctk.CTkLabel(
            variants_row,
            text="Max Variants per Task:",
            font=("Segoe UI", 14),
            text_color=self.app.colors["text"],
            width=200
        )
        variants_label.pack(side="left")
        
        variants_entry = ctk.CTkEntry(
            variants_row,
            textvariable=self._max_variants_var,
            width=100,
            font=("Segoe UI", 13)
        )
        variants_entry.pack(side="left", padx=10)
        
        # Semaphore Limit
        semaphore_row = ctk.CTkFrame(batch_frame, fg_color="transparent")
        semaphore_row.pack(fill="x", padx=25, pady=10)
        
        semaphore_label = ctk.CTkLabel(
            semaphore_row,
            text="Semaphore Limit:",
            font=("Segoe UI", 14),
            text_color=self.app.colors["text"],
            width=200
        )
        semaphore_label.pack(side="left")
        
        semaphore_entry = ctk.CTkEntry(
            semaphore_row,
            textvariable=self._semaphore_limit_var,
            width=100,
            font=("Segoe UI", 13)
        )
        semaphore_entry.pack(side="left", padx=10)
        
        # Other Settings
        other_frame = ctk.CTkFrame(
            settings_container,
            fg_color=self.app.colors["card"],
            corner_radius=14,
            border_width=1,
            border_color=self.app.colors["border"]
        )
        other_frame.pack(fill="x", pady=12)
        
        other_title = ctk.CTkLabel(
            other_frame,
            text="⚙️ Other Settings",
            font=("Segoe UI", 22, "bold"),
            text_color=self.app.colors["text"]
        )
        other_title.pack(anchor="w", padx=25, pady=(25, 15))
        
        # Scroll Delay
        scroll_delay_row = ctk.CTkFrame(other_frame, fg_color="transparent")
        scroll_delay_row.pack(fill="x", padx=25, pady=8)
        
        scroll_delay_label = ctk.CTkLabel(
            scroll_delay_row,
            text="Scroll Delay (ms):",
            font=("Segoe UI", 13),
            text_color=self.app.colors["text"],
            width=200
        )
        scroll_delay_label.pack(side="left")
        
        scroll_delay_entry = ctk.CTkEntry(
            scroll_delay_row,
            textvariable=self._scroll_delay_var,
            width=100,
            font=("Segoe UI", 13)
        )
        scroll_delay_entry.pack(side="left", padx=10)
        
        # Download Timeout
        download_timeout_row = ctk.CTkFrame(other_frame, fg_color="transparent")
        download_timeout_row.pack(fill="x", padx=25, pady=8)
        
        download_timeout_label = ctk.CTkLabel(
            download_timeout_row,
            text="Download Timeout (seconds):",
            font=("Segoe UI", 13),
            text_color=self.app.colors["text"],
            width=200
        )
        download_timeout_label.pack(side="left")
        
        download_timeout_entry = ctk.CTkEntry(
            download_timeout_row,
            textvariable=self._download_timeout_var,
            width=100,
            font=("Segoe UI", 13)
        )
        download_timeout_entry.pack(side="left", padx=10)
        
        # Navigation Retries
        nav_retries_row = ctk.CTkFrame(other_frame, fg_color="transparent")
        nav_retries_row.pack(fill="x", padx=25, pady=8)
        
        nav_retries_label = ctk.CTkLabel(
            nav_retries_row,
            text="Navigation Retries:",
            font=("Segoe UI", 13),
            text_color=self.app.colors["text"],
            width=200
        )
        nav_retries_label.pack(side="left")
        
        nav_retries_entry = ctk.CTkEntry(
            nav_retries_row,
            textvariable=self._navigation_retries_var,
            width=100,
            font=("Segoe UI", 13)
        )
        nav_retries_entry.pack(side="left", padx=10)
        
        # Notification Settings Section
        notif_frame = ctk.CTkFrame(
            settings_container,
            fg_color=self.app.colors["card"],
            corner_radius=14,
            border_width=1,
            border_color=self.app.colors["border"]
        )
        notif_frame.pack(fill="x", pady=12)
        
        notif_title = ctk.CTkLabel(
            notif_frame,
            text="🔔 Notifications",
            font=("Segoe UI", 22, "bold"),
            text_color=self.app.colors["text"]
        )
        notif_title.pack(anchor="w", padx=25, pady=(25, 15))
        
        self.notif_enabled_var = ctk.BooleanVar(value=self.config.notifications_enabled)
        notif_enabled = ctk.CTkCheckBox(
            notif_frame,
            text="Enable Notifications",
            font=("Segoe UI", 14),
            variable=self.notif_enabled_var,
            command=self._on_notification_change
        )
        notif_enabled.pack(anchor="w", padx=25, pady=5)
        
        self.notif_task_var = ctk.BooleanVar(value=self.config.notify_on_task_complete)
        notif_task = ctk.CTkCheckBox(
            notif_frame,
            text="Notify on Task Complete",
            font=("Segoe UI", 13),
            variable=self.notif_task_var
        )
        notif_task.pack(anchor="w", padx=25, pady=5)
        
        self.notif_batch_var = ctk.BooleanVar(value=self.config.notify_on_batch_complete)
        notif_batch = ctk.CTkCheckBox(
            notif_frame,
            text="Notify on Batch Complete",
            font=("Segoe UI", 13),
            variable=self.notif_batch_var
        )
        notif_batch.pack(anchor="w", padx=25, pady=5)
        
        self.notif_error_var = ctk.BooleanVar(value=self.config.notify_on_error)
        notif_error = ctk.CTkCheckBox(
            notif_frame,
            text="Notify on Error",
            font=("Segoe UI", 13),
            variable=self.notif_error_var
        )
        notif_error.pack(anchor="w", padx=25, pady=5)
        
        # Save button
        save_frame = ctk.CTkFrame(settings_container, fg_color="transparent")
        save_frame.pack(fill="x", pady=20)
        
        save_btn = ctk.CTkButton(
            save_frame,
            text="💾 Save Settings",
            font=("Segoe UI", 16, "bold"),
            fg_color=self.app.colors["accent"],
            hover_color=self.app.colors["accent_hover"],
            width=200,
            height=50,
            corner_radius=12,
            command=self._save_settings
        )
        save_btn.pack()
        
        # Info message
        info_frame = ctk.CTkFrame(settings_container, fg_color="transparent")
        info_frame.pack(fill="x", pady=(0, 20))
        
        info = ctk.CTkLabel(
            info_frame,
            text="💡 Note: Some settings require application restart to take effect.",
            font=("Segoe UI", 13),
            text_color=self.app.colors["text_secondary"]
        )
        info.pack()

    def _on_profiles_changed(self, selected: List[str]):
        """Handle profile selection change."""
        self._selected_profiles = selected
        self.settings_service.set_selected_profiles(selected)
        self.logger.info("Profiles updated in settings", count=len(selected))
    
    def _on_profiles_list_updated(self, available: List[str]):
        """Handle available profiles list change (add/remove)."""
        self._available_profiles = available
        self.settings_service.set_available_profiles(available)
        # Update selected profiles to remove any that are no longer available
        self._selected_profiles = [p for p in self._selected_profiles if p in available]
        self.settings_service.set_selected_profiles(self._selected_profiles)
        self.logger.info("Available profiles list updated", count=len(available))
    
    def _on_appearance_change(self, value: str):
        """Change app appearance mode."""
        try:
            import customtkinter as ctk_mod
            ctk_mod.set_appearance_mode(value.lower())
            self.settings_service.set_appearance_mode(value)
            self.app.footer_label.configure(text=f"Appearance set to {value}")
            self.logger.info("Appearance changed", mode=value)
        except Exception as e:
            self.logger.error("Failed to change appearance", error=str(e))

    def _on_scale_change(self, scale_value: float):
        """Change UI scale across widgets."""
        try:
            import customtkinter as ctk_mod
            ctk_mod.set_widget_scaling(scale_value)
            pct = int(round(scale_value * 100))
            self._scale_value_label.configure(text=f"{pct}%")
            self.settings_service.set_ui_scale(scale_value)
            self.logger.debug("UI scale changed", scale=scale_value)
        except Exception as e:
            self.logger.error("Failed to change UI scale", error=str(e))
    
    def _on_notification_change(self):
        """Handle notification enabled change."""
        enabled = self.notif_enabled_var.get()
        self.logger.debug("Notification enabled changed", enabled=enabled)
        # Note: This would need to be saved to config.yaml for persistence
    
    def _browse_chrome_path(self):
        """Browse for Chrome profile directory."""
        directory = filedialog.askdirectory(
            title="Select Chrome User Data Directory",
            initialdir=str(self.config.chrome_base.parent) if self.config.chrome_base.exists() else "."
        )
        if directory:
            self.profile_path_entry.delete(0, "end")
            self.profile_path_entry.insert(0, directory)
            self.logger.info("Chrome path updated", path=directory)
    
    def _save_settings(self):
        """Save all settings."""
        try:
            # Save browser settings
            self.settings_service.set_max_concurrent_browser_launches(self._max_concurrent_launches_var.get())
            self.settings_service.set_max_parallel_browsers(self._max_parallel_browsers_var.get())
            self.settings_service.set_delay_setting("browser_launch_delay_ms", self._browser_launch_delay_var.get())
            self.settings_service.set_delay_setting("browser_stagger_delay_ms", self._browser_stagger_delay_var.get())
            self.settings_service.set_delay_setting("wave_delay_ms", self._wave_delay_var.get())
            self.settings_service.set_delay_setting("qwen_browser_delay_ms", self._qwen_browser_delay_var.get())
            
            # Save timeout settings
            self.settings_service.set_timeout_setting("browser_timeout", self._browser_timeout_var.get() * 1000)
            self.settings_service.set_timeout_setting("navigation_timeout", self._navigation_timeout_var.get() * 1000)
            self.settings_service.set_timeout_setting("button_wait_seconds", self._button_wait_var.get())
            self.settings_service.set_timeout_setting("notification_timeout_seconds", self._notification_timeout_var.get())
            
            # Save upload settings
            self.settings_service.set_delay_setting("upload_delay", self._upload_delay_var.get())
            self.settings_service.set_delay_setting("upload_delay_last", self._upload_delay_last_var.get())
            self.settings_service.set_delay_setting("create_click_delay", self._create_click_delay_var.get())
            
            # Save batch settings
            self.settings_service.set_batch_setting("max_concurrent_tasks", self._max_concurrent_tasks_var.get())
            self.settings_service.set_batch_setting("max_variants_per_task", self._max_variants_var.get())
            self.settings_service.set_batch_setting("semaphore_limit", self._semaphore_limit_var.get())
            
            # Save other settings
            self.settings_service.set_delay_setting("scroll_delay", self._scroll_delay_var.get())
            self.settings_service.set_timeout_setting("download_timeout", self._download_timeout_var.get() * 1000)
            self.settings_service.set_batch_setting("navigation_retries", self._navigation_retries_var.get())
            
            show_info(
                "Settings Saved",
                "All settings have been saved successfully!\n\n"
                "Note: Chrome Profile Path and Sora URL changes require editing config.yaml manually.\n"
                "Some settings may require restarting the application to take full effect.",
                logger=self.logger
            )
        except Exception as e:
            show_error(
                "Save Error",
                "Failed to save settings",
                details=str(e),
                exc_info=e,
                logger=self.logger
            )
