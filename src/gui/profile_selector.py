"""Profile selector component for choosing Chrome profiles."""

import customtkinter as ctk
from typing import List, Optional, Callable
from pathlib import Path
from tkinter import messagebox, simpledialog


class ProfileSelector(ctk.CTkFrame):
    """Component for selecting Chrome profiles with checkboxes and add/remove functionality."""
    
    def __init__(
        self,
        parent,
        available_profiles: List[str],
        selected_profiles: Optional[List[str]] = None,
        on_change: Optional[Callable[[List[str]], None]] = None,
        on_profiles_updated: Optional[Callable[[List[str]], None]] = None,
        colors: Optional[dict] = None,
        chrome_base: Optional[Path] = None
    ):
        """
        Initialize profile selector.
        
        Args:
            parent: Parent widget
            available_profiles: List of all available profile names
            selected_profiles: Initially selected profiles (defaults to all)
            on_change: Callback when selection changes
            on_profiles_updated: Callback when available profiles list changes (add/remove)
            colors: Color scheme dict
            chrome_base: Chrome base directory path for validation
        """
        super().__init__(parent, fg_color="transparent")
        
        self.available_profiles = list(available_profiles)  # Make it mutable
        self.selected_profiles = set(selected_profiles) if selected_profiles else set(available_profiles)
        self.on_change = on_change
        self.on_profiles_updated = on_profiles_updated
        self.colors = colors or {}
        self.chrome_base = chrome_base
        
        self.checkboxes: dict[str, ctk.CTkCheckBox] = {}
        self.container = None
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup profile selector UI."""
        # Header
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.pack(fill="x", pady=(0, 12))
        
        title = ctk.CTkLabel(
            header_frame,
            text="Chrome Profiles",
            font=("Segoe UI", 16, "bold"),
            text_color=self.colors.get("text", "#FFFFFF")
        )
        title.pack(side="left")
        
        count_label = ctk.CTkLabel(
            header_frame,
            text=f"({len(self.selected_profiles)}/{len(self.available_profiles)} selected)",
            font=("Segoe UI", 13),
            text_color=self.colors.get("text_secondary", "#B3B3B3")
        )
        count_label.pack(side="left", padx=(8, 0))
        self.count_label = count_label
        
        # Action buttons frame
        button_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        button_frame.pack(side="right")
        
        # Add profile button
        add_profile_btn = ctk.CTkButton(
            button_frame,
            text="➕ Add",
            font=("Segoe UI", 11),
            fg_color=self.colors.get("success", "#26d67c"),
            hover_color=self.colors.get("success_hover", "#2EE88C"),
            width=70,
            height=28,
            corner_radius=6,
            command=self._add_profile
        )
        add_profile_btn.pack(side="left", padx=(0, 6))
        
        # Select all button
        select_all_btn = ctk.CTkButton(
            button_frame,
            text="Select All",
            font=("Segoe UI", 11),
            fg_color=self.colors.get("secondary", "#564D4D"),
            hover_color=self.colors.get("secondary_hover", "#6B5B5B"),
            width=90,
            height=28,
            corner_radius=6,
            command=self._select_all
        )
        select_all_btn.pack(side="left", padx=(0, 6))
        
        # Deselect all button
        deselect_all_btn = ctk.CTkButton(
            button_frame,
            text="Deselect All",
            font=("Segoe UI", 11),
            fg_color=self.colors.get("secondary", "#564D4D"),
            hover_color=self.colors.get("secondary_hover", "#6B5B5B"),
            width=90,
            height=28,
            corner_radius=6,
            command=self._deselect_all
        )
        deselect_all_btn.pack(side="left")
        
        # Profiles container with scroll
        self.container = ctk.CTkScrollableFrame(
            self,
            fg_color=self.colors.get("card", "#1A1A1A"),
            corner_radius=10,
            border_width=1,
            border_color=self.colors.get("border", "#333333"),
            height=min(250, len(self.available_profiles) * 40 + 30)
        )
        self.container.pack(fill="both", expand=True)
        
        # Create checkboxes for each profile
        self._refresh_profiles_list()
    
    def _create_profile_checkbox(self, parent, profile: str):
        """Create a checkbox for a profile with remove button."""
        checkbox_frame = ctk.CTkFrame(parent, fg_color="transparent")
        checkbox_frame.pack(fill="x", padx=10, pady=6)
        
        var = ctk.BooleanVar(value=profile in self.selected_profiles)
        checkbox = ctk.CTkCheckBox(
            checkbox_frame,
            text=profile,
            variable=var,
            font=("Segoe UI", 13),
            command=lambda p=profile, v=var: self._on_checkbox_change(p, v)
        )
        checkbox.pack(side="left", padx=(0, 10))
        
        # Status indicator (check if profile exists)
        if self.chrome_base:
            profile_path = self.chrome_base / profile
            if profile_path.exists():
                status_label = ctk.CTkLabel(
                    checkbox_frame,
                    text="✓",
                    font=("Segoe UI", 12),
                    text_color=self.colors.get("success", "#26d67c"),
                    width=20
                )
                status_label.pack(side="left", padx=(0, 5))
            else:
                status_label = ctk.CTkLabel(
                    checkbox_frame,
                    text="⚠",
                    font=("Segoe UI", 12),
                    text_color=self.colors.get("warning", "#FFD166"),
                    width=20
                )
                status_label.pack(side="left", padx=(0, 5))
        
        # Remove button (only for custom profiles, not default ones)
        # We'll allow removing any profile, but warn if it's in use
        remove_btn = ctk.CTkButton(
            checkbox_frame,
            text="🗑️",
            font=("Segoe UI", 12),
            fg_color="transparent",
            hover_color=self.colors.get("error", "#E50914"),
            width=30,
            height=25,
            corner_radius=5,
            command=lambda p=profile: self._remove_profile(p)
        )
        remove_btn.pack(side="right")
        
        self.checkboxes[profile] = checkbox
        checkbox_frame.profile_name = profile  # Store for removal
    
    def _on_checkbox_change(self, profile: str, var: ctk.BooleanVar):
        """Handle checkbox state change."""
        if var.get():
            self.selected_profiles.add(profile)
        else:
            self.selected_profiles.discard(profile)
        
        self._update_count()
        
        if self.on_change:
            self.on_change(self.get_selected())
    
    def _select_all(self):
        """Select all profiles."""
        for profile, checkbox in self.checkboxes.items():
            checkbox.select()
            self.selected_profiles.add(profile)
        
        self._update_count()
        
        if self.on_change:
            self.on_change(self.get_selected())
    
    def _deselect_all(self):
        """Deselect all profiles."""
        for profile, checkbox in self.checkboxes.items():
            checkbox.deselect()
            self.selected_profiles.clear()
        
        self._update_count()
        
        if self.on_change:
            self.on_change(self.get_selected())
    
    def _add_profile(self):
        """Add a new profile."""
        # Ask for profile name
        profile_name = simpledialog.askstring(
            "Add Chrome Profile",
            "Enter profile name (e.g., 'Profile 1', 'Profile 10', 'Default'):",
            initialvalue="Profile "
        )
        
        if not profile_name or not profile_name.strip():
            return
        
        profile_name = profile_name.strip()
        
        # Check if already exists
        if profile_name in self.available_profiles:
            messagebox.showwarning("Profile Exists", f"Profile '{profile_name}' is already in the list.")
            return
        
        # Validate profile path if chrome_base is provided
        if self.chrome_base:
            profile_path = self.chrome_base / profile_name
            if not profile_path.exists():
                response = messagebox.askyesno(
                    "Profile Not Found",
                    f"Profile '{profile_name}' was not found at:\n{profile_path}\n\n"
                    "Do you want to add it anyway? (You can create it later in Chrome)"
                )
                if not response:
                    return
        
        # Add to list
        self.available_profiles.append(profile_name)
        self.selected_profiles.add(profile_name)
        
        # Refresh UI
        self._refresh_profiles_list()
        self._update_count()
        
        # Notify callbacks
        if self.on_change:
            self.on_change(self.get_selected())
        if self.on_profiles_updated:
            self.on_profiles_updated(self.available_profiles)
    
    def _remove_profile(self, profile: str):
        """Remove a profile from the list."""
        if profile not in self.available_profiles:
            return
        
        # Warn if selected
        if profile in self.selected_profiles:
            response = messagebox.askyesno(
                "Remove Profile",
                f"Profile '{profile}' is currently selected.\n\n"
                "Do you want to remove it from the list?\n"
                "(This won't delete the actual Chrome profile)"
            )
            if not response:
                return
        
        # Remove from lists
        self.available_profiles.remove(profile)
        self.selected_profiles.discard(profile)
        
        # Refresh UI
        self._refresh_profiles_list()
        self._update_count()
        
        # Notify callbacks
        if self.on_change:
            self.on_change(self.get_selected())
        if self.on_profiles_updated:
            self.on_profiles_updated(self.available_profiles)
    
    def _refresh_profiles_list(self):
        """Refresh the profiles list UI."""
        if not self.container:
            return
        
        # Clear existing widgets
        for widget in self.container.winfo_children():
            widget.destroy()
        self.checkboxes.clear()
        
        # Recreate checkboxes
        for profile in sorted(self.available_profiles):
            self._create_profile_checkbox(self.container, profile)
    
    def _update_count(self):
        """Update the count label."""
        count = len(self.selected_profiles)
        total = len(self.available_profiles)
        self.count_label.configure(text=f"({count}/{total} selected)")
    
    def get_selected(self) -> List[str]:
        """Get list of selected profiles."""
        return sorted(list(self.selected_profiles))
    
    def get_available(self) -> List[str]:
        """Get list of all available profiles."""
        return list(self.available_profiles)
    
    def set_available(self, profiles: List[str]):
        """Set available profiles list."""
        self.available_profiles = list(profiles)
        # Remove selected profiles that are no longer available
        self.selected_profiles = {p for p in self.selected_profiles if p in self.available_profiles}
        self._refresh_profiles_list()
        self._update_count()
        if self.on_profiles_updated:
            self.on_profiles_updated(self.available_profiles)
    
    def set_selected(self, profiles: List[str]):
        """Set selected profiles."""
        self.selected_profiles = set(profiles)
        for profile, checkbox in self.checkboxes.items():
            if profile in self.selected_profiles:
                checkbox.select()
            else:
                checkbox.deselect()
        
        self._update_count()
        
        if self.on_change:
            self.on_change(self.get_selected())

