"""Prompt Library view with search, tags, and favorites."""

import customtkinter as ctk
from tkinter import messagebox
from typing import List, Optional, TYPE_CHECKING
import asyncio
import threading

from src.config import AppConfig
from src.services.logger import get_logger_service
from src.services.prompt_library import get_prompt_library
from src.dto import PromptTemplate
from src.gui.clipboard_utils import setup_clipboard_support

if TYPE_CHECKING:
    from src.gui.app import AVEApp


class PromptLibraryView(ctk.CTkFrame):
    """Prompt Library view with search and management."""
    
    def __init__(self, parent, config: AppConfig, app: "AVEApp"):
        super().__init__(parent, fg_color=app.colors["bg"])
        self.config = config
        self.app = app
        self.logger = get_logger_service().get_logger("prompt_library")
        self.prompt_library = get_prompt_library()
        
        self.templates: List[PromptTemplate] = []
        self.selected_template: Optional[PromptTemplate] = None
        
        self._setup_ui()
        self._load_templates()
    
    def _setup_ui(self):
        """Setup prompt library UI."""
        # Header with subtitle
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.pack(pady=(20, 15))
        
        header = ctk.CTkLabel(
            header_frame,
            text="Prompt Library",
            font=("Segoe UI", 32, "bold"),
            text_color=self.app.colors["accent"]
        )
        header.pack()
        
        subtitle = ctk.CTkLabel(
            header_frame,
            text="Manage and organize your prompt templates",
            font=("Segoe UI", 13),
            text_color=self.app.colors["text_secondary"]
        )
        subtitle.pack(pady=(5, 0))
        
        # Search and filters
        search_frame = ctk.CTkFrame(self, fg_color=self.app.colors["card"], corner_radius=12, border_width=1, border_color=self.app.colors["border"])
        search_frame.pack(fill="x", padx=40, pady=12)
        
        ctk.CTkLabel(
            search_frame,
            text="Search:",
            font=("Segoe UI", 14),
            text_color=self.app.colors["text"]
        ).pack(side="left", padx=10)
        
        self.search_entry = ctk.CTkEntry(
            search_frame,
            width=300,
            placeholder_text="Search prompts..."
        )
        self.search_entry.pack(side="left", padx=5)
        self.search_entry.bind("<KeyRelease>", lambda e: self._on_search())
        setup_clipboard_support(self.search_entry)
        
        ctk.CTkButton(
            search_frame,
            text="Search",
            width=100,
            command=self._on_search
        ).pack(side="left", padx=5)
        
        ctk.CTkButton(
            search_frame,
            text="Favorites Only",
            width=120,
            fg_color=self.app.colors["secondary"],
            command=self._toggle_favorites
        ).pack(side="left", padx=5)
        
        # Templates list
        list_frame = ctk.CTkFrame(self, fg_color=self.app.colors["card"], corner_radius=14, border_width=1, border_color=self.app.colors["border"])
        list_frame.pack(fill="both", expand=True, padx=40, pady=12)
        
        scroll_frame = ctk.CTkScrollableFrame(
            list_frame,
            fg_color=self.app.colors["bg"],
            width=1000,
            height=400
        )
        scroll_frame.pack(fill="both", expand=True, padx=10, pady=10)
        self.templates_container = scroll_frame
        
        # Action buttons
        action_frame = ctk.CTkFrame(self, fg_color=self.app.colors["bg"])
        action_frame.pack(fill="x", padx=40, pady=10)
        
        new_btn = ctk.CTkButton(
            action_frame,
            text="➕ New Template",
            font=("Segoe UI", 16, "bold"),
            fg_color=self.app.colors["accent"],
            hover_color=self.app.colors["accent_hover"],
            width=160,
            height=40,
            corner_radius=8,
            command=self._show_new_template_dialog
        )
        new_btn.pack(side="left", padx=5)
        
        ctk.CTkButton(
            action_frame,
            text="Edit",
            font=("Segoe UI", 16),
            fg_color=self.app.colors["secondary"],
            width=120,
            command=self._edit_selected
        ).pack(side="left", padx=5)
        
        ctk.CTkButton(
            action_frame,
            text="Delete",
            font=("Segoe UI", 16),
            fg_color="#8B0000",
            width=120,
            command=self._delete_selected
        ).pack(side="left", padx=5)
        
        ctk.CTkButton(
            action_frame,
            text="Use in Pairing",
            font=("Segoe UI", 16),
            fg_color="#26d67c",
            width=150,
            command=self._use_in_pairing
        ).pack(side="right", padx=5)
    
    def _load_templates(self):
        """Load templates from library."""
        def load_async():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                templates = loop.run_until_complete(self.prompt_library.get_all_templates())
                self.app.after(0, lambda: self._display_templates(templates))
            finally:
                loop.close()
        
        threading.Thread(target=load_async, daemon=True).start()
    
    def _display_templates(self, templates: List[PromptTemplate]):
        """Display templates in UI."""
        self.templates = templates
        
        # Clear container
        for widget in self.templates_container.winfo_children():
            widget.destroy()
        
        if not templates:
            # Empty state
            empty_frame = ctk.CTkFrame(self.templates_container, fg_color="transparent")
            empty_frame.pack(expand=True, pady=50)
            
            empty_icon = ctk.CTkLabel(
                empty_frame,
                text="📝",
                font=("Segoe UI", 48),
                text_color=self.app.colors["text_muted"]
            )
            empty_icon.pack()
            
            empty_label = ctk.CTkLabel(
                empty_frame,
                text="No templates yet",
                font=("Segoe UI", 18, "bold"),
                text_color=self.app.colors["text_secondary"]
            )
            empty_label.pack(pady=(10, 5))
            
            hint_label = ctk.CTkLabel(
                empty_frame,
                text="Click 'New Template' to create your first prompt template",
                font=("Segoe UI", 13),
                text_color=self.app.colors["text_muted"]
            )
            hint_label.pack()
        else:
            # Display each template
            for template in templates:
                self._create_template_widget(template)
    
    def _create_template_widget(self, template: PromptTemplate):
        """Create UI widget for a template."""
        template_frame = ctk.CTkFrame(
            self.templates_container,
            fg_color=self.app.colors["card"],
            height=95,
            corner_radius=10,
            border_width=1,
            border_color=self.app.colors["border"]
        )
        template_frame.pack(fill="x", padx=8, pady=7)
        
        # Add enhanced hover effect
        def make_template_hover(f):
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
        
        make_template_hover(template_frame)
        
        # Selection checkbox
        select_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            template_frame,
            text="",
            variable=select_var,
            command=lambda t=template, v=select_var: self._select_template(t, v)
        ).pack(side="left", padx=10)
        
        # Favorite star
        star_text = "★" if template.is_favorite else "☆"
        star_btn = ctk.CTkButton(
            template_frame,
            text=star_text,
            width=30,
            height=30,
            fg_color="transparent",
            text_color="#FFD700" if template.is_favorite else "#666",
            command=lambda t=template: self._toggle_favorite(t)
        )
        star_btn.pack(side="left", padx=5)
        
        # Template info
        info_frame = ctk.CTkFrame(template_frame, fg_color="transparent")
        info_frame.pack(side="left", fill="both", expand=True, padx=10)
        
        name_label = ctk.CTkLabel(
            info_frame,
            text=template.name,
            font=("Segoe UI", 16, "bold"),
            text_color=self.app.colors["text"]
        )
        name_label.pack(anchor="w")
        
        # Preview
        preview = template.content[:100] + "..." if len(template.content) > 100 else template.content
        preview_label = ctk.CTkLabel(
            info_frame,
            text=preview,
            font=("Segoe UI", 12),
            text_color=self.app.colors["text_secondary"]
        )
        preview_label.pack(anchor="w")
        
        # Tags
        if template.tags:
            tags_text = " ".join([f"#{tag}" for tag in template.tags[:3]])
            tags_label = ctk.CTkLabel(
                info_frame,
                text=tags_text,
                font=("Segoe UI", 10),
                text_color="#888"
            )
            tags_label.pack(anchor="w")
        
        # Store reference
        template_frame.template_data = template
    
    def _select_template(self, template: PromptTemplate, var: ctk.BooleanVar):
        """Select/deselect template."""
        if var.get():
            self.selected_template = template
            # Deselect others
            for widget in self.templates_container.winfo_children():
                if hasattr(widget, 'template_data') and widget.template_data != template:
                    # Find checkbox and uncheck
                    for child in widget.winfo_children():
                        if isinstance(child, ctk.CTkCheckBox):
                            child.deselect()
        else:
            if self.selected_template == template:
                self.selected_template = None
    
    def _toggle_favorite(self, template: PromptTemplate):
        """Toggle favorite status."""
        def toggle_async():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                updated = loop.run_until_complete(
                    self.prompt_library.toggle_favorite(template.template_id)
                )
                if updated:
                    self.app.after(0, lambda: self._load_templates())
            finally:
                loop.close()
        
        threading.Thread(target=toggle_async, daemon=True).start()
    
    def _on_search(self):
        """Perform search."""
        query = self.search_entry.get().strip()
        if not query:
            self._load_templates()
            return
        
        def search_async():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                results = loop.run_until_complete(
                    self.prompt_library.search_templates(query)
                )
                self.app.after(0, lambda: self._display_templates(results))
            finally:
                loop.close()
        
        threading.Thread(target=search_async, daemon=True).start()
    
    def _toggle_favorites(self):
        """Toggle favorites filter."""
        def load_favorites():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                favorites = loop.run_until_complete(
                    self.prompt_library.get_all_templates(favorites_only=True)
                )
                self.app.after(0, lambda: self._display_templates(favorites))
            finally:
                loop.close()
        
        threading.Thread(target=load_favorites, daemon=True).start()
    
    def _show_new_template_dialog(self):
        """Show dialog for creating new template."""
        from tkinter import Toplevel, Text
        
        dialog = Toplevel(self.app)
        dialog.title("New Prompt Template")
        dialog.geometry("600x500")
        dialog.configure(bg="#0F0F0F")
        
        # Name
        ctk.CTkLabel(dialog, text="Name:", font=("Segoe UI", 14)).pack(pady=5)
        name_entry = ctk.CTkEntry(dialog, width=400)
        name_entry.pack(pady=5)
        setup_clipboard_support(name_entry)
        
        # Content
        ctk.CTkLabel(dialog, text="Prompt:", font=("Segoe UI", 14)).pack(pady=5)
        content_text = Text(dialog, width=70, height=15, bg="#1A1A1A", fg="#FFF")
        content_text.pack(pady=5)
        setup_clipboard_support(content_text)
        
        # Tags
        ctk.CTkLabel(dialog, text="Tags (comma-separated):", font=("Segoe UI", 14)).pack(pady=5)
        tags_entry = ctk.CTkEntry(dialog, width=400)
        tags_entry.pack(pady=5)
        setup_clipboard_support(tags_entry)
        
        # Favorite
        favorite_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(dialog, text="Favorite", variable=favorite_var).pack(pady=5)
        
        def save_template():
            name = name_entry.get().strip()
            content = content_text.get("1.0", "end-1c").strip()
            tags_str = tags_entry.get().strip()
            tags = [t.strip() for t in tags_str.split(",") if t.strip()] if tags_str else []
            
            if not name or not content:
                messagebox.showwarning("Missing Fields", "Name and Prompt are required!")
                return
            
            def create_async():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(
                        self.prompt_library.create_template(
                            name=name,
                            content=content,
                            tags=tags,
                            is_favorite=favorite_var.get()
                        )
                    )
                    self.app.after(0, lambda: (self._load_templates(), dialog.destroy()))
                finally:
                    loop.close()
            
            threading.Thread(target=create_async, daemon=True).start()
        
        ctk.CTkButton(
            dialog,
            text="Save",
            command=save_template,
            fg_color=self.app.colors["accent"]
        ).pack(pady=10)
    
    def _edit_selected(self):
        """Edit selected template."""
        if not self.selected_template:
            messagebox.showwarning("No Selection", "Please select a template to edit!")
            return
        
        # Similar to new template dialog but with existing data
        from tkinter import Toplevel, Text
        
        dialog = Toplevel(self.app)
        dialog.title("Edit Prompt Template")
        dialog.geometry("600x500")
        dialog.configure(bg="#0F0F0F")
        
        # Name
        ctk.CTkLabel(dialog, text="Name:", font=("Segoe UI", 14)).pack(pady=5)
        name_entry = ctk.CTkEntry(dialog, width=400)
        name_entry.insert(0, self.selected_template.name)
        name_entry.pack(pady=5)
        setup_clipboard_support(name_entry)
        
        # Content
        ctk.CTkLabel(dialog, text="Prompt:", font=("Segoe UI", 14)).pack(pady=5)
        content_text = Text(dialog, width=70, height=15, bg="#1A1A1A", fg="#FFF")
        content_text.insert("1.0", self.selected_template.content)
        content_text.pack(pady=5)
        setup_clipboard_support(content_text)
        
        # Tags
        ctk.CTkLabel(dialog, text="Tags (comma-separated):", font=("Segoe UI", 14)).pack(pady=5)
        tags_entry = ctk.CTkEntry(dialog, width=400)
        tags_entry.insert(0, ", ".join(self.selected_template.tags))
        tags_entry.pack(pady=5)
        setup_clipboard_support(tags_entry)
        
        # Favorite
        favorite_var = ctk.BooleanVar(value=self.selected_template.is_favorite)
        ctk.CTkCheckBox(dialog, text="Favorite", variable=favorite_var).pack(pady=5)
        
        def save_template():
            name = name_entry.get().strip()
            content = content_text.get("1.0", "end-1c").strip()
            tags_str = tags_entry.get().strip()
            tags = [t.strip() for t in tags_str.split(",") if t.strip()] if tags_str else []
            
            if not name or not content:
                messagebox.showwarning("Missing Fields", "Name and Prompt are required!")
                return
            
            def update_async():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(
                        self.prompt_library.update_template(
                            template_id=self.selected_template.template_id,
                            name=name,
                            content=content,
                            tags=tags,
                            is_favorite=favorite_var.get()
                        )
                    )
                    self.app.after(0, lambda: (self._load_templates(), dialog.destroy()))
                finally:
                    loop.close()
            
            threading.Thread(target=update_async, daemon=True).start()
        
        ctk.CTkButton(
            dialog,
            text="Update",
            command=save_template,
            fg_color=self.app.colors["accent"]
        ).pack(pady=10)
    
    def _delete_selected(self):
        """Delete selected template."""
        if not self.selected_template:
            messagebox.showwarning("No Selection", "Please select a template to delete!")
            return
        
        if not messagebox.askyesno("Confirm Delete", f"Delete template '{self.selected_template.name}'?"):
            return
        
        def delete_async():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(
                    self.prompt_library.delete_template(self.selected_template.template_id)
                )
                self.app.after(0, lambda: (self._load_templates(), setattr(self, 'selected_template', None)))
            finally:
                loop.close()
        
        threading.Thread(target=delete_async, daemon=True).start()
    
    def _use_in_pairing(self):
        """Use selected template in pairing view."""
        if not self.selected_template:
            messagebox.showwarning("No Selection", "Please select a template!")
            return
        
        # Switch to pairing view and insert prompt
        self.app._switch_view("pairing")
        try:
            pairing_view = self.app.views.get("pairing")
            if pairing_view and hasattr(pairing_view, "apply_prompt_to_all"):
                count = pairing_view.apply_prompt_to_all(self.selected_template.content)
                messagebox.showinfo("Prompt Applied", f"Applied template to {count} pair(s).")
            else:
                messagebox.showwarning("Unavailable", "Pairing view is not ready.")
        except Exception as e:
            self.logger.error("Failed to apply prompt in pairing view", error=str(e))
            messagebox.showerror("Error", f"Failed to apply prompt: {e}")

