"""Login Mode view for sequential browser login."""

import customtkinter as ctk
import threading
import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, List
from tkinter import messagebox

from src.config import AppConfig
from src.services.logger import get_logger_service
from src.services.browser_service import BrowserService
from src.services.browser_pool import get_browser_pool
from src.services.settings_service import get_settings_service
from core import PROFILES

if TYPE_CHECKING:
    from src.gui.app import AVEApp


class LoginView(ctk.CTkFrame):
    """Login Mode view for logging into all services across browsers."""
    
    def __init__(self, parent, config: AppConfig, app: "AVEApp"):
        super().__init__(parent, fg_color=app.colors["bg"])
        self.config = config
        self.app = app
        self.logger = get_logger_service().get_logger("login")
        
        self.current_profile_index = 0
        # Load profiles from settings (same logic as other views)
        settings_service = get_settings_service()
        saved_profiles = settings_service.get_selected_profiles()
        available_profiles = settings_service.get_available_profiles()
        
        # Use selected profiles if set, otherwise use available profiles, otherwise use PROFILES
        if saved_profiles:
            self.profiles = saved_profiles
        elif available_profiles:
            self.profiles = available_profiles
        else:
            self.profiles = list(PROFILES) if PROFILES else []
        
        self.current_context = None
        self.current_page = None
        self.browser_service = None
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup login UI."""
        # Header
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.pack(pady=(20, 15))
        
        header = ctk.CTkLabel(
            header_frame,
            text="🔐 Login Mode",
            font=("Segoe UI", 32, "bold"),
            text_color=self.app.colors["accent"]
        )
        header.pack()
        
        subtitle = ctk.CTkLabel(
            header_frame,
            text="Log into all services across your Chrome profiles",
            font=("Segoe UI", 13),
            text_color=self.app.colors["text_secondary"]
        )
        subtitle.pack(pady=(5, 0))
        
        # Status card
        status_frame = ctk.CTkFrame(
            self,
            fg_color=self.app.colors["card"],
            corner_radius=12,
            border_width=1,
            border_color=self.app.colors["border"]
        )
        status_frame.pack(fill="x", padx=40, pady=20)
        
        status_content = ctk.CTkFrame(status_frame, fg_color="transparent")
        status_content.pack(fill="x", padx=30, pady=25)
        
        self.status_label = ctk.CTkLabel(
            status_content,
            text="Ready to start login process",
            font=("Segoe UI", 18, "bold"),
            text_color=self.app.colors["text"]
        )
        self.status_label.pack(side="left")
        
        self.profile_label = ctk.CTkLabel(
            status_content,
            text="",
            font=("Segoe UI", 14),
            text_color=self.app.colors["text_secondary"]
        )
        self.profile_label.pack(side="right")
        
        # Instructions
        instructions_frame = ctk.CTkFrame(
            self,
            fg_color=self.app.colors["card"],
            corner_radius=12,
            border_width=1,
            border_color=self.app.colors["border"]
        )
        instructions_frame.pack(fill="x", padx=40, pady=10)
        
        instructions_content = ctk.CTkFrame(instructions_frame, fg_color="transparent")
        instructions_content.pack(fill="x", padx=30, pady=20)
        
        instructions_text = ctk.CTkLabel(
            instructions_content,
            text="📋 Instructions:\n"
                 "1. Click 'Start Login' to open the first browser with 3 tabs:\n"
                 "   • Sora (https://sora.chatgpt.com/library)\n"
                 "   • Outpaint/Pixelcut (https://www.pixelcut.ai/uncrop/ai-outpainting)\n"
                 "   • Qwen (https://chat.qwen.ai/)\n"
                 "2. Log into all 3 services in the opened tabs\n"
                 "3. Click 'Next Profile' when done to move to the next browser\n"
                 "4. Repeat until all profiles are logged in",
            font=("Segoe UI", 14),
            text_color=self.app.colors["text_secondary"],
            justify="left"
        )
        instructions_text.pack(anchor="w")
        
        # Action buttons
        buttons_frame = ctk.CTkFrame(self, fg_color="transparent")
        buttons_frame.pack(fill="x", padx=40, pady=30)
        
        self.start_btn = ctk.CTkButton(
            buttons_frame,
            text="🚀 Start Login",
            font=("Segoe UI", 20, "bold"),
            fg_color=self.app.colors["accent"],
            hover_color=self.app.colors["accent_hover"],
            width=200,
            height=60,
            corner_radius=12,
            command=self._start_login
        )
        self.start_btn.pack(side="left", padx=10)
        
        self.next_btn = ctk.CTkButton(
            buttons_frame,
            text="➡️ Next Profile",
            font=("Segoe UI", 20, "bold"),
            fg_color=self.app.colors["success"],
            hover_color=self.app.colors["success_hover"],
            width=200,
            height=60,
            corner_radius=12,
            command=self._next_profile,
            state="disabled"
        )
        self.next_btn.pack(side="left", padx=10)
        
        self.stop_btn = ctk.CTkButton(
            buttons_frame,
            text="⏹️ Stop",
            font=("Segoe UI", 20, "bold"),
            fg_color=self.app.colors["secondary"],
            hover_color=self.app.colors["secondary_hover"],
            width=200,
            height=60,
            corner_radius=12,
            command=self._stop_login,
            state="disabled"
        )
        self.stop_btn.pack(side="left", padx=10)
        
        # Progress
        progress_frame = ctk.CTkFrame(self, fg_color="transparent")
        progress_frame.pack(fill="x", padx=40, pady=20)
        
        self.progress_label = ctk.CTkLabel(
            progress_frame,
            text=f"0 / {len(self.profiles)} profiles",
            font=("Segoe UI", 16),
            text_color=self.app.colors["text_secondary"]
        )
        self.progress_label.pack()
        
        self.progress_bar = ctk.CTkProgressBar(
            progress_frame,
            width=600,
            height=30,
            progress_color=self.app.colors["accent"],
            corner_radius=15
        )
        self.progress_bar.pack(pady=(10, 0))
        self.progress_bar.set(0)
    
    def _start_login(self):
        """Start login process."""
        if not self.profiles:
            messagebox.showerror("Error", "No Chrome profiles configured!")
            return
        
        self.current_profile_index = 0
        self.start_btn.configure(state="disabled")
        self.next_btn.configure(state="normal")
        self.stop_btn.configure(state="normal")
        
        self._open_browser_for_profile()
    
    def _open_browser_for_profile(self):
        """Open browser for current profile."""
        if self.current_profile_index >= len(self.profiles):
            self._finish_login()
            return
        
        profile_name = self.profiles[self.current_profile_index]
        self.logger.info("Opening browser for login", profile=profile_name, index=self.current_profile_index + 1)

        # Validate profile path exists before attempting to launch
        profile_path = Path(self.config.chrome_base) / profile_name
        if not profile_path.exists():
            self.logger.error(
                "Chrome profile not found",
                profile=profile_name,
                path=str(profile_path)
            )
            messagebox.showerror(
                "Profile Not Found",
                f"Chrome profile '{profile_name}' was not found at:\n{profile_path}\n\n"
                "Please create this profile or update your configuration."
            )
            # Move to next profile automatically
            self.current_profile_index += 1
            if self.current_profile_index >= len(self.profiles):
                self._finish_login()
            else:
                self._open_browser_for_profile()
            return
        
        # Update UI immediately
        self.app.after(0, lambda: (
            self.status_label.configure(
                text=f"Opening browser {self.current_profile_index + 1} of {len(self.profiles)}...",
                text_color=self.app.colors["accent"]
            ),
            self.profile_label.configure(text=f"Profile: {profile_name}"),
            self.progress_label.configure(text=f"{self.current_profile_index} / {len(self.profiles)} profiles"),
            self.progress_bar.set(self.current_profile_index / len(self.profiles)),
            self.next_btn.configure(state="disabled")  # Disable while opening
        ))
        
        # Open browser in background thread
        def open_browser():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                async def open_async():
                    try:
                        self.logger.info("Starting browser service", profile=profile_name)
                        self.browser_service = BrowserService(self.config)
                        await self.browser_service.start()
                        
                        # For login mode, create a fresh context directly (don't use pool to avoid conflicts)
                        self.logger.info("Creating new browser context for login", profile=profile_name)
                        self.current_context = await self.browser_service.create_context(profile_name, headless=False)
                        self.logger.info("Context created successfully, creating pages", profile=profile_name)
                        
                        # Open 3 tabs in parallel for faster loading
                        from src.services.outpaint_service import OutpaintService
                        from src.services.qwen_service import QwenService
                        
                        self.logger.info("Creating all pages", profile=profile_name)
                        sora_page = await self.current_context.new_page()
                        outpaint_page = await self.current_context.new_page()
                        qwen_page = await self.current_context.new_page()
                        
                        # Navigate all pages in parallel
                        self.logger.info("Navigating to all sites in parallel", profile=profile_name)
                        await asyncio.gather(
                            sora_page.goto(
                                self.config.sora_url, 
                                wait_until="commit",  # Faster than domcontentloaded
                                timeout=60000
                            ),
                            outpaint_page.goto(
                                OutpaintService.PIXELCUT_URL, 
                                wait_until="commit",
                                timeout=60000
                            ),
                            qwen_page.goto(
                                QwenService.QWEN_URL, 
                                wait_until="commit",
                                timeout=60000
                            ),
                            return_exceptions=True
                        )
                        
                        self.logger.info("All pages navigated, waiting for load", profile=profile_name)
                        await asyncio.gather(
                            sora_page.wait_for_load_state("domcontentloaded", timeout=30000),
                            outpaint_page.wait_for_load_state("domcontentloaded", timeout=30000),
                            qwen_page.wait_for_load_state("domcontentloaded", timeout=30000),
                            return_exceptions=True
                        )
                        
                        self.logger.info("All pages loaded successfully", profile=profile_name)
                        
                        # Store the first page as current_page for compatibility
                        self.current_page = sora_page
                        
                        # Verify browser is actually visible
                        context_pages = self.current_context.pages
                        self.logger.info(f"Browser context has {len(context_pages)} pages", profile=profile_name)
                        
                        # Bring browser to front (if possible)
                        try:
                            # Try to focus the first page
                            await sora_page.bring_to_front()
                            self.logger.info("Brought browser to front", profile=profile_name)
                        except Exception as e:
                            self.logger.warning("Could not bring browser to front", error=str(e), profile=profile_name)
                        
                        self.logger.info("All pages opened successfully", profile=profile_name)
                        self.app.after(0, lambda: (
                            self.status_label.configure(
                                text=f"Browser {self.current_profile_index + 1} ready - 3 tabs opened (Sora, Outpaint, Qwen). Log in and click 'Next Profile'",
                                text_color=self.app.colors["success"]
                            ),
                            self.next_btn.configure(state="normal")  # Re-enable Next button
                        ))
                    except Exception as inner_e:
                        self.logger.error("Error in open_async", error=str(inner_e), exc_info=True, profile=profile_name)
                        raise
                
                loop.run_until_complete(open_async())
            except Exception as e:
                error_msg = str(e)
                self.logger.error("Failed to open browser", error=error_msg, exc_info=True)
                self.app.after(0, lambda msg=error_msg: messagebox.showerror("Error", f"Failed to open browser: {msg}"))
        
        thread = threading.Thread(target=open_browser, daemon=True)
        thread.start()
    
    def _next_profile(self):
        """Move to next profile."""
        self.logger.info("Next Profile clicked", current_index=self.current_profile_index)
        
        # Disable button while processing
        self.next_btn.configure(state="disabled")
        self.status_label.configure(
            text="Closing browser...",
            text_color=self.app.colors["warning"]
        )
        
        if self.current_context:
            # Get current profile name before closing
            current_profile_name = self.profiles[self.current_profile_index] if self.current_profile_index < len(self.profiles) else None
            self.logger.info("Closing current browser context", current_index=self.current_profile_index, profile=current_profile_name)
            
            # Close current browser context - use a flag to track completion
            close_completed = threading.Event()
            close_error = [None]  # Use list to allow modification in nested function
            
            def close_browser():
                try:
                    self.logger.info("Starting browser close thread", current_index=self.current_profile_index)
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    
                    async def close_async():
                        context = self.current_context
                        self.logger.info("In close_async", has_context=context is not None)
                        
                        if context:
                            # Close all pages in context with timeout
                            try:
                                pages = context.pages
                                self.logger.info(f"Closing {len(pages)} pages")
                                
                                # Close pages with individual timeouts
                                close_tasks = []
                                for page in pages:
                                    if not page.is_closed():
                                        async def close_page(p):
                                            try:
                                                await asyncio.wait_for(p.close(), timeout=3.0)
                                            except asyncio.TimeoutError:
                                                self.logger.warning(f"Page close timeout, forcing close")
                                            except Exception as e:
                                                self.logger.warning(f"Error closing page: {e}")
                                        
                                        close_tasks.append(close_page(page))
                                
                                if close_tasks:
                                    await asyncio.gather(*close_tasks, return_exceptions=True)
                                
                                self.logger.info("All pages closed")
                            except Exception as e:
                                self.logger.warning("Error closing pages", error=str(e), exc_info=True)
                            
                            # Close context with timeout - force close if needed
                            try:
                                self.logger.info("Closing context")
                                try:
                                    await asyncio.wait_for(context.close(), timeout=5.0)
                                    self.logger.info("Context closed successfully")
                                except asyncio.TimeoutError:
                                    self.logger.warning("Context close timeout - trying to force close")
                                    # Try to close all pages first
                                    try:
                                        for p in context.pages:
                                            if not p.is_closed():
                                                try:
                                                    await p.close()
                                                except:
                                                    pass
                                    except:
                                        pass
                                    # Try closing context again
                                    try:
                                        await context.close()
                                    except:
                                        self.logger.warning("Could not force close context")
                            except Exception as e:
                                self.logger.warning("Error closing context", error=str(e), exc_info=True)
                        
                        # Note: Don't cleanup browser_service here as it's shared
                        # The browser pool will handle context cleanup
                    
                    loop.run_until_complete(close_async())
                    loop.close()
                    self.logger.info("Browser close thread completed")
                    close_completed.set()
                except Exception as e:
                    self.logger.error("Error in close_browser thread", error=str(e), exc_info=True)
                    close_error[0] = str(e)
                    close_completed.set()
            
            thread = threading.Thread(target=close_browser, daemon=False, name="CloseBrowser")
            thread.start()
            self.logger.info("Close browser thread started, waiting for completion")
            
            # Wait for close to complete (with timeout)
            if close_completed.wait(timeout=15):  # Wait up to 15 seconds
                self.logger.info("Browser close completed successfully")
            else:
                self.logger.warning("Browser close did not complete in time, forcing close")
                # Try to kill browser process if it's still running
                if current_profile_name:
                    try:
                        import psutil
                        profile_path = Path(self.config.chrome_base) / current_profile_name
                        self.logger.info(f"Attempting to kill Chrome processes for profile: {current_profile_name}")
                        # Find and kill Chrome processes using this profile
                        killed_count = 0
                        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                            try:
                                if proc.info['name'] and 'chrome' in proc.info['name'].lower():
                                    cmdline = proc.info.get('cmdline', [])
                                    if cmdline and any(str(profile_path) in str(arg) for arg in cmdline):
                                        self.logger.info(f"Killing Chrome process {proc.info['pid']} for profile {current_profile_name}")
                                        proc.kill()
                                        killed_count += 1
                            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                                pass
                        if killed_count > 0:
                            self.logger.info(f"Killed {killed_count} Chrome process(es) for profile {current_profile_name}")
                    except ImportError:
                        self.logger.warning("psutil not available, cannot force kill browser. Install psutil for better browser management.")
                    except Exception as e:
                        self.logger.warning(f"Error killing browser process: {e}")
            
            # Clear references immediately after close attempt
            old_context = self.current_context
            self.current_context = None
            self.current_page = None
            
            # Wait longer to ensure browser process actually closes and releases the profile
            import time
            self.logger.info("Waiting for browser to fully close...")
            time.sleep(3)  # Wait 3 seconds for browser to fully close
            
            # Verify context is actually closed
            if old_context:
                try:
                    # Try to access context - if it fails, it's closed
                    _ = old_context.pages
                    self.logger.warning("Context still accessible, may not be fully closed")
                except Exception:
                    self.logger.info("Context is closed")
            
            # Now proceed to next profile
            self.app.after(0, self._on_browser_closed)
        else:
            # No browser to close, proceed directly
            self.logger.info("No browser to close, proceeding directly")
            self._on_browser_closed()
    
    def _on_browser_closed(self):
        """Called after browser is closed, opens next profile."""
        self.logger.info("Browser closed, opening next profile", next_index=self.current_profile_index + 1)
        self.current_context = None
        self.current_page = None
        
        self.current_profile_index += 1
        
        # Check if we have more profiles
        if self.current_profile_index >= len(self.profiles):
            self._finish_login()
            return
        
        self._open_browser_for_profile()
    
    def _stop_login(self):
        """Stop login process."""
        if self.current_context:
            def close_browser():
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    
                    async def close_async():
                        context = self.current_context
                        if context:
                            # Close all pages in context
                            try:
                                for page in context.pages:
                                    if not page.is_closed():
                                        await page.close()
                            except Exception as e:
                                self.logger.warning("Error closing pages", error=str(e))
                            
                            # Close context
                            try:
                                await context.close()
                            except Exception as e:
                                self.logger.warning("Error closing context", error=str(e))
                    
                    loop.run_until_complete(close_async())
                    loop.close()
                except Exception as e:
                    self.logger.warning("Error closing browser", error=str(e))
            
            thread = threading.Thread(target=close_browser, daemon=False)
            thread.start()
            thread.join(timeout=5)
        
        self.current_context = None
        self.current_page = None
        self._reset_ui()
    
    def _finish_login(self):
        """Finish login process."""
        messagebox.showinfo("Complete", f"Login process completed for all {len(self.profiles)} profiles!")
        self._reset_ui()
    
    def _reset_ui(self):
        """Reset UI to initial state."""
        self.current_profile_index = 0
        self.current_context = None
        self.current_page = None
        self.browser_service = None
        
        self.start_btn.configure(state="normal")
        self.next_btn.configure(state="disabled")
        self.stop_btn.configure(state="disabled")
        
        self.status_label.configure(
            text="Ready to start login process",
            text_color=self.app.colors["text"]
        )
        self.profile_label.configure(text="")
        self.progress_label.configure(text=f"0 / {len(self.profiles)} profiles")
        self.progress_bar.set(0)
    
    def on_view_shown(self):
        """Called when view is shown - refresh profiles from settings."""
        settings_service = get_settings_service()
        saved_profiles = settings_service.get_selected_profiles()
        available_profiles = settings_service.get_available_profiles()
        
        # Use selected profiles if set, otherwise use available profiles, otherwise use PROFILES
        if saved_profiles:
            self.profiles = saved_profiles
        elif available_profiles:
            self.profiles = available_profiles
        else:
            self.profiles = list(PROFILES) if PROFILES else []
        
        # Update UI to reflect new profile count
        self.progress_label.configure(text=f"0 / {len(self.profiles)} profiles")
        self.progress_bar.set(0)

