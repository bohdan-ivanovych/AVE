"""Async browser automation service using Playwright."""

import asyncio
import random
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from playwright.async_api import async_playwright, BrowserContext, Page, TimeoutError as PlaywrightTimeout
from datetime import datetime

from src.config import get_config
from src.services.logger import get_logger_service
from src.utils.path_utils import sanitize_path, ensure_directory


class BrowserService:
    """Async browser automation service with proper resource management."""
    
    # Store semaphores per event loop to avoid cross-loop errors
    _loop_semaphores: Dict[int, asyncio.Semaphore] = {}
    _loop_locks: Dict[int, asyncio.Lock] = {}
    # Per-profile coordination to avoid concurrent launches on same Chrome profile
    _profile_locks: Dict[str, asyncio.Lock] = {}
    _profile_active_counts: Dict[str, int] = {}
    _STEALTH_INIT_SCRIPT = r"""
(() => {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    window.navigator.chrome = window.navigator.chrome || { runtime: {} };
    const originalPermissionsQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = parameters => (
        parameters && parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : originalPermissionsQuery(parameters)
    );
    const noop = () => undefined;
    window.navigator.plugins = window.navigator.plugins || [1, 2, 3];
    window.navigator.language = window.navigator.language || 'en-US';
    window.navigator.languages = window.navigator.languages || ['en-US', 'en'];
    window.navigator.vendor = window.navigator.vendor || 'Google Inc.';
    const originalPushState = history.pushState;
    history.pushState = function () {
        return originalPushState.apply(this, arguments);
    };
})();
"""
    _EDGE_USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.2151.44"
    )
    
    def __init__(self, config=None):
        self.config = config or get_config()
        self.logger = get_logger_service().get_logger("browser")
        self._playwright = None
        self._contexts: List[BrowserContext] = []
        self._stealth_enabled = getattr(self.config, "enable_browser_stealth", False)
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - ensures cleanup."""
        await self.cleanup()
    
    async def start(self):
        """Start Playwright instance."""
        if self._playwright is None:
            try:
                self._playwright = await async_playwright().start()
                self.logger.info("Playwright started")
            except Exception as e:
                self.logger.error("Failed to start Playwright", error=str(e))
                self._playwright = None
                raise
    
    async def cleanup(self):
        """Clean up all browser contexts and stop Playwright."""
        # Close all contexts
        contexts_to_close = list(self._contexts)
        self._contexts.clear()
        for ctx in contexts_to_close:
            await self._close_context(ctx)
        
        # Stop Playwright only if we have active contexts or if explicitly requested
        if self._playwright:
            try:
                # Check if playwright is still valid before stopping
                try:
                    # Try to access a property to verify it's still valid
                    _ = self._playwright.chromium
                    await self._playwright.stop()
                except (AttributeError, RuntimeError) as e:
                    # Playwright might already be stopped or invalid
                    self.logger.debug("Playwright already stopped or invalid", error=str(e))
                self._playwright = None
                self.logger.info("Playwright stopped")
            except Exception as e:
                self.logger.warning("Error stopping Playwright", error=str(e))
                self._playwright = None

    async def _close_context(self, context: BrowserContext):
        """Close all pages within the context before closing the context."""
        if context is None:
            return
        profile_key = getattr(context, "_profile_key", None)
        try:
            for page in list(context.pages):
                if not page.is_closed():
                    try:
                        await page.close()
                    except Exception as page_err:
                        self.logger.debug("Failed to close page", error=str(page_err))
            if not context.browser or not context.browser.is_connected():
                # Context already closed or browser disconnected
                return
            await context.close()
        except Exception as ctx_err:
            self.logger.warning("Error closing context", error=str(ctx_err))
        finally:
            if profile_key:
                self._decrement_profile_usage(profile_key)

    @staticmethod
    def _profile_key_from_path(profile_path: Path) -> str:
        """Normalized key for profile tracking."""
        try:
            return str(profile_path.resolve())
        except Exception:
            return str(profile_path)

    @classmethod
    def _get_profile_lock(cls, profile_key: str) -> asyncio.Lock:
        """Return (or create) an async lock for a profile."""
        if profile_key not in cls._profile_locks:
            cls._profile_locks[profile_key] = asyncio.Lock()
        return cls._profile_locks[profile_key]

    @classmethod
    def _increment_profile_usage(cls, profile_key: str) -> None:
        cls._profile_active_counts[profile_key] = cls._profile_active_counts.get(profile_key, 0) + 1

    @classmethod
    def _decrement_profile_usage(cls, profile_key: str) -> None:
        if profile_key in cls._profile_active_counts:
            cls._profile_active_counts[profile_key] = max(0, cls._profile_active_counts[profile_key] - 1)
            if cls._profile_active_counts[profile_key] == 0:
                # Clean up to avoid unbounded growth
                cls._profile_active_counts.pop(profile_key, None)

    async def _configure_context(self, context: BrowserContext) -> None:
        """Apply stealth and other overrides to the context."""
        if context is None:
            return
        if self._stealth_enabled:
            try:
                await context.add_init_script(self._STEALTH_INIT_SCRIPT)
                context.on("page", lambda page: asyncio.create_task(page.add_init_script(self._STEALTH_INIT_SCRIPT)))
                self.logger.debug("Stealth init script attached to context")
            except Exception as stealth_err:
                self.logger.warning("Failed to attach stealth init script", error=str(stealth_err))
    
    async def create_context(
        self,
        profile_name: str,
        headless: bool = False,
        proxy_server: Optional[str] = None,
        service_name: Optional[str] = None
    ) -> BrowserContext:
        """
        Create a browser context for a specific Chrome profile.
        
        Args:
            profile_name: Name of the Chrome profile
            headless: Whether to run in headless mode
            
        Returns:
            BrowserContext instance
            
        Raises:
            ValueError: If profile path is invalid or doesn't exist
        """
        # Ensure Playwright is started
        if not self._playwright:
            await self.start()
        
        # Double check after start
        if not self._playwright:
            self.logger.error("Playwright failed to start", profile=profile_name)
            raise RuntimeError("Playwright instance is None after start()")
        
        # Sanitize and validate profile path
        chrome_base = sanitize_path(self.config.chrome_base)
        profile_path = sanitize_path(profile_name, base_dir=chrome_base)
        profile_key = self._profile_key_from_path(profile_path)
        
        if not profile_path.exists():
            raise ValueError(f"Profile path does not exist: {profile_path}")

        max_per_profile = max(1, getattr(self.config, "max_contexts_per_profile", 1))
        lock_timeout = max(5, getattr(self.config, "profile_lock_timeout_seconds", 45))
        
        try:
            loop_id = id(asyncio.get_running_loop())
            
            async def get_semaphore() -> asyncio.Semaphore:
                """Get or create a semaphore scoped to the current event loop."""
                if loop_id not in BrowserService._loop_semaphores:
                    if loop_id not in BrowserService._loop_locks:
                        BrowserService._loop_locks[loop_id] = asyncio.Lock()
                    async with BrowserService._loop_locks[loop_id]:
                        if loop_id not in BrowserService._loop_semaphores:
                            # Get from settings first, fallback to config
                            try:
                                from src.services.settings_service import get_settings_service
                                settings_service = get_settings_service()
                                max_concurrent_launches = settings_service.get_max_concurrent_browser_launches() or getattr(self.config, 'max_concurrent_browser_launches', 2)
                            except:
                                max_concurrent_launches = getattr(self.config, 'max_concurrent_browser_launches', 2)
                            BrowserService._loop_semaphores[loop_id] = asyncio.Semaphore(max_concurrent_launches)
                return BrowserService._loop_semaphores[loop_id]
            
            # Verify playwright is still valid before using
            if not self._playwright:
                self.logger.warning("Playwright became None, restarting", profile=profile_name)
                await self.start()
                if not self._playwright:
                    raise RuntimeError("Failed to restart Playwright")
            
            profile_lock = self._get_profile_lock(profile_key)
            wait_elapsed = 0.0

            async with profile_lock:
                # Ensure we don't launch multiple browsers on the same profile in parallel
                while BrowserService._profile_active_counts.get(profile_key, 0) >= max_per_profile:
                    if wait_elapsed >= lock_timeout:
                        raise RuntimeError(
                            f"Profile {profile_name} is already in use by another browser instance"
                        )
                    if int(wait_elapsed) % 5 == 0:
                        self.logger.info(
                            "Waiting for profile lock",
                            profile=profile_name,
                            active=BrowserService._profile_active_counts.get(profile_key, 0),
                            limit=max_per_profile
                        )
                    await asyncio.sleep(0.5)
                    wait_elapsed += 0.5

                # Use semaphore to limit concurrent browser launches
                launch_semaphore = await get_semaphore()
                async with launch_semaphore:
                    # Optimized delay for slow computers - increased stagger to prevent overload
                    # For 12 browsers, we need more spacing to avoid system lag
                    stagger_delay = getattr(self.config, 'browser_stagger_delay_ms', 1000) / 1000.0
                    await asyncio.sleep(stagger_delay)  # 1s default stagger between browsers
                    
                    # Additional check: ensure profile is not locked by another process
                    try:
                        import psutil
                        profile_str = str(profile_path)
                        # Check if any Chrome process is using this profile
                        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                            try:
                                if proc.info['name'] and 'chrome' in proc.info['name'].lower():
                                    cmdline = proc.info.get('cmdline', [])
                                    if cmdline and any(profile_str in str(arg) for arg in cmdline):
                                        # Wait a bit if profile is in use
                                        await asyncio.sleep(2)
                                        break
                            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                                pass
                    except ImportError:
                        # psutil not available, skip check
                        pass
                    except Exception:
                        # Ignore errors in profile check
                        pass
                    
                    # Optimized launch args for better performance and reduced lag
                    # Core performance optimizations (safe for all services)
                    # NOTE: Removed --disable-background-networking and --disable-gpu as they can block video downloads
                    launch_args = [
                        "--disable-blink-features=AutomationControlled",
                        "--disable-infobars"
                    ]
                    
                    # Add headless optimizations
                    try:
                        extra_args = getattr(self.config, "browser_extra_args", []) or []
                        launch_args.extend(extra_args)
                        if service_name == "qwen":
                            qwen_extra_args = getattr(self.config, "qwen_browser_extra_args", []) or []
                            launch_args.extend(qwen_extra_args)
                    except Exception as arg_err:
                        self.logger.warning("Failed to apply custom browser args", error=str(arg_err))
                    
                    # Final check before launching - playwright might have become None
                    if not self._playwright:
                        self.logger.warning("Playwright is None before launch, restarting", profile=profile_name)
                        await self.start()
                        if not self._playwright:
                            raise RuntimeError("Failed to restart Playwright before context creation")
                    
                    # Verify playwright is still valid by checking chromium attribute
                    try:
                        _ = self._playwright.chromium
                    except (AttributeError, RuntimeError) as e:
                        self.logger.error("Playwright chromium attribute invalid, restarting", error=str(e), profile=profile_name)
                        await self.start()
                        if not self._playwright:
                            raise RuntimeError("Failed to restart Playwright - chromium attribute invalid")
                        try:
                            _ = self._playwright.chromium
                        except (AttributeError, RuntimeError) as e2:
                            raise RuntimeError(f"Playwright still invalid after restart: {e2}")
                    
                    browser_channel = getattr(self.config, "browser_channel", "chrome") or "chrome"
                    executable_path = getattr(self.config, "browser_executable_path", None)
                    
                    # Smart Executable Finder
                    if not executable_path:
                        import os
                        username = os.environ.get("USERNAME", "")
                        possible_paths = [
                            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                            f"C:\\Users\\{username}\\AppData\\Local\\Google\\Chrome\\Application\\chrome.exe"
                        ]
                        for path in possible_paths:
                            if os.path.exists(path):
                                executable_path = path
                                break

                    if executable_path:
                        executable_path = str(executable_path)
                    configured_ua = getattr(self.config, "browser_user_agent", None)
                    if configured_ua:
                        user_agent = configured_ua
                    else:
                        # Light UA randomization between common real-world variants
                        ua_candidates = [
                            self._EDGE_USER_AGENT,
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
                        ]
                        user_agent = random.choice(ua_candidates)
                    
                    self.logger.info(
                        "Launching browser context",
                        profile=profile_name,
                        headless=headless,
                        channel="executable" if executable_path else browser_channel
                    )
                    
                    # Orphan Lock Sweeper
                    lock_file = profile_path / "SingletonLock"
                    cookie_lock = profile_path / "SingletonCookie"
                    try:
                        if lock_file.exists():
                            lock_file.unlink()
                            self.logger.info("Removed orphaned SingletonLock", profile=profile_name)
                        if cookie_lock.exists():
                            cookie_lock.unlink()
                            self.logger.info("Removed orphaned SingletonCookie", profile=profile_name)
                    except Exception as lock_err:
                        self.logger.debug("Lock files exist but could not be removed (browser may be actively running)", error=str(lock_err))
                    try:
                        # Randomize viewport a bit to look less like a bot farm
                        viewport = None
                        if not headless:
                            width = random.randint(1360, 1920)
                            height = random.randint(768, 1080)
                            viewport = {"width": width, "height": height}

                        ctx = await self._playwright.chromium.launch_persistent_context(
                            user_data_dir=str(profile_path),
                            headless=headless,
                            channel=None if executable_path else browser_channel,
                            executable_path=executable_path,
                            args=launch_args,
                            ignore_default_args=["--enable-automation"],
                            timeout=120000,
                            proxy={"server": proxy_server} if proxy_server else None,
                            accept_downloads=True,  # Enable downloads for video/media files
                            # Performance optimizations
                            viewport=viewport,
                            java_script_enabled=True,
                            bypass_csp=True,
                            user_agent=user_agent
                        )
                    except AttributeError as launch_err:
                        if "'NoneType' object has no attribute" in str(launch_err) or self._playwright is None:
                            self.logger.error("Playwright became None during launch, restarting", profile=profile_name, error=str(launch_err))
                            await self.start()
                            if not self._playwright:
                                raise RuntimeError("Failed to restart Playwright after launch error")
                            # Retry once
                            ctx = await self._playwright.chromium.launch_persistent_context(
                                user_data_dir=str(profile_path),
                                headless=headless,
                                channel=None if executable_path else browser_channel,
                                executable_path=executable_path,
                                args=launch_args,
                                ignore_default_args=["--enable-automation"],
                                timeout=120000,
                                proxy={"server": proxy_server} if proxy_server else None,
                                viewport={"width": 1920, "height": 1080} if not headless else None,
                                java_script_enabled=True,
                                bypass_csp=True,
                                user_agent=user_agent
                            )
                        else:
                            raise
                    self._contexts.append(ctx)
                    setattr(ctx, "_profile_key", profile_key)
                    BrowserService._increment_profile_usage(profile_key)
                    ctx.on("close", lambda _: BrowserService._decrement_profile_usage(profile_key))
                    self.logger.info(
                        "Browser context created",
                        profile=profile_name,
                        active_profiles=BrowserService._profile_active_counts.get(profile_key, 1)
                    )
                    
                    await self._configure_context(ctx)
                    
                    # Small delay to let browser stabilize
                    await asyncio.sleep(0.5)
                    
                    return ctx
        except AttributeError as e:
            if "'NoneType' object has no attribute" in str(e):
                self.logger.error("Playwright became None during context creation, restarting", profile=profile_name, error=str(e))
                # Try to restart
                await self.start()
                if not self._playwright:
                    raise RuntimeError("Failed to restart Playwright after NoneType error")
                # Retry once
                try:
                    profile_lock = self._get_profile_lock(profile_key)
                    wait_elapsed = 0.0
                    async with profile_lock:
                        while BrowserService._profile_active_counts.get(profile_key, 0) >= max_per_profile:
                            if wait_elapsed >= lock_timeout:
                                raise RuntimeError(
                                    f"Profile {profile_name} is already in use by another browser instance"
                                )
                            await asyncio.sleep(0.5)
                            wait_elapsed += 0.5

                        launch_semaphore = await get_semaphore()
                        async with launch_semaphore:
                            # Increased stagger for browsers in same batch (optimized for slow computers)
                            stagger_delay = getattr(self.config, 'browser_stagger_delay_ms', 1000) / 1000.0
                            await asyncio.sleep(stagger_delay)
                            
                            launch_args = [
                                "--disable-blink-features=AutomationControlled",
                                "--disable-dev-shm-usage",
                            ]
                            # Only disable GPU in headless mode
                            if headless:
                                launch_args.append("--disable-gpu")
                            ctx = await self._playwright.chromium.launch_persistent_context(
                                user_data_dir=str(profile_path),
                                headless=headless,
                                channel=None if executable_path else browser_channel,
                                executable_path=executable_path,
                                args=launch_args,
                                ignore_default_args=["--enable-automation"],
                                timeout=120000,
                                proxy={"server": proxy_server} if proxy_server else None,
                                accept_downloads=True,  # Enable downloads for video/media files
                                user_agent=user_agent
                            )
                            self._contexts.append(ctx)
                            setattr(ctx, "_profile_key", profile_key)
                            BrowserService._increment_profile_usage(profile_key)
                            ctx.on("close", lambda _: BrowserService._decrement_profile_usage(profile_key))
                            self.logger.info("Browser context created after retry", profile=profile_name)
                            await self._configure_context(ctx)
                            
                            # Add delay after launch before releasing semaphore (optimized for slow computers)
                            launch_delay = getattr(self.config, 'browser_launch_delay_ms', 2000) / 1000.0
                            await asyncio.sleep(launch_delay)
                            
                            return ctx
                except Exception as retry_e:
                    self.logger.error("Failed to create context after retry", error=str(retry_e), profile=profile_name)
                    raise
            else:
                raise
        except Exception as e:
            self.logger.error("Failed to create browser context", error=str(e), profile=profile_name)
            raise
    
    async def create_context_and_navigate(
        self,
        profile_name: str,
        headless: bool = False,
        proxy_server: Optional[str] = None
    ) -> Tuple[BrowserContext, Page]:
        """
        Create browser context, create page, and navigate to Sora.
        This ensures the page is loaded before the next browser starts.
        
        Args:
            profile_name: Name of the Chrome profile
            headless: Whether to run in headless mode
            proxy_server: Optional proxy server
            
        Returns:
            Tuple of (BrowserContext, Page) - both ready to use
        """
        # Create context
        ctx = await self.create_context(profile_name, headless, proxy_server)
        
        # Create page
        page = await ctx.new_page()
        
        # Navigate to Sora and wait for it to load
        if not await self.navigate_to_sora(page):
            await page.close()
            raise Exception("Failed to navigate to Sora")
        
        # Wait for page to be fully ready
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except:
            # Fallback to domcontentloaded if networkidle takes too long
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
        
        self.logger.info("Browser context and page ready", profile=profile_name)
        return ctx, page
    
    async def navigate_to_sora(
        self,
        page: Page,
        retries: Optional[int] = None
    ) -> bool:
        """
        Navigate to Sora URL with retry logic.
        
        Args:
            page: Playwright Page instance
            retries: Number of retry attempts (defaults to config value)
            
        Returns:
            True if navigation successful, False otherwise
        """
        retries = retries or self.config.navigation_retries
        
        for attempt in range(retries):
            try:
                await page.goto(
                    self.config.sora_url,
                    wait_until="domcontentloaded",
                    timeout=120000
                )
                # Wait for page to be fully loaded
                try:
                    await page.wait_for_load_state("networkidle", timeout=15000)
                except:
                    await page.wait_for_load_state("domcontentloaded", timeout=10000)
                
                # Wait for first interactive element to appear (Create/Remix button or file input)
                self.logger.info("Waiting for Sora page elements to load", attempt=attempt + 1)
                try:
                    await page.wait_for_selector(
                        'textarea[placeholder*="Describe"], button:has-text("Create"), button:has-text("Remix"), input[type="file"]',
                        timeout=30000,
                        state="visible"
                    )
                    self.logger.info("Sora page elements loaded successfully", attempt=attempt + 1)
                except Exception as e:
                    self.logger.warning("Main elements not found, waiting longer", attempt=attempt + 1, error=str(e))
                    # Additional wait for slow connections
                    await page.wait_for_timeout(5000)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=10000)
                    except:
                        await page.wait_for_load_state("domcontentloaded", timeout=5000)
                
                self.logger.info("Navigation successful", attempt=attempt + 1)
                return True
            except Exception as e:
                if attempt < retries - 1:
                    self.logger.warning("Navigation failed, retrying", attempt=attempt + 1, error=str(e))
                    await asyncio.sleep(3)
                else:
                    self.logger.error("Navigation failed after all retries", error=str(e))
                    return False
        
        return False
    
    async def check_login_status(self, page: Page) -> bool:
        """
        Check if user is logged in to Sora.
        
        Args:
            page: Playwright Page instance
            
        Returns:
            True if logged in, False otherwise
        """
        url = page.url.lower()
        if "login" in url or "auth" in url:
            self.logger.warning("Not logged in", url=url)
            return False
        return True
    
    async def upload_images(
        self,
        page: Page,
        image_paths: List[Path],
        delay_ms: int = 2000
    ) -> bool:
        """
        Upload multiple images to Sora with optimized delays and better error handling.
        
        Args:
            page: Playwright Page instance
            image_paths: List of image file paths to upload
            delay_ms: Delay between uploads in milliseconds
            
        Returns:
            True if all uploads successful, False otherwise
        """
        if not image_paths:
            self.logger.warning("No images provided for upload")
            return False
        
        if page.is_closed():
            self.logger.error("Page is closed, cannot upload images")
            return False
        
        for idx, img_path in enumerate(image_paths):
            # Sanitize path
            sanitized = sanitize_path(img_path)
            
            if not sanitized.exists():
                self.logger.error("Image file not found", path=str(sanitized))
                return False
            
            try:
                # Wait for file input to be available with better retry logic
                file_input = page.locator('input[type="file"]').first
                
                # Wait for input to be attached to DOM with more retries and better checks
                max_wait_attempts = 15
                input_ready = False
                for wait_attempt in range(max_wait_attempts):
                    try:
                        count = await file_input.count()
                        if count > 0:
                            # Try to wait for input to be attached
                            try:
                                await file_input.wait_for(state="attached", timeout=5000)
                                # Additional check: verify input is actually usable
                                try:
                                    # Try to check if input is accessible
                                    is_visible = await file_input.is_visible()
                                    # Even if hidden, it should be attached
                                    input_ready = True
                                    break
                                except:
                                    # If visibility check fails but count > 0, still try
                                    input_ready = True
                                    break
                            except Exception as attach_err:
                                # If wait_for fails but count > 0, still try to use it
                                if count > 0:
                                    self.logger.debug("Input found but wait_for failed, trying anyway", error=str(attach_err))
                                    input_ready = True
                                    break
                    except Exception as wait_e:
                        self.logger.debug("Waiting for file input", attempt=wait_attempt + 1, error=str(wait_e))
                    
                    if wait_attempt < max_wait_attempts - 1:
                        await asyncio.sleep(0.5)  # Wait 500ms between attempts
                
                if not input_ready:
                    self.logger.error("File input not found or not ready after waiting", attempts=max_wait_attempts, path=str(sanitized))
                    return False
                
                # Upload the file with longer timeout
                try:
                    # Verify file still exists before upload
                    if not sanitized.exists():
                        self.logger.error("Image file disappeared before upload", path=str(sanitized))
                        return False
                    
                    await file_input.set_input_files(str(sanitized.absolute()), timeout=60000)
                    self.logger.info("Image uploaded", index=idx + 1, total=len(image_paths), filename=sanitized.name)
                except PlaywrightTimeout as upload_err:
                    # Retry once with a fresh locator
                    self.logger.warning("Upload timeout, retrying with fresh locator", error=str(upload_err), path=str(sanitized))
                    await asyncio.sleep(1)
                    try:
                        file_input = page.locator('input[type="file"]').first
                        await file_input.set_input_files(str(sanitized.absolute()), timeout=60000)
                        self.logger.info("Image uploaded on retry", index=idx + 1, total=len(image_paths), filename=sanitized.name)
                    except Exception as retry_err:
                        self.logger.error("Upload failed on retry", error=str(retry_err), path=str(sanitized))
                        return False
                except Exception as upload_err:
                    self.logger.error("Upload failed with unexpected error", error=str(upload_err), path=str(sanitized))
                    return False
                
                # Wait for upload to process
                if idx < len(image_paths) - 1:
                    # Wait for upload to process (reduced delay)
                    await asyncio.sleep(delay_ms / 1000.0)
                else:
                    # Last image - wait a bit longer to ensure processing
                    await asyncio.sleep((delay_ms * 1.5) / 1000.0)
            except Exception as e:
                self.logger.error("Failed to upload image", error=str(e), path=str(sanitized), index=idx + 1)
                return False
        
        return True
    
    async def wait_for_create_button(
        self,
        page: Page,
        timeout_seconds: Optional[int] = None
    ) -> bool:
        """
        Wait for the Create/Remix button to appear and become enabled with improved reliability.
        
        Args:
            page: Playwright Page instance
            timeout_seconds: Maximum wait time in seconds
            
        Returns:
            True if button becomes ready, False on timeout
        """
        timeout = timeout_seconds or self.config.button_wait_seconds
        
        self.logger.info("Waiting for Create/Remix button to appear", timeout=timeout)
        
        # First, wait for the button element to exist and be visible
        try:
            # Wait for button to appear in DOM first
            await page.wait_for_selector(
                'button:has-text("Create"), button:has-text("Remix")',
                timeout=timeout * 1000,
                state="attached"
            )
            self.logger.info("Create/Remix button found in DOM")
        except Exception as e:
            self.logger.warning("Create/Remix button not found in DOM", error=str(e))
            return False
        
        # Wait for files to fully process before checking button state
        self.logger.info("Waiting for files to fully process...")
        await asyncio.sleep(0.8)
        
        # Then wait for it to be enabled with improved polling
        try:
            # Try to wait for button to be enabled using Playwright's built-in waiting
            await page.wait_for_function(
                """
                () => {
                    const btn = Array.from(document.querySelectorAll('button'))
                        .find(b => b.textContent.includes('Remix') || b.textContent.includes('Create'));
                    if (!btn) return false;
                    const disabled = btn.getAttribute('data-disabled');
                    // Also check if button is not disabled via class or aria-disabled
                    const isDisabled = disabled === 'true' || 
                                       btn.hasAttribute('disabled') || 
                                       btn.getAttribute('aria-disabled') === 'true';
                    return !isDisabled;
                }
                """,
                timeout=timeout * 1000,
                polling=500
            )
            self.logger.info("Create button ready and enabled")
            return True
        except Exception as e:
            # Fallback to manual polling if wait_for_function fails
            self.logger.debug("wait_for_function failed, using manual polling", error=str(e))
            for attempt in range(min(timeout, 60)):
                try:
                    button_state = await page.evaluate("""
                        () => {
                            const btn = Array.from(document.querySelectorAll('button'))
                                .find(b => b.textContent.includes('Remix') || b.textContent.includes('Create'));
                            if (!btn) return 'notfound';
                            const disabled = btn.getAttribute('data-disabled');
                            const hasDisabledAttr = btn.hasAttribute('disabled');
                            const ariaDisabled = btn.getAttribute('aria-disabled');
                            if (disabled === 'false' && !hasDisabledAttr && ariaDisabled !== 'true') {
                                return 'ready';
                            }
                            return 'disabled';
                        }
                    """)
                    
                    if button_state == 'ready':
                        self.logger.info("Create button ready", attempt=attempt + 1)
                        return True
                    elif button_state == 'notfound':
                        self.logger.warning("Create button not found during polling", attempt=attempt + 1)
                    
                    if (attempt + 1) % 10 == 0:
                        self.logger.debug("Still waiting for button", attempt=attempt + 1, state=button_state)
                    
                    await asyncio.sleep(1)
                except Exception as e2:
                    self.logger.warning("Error checking button", error=str(e2))
                    await asyncio.sleep(1)
        
        self.logger.error("Create button never became ready", timeout=timeout)
        return False
    
    async def set_prompt_and_click(
        self,
        page: Page,
        prompt: str,
        max_attempts: int = 20
    ) -> bool:
        """
        Set the prompt text and click the Create button with verification.
        
        Args:
            page: Playwright Page instance
            prompt: Prompt text to set
            max_attempts: Maximum number of click attempts
            
        Returns:
            True if successful, False otherwise
        """
        if not prompt or not prompt.strip():
            self.logger.warning("Empty prompt provided")
            return False
        
        for attempt in range(max_attempts):
            try:
                # First, set the prompt
                set_result = await page.evaluate(
                    """
                    (prompt) => {
                        const textarea = document.querySelector('textarea[placeholder*="Describe"]');
                        if (!textarea) return {success: false, error: "notextarea"};
                        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
                        nativeInputValueSetter.call(textarea, prompt);
                        textarea.dispatchEvent(new Event('input', { bubbles: true }));
                        textarea.dispatchEvent(new Event('change', { bubbles: true }));
                        const actualValue = textarea.value;
                        // Verify that prompt was actually set
                        const isSet = actualValue === prompt || actualValue.length === prompt.length;
                        return {
                            success: true, 
                            promptLength: actualValue.length,
                            expectedLength: prompt.length,
                            isSet: isSet,
                            actualValue: actualValue.substring(0, 50)  // First 50 chars for debugging
                        };
                    }
                    """,
                    prompt
                )
                
                if not set_result.get('success'):
                    self.logger.warning("Failed to set prompt", error=set_result.get('error'))
                    await asyncio.sleep(0.5)
                    continue
                
                # CRITICAL: Verify that prompt was actually set
                if not set_result.get('isSet'):
                    self.logger.warning(
                        "Prompt not properly set",
                        expected_length=set_result.get('expectedLength'),
                        actual_length=set_result.get('promptLength'),
                        actual_preview=set_result.get('actualValue'),
                        attempt=attempt + 1
                    )
                    # Try to clear and set again
                    await page.evaluate("""
                        () => {
                            const textarea = document.querySelector('textarea[placeholder*="Describe"]');
                            if (textarea) {
                                textarea.value = '';
                                textarea.dispatchEvent(new Event('input', { bubbles: true }));
                                textarea.dispatchEvent(new Event('change', { bubbles: true }));
                            }
                        }
                    """)
                    await asyncio.sleep(0.3)
                    continue
                
                # Wait a bit for Sora to process the input (may temporarily disable button)
                await asyncio.sleep(0.5)
                
                # Now try to click the button - check if it's enabled after setting prompt
                click_result = await page.evaluate(
                    """
                    () => {
                        const buttons = Array.from(document.querySelectorAll('button'));
                        const createBtn = buttons.find(b => b.textContent.includes('Remix') || b.textContent.includes('Create'));
                        if (!createBtn) return {found: false};
                        const disabled = createBtn.getAttribute('data-disabled');
                        if (disabled === 'false') {
                            createBtn.click();
                            return {found: true, clicked: true};
                        }
                        return {found: true, clicked: false, disabled: disabled};
                    }
                    """
                )
                
                if click_result.get('clicked'):
                    self.logger.info(
                        "Prompt set and Create clicked",
                        prompt_length=set_result.get('promptLength'),
                        verified=True
                    )
                    # Wait for page to start processing
                    try:
                        await page.wait_for_timeout(2000)
                        await page.wait_for_load_state("networkidle", timeout=5000)
                    except:
                        await page.wait_for_timeout(3000)
                    return True
                
                if not click_result.get('found'):
                    self.logger.warning("Create button not found", attempt=attempt + 1)
                    await asyncio.sleep(0.5)
                    continue
                
                if (attempt + 1) % 5 == 0:
                    self.logger.debug("Waiting to click", attempt=attempt + 1, disabled=click_result.get('disabled'))
                
                await asyncio.sleep(0.5)
            except Exception as e:
                self.logger.warning("Error setting prompt", error=str(e), attempt=attempt + 1)
                await asyncio.sleep(0.5)
        
        self.logger.error("Failed to click Create button", max_attempts=max_attempts)
        return False
    
    async def wait_for_sora_notification(
        self,
        page: Page,
        timeout_seconds: Optional[int] = None
    ) -> bool:
        """
        Wait for Sora generation notification.
        
        Args:
            page: Playwright Page instance
            timeout_seconds: Maximum wait time in seconds
            
        Returns:
            True if notification detected, False on timeout
        """
        timeout = timeout_seconds or self.config.notification_timeout_seconds
        
        # Optimized: Use wait_for_selector with timeout instead of manual polling
        try:
            img = await page.wait_for_selector(
                'img[alt="Sora generation"].object-cover',
                timeout=timeout * 1000,  # Convert to milliseconds
                state="visible"
            )
            if img:
                src = await img.get_attribute("src")
                self.logger.info("Sora notification detected", src=src)
                return True
        except Exception as e:
            # Fallback to polling if wait_for_selector fails
            self.logger.debug("wait_for_selector failed, using polling", error=str(e))
            waited = 0
            while waited < timeout:
                try:
                    img = await page.query_selector('img[alt="Sora generation"].object-cover')
                    if img:
                        src = await img.get_attribute("src")
                        self.logger.info("Sora notification detected", src=src)
                        return True
                    await asyncio.sleep(1)  # Reduced from 2s to 1s
                    waited += 1
                except Exception as e2:
                    self.logger.debug("Error checking notification", error=str(e2))
                    await asyncio.sleep(1)
                    waited += 1
        
        self.logger.warning("Notification timeout", timeout=timeout)
        return False
    
    async def download_generated_variants(
        self,
        page: Page,
        output_dir: Path,
        worker_id: int,
        task_name: str,
        max_variants: int = 2
    ) -> List[Path]:
        """
        Download generated image variants from Sora.
        
        Args:
            page: Playwright Page instance
            output_dir: Directory to save downloads
            worker_id: Worker identifier
            task_name: Task name for filename
            max_variants: Maximum number of variants to download
            
        Returns:
            List of downloaded file paths
        """
        output_dir = ensure_directory(sanitize_path(output_dir))
        downloaded_files = []
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        try:
            await page.evaluate("window.scrollTo(0, 0)")
            # Optimized: Wait for content to load instead of fixed timeout
            await page.wait_for_load_state("domcontentloaded", timeout=2000)
            
            tiles = page.locator('div.group\\/tile')
            total = await tiles.count()
            self.logger.info("Found tiles", total=total, max_variants=max_variants)
            
            for idx in range(min(max_variants, total)):
                try:
                    tile = tiles.nth(idx)
                    self.logger.info("Downloading variant", index=idx + 1, total=min(max_variants, total))
                    
                    await tile.scroll_into_view_if_needed()
                    # Reduced delay - wait for element to be visible
                    await tile.wait_for(state="visible", timeout=3000)
                    await tile.hover()
                    # Reduced delay - wait for menu button to appear
                    await asyncio.sleep(0.3)  # Reduced from 1000ms
                    
                    menu_button = tile.locator('button[aria-haspopup="menu"]')
                    await menu_button.wait_for(state="visible", timeout=5000)
                    await menu_button.click()
                    # Reduced delay - wait for menu to open
                    await asyncio.sleep(0.4)  # Reduced from 800ms
                    
                    download_item = page.locator('div[role="menuitem"]:has-text("Download")')
                    await download_item.wait_for(state="visible", timeout=5000)
                    
                    async with page.expect_download(timeout=30000) as download_info:
                        await download_item.click()
                        download = await download_info.value
                        
                        filename = f"{timestamp}_W{worker_id}_{task_name}_v{idx + 1}.webp"
                        save_path = output_dir / filename
                        await download.save_as(save_path)
                        
                        downloaded_files.append(save_path)
                        self.logger.info("Downloaded variant", filename=filename, path=str(save_path))
                        # Reduced delay between downloads
                        await asyncio.sleep(0.5)  # Reduced from 1000ms
                        
                except Exception as e:
                    self.logger.error("Failed to download variant", error=str(e), index=idx + 1)
                    # Take screenshot for debugging
                    try:
                        screenshot_path = output_dir / f"debug_W{worker_id}_fail_{idx}.png"
                        await page.screenshot(path=str(screenshot_path))
                        self.logger.info("Screenshot saved", path=str(screenshot_path))
                    except Exception as e2:
                        self.logger.warning("Failed to save screenshot", error=str(e2))
                    continue
            
            self.logger.info("Download complete", downloaded=len(downloaded_files), requested=max_variants)
            return downloaded_files
            
        except Exception as e:
            self.logger.error("Download error", error=str(e))
            return downloaded_files

