"""Manual pairing with drag-and-drop support for 1-4 images per group."""

import customtkinter as ctk
from pathlib import Path
from typing import List, Optional
from tkinter import filedialog
from PIL import Image

from src.dto import ImagePair
from src.services.image_service import ImageService
from src.config import AppConfig


class ManualPairingEditor(ctk.CTkFrame):
    """Manual pairing editor with drag-and-drop for 1-4 images."""
    
    def __init__(self, parent, config: AppConfig, image_service: ImageService, on_pair_added=None):
        super().__init__(parent, fg_color="#1A1A1A")
        self.config = config
        self.image_service = image_service
        self.on_pair_added = on_pair_added
        self.current_pair: List[Path] = []
        self.max_images = config.max_images_per_task
        
        # Try to get colors from parent app if available
        self.colors = {
            "bg": "#1A1A1A",
            "card": "#2A2A2A",
            "accent": "#E50914",
            "text": "#FFFFFF",
            "text_secondary": "#B3B3B3"
        }
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup manual pairing UI."""
        # Header with better styling
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.pack(pady=(15, 10))
        
        header = ctk.CTkLabel(
            header_frame,
            text="Manual Pairing",
            font=("Segoe UI", 24, "bold"),
            text_color=self.colors["accent"]
        )
        header.pack()
        
        subtitle = ctk.CTkLabel(
            header_frame,
            text="Select 1-4 images for this pairing",
            font=("Segoe UI", 12),
            text_color=self.colors["text_secondary"]
        )
        subtitle.pack(pady=(5, 0))
        
        # Drop zone for images with better styling
        self.drop_zone = ctk.CTkFrame(
            self,
            fg_color=self.colors["card"],
            width=600,
            height=220,
            corner_radius=12,
            border_width=2,
            border_color="#444444"
        )
        self.drop_zone.pack(pady=20, padx=20, fill="both", expand=True)
        
        drop_label = ctk.CTkLabel(
            self.drop_zone,
            text="📁 Drop images here (1-4 images)\nor click to browse",
            font=("Segoe UI", 15),
            text_color=self.colors["text_secondary"]
        )
        drop_label.pack(expand=True)
        
        # Image previews container
        self.previews_frame = ctk.CTkFrame(self.drop_zone, fg_color="transparent")
        self.previews_frame.pack(fill="x", padx=10, pady=10)
        
        # Bind click to browse
        self.drop_zone.bind("<Button-1>", self._browse_images)
        drop_label.bind("<Button-1>", self._browse_images)
        
        # Buttons
        button_frame = ctk.CTkFrame(self, fg_color="transparent")
        button_frame.pack(pady=10)
        
        ctk.CTkButton(
            button_frame,
            text="📂 Browse Images",
            command=self._browse_images,
            width=160,
            height=40,
            font=("Segoe UI", 14, "bold"),
            corner_radius=8
        ).pack(side="left", padx=8)
        
        ctk.CTkButton(
            button_frame,
            text="🗑️ Clear",
            command=self._clear_images,
            width=120,
            height=40,
            font=("Segoe UI", 14, "bold"),
            fg_color="#564D4D",
            hover_color="#6B5B5B",
            corner_radius=8
        ).pack(side="left", padx=8)
        
        ctk.CTkButton(
            button_frame,
            text="✅ Add Pair",
            command=self._add_pair,
            width=140,
            height=40,
            font=("Segoe UI", 14, "bold"),
            fg_color=self.colors["accent"],
            hover_color="#F40612",
            corner_radius=8
        ).pack(side="left", padx=8)
    
    def _browse_images(self, event=None):
        """Browse and select images."""
        files = filedialog.askopenfilenames(
            title="Select Images (1-4)",
            filetypes=[
                ("Image files", "*.jpg *.jpeg *.png *.webp"),
                ("All files", "*.*")
            ]
        )
        
        if files:
            selected = [Path(f) for f in files[:self.max_images]]
            self._add_images(selected)
    
    def _add_images(self, image_paths: List[Path]):
        """Add images to current pair."""
        # Validate images
        valid_images = []
        for img_path in image_paths:
            is_valid, error = self.image_service.validate_image(img_path)
            if is_valid:
                valid_images.append(img_path)
            else:
                print(f"Invalid image {img_path}: {error}")
        
        if not valid_images:
            return
        
        # Limit to max_images
        self.current_pair = valid_images[:self.max_images]
        self._update_previews()
    
    def _update_previews(self):
        """Update image previews."""
        # Clear existing previews
        for widget in self.previews_frame.winfo_children():
            widget.destroy()
        
        # Show current images
        for idx, img_path in enumerate(self.current_pair):
            try:
                pil_img = Image.open(img_path).resize((80, 80), Image.LANCZOS)
                from customtkinter import CTkImage
                ctk_img = CTkImage(light_image=pil_img, dark_image=pil_img, size=(80, 80))
                
                preview_frame = ctk.CTkFrame(
                    self.previews_frame, 
                    fg_color="#3A3A3A", 
                    width=110, 
                    height=110,
                    corner_radius=8,
                    border_width=1,
                    border_color="#555555"
                )
                preview_frame.pack(side="left", padx=8, pady=8)
                preview_frame.pack_propagate(False)
                
                img_label = ctk.CTkLabel(
                    preview_frame, 
                    image=ctk_img, 
                    text="",
                    corner_radius=6
                )
                img_label.image = ctk_img
                img_label.pack(padx=8, pady=8)
                
                # Remove button with better styling
                remove_btn = ctk.CTkButton(
                    preview_frame,
                    text="×",
                    width=24,
                    height=24,
                    font=("Arial", 16, "bold"),
                    fg_color="#E50914",
                    hover_color="#F40612",
                    corner_radius=12,
                    command=lambda i=idx: self._remove_image(i)
                )
                remove_btn.place(x=82, y=5)
                
            except Exception as e:
                print(f"Error loading preview: {e}")
    
    def _remove_image(self, index: int):
        """Remove image from current pair."""
        if 0 <= index < len(self.current_pair):
            self.current_pair.pop(index)
            self._update_previews()
    
    def _clear_images(self):
        """Clear all images."""
        self.current_pair = []
        self._update_previews()
    
    def _add_pair(self):
        """Add current pair to pairing list."""
        if len(self.current_pair) < 1:
            from tkinter import messagebox
            messagebox.showwarning(
                "No Images", 
                "Please select at least 1 image!",
                icon="warning"
            )
            return
        
        if len(self.current_pair) > self.max_images:
            from tkinter import messagebox
            messagebox.showwarning(
                "Too Many Images", 
                f"Maximum {self.max_images} images allowed. Please remove some images.",
                icon="warning"
            )
            return
        
        try:
            if self.on_pair_added:
                pair = ImagePair(
                    images=self.current_pair.copy(),
                    prompt="",
                    enabled=True
                )
                self.on_pair_added(pair)
                self._clear_images()
        except Exception as e:
            from tkinter import messagebox
            messagebox.showerror(
                "Error",
                f"Failed to add pair: {e}",
                icon="error"
            )

