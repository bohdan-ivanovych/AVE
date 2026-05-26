"""Browser context pool for efficient resource management."""

import asyncio
from typing import Optional, Dict
from collections import deque
from datetime import datetime, timedelta
from playwright.async_api import BrowserContext

from src.config import get_config
from src.services.logger import get_logger_service
from src.services.browser_service import BrowserService


class BrowserPool:
    """Pool of browser contexts for reuse and performance optimization."""
    
    def __init__(self, config=None, max_size: int = 5, max_idle_time: int = 300):
        """
        Initialize browser pool.
        
        Args:
            config: AppConfig instance
            max_size: Maximum number of contexts in pool
            max_idle_time: Maximum idle time in seconds before cleanup
        """
        self.config = config or get_config()
        self.logger = get_logger_service().get_logger("browser_pool")
        self.max_size = max_size
        self.max_idle_time = max_idle_time
        
        self._pool: Dict[str, deque] = {}  # profile_name -> deque of (context, last_used)
        self._lock: Optional[asyncio.Lock] = None
        self._lock_loop = None  # Track which event loop the lock belongs to
        self._browser_service = BrowserService(self.config)
        self._cleanup_task: Optional[asyncio.Task] = None
        
        # Don't start cleanup task here - it will be started when needed
        # self._start_cleanup_task()
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self._browser_service.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.cleanup()
    
    def _get_lock(self) -> asyncio.Lock:
        """Get or create lock for current event loop."""
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop, create new lock (will be bound when used)
            if self._lock is None:
                self._lock = asyncio.Lock()
            return self._lock
        
        # Check if lock is bound to current loop
        if self._lock is None or self._lock_loop is not current_loop:
            self._lock = asyncio.Lock()
            self._lock_loop = current_loop
        return self._lock
    
    def _start_cleanup_task(self):
        """Start background task to clean up idle contexts."""
        # Cancel existing task if any
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
        
        async def cleanup_loop():
            while True:
                try:
                    await asyncio.sleep(60)  # Check every minute
                    await self._cleanup_idle_contexts()
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    self.logger.error("Cleanup task error", error=str(e))
        
        try:
            self._cleanup_task = asyncio.create_task(cleanup_loop())
        except RuntimeError:
            # No event loop running, skip cleanup task
            self.logger.debug("No event loop for cleanup task")
    
    async def _cleanup_idle_contexts(self):
        """Remove contexts that have been idle too long."""
        async with self._get_lock():
            now = datetime.now()
            for profile_name, contexts in list(self._pool.items()):
                while contexts:
                    context, last_used = contexts[0]
                    idle_time = (now - last_used).total_seconds()
                    
                    if idle_time > self.max_idle_time:
                        try:
                            await context.close()
                            contexts.popleft()
                            self.logger.debug("Closed idle context", profile=profile_name, idle_seconds=idle_time)
                        except Exception as e:
                            self.logger.warning("Error closing idle context", error=str(e))
                            contexts.popleft()  # Remove anyway
                    else:
                        break  # Rest are newer
    
    async def get_context(self, profile_name: str, headless: bool = False, proxy_server: Optional[str] = None, service_name: Optional[str] = None) -> BrowserContext:
        """
        Get a browser context from pool or create new one.
        
        Args:
            profile_name: Chrome profile name
            headless: Whether to run in headless mode
            
        Returns:
            BrowserContext instance
        """
        async with self._get_lock():
            # If a proxy is specified, always create a fresh context with that proxy
            if proxy_server:
                self.logger.debug("Creating new context with proxy", profile=profile_name)
                # Ensure browser service is started
                try:
                    await self._browser_service.start()
                except Exception as e:
                    self.logger.warning("Failed to start browser service for proxy, retrying", error=str(e))
                    await self._browser_service.cleanup()
                    await self._browser_service.start()
                context = await self._browser_service.create_context(profile_name, headless, proxy_server=proxy_server, service_name=service_name)
                return context

            # Try to get from pool when no proxy override
            if profile_name in self._pool and self._pool[profile_name]:
                context, _ = self._pool[profile_name].popleft()
                # Check if context is still valid
                try:
                    # Quick check - try to get pages
                    pages = context.pages
                    if pages:
                        self.logger.debug("Reusing context from pool", profile=profile_name)
                        return context
                except Exception:
                    # Context is closed, create new one
                    self.logger.debug("Context from pool is closed, creating new", profile=profile_name)
            
            # Create new context
            self.logger.debug("Creating new context", profile=profile_name)
            # Ensure browser service is started and valid
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    await self._browser_service.start()
                    # Verify playwright is valid
                    if hasattr(self._browser_service, '_playwright') and self._browser_service._playwright is None:
                        raise RuntimeError("Playwright is None after start")
                    # Additional check: verify chromium attribute is accessible
                    try:
                        _ = self._browser_service._playwright.chromium
                    except (AttributeError, RuntimeError) as e:
                        self.logger.warning("Playwright chromium invalid, restarting", error=str(e), attempt=attempt + 1)
                        await self._browser_service.cleanup()
                        await self._browser_service.start()
                        if self._browser_service._playwright is None:
                            raise RuntimeError("Playwright is None after restart")
                        _ = self._browser_service._playwright.chromium  # Verify again
                    break
                except Exception as e:
                    if attempt < max_retries - 1:
                        self.logger.warning(f"Failed to start browser service (attempt {attempt + 1}/{max_retries}), retrying", error=str(e))
                        # Try to restart
                        try:
                            await self._browser_service.cleanup()
                        except Exception:
                            pass
                        await asyncio.sleep(0.5 * (attempt + 1))  # Exponential backoff
                    else:
                        self.logger.error("Failed to start browser service after retries", error=str(e))
                        raise
            
            try:
                context = await self._browser_service.create_context(profile_name, headless, service_name=service_name)
                return context
            except Exception as e:
                if "'NoneType' object has no attribute" in str(e) or "Playwright" in str(e):
                    self.logger.warning("Playwright error during context creation, restarting service", error=str(e))
                    # Try one more time with fresh service
                    try:
                        await self._browser_service.cleanup()
                        await self._browser_service.start()
                        context = await self._browser_service.create_context(profile_name, headless, service_name=service_name)
                        return context
                    except Exception as retry_err:
                        self.logger.error("Failed to create context after retry", error=str(retry_err))
                        raise
                raise
    
    async def return_context(self, profile_name: str, context: BrowserContext):
        """
        Return a context to the pool for reuse.
        
        Args:
            profile_name: Chrome profile name
            context: BrowserContext to return
        """
        async with self._get_lock():
            if profile_name not in self._pool:
                self._pool[profile_name] = deque(maxlen=self.max_size)
            
            # Check if pool is full
            if len(self._pool[profile_name]) >= self.max_size:
                # Remove oldest
                try:
                    old_context, _ = self._pool[profile_name].popleft()
                    await old_context.close()
                    self.logger.debug("Pool full, closed oldest context", profile=profile_name)
                except Exception as e:
                    self.logger.warning("Error closing old context", error=str(e))
            
            # Add to pool
            self._pool[profile_name].append((context, datetime.now()))
            self.logger.debug("Context returned to pool", profile=profile_name, pool_size=len(self._pool[profile_name]))
    
    async def cleanup(self):
        """Clean up all contexts in pool."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        async with self._get_lock():
            for profile_name, contexts in self._pool.items():
                while contexts:
                    context, _ = contexts.popleft()
                    try:
                        await context.close()
                    except Exception as e:
                        self.logger.warning("Error closing context during cleanup", error=str(e))
            
            self._pool.clear()
            await self._browser_service.cleanup()
            self.logger.info("Browser pool cleaned up")
    
    def get_pool_stats(self) -> Dict[str, int]:
        """Get statistics about pool usage."""
        return {
            profile: len(contexts)
            for profile, contexts in self._pool.items()
        }


# Global browser pool instance
_browser_pool: Optional[BrowserPool] = None


async def get_browser_pool() -> BrowserPool:
    """Get or create global browser pool."""
    global _browser_pool
    if _browser_pool is None:
        _browser_pool = BrowserPool()
        # Ensure browser service is started
        await _browser_pool._browser_service.start()
        # Start cleanup task in current loop
        try:
            _browser_pool._start_cleanup_task()
        except RuntimeError:
            # No event loop running yet, will start later
            pass
    else:
        # Ensure browser service is still valid
        if _browser_pool._browser_service._playwright is None:
            await _browser_pool._browser_service.start()
        # Ensure cleanup task is running in current loop
        try:
            current_loop = asyncio.get_running_loop()
            if _browser_pool._cleanup_task is None or _browser_pool._cleanup_task.done():
                _browser_pool._start_cleanup_task()
            # Reset lock if it's from different loop (will be recreated by _get_lock)
            if _browser_pool._lock_loop is not None and _browser_pool._lock_loop is not current_loop:
                _browser_pool._lock = None
                _browser_pool._lock_loop = None
        except RuntimeError:
            # No event loop running, skip cleanup task
            pass
    return _browser_pool

