"""UI improvements and helper utilities for better UX."""

import customtkinter as ctk
from typing import Optional, Callable


class ImprovedButton(ctk.CTkButton):
    """Enhanced button with better hover effects and feedback."""
    
    def __init__(self, parent, *args, **kwargs):
        # Extract custom parameters
        icon = kwargs.pop('icon', None)
        description = kwargs.pop('description', None)
        
        # Build text with icon if provided
        if icon:
            text = kwargs.get('text', '')
            if text:
                kwargs['text'] = f"{icon} {text}"
            else:
                kwargs['text'] = icon
        
        super().__init__(parent, *args, **kwargs)
        
        # Add description tooltip if provided
        if description:
            from src.gui.tooltip import create_tooltip
            create_tooltip(self, description)
        
        # Enhanced hover effect
        self._original_fg_color = kwargs.get('fg_color', 'transparent')
        self._original_hover_color = kwargs.get('hover_color', None)
        
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
    
    def _on_enter(self, event):
        """Enhanced hover effect."""
        if self._original_hover_color:
            self.configure(fg_color=self._original_hover_color)
    
    def _on_leave(self, event):
        """Reset on leave."""
        if self._original_fg_color:
            self.configure(fg_color=self._original_fg_color)


class StatusCard(ctk.CTkFrame):
    """Card component for displaying status information."""
    
    def __init__(self, parent, title: str, value: str, icon: Optional[str] = None, 
                 color: Optional[str] = None, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        
        self.title = title
        self.value = value
        self.icon = icon
        self.color = color or "#007AFF"
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup card UI."""
        # Icon and title row
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.pack(fill="x", padx=15, pady=(15, 8))
        
        if self.icon:
            icon_label = ctk.CTkLabel(
                header_frame,
                text=self.icon,
                font=("Segoe UI", 20)
            )
            icon_label.pack(side="left", padx=(0, 8))
        
        title_label = ctk.CTkLabel(
            header_frame,
            text=self.title,
            font=("Segoe UI", 12),
            text_color="#8E8E93"
        )
        title_label.pack(side="left")
        
        # Value
        value_label = ctk.CTkLabel(
            self,
            text=self.value,
            font=("Segoe UI", 24, "bold"),
            text_color=self.color
        )
        value_label.pack(padx=15, pady=(0, 15))
        
        self.value_label = value_label
    
    def update_value(self, new_value: str, color: Optional[str] = None):
        """Update the displayed value."""
        self.value = new_value
        self.value_label.configure(text=new_value)
        if color:
            self.value_label.configure(text_color=color)


class ActionButton(ctk.CTkButton):
    """Large action button with icon and description."""
    
    def __init__(self, parent, text: str, icon: str, description: str,
                 command: Optional[Callable] = None, *args, **kwargs):
        # Build full text
        full_text = f"{icon} {text}"
        
        # Default styling for action buttons
        defaults = {
            'font': ("Segoe UI", 18, "bold"),
            'height': 60,
            'corner_radius': 14,
            'fg_color': "#007AFF",
            'hover_color': "#0051D5",
        }
        defaults.update(kwargs)
        
        super().__init__(parent, text=full_text, command=command, *args, **defaults)
        
        # Add tooltip
        if description:
            from src.gui.tooltip import create_tooltip
            create_tooltip(self, description)


class SectionHeader(ctk.CTkFrame):
    """Section header with title and optional action button."""
    
    def __init__(self, parent, title: str, subtitle: Optional[str] = None,
                 action_text: Optional[str] = None, action_command: Optional[Callable] = None,
                 *args, **kwargs):
        super().__init__(parent, fg_color="transparent", *args, **kwargs)
        
        self.title = title
        self.subtitle = subtitle
        self.action_text = action_text
        self.action_command = action_command
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup section header UI."""
        # Left side: Title and subtitle
        left_frame = ctk.CTkFrame(self, fg_color="transparent")
        left_frame.pack(side="left", fill="x", expand=True)
        
        title_label = ctk.CTkLabel(
            left_frame,
            text=self.title,
            font=("Segoe UI", 24, "bold"),
            anchor="w"
        )
        title_label.pack(anchor="w", pady=(0, 4) if self.subtitle else 0)
        
        if self.subtitle:
            subtitle_label = ctk.CTkLabel(
                left_frame,
                text=self.subtitle,
                font=("Segoe UI", 13),
                text_color="#8E8E93",
                anchor="w"
            )
            subtitle_label.pack(anchor="w")
        
        # Right side: Action button
        if self.action_text and self.action_command:
            action_btn = ctk.CTkButton(
                self,
                text=self.action_text,
                font=("Segoe UI", 14),
                fg_color="#48484A",
                hover_color="#636366",
                height=36,
                corner_radius=8,
                command=self.action_command
            )
            action_btn.pack(side="right")


class EmptyState(ctk.CTkFrame):
    """Empty state component for when there's no content."""
    
    def __init__(self, parent, icon: str, title: str, description: str,
                 action_text: Optional[str] = None, action_command: Optional[Callable] = None,
                 *args, **kwargs):
        super().__init__(parent, fg_color="transparent", *args, **kwargs)
        
        self.icon = icon
        self.title = title
        self.description = description
        self.action_text = action_text
        self.action_command = action_command
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup empty state UI."""
        # Center container
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(expand=True, fill="both", pady=80)
        
        # Icon
        icon_label = ctk.CTkLabel(
            container,
            text=self.icon,
            font=("Segoe UI", 72),
            text_color="#3A3A3C"
        )
        icon_label.pack(pady=(0, 20))
        
        # Title
        title_label = ctk.CTkLabel(
            container,
            text=self.title,
            font=("Segoe UI", 22, "bold"),
            text_color="#FFFFFF"
        )
        title_label.pack(pady=(0, 8))
        
        # Description
        desc_label = ctk.CTkLabel(
            container,
            text=self.description,
            font=("Segoe UI", 14),
            text_color="#8E8E93",
            wraplength=400
        )
        desc_label.pack(pady=(0, 30))
        
        # Action button
        if self.action_text and self.action_command:
            action_btn = ctk.CTkButton(
                container,
                text=self.action_text,
                font=("Segoe UI", 16, "bold"),
                fg_color="#007AFF",
                hover_color="#0051D5",
                height=48,
                corner_radius=12,
                command=self.action_command
            )
            action_btn.pack()


class ProgressIndicator(ctk.CTkFrame):
    """Progress indicator with status and progress bar."""
    
    def __init__(self, parent, *args, **kwargs):
        super().__init__(parent, fg_color="transparent", *args, **kwargs)
        
        self.status_label = None
        self.progress_bar = None
        self.detail_label = None
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup progress indicator UI."""
        # Status text
        self.status_label = ctk.CTkLabel(
            self,
            text="Ready",
            font=("Segoe UI", 16, "bold"),
            text_color="#FFFFFF"
        )
        self.status_label.pack(pady=(0, 8))
        
        # Progress bar
        self.progress_bar = ctk.CTkProgressBar(
            self,
            width=400,
            height=8,
            progress_color="#007AFF",
            corner_radius=4
        )
        self.progress_bar.pack(pady=(0, 8))
        self.progress_bar.set(0)
        
        # Detail text
        self.detail_label = ctk.CTkLabel(
            self,
            text="",
            font=("Segoe UI", 12),
            text_color="#8E8E93"
        )
        self.detail_label.pack()
    
    def update(self, status: str, progress: float, detail: Optional[str] = None):
        """Update progress indicator."""
        self.status_label.configure(text=status)
        self.progress_bar.set(progress)
        if detail:
            self.detail_label.configure(text=detail)
        else:
            self.detail_label.configure(text="")

