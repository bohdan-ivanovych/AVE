"""Animation utilities for smooth Apple-like transitions."""

import customtkinter as ctk
from typing import Callable, Optional, Tuple


def animate_color_transition(
    widget,
    start_color: str,
    end_color: str,
    duration_ms: int = 200,
    steps: int = 10,
    callback: Optional[Callable] = None
):
    """
    Animate color transition smoothly.
    
    Args:
        widget: Widget to animate
        start_color: Starting color (hex or "transparent")
        end_color: Ending color (hex or "transparent")
        duration_ms: Duration in milliseconds
        steps: Number of animation steps
        callback: Optional callback when animation completes
    """
    def resolve_transparent_color(widget, color: str) -> str:
        """Resolve 'transparent' to actual color value."""
        if color.lower() != "transparent":
            return color
        
        # Try to get widget's current color
        try:
            current_color = widget.cget("fg_color")
            if current_color and current_color.lower() != "transparent":
                return current_color
        except:
            pass
        
        # Try to get parent's background color
        try:
            parent = widget.master
            if parent:
                parent_bg = parent.cget("fg_color")
                if parent_bg and parent_bg.lower() != "transparent":
                    return parent_bg
        except:
            pass
        
        # Default fallback - card background color
        return "#1C1C1E"
    
    def hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
        """Convert hex color to RGB."""
        # Remove # if present
        hex_color = hex_color.lstrip('#')
        
        # Validate hex color format
        if len(hex_color) != 6:
            # If invalid, default to a neutral color
            hex_color = "1C1C1E"
        
        try:
            return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        except ValueError:
            # If parsing fails, return default gray
            return (28, 28, 30)  # #1C1C1E
    
    def rgb_to_hex(rgb: Tuple[int, int, int]) -> str:
        """Convert RGB to hex color."""
        return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
    
    # Store original end_color to restore "transparent" if needed
    original_end_color = end_color
    
    # Resolve transparent colors to actual color values for animation
    start_color_resolved = resolve_transparent_color(widget, start_color)
    end_color_resolved = resolve_transparent_color(widget, end_color)
    
    start_rgb = hex_to_rgb(start_color_resolved)
    end_rgb = hex_to_rgb(end_color_resolved)
    
    step_delay = duration_ms // steps
    current_step = [0]
    
    def animate_step():
        if current_step[0] >= steps:
            # Set final color - restore "transparent" if that was the target
            try:
                if original_end_color.lower() == "transparent":
                    widget.configure(fg_color="transparent")
                else:
                    widget.configure(fg_color=end_color_resolved)
            except:
                pass
            
            if callback:
                callback()
            return
        
        progress = current_step[0] / steps
        # Ease-in-out curve for smooth animation
        eased = progress * progress * (3 - 2 * progress)
        
        current_rgb = tuple(
            int(start_rgb[i] + (end_rgb[i] - start_rgb[i]) * eased)
            for i in range(3)
        )
        current_color = rgb_to_hex(current_rgb)
        
        try:
            widget.configure(fg_color=current_color)
        except:
            pass
        
        current_step[0] += 1
        widget.after(step_delay, animate_step)
    
    animate_step()


def animate_scale(
    widget,
    start_scale: float = 1.0,
    end_scale: float = 1.05,
    duration_ms: int = 150,
    steps: int = 8
):
    """
    Animate scale effect (visual only through corner radius change).
    
    Args:
        widget: Widget to animate
        start_scale: Starting scale
        end_scale: Ending scale
        duration_ms: Duration in milliseconds
        steps: Number of animation steps
    """
    if not hasattr(widget, 'configure'):
        return
    
    try:
        original_radius = widget.cget("corner_radius") or 10
    except:
        original_radius = 10
    
    step_delay = duration_ms // steps
    current_step = [0]
    
    def animate_step():
        if current_step[0] >= steps:
            return
        
        progress = current_step[0] / steps
        # Ease-out curve
        eased = 1 - (1 - progress) ** 2
        
        current_scale = start_scale + (end_scale - start_scale) * eased
        new_radius = int(original_radius * current_scale)
        
        try:
            widget.configure(corner_radius=new_radius)
        except:
            pass
        
        current_step[0] += 1
        widget.after(step_delay, animate_step)
    
    animate_step()


def add_apple_hover_effect(
    widget,
    normal_color: str,
    hover_color: str,
    colors: dict
):
    """
    Add smooth Apple-like hover effect to a widget.
    
    Args:
        widget: Widget to add effect to
        normal_color: Normal state color
        hover_color: Hover state color
        colors: Color scheme dict
    """
    original_color = normal_color
    is_hovering = [False]
    
    def on_enter(e):
        is_hovering[0] = True
        animate_color_transition(
            widget,
            normal_color,
            hover_color,
            duration_ms=150,
            steps=8
        )
    
    def on_leave(e):
        is_hovering[0] = False
        animate_color_transition(
            widget,
            hover_color,
            normal_color,
            duration_ms=150,
            steps=8
        )
    
    widget.bind("<Enter>", on_enter)
    widget.bind("<Leave>", on_leave)


def add_apple_press_effect(widget, colors: dict):
    """
    Add Apple-like press effect (subtle darkening).
    
    Args:
        widget: Widget to add effect to
        colors: Color scheme dict
    """
    original_color = None
    
    def on_press(e):
        nonlocal original_color
        try:
            original_color = widget.cget("fg_color")
            # Slightly darken on press
            widget.configure(fg_color=colors.get("card_active", "#3A3A3C"))
        except:
            pass
    
    def on_release(e):
        if original_color:
            try:
                widget.configure(fg_color=original_color)
            except:
                pass
    
    widget.bind("<Button-1>", on_press)
    widget.bind("<ButtonRelease-1>", on_release)


def fade_in(widget, duration_ms: int = 300):
    """
    Fade in animation for widgets.
    
    Args:
        widget: Widget to fade in
        duration_ms: Duration in milliseconds
    """
    steps = 15
    step_delay = duration_ms // steps
    current_step = [0]
    
    def fade_step():
        if current_step[0] >= steps:
            return
        
        progress = current_step[0] / steps
        # Ease-out curve
        eased = 1 - (1 - progress) ** 2
        
        try:
            # CustomTkinter doesn't support opacity directly,
            # but we can use this for future enhancements
            pass
        except:
            pass
        
        current_step[0] += 1
        widget.after(step_delay, fade_step)
    
    fade_step()

