"""Qwen video generation service."""

import asyncio
import random
import time
from pathlib import Path
from typing import List, Optional, Tuple
from datetime import datetime
from playwright.async_api import Page, Locator, TimeoutError as PlaywrightTimeout, BrowserContext

from src.config import get_config
from src.services.logger import get_logger_service
from src.services.browser_service import BrowserService
from src.services.browser_pool import get_browser_pool
from src.utils.path_utils import sanitize_path
from src.utils.name_utils import describe_media_name


class VideoGenerationActivationError(Exception):
    """Raised when the Video Generation button cannot be activated reliably."""
    pass


class QwenService:
    """Service for generating videos from images using Qwen."""
    
    QWEN_URL = "https://chat.qwen.ai/"
    IMAGE_STABILIZE_DELAY_MS = 5000  # Зменшено з 17_000 для швидшої роботи
    SEARCH_URLS = [
        "https://www.google.com/",
        "https://www.bing.com/",
    ]
    
    def __init__(self, config=None):
        self.config = config or get_config()
        self.logger = get_logger_service().get_logger("qwen")

    async def _navigate_to_qwen_via_search(self, page: Page, worker_id: int) -> None:
        """
        Navigate to Qwen via search engine instead of direct URL.
        
        Це має виглядати максимально по-людськи:
        - відкриваємо bing / google
        - вводимо 'qwen' в пошуку (по-людськи, з затримками)
        - клікаємо по результату chat.qwen.ai
        """
        last_error = None
        for search_url in self.SEARCH_URLS:
            try:
                self.logger.info("Navigating to search engine before Qwen", worker_id=worker_id, url=search_url)
                await page.goto(
                    search_url,
                    wait_until="domcontentloaded",
                    timeout=45000
                )
                await page.wait_for_timeout(random.randint(500, 1000))  # Optimized wait
                await self._handle_access_verification(page, worker_id, stage="search_page", suppress_exceptions=True)
                
                # Знаходимо поле пошуку
                search_box = page.locator(
                    'input[name="q"], input[type="search"], textarea[role="combobox"], input[aria-label*="Search" i], input[name="search"], input[placeholder*="Search" i]'
                ).first
                await search_box.wait_for(state="visible", timeout=15000)
                
                # Human-like click and type (optimized)
                await search_box.click()
                await page.wait_for_timeout(random.randint(50, 150))
                
                # Type "qwen" character by character (human-like but faster)
                search_text = "qwen"
                for char in search_text:
                    await search_box.type(char, delay=random.randint(30, 80))
                    await page.wait_for_timeout(random.randint(20, 50))
                
                await page.wait_for_timeout(random.randint(100, 300))
                await page.keyboard.press("Enter")
                
                # Чекаємо результати (optimized)
                await page.wait_for_timeout(random.randint(1000, 1500))
                await self._handle_access_verification(page, worker_id, stage="search_results", suppress_exceptions=True)
                
                # Перший результат, який веде на qwen.ai - пробуємо різні селектори
                result_link = None
                result_selectors = [
                    'a[href*="chat.qwen.ai"]',
                    'a[href*="qwen.ai"]',
                    'a:has-text("chat.qwen.ai")',
                    'a:has-text("Qwen")',
                    'h3 a[href*="qwen"]',
                    'div a[href*="qwen.ai"]',
                    'cite:has-text("qwen.ai")',
                    'a[data-ved] a[href*="qwen"]'
                ]
                
                for selector in result_selectors:
                    try:
                        locator = page.locator(selector).first
                        if await locator.count() > 0:
                            result_link = locator
                            self.logger.info(f"Found Qwen result with selector: {selector}", worker_id=worker_id)
                            break
                    except Exception:
                        continue
                
                if not result_link:
                    raise Exception("Could not find Qwen search result")
                
                await result_link.wait_for(state="visible", timeout=20000)
                
                # Human-like hover before click (optimized)
                await result_link.hover()
                await page.wait_for_timeout(random.randint(50, 150))
                
                href = await result_link.get_attribute("href")
                self.logger.info("Clicking search result for Qwen", worker_id=worker_id, href=href or "")
                await result_link.click()
                
                # Чекаємо завантаження Qwen (optimized)
                await page.wait_for_timeout(random.randint(1000, 1500))
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=30000)
                except Exception:
                    pass
                await self._handle_access_verification(page, worker_id, stage="post_search_click", suppress_exceptions=True)
                
                # Якщо реально опинилися на qwen.ai — успіх
                current_url = page.url or ""
                if "qwen.ai" in current_url:
                    self.logger.info("Successfully navigated to Qwen via search", worker_id=worker_id, url=current_url)
                    return
                else:
                    self.logger.warning("Search result did not land on qwen.ai, trying next search engine", worker_id=worker_id, url=current_url)
                    last_error = RuntimeError("Search did not land on qwen.ai")
            except Exception as e:
                last_error = e
                self.logger.warning("Failed to navigate to Qwen via search engine", worker_id=worker_id, search_url=search_url, error=str(e))
        
        # Якщо всі спроби через пошук провалилися — fallback на прямий URL
        self.logger.warning("All search-based navigation attempts failed, falling back to direct Qwen URL", worker_id=worker_id, error=str(last_error) if last_error else "")
        await page.goto(
            self.QWEN_URL,
            wait_until="domcontentloaded",
            timeout=60000
        )
        await page.wait_for_timeout(2000)
        await self._handle_access_verification(page, worker_id, stage="fallback_direct_qwen", suppress_exceptions=True)

    async def _is_captcha_failed(self, page: Page) -> bool:
        """Check if captcha verification failed and refresh is needed."""
        try:
            fail_selectors = [
                "#aliyunCaptcha-sliding-fail-text",
                ".aliyunCaptcha-sliding-fail-text",
                'span:has-text("Verify failed, please refresh")',
                'text="Verify failed, please refresh"'
            ]
            for selector in fail_selectors:
                try:
                    locator = page.locator(selector).first
                    if await locator.count() > 0 and await locator.is_visible():
                        return True
                except Exception:
                    continue
            return False
        except Exception:
            return False
    
    async def _click_captcha_refresh(self, page: Page, worker_id: int) -> bool:
        """Click the refresh button if captcha verification failed."""
        try:
            refresh_selectors = [
                "#aliyunCaptcha-sliding-refresh",
                ".aliyunCaptcha-sliding-refresh",
                'span#aliyunCaptcha-sliding-refresh',
                'span[class*="aliyunCaptcha-sliding-refresh"]'
            ]
            
            for selector in refresh_selectors:
                try:
                    refresh_btn = page.locator(selector).first
                    if await refresh_btn.count() > 0 and await refresh_btn.is_visible():
                        self.logger.info("Clicking captcha refresh button", worker_id=worker_id)
                        # Human-like hover before click
                        await refresh_btn.hover()
                        await page.wait_for_timeout(random.randint(100, 200))
                        await refresh_btn.click()
                        await page.wait_for_timeout(random.randint(500, 1000))
                        return True
                except Exception:
                    continue
            
            # Try to find parent element with refresh text
            try:
                fail_text = page.locator('text="Verify failed, please refresh"').first
                if await fail_text.count() > 0:
                    # Find refresh icon nearby
                    parent = fail_text.locator('..')
                    refresh_icon = parent.locator('#aliyunCaptcha-sliding-refresh, span[class*="refresh"]').first
                    if await refresh_icon.count() > 0:
                        await refresh_icon.hover()
                        await page.wait_for_timeout(random.randint(100, 200))
                        await refresh_icon.click()
                        await page.wait_for_timeout(random.randint(500, 1000))
                        return True
            except Exception:
                pass
            
            return False
        except Exception as e:
            self.logger.warning(f"Failed to click refresh button: {e}", worker_id=worker_id)
            return False

    async def _is_access_verification_visible(self, page: Page) -> bool:
        """Detect if the Aliyun WAF slider verification is currently blocking the UI."""
        selectors = [
            "#WAF_NC_WRAPPER",
            "div.waf-nc-wrapper",
            "#nocaptcha",
            "#aliyunCaptcha-window-embed",
            "#aliyunCaptcha-sliding-wrapper",
            "#aliyunCaptcha-sliding-text-box",
            ".aliyunCaptcha-sliding-text-box"
        ]
        for selector in selectors:
            try:
                locator = page.locator(selector).first
                if await locator.count() > 0 and await locator.is_visible():
                    return True
            except Exception:
                continue
        
        text_indicators = [
            'text="Access Verification"',
            'text="Please slide to verify"',
            'text="Please complete the operation to verify"'
        ]
        for selector in text_indicators:
            try:
                locator = page.locator(selector).first
                if await locator.count() > 0 and await locator.is_visible():
                    return True
            except Exception:
                continue
        return False

    async def _solve_access_verification_slider(self, page: Page, worker_id: int) -> bool:
        """Attempt to solve the Aliyun slider challenge by simulating a human drag."""
        # Wait for captcha to fully appear and stabilize (human-like behavior)
        self.logger.info("Waiting for captcha to fully appear", worker_id=worker_id)
        await page.wait_for_timeout(random.randint(800, 1500))  # Human-like wait after seeing captcha
        
        # Try multiple selectors for the slider button
        slider_selectors = [
            "#aliyunCaptcha-sliding-slider",
            ".aliyunCaptcha-sliding-slider",
            "div[class*='aliyunCaptcha-sliding-slider']",
            "div[id*='slider']",
            "div[class*='slider']:has-text('')",
            "span[class*='slider']",
            "button[class*='slider']"
        ]
        
        slider = None
        slider_box = None
        
        for selector in slider_selectors:
            try:
                locator = page.locator(selector).first
                if await locator.count() > 0 and await locator.is_visible():
                    slider = locator
                    slider_box = await locator.bounding_box()
                    self.logger.info(f"Found slider with selector: {selector}", worker_id=worker_id)
                    break
            except Exception:
                continue
        
        if not slider or not slider_box:
            self.logger.warning("Slider element not found", worker_id=worker_id)
            return False
        
        # Try multiple selectors for the slider track/body
        body_selectors = [
            "#aliyunCaptcha-sliding-body",
            ".aliyunCaptcha-sliding-body",
            "#aliyunCaptcha-sliding-wrapper",
            ".aliyunCaptcha-sliding-wrapper",
            "div[class*='aliyunCaptcha-sliding-body']",
            "div[class*='aliyunCaptcha-sliding-wrapper']"
        ]
        
        body_box = None
        for selector in body_selectors:
            try:
                locator = page.locator(selector).first
                if await locator.count() > 0:
                    body_box = await locator.bounding_box()
                    if body_box:
                        self.logger.info(f"Found slider body with selector: {selector}", worker_id=worker_id)
                        break
            except Exception:
                continue
        
        slider_center_x = slider_box["x"] + slider_box["width"] / 2
        slider_center_y = slider_box["y"] + slider_box["height"] / 2
        
        # Calculate drag distance - be more precise
        drag_distance = 220  # default
        if body_box:
            # Calculate exact distance needed - go to the very end
            drag_distance = body_box["width"] - slider_box["width"] - 4  # More precise, ensure we reach end
        
        # Ensure we drag far enough but not too far
        drag_distance = max(120, min(drag_distance, 340))
        
        # Add small random offset to make it more human-like but ensure we go far enough
        # Always ensure we go slightly past the end for reliability
        drag_distance = drag_distance + random.uniform(2, 8)  # Ensure we reach and slightly exceed end
        
        self.logger.info(
            "Attempting to solve Aliyun slider",
            worker_id=worker_id,
            drag_distance=drag_distance,
            slider_pos=f"({slider_center_x}, {slider_center_y})"
        )
        
        # Human-like slider drag with natural behavior
        try:
            # Scroll to make sure slider is visible
            await slider.scroll_into_view_if_needed()
            await page.wait_for_timeout(random.randint(150, 300))  # Optimized pause
            
            # Calculate end position - be very precise, go slightly past end for reliability
            if body_box:
                # Go to the very end of the track, slightly past for reliability
                end_x = body_box["x"] + body_box["width"] - slider_box["width"] / 2 - 1
                end_y = body_box["y"] + body_box["height"] / 2
            else:
                # Add extra distance to ensure we reach the end
                end_x = slider_center_x + drag_distance + 3
                end_y = slider_center_y
            
            # Ensure we go all the way to the end
            actual_drag_distance = end_x - slider_center_x
            
            # Human-like behavior: hover first, then move to position with realistic mouse movement
            await slider.hover()
            await page.wait_for_timeout(random.randint(100, 200))  # Optimized pause
            
            # Move mouse to slider position with realistic curved path (humans don't move in straight lines)
            # Create intermediate point for more natural movement
            start_x = slider_center_x - random.randint(50, 100)
            start_y = slider_center_y - random.randint(20, 40)
            mid_x = slider_center_x - random.randint(20, 40)
            mid_y = slider_center_y - random.randint(5, 15)
            
            # Move through intermediate points (more human-like, optimized)
            await page.mouse.move(start_x, start_y, steps=random.randint(2, 4))
            await page.wait_for_timeout(random.randint(15, 30))
            await page.mouse.move(mid_x, mid_y, steps=random.randint(2, 4))
            await page.wait_for_timeout(random.randint(15, 30))
            await page.mouse.move(slider_center_x, slider_center_y, steps=random.randint(2, 4))
            await page.wait_for_timeout(random.randint(80, 150))  # Pause before clicking
            
            # Press mouse down
            await page.mouse.down()
            await page.wait_for_timeout(random.randint(30, 80))  # Small pause after click
            
            # Human-like drag: optimized for reliability and speed
            # More steps for better precision and smoother movement
            steps = max(25, min(35, int(actual_drag_distance // 4)))  # More steps for precision
            for step in range(steps):
                progress = (step + 1) / steps
                # More natural human curve: slow start, accelerate, maintain speed, slow end
                # Optimized for better success rate
                if progress < 0.12:
                    # Very slow start (human hesitation)
                    eased = progress * progress * 4.0
                elif progress < 0.35:
                    # Accelerating
                    eased = 0.0576 + (progress - 0.12) * 1.7
                elif progress < 0.75:
                    # Maintaining speed (longer phase for reliability)
                    eased = 0.4486 + (progress - 0.35) * 1.35
                else:
                    # Slowing down at end but ensure we reach 1.0
                    remaining = 1.0 - 0.7861
                    eased = 0.7861 + (progress - 0.75) * remaining * 4.5
                
                # Ensure we always reach the end (critical for success)
                if step == steps - 1:
                    eased = 1.0
                elif step >= steps - 3:
                    # In last 3 steps, ensure we're making progress to the end
                    eased = max(eased, 0.95 + (step - steps + 3) * 0.0167)
                
                current_x = slider_center_x + (end_x - slider_center_x) * eased
                # Natural vertical jitter (humans don't move perfectly straight)
                jitter_y = slider_center_y + random.uniform(-1.0, 1.0)
                # Use steps for smoother movement (more realistic)
                await page.mouse.move(current_x, jitter_y, steps=random.randint(2, 4))
                
                # Human-like delays: slower at start and end, faster in middle (optimized)
                if step < steps * 0.15:
                    delay = random.randint(10, 18)  # Slow start (hesitation)
                elif step < steps * 0.8:
                    delay = random.randint(6, 12)  # Medium speed (faster)
                else:
                    delay = random.randint(8, 15)  # Slowing down at end
                await page.wait_for_timeout(delay)
            
            # Small pause before releasing
            await page.wait_for_timeout(random.randint(50, 150))
            await page.mouse.up()
            
            # Wait for captcha to process (optimized)
            await page.wait_for_timeout(random.randint(400, 700))  # Wait for verification
            
            # Check if captcha failed and needs refresh
            if await self._is_captcha_failed(page):
                self.logger.warning("Captcha verification failed, clicking refresh", worker_id=worker_id)
                if await self._click_captcha_refresh(page, worker_id):
                    # Wait for captcha to reset
                    await page.wait_for_timeout(random.randint(1000, 1500))
                    # Return False to trigger retry
                    return False
            
            # Check if captcha is gone
            if not await self._is_access_verification_visible(page):
                self.logger.info("Slider solved successfully", worker_id=worker_id)
                return True
        except Exception as drag_error:
            self.logger.warning("Failed to drag slider", worker_id=worker_id, error=str(drag_error))
            try:
                await page.mouse.up()
            except Exception:
                pass
            return False
        
        # Wait for verification to disappear (longer wait for reliability)
        await page.wait_for_timeout(1500)
        
        # Check again if captcha failed
        if await self._is_captcha_failed(page):
            self.logger.warning("Captcha verification failed after drag, clicking refresh", worker_id=worker_id)
            if await self._click_captcha_refresh(page, worker_id):
                await page.wait_for_timeout(random.randint(1000, 1500))
                return False
        
        # Multiple checks for success (more reliable)
        success_checks = 0
        for check_attempt in range(3):
            await page.wait_for_timeout(500)
            still_visible = await self._is_access_verification_visible(page)
            if not still_visible:
                success_checks += 1
                if success_checks >= 2:  # Need 2 consecutive successful checks
                    self.logger.info("Captcha solved (confirmed multiple times)", worker_id=worker_id)
                    return True
            else:
                success_checks = 0  # Reset if visible again
        
        # Final check with selector
        try:
            await page.wait_for_selector(
                "#WAF_NC_WRAPPER, div.waf-nc-wrapper, #nocaptcha, #aliyunCaptcha-window-embed, #aliyunCaptcha-sliding-wrapper, #aliyunCaptcha-sliding-text-box",
                state="hidden",
                timeout=2000
            )
            self.logger.info("Captcha disappeared after slider solve (selector check)", worker_id=worker_id)
            return True
        except PlaywrightTimeout:
            still_visible = await self._is_access_verification_visible(page)
            if not still_visible:
                self.logger.info("Captcha solved (final check)", worker_id=worker_id)
                return True
            self.logger.warning("Captcha still visible after slider solve", worker_id=worker_id)
            return False
        except Exception as e:
            still_visible = await self._is_access_verification_visible(page)
            if not still_visible:
                self.logger.info("Captcha solved (exception check)", worker_id=worker_id)
                return True
            self.logger.warning(f"Error checking captcha: {e}", worker_id=worker_id)
            return False

    async def _handle_access_verification(
        self,
        page: Page,
        worker_id: int,
        stage: str = "general",
        suppress_exceptions: bool = False,
        wait_for_manual: bool = True
    ) -> bool:
        """
        Detect and wait for manual resolution of Aliyun access verification slider.
        
        If wait_for_manual is True, waits for user to manually solve the captcha.
        Otherwise attempts automated solution.
        
        Returns True if the challenge was present and solved, False if not present.
        """
        try:
            if not await self._is_access_verification_visible(page):
                return False
            
            if wait_for_manual:
                # Wait a bit to see if captcha appears on other browsers too
                await page.wait_for_timeout(3000)
                
                # Send notification
                try:
                    from src.services.notifications import get_notification_service
                    notification_service = get_notification_service()
                    notification_service.notify(
                        title="🔐 Капча виявлена",
                        msg=f"Браузер {worker_id}: Будь ласка, пройдіть капчу вручну. Система чекає...",
                        duration=30
                    )
                except Exception as e:
                    self.logger.warning(f"Failed to send notification: {e}")
                
                self.logger.warning(
                    "Access verification detected, waiting for manual solution",
                    worker_id=worker_id,
                    stage=stage
                )
                
                # Wait for captcha to be solved manually (check every 2 seconds)
                max_wait_time = 300  # 5 minutes max wait
                waited = 0
                check_interval = 2000  # Check every 2 seconds
                auto_attempt_after = 60  # seconds before we try to auto-solve even in manual mode
                auto_attempts = 0
                auto_attempt_limit = 2
                
                while waited < max_wait_time:
                    await page.wait_for_timeout(check_interval)
                    waited += check_interval / 1000
                    
                    # Check if captcha is still visible
                    if not await self._is_access_verification_visible(page):
                        self.logger.info(
                            "Captcha solved manually",
                            worker_id=worker_id,
                            stage=stage,
                            waited_seconds=waited
                        )
                        # Send success notification
                        try:
                            from src.services.notifications import get_notification_service
                            notification_service = get_notification_service()
                            notification_service.notify(
                                title="✅ Капча пройдена",
                                msg=f"Браузер {worker_id}: Капча успішно пройдена!",
                                duration=5
                            )
                        except Exception:
                            pass
                        return True

                    # Auto-attempt slider solve if user hasn't interacted for a while
                    auto_trigger = auto_attempt_after * (auto_attempts + 1)
                    if (
                        waited >= auto_trigger
                        and auto_attempts < auto_attempt_limit
                        and await self._is_access_verification_visible(page)
                    ):
                        auto_attempts += 1
                        self.logger.info(
                            "Auto-attempting captcha solve while waiting for manual action",
                            worker_id=worker_id,
                            stage=stage,
                            attempt=auto_attempts,
                            waited_seconds=waited
                        )
                        try:
                            # Refresh if fail text is visible
                            if await self._is_captcha_failed(page):
                                await self._click_captcha_refresh(page, worker_id)
                                await page.wait_for_timeout(random.randint(1200, 1800))
                            solved = await self._solve_access_verification_slider(page, worker_id)
                            await page.wait_for_timeout(random.randint(300, 600))
                            if solved and not await self._is_access_verification_visible(page):
                                self.logger.info(
                                    "Captcha cleared by auto-attempt during manual wait",
                                    worker_id=worker_id,
                                    stage=stage,
                                    attempt=auto_attempts
                                )
                                return True
                        except Exception as auto_err:
                            self.logger.debug(
                                "Auto-attempt during manual wait failed",
                                worker_id=worker_id,
                                stage=stage,
                                attempt=auto_attempts,
                                error=str(auto_err)
                            )
                    
                    # Log progress every 30 seconds
                    if int(waited) % 30 == 0 and waited > 0:
                        self.logger.info(
                            f"Still waiting for manual captcha solution (waited {int(waited)}s)",
                            worker_id=worker_id,
                            stage=stage
                        )
                
                # Timeout - captcha not solved
                self.logger.error(
                    "Timeout waiting for manual captcha solution",
                    worker_id=worker_id,
                    stage=stage,
                    waited_seconds=waited
                )
                return False
            
            # Automated solution (old behavior)
            self.logger.warning(
                "Access verification detected, attempting automated slider solution",
                worker_id=worker_id,
                stage=stage
            )
            
            max_attempts = 7  # Increased attempts for better reliability
            for attempt in range(max_attempts):
                # Check if captcha failed and needs refresh before retry
                if attempt > 0:
                    if await self._is_captcha_failed(page):
                        self.logger.warning(
                            "Captcha failed detected before retry, clicking refresh",
                            worker_id=worker_id,
                            stage=stage,
                            attempt=attempt + 1
                        )
                        if await self._click_captcha_refresh(page, worker_id):
                            await page.wait_for_timeout(random.randint(1500, 2500))  # Wait for reset
                    else:
                        # Normal wait between attempts
                        wait_time = random.randint(1000, 2000)  # Human-like pause between attempts
                        self.logger.info(
                            f"Waiting {wait_time}ms before retry attempt {attempt + 1}",
                            worker_id=worker_id,
                            stage=stage
                        )
                        await page.wait_for_timeout(wait_time)
                
                solved = await self._solve_access_verification_slider(page, worker_id)
                
                # Wait a bit for captcha to disappear if solved
                await page.wait_for_timeout(random.randint(300, 600))
                
                # Check if captcha failed after attempt
                if await self._is_captcha_failed(page):
                    self.logger.warning(
                        "Captcha verification failed after attempt, will refresh on next retry",
                        worker_id=worker_id,
                        stage=stage,
                        attempt=attempt + 1
                    )
                    # Continue to next attempt, refresh will be clicked at start of next iteration
                    continue
                
                still_visible = await self._is_access_verification_visible(page)
                
                if solved and not still_visible:
                    self.logger.info(
                        "Access verification solved",
                        worker_id=worker_id,
                        stage=stage,
                        attempt=attempt + 1
                    )
                    return True
                
                # If captcha is still visible, log and retry
                if still_visible:
                    self.logger.warning(
                        "Slider solve attempt failed, captcha still visible, retrying",
                        worker_id=worker_id,
                        stage=stage,
                        attempt=attempt + 1,
                        max_attempts=max_attempts
                    )
                else:
                    # Captcha disappeared but solve returned False - might be a false negative
                    self.logger.info(
                        "Captcha disappeared, considering solved",
                        worker_id=worker_id,
                        stage=stage,
                        attempt=attempt + 1
                    )
                    return True
            
            # If we reach this point, verification is still active
            screenshot_path = Path(self.config.outputs_dir) / "qwen" / f"access_verification_W{worker_id}_{int(time.time())}.png"
            try:
                screenshot_path.parent.mkdir(parents=True, exist_ok=True)
                await page.screenshot(path=str(screenshot_path), full_page=True)
                self.logger.error(
                    "Access verification could not be solved automatically",
                    worker_id=worker_id,
                    stage=stage,
                    screenshot=str(screenshot_path)
                )
            except Exception:
                pass
            
            raise RuntimeError("Unable to clear Access Verification slider. Manual intervention required.")
        except Exception as err:
            if suppress_exceptions:
                self.logger.warning(
                    "Access verification handler suppressed exception",
                    worker_id=worker_id,
                    stage=stage,
                    error=str(err)
                )
                return False
            raise

    async def _open_upload_popover(self, page: Page, worker_id: int) -> None:
        """Open the upload popover/menu (тільки клік на плюс, без кліку на Upload Image)."""
        self.logger.info("Clicking upload icon to open menu", worker_id=worker_id)
        
        # Клік на кнопку з плюсом (точний селектор з HTML)
        upload_icon = page.locator('span.anticon.chat-prompt-upload-group-btn-icon').first
        icon_count = await upload_icon.count()
        self.logger.info(f"Upload icon (span.anticon.chat-prompt-upload-group-btn-icon) found: {icon_count > 0} (worker {worker_id})")
        
        if icon_count == 0:
            # Fallback до батьківського елемента, якщо span не знайдено
            upload_icon = page.locator('.chat-prompt-upload-group-btn-icon').first
            icon_count = await upload_icon.count()
            self.logger.info(f"Upload icon (.chat-prompt-upload-group-btn-icon) found: {icon_count > 0} (worker {worker_id})")
        
        icon_clicked = False
        if icon_count > 0:
            try:
                is_visible = await upload_icon.is_visible()
                self.logger.info(f"Upload icon visible: {is_visible} (worker {worker_id})")
                if is_visible:
                    await upload_icon.scroll_into_view_if_needed()
                    await upload_icon.click()
                    await page.wait_for_timeout(700)
                    self.logger.info("Upload icon clicked, menu should be open now", worker_id=worker_id)
                    icon_clicked = True
            except Exception as e:
                self.logger.warning(f"Failed to click upload icon: {e} (worker {worker_id})")
        
        if not icon_clicked:
            self.logger.warning("Upload icon not found or not clickable, trying fallback selectors", worker_id=worker_id)
            # Fallback до старих селекторів
            upload_icon_selectors = [
                'i.chat-prompt-upload-group-btn-upload',
                'i.icon-line-plus-03',
                'i[class*="upload"][class*="btn"]',
                'button:has(i.icon-line-plus-03)'
            ]
            for selector in upload_icon_selectors:
                icon = page.locator(selector).first
                if await icon.count() > 0 and await icon.is_visible():
                    self.logger.info(f"Found fallback icon with selector: {selector} (worker {worker_id})")
                    await icon.click()
                    await page.wait_for_timeout(700)
                    icon_clicked = True
                    break
        
        if not icon_clicked:
            self.logger.error(f"Could not find or click upload icon (worker {worker_id})")
            raise Exception("Upload icon not found or not clickable")
        
        # Перевіряємо, чи меню відкрилося
        await page.wait_for_timeout(500)
        upload_menu = page.locator('div.qwen-upload-group-menu-item').first
        menu_visible = await upload_menu.count() > 0 and await upload_menu.is_visible()
        self.logger.info(f"Upload menu visible: {menu_visible} (worker {worker_id})")

    async def _dismiss_upload_overlay(self, page: Page, worker_id: int) -> None:
        """Close any lingering upload popover/dialog so it does not block the UI."""
        overlay_selectors = [
            'div[data-state="open"][role="dialog"]',
            'div[role="dialog"]',
            'div[class*="upload"][class*="popover"]',
            'div[class*="upload"][class*="modal"]'
        ]
        close_selectors = [
            'button:has(i.icon-line-close)',
            'button[aria-label="Close"]',
            'button:has-text("Close")',
            'button:has-text("Cancel")'
        ]
        
        for _ in range(4):
            overlay = None
            for overlay_selector in overlay_selectors:
                candidate = page.locator(overlay_selector).first
                if await candidate.count() > 0 and await candidate.is_visible():
                    overlay = candidate
                    break
            if overlay is None:
                return
            
            closed = False
            for close_selector in close_selectors:
                btn = overlay.locator(close_selector).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click()
                    await page.wait_for_timeout(400)
                    closed = True
                    break
            
            if closed:
                continue
            
            # Fallbacks: press Escape and click outside to dismiss menu
            try:
                await page.keyboard.press("Escape")
            except Exception:
                pass
            await page.wait_for_timeout(200)
            try:
                await page.mouse.click(5, 5)
            except Exception:
                pass
            await page.wait_for_timeout(200)

        self.logger.debug("Upload overlay still detected after dismiss attempts", worker_id=worker_id)

    async def _nudge_viewport(self, page: Page) -> None:
        """Lightly adjust viewport to dismiss overlays or bring elements into view."""
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass
        try:
            await page.mouse.move(5, 5)
        except Exception:
            pass
        try:
            await page.mouse.wheel(0, -600)
        except Exception:
            pass
        try:
            await page.evaluate("window.scrollBy(0, -200)")
        except Exception:
            pass
        await page.wait_for_timeout(300)

    async def _safe_click(self, page: Page, locator, worker_id: int, description: str, retries: int = 3):
        """Click a locator with retries and viewport nudges."""
        last_error = None
        for attempt in range(retries):
            try:
                await locator.scroll_into_view_if_needed()
            except Exception:
                pass
            
            # If this is video generation button, try to close any overlays first
            if "Video Generation" in description and attempt == 0:
                try:
                    # Try to close video recommendation modal
                    await page.keyboard.press("Escape")
                    await page.wait_for_timeout(500)
                except Exception:
                    pass
            
            try:
                await locator.click(timeout=8000)
                return
            except Exception as e:
                last_error = e
                error_str = str(e)
                await self._handle_access_verification(
                    page,
                    worker_id,
                    stage=f"click:{description}",
                    suppress_exceptions=True
                )
                
                # If element is intercepted by another element, try JavaScript click
                if "intercepts pointer events" in error_str:
                    try:
                        self.logger.info(
                            f"Element intercepted, trying JavaScript click",
                            worker_id=worker_id,
                            description=description,
                            attempt=attempt + 1
                        )
                        await locator.evaluate("element => element.click()")
                        return
                    except Exception as js_error:
                        self.logger.warning(
                            "JavaScript click also failed",
                            worker_id=worker_id,
                            description=description,
                            error=str(js_error)
                        )
                
                self.logger.warning(
                    "Click failed, retrying",
                    worker_id=worker_id,
                    description=description,
                    attempt=attempt + 1,
                    error=error_str[:200]
                )
                await self._nudge_viewport(page)
        raise last_error if last_error else RuntimeError(f"Unable to click {description}")

    async def _count_upload_previews(self, page: Page) -> int:
        """Count current upload previews/attachments near the composer."""
        cards_locator = page.locator(
            'div[class*="chat-prompt-upload"], '
            'div[class*="chat-attachment"], '
            'div[class*="chat-image-card"], '
            'div[class*="upload-card"], '
            'div[data-role="attachment"]'
        )
        try:
            return await cards_locator.count()
        except Exception:
            return 0

    async def _upload_image_without_modal(self, page: Page, sanitized_path: Path, worker_id: int) -> None:
        """Upload image via filechooser - правильний спосіб для Qwen."""
        self.logger.info("Uploading image via filechooser", worker_id=worker_id, image_path=str(sanitized_path))
        self.logger.info(f"File exists: {sanitized_path.exists()}, is_file: {sanitized_path.is_file() if sanitized_path.exists() else False}")
        
        if not sanitized_path.exists():
            raise Exception(f"Image file does not exist: {sanitized_path.absolute()}")
        
        existing_previews = await self._count_upload_previews(page)
        self.logger.info(f"Existing upload previews: {existing_previews} (worker {worker_id})")
        
        abs_path = str(sanitized_path.absolute())
        
        # ВИКОРИСТОВУЄМО FILECHOOSER - правильний спосіб для Qwen
        self.logger.info(f"Opening upload popover and waiting for filechooser (worker {worker_id})")
        
        # Відкриваємо меню завантаження
        await self._open_upload_popover(page, worker_id)
        
        # Чекаємо трохи, щоб меню відкрилося
        await page.wait_for_timeout(500)
        
        # Шукаємо кнопку "Upload Image" і клікаємо на неї з перехопленням filechooser
        self.logger.info(f"Clicking Upload Image and waiting for filechooser (worker {worker_id})")
        
        try:
            # Перехоплюємо filechooser ПЕРЕД кліком
            async with page.expect_file_chooser(timeout=10000) as fc_info:
                # Знаходимо і клікаємо на "Upload Image"
                upload_image_option = page.locator('div.qwen-upload-group-menu-item:has-text("Upload Image")').first
                
                if await upload_image_option.count() == 0:
                    # Fallback
                    upload_image_option = page.locator(
                        'button:has-text("Upload Image"), '
                        'div[role="menuitem"]:has-text("Upload Image"), '
                        'span:has-text("Upload Image")'
                    ).first
                
                if await upload_image_option.count() == 0:
                    raise Exception("Upload Image option not found")
                
                self.logger.info(f"Clicking Upload Image option (worker {worker_id})")
                await upload_image_option.click()
            
            # Отримуємо filechooser і встановлюємо файл
            file_chooser = await fc_info.value
            self.logger.info(f"File chooser opened, setting file: {abs_path} (worker {worker_id})")
            await file_chooser.set_files(abs_path)
            self.logger.info(f"File set via filechooser successfully (worker {worker_id})")
            
        except Exception as e:
            self.logger.error(f"Filechooser method failed: {e}, trying fallback (worker {worker_id})")
            # Fallback: спробуємо через set_input_files
            file_input = page.locator('input[type="file"]').first
            file_input_count = await file_input.count()
            
            if file_input_count == 0:
                # Шукаємо файловий інпут після кліку
                for attempt in range(10):
                    await page.wait_for_timeout(300)
                    file_input = page.locator('input[type="file"]').first
                    file_input_count = await file_input.count()
                    if file_input_count > 0:
                        break
                
                if file_input_count == 0:
                    raise Exception(f"File input not found after clicking Upload Image (worker {worker_id})")
            
            self.logger.info(f"Using fallback method: set_input_files (worker {worker_id})")
            await file_input.wait_for(state="attached", timeout=10000)
            await file_input.set_input_files(abs_path)
            self.logger.info(f"File set via set_input_files (worker {worker_id})")
        
        # Чекаємо, поки файл обробиться
        await page.wait_for_timeout(2000)
        await self._dismiss_upload_overlay(page, worker_id)
        
        # Діагностика: скріншот після завантаження
        try:
            screenshot_path = Path(self.config.outputs_dir) / "qwen" / f"after_upload_W{worker_id}_{int(time.time())}.png"
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(screenshot_path), full_page=False)
            self.logger.info(f"Screenshot after upload: {screenshot_path} (worker {worker_id})")
        except Exception as e:
            self.logger.warning(f"Failed to save screenshot: {e} (worker {worker_id})")
        
        await self._wait_for_image_upload_ready(
            page,
            worker_id,
            sanitized_path.name,
            existing_previews
        )
        try:
            self.logger.info(
                "Stabilizing uploaded image before prompting",
                worker_id=worker_id,
                delay_ms=self.IMAGE_STABILIZE_DELAY_MS
            )
            await page.wait_for_timeout(self.IMAGE_STABILIZE_DELAY_MS)
        except Exception:
            pass

    async def _wait_for_image_upload_ready(
        self,
        page: Page,
        worker_id: int,
        image_name: str,
        existing_previews: int,
        timeout: int = 45
    ) -> None:
        """Wait until Qwen confirms the uploaded image preview is ready."""
        self.logger.info("Waiting for image upload to finish", worker_id=worker_id, image=image_name)
        deadline = time.monotonic() + timeout
        check_count = 0

        def remaining_ms() -> int:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return 0
            return int(remaining * 1000)

        def build_specific_locator(name_fragment: str):
            fragment = name_fragment.replace('"', '\\"')
            selectors = [
                f'img.vision-item-image[alt*="{fragment}"]',
                f'img.vision-item-image',
                f'img[alt*="{fragment}"]',
                f'img[src*="{fragment}"]',
                f'div[data-filename*="{fragment}"] img',
                f'div:has-text("{fragment}") img'
            ]
            selector = ", ".join(selectors)
            return page.locator(selector).first

        async def element_ready(handle) -> bool:
            if handle is None:
                return False
            try:
                return await handle.evaluate(
                    """el => {
                        if (!el) return false;
                        if (el.tagName === 'IMG') {
                            return el.complete && el.naturalWidth > 0 && el.naturalHeight > 0;
                        }
                        if (el.tagName === 'VIDEO') {
                            return el.readyState >= 2;
                        }
                        if (el.tagName === 'CANVAS') {
                            return el.width > 0 && el.height > 0;
                        }
                        return false;
                    }"""
                )
            except Exception:
                return False

        # Strategy 0: перевірка наявності img.vision-item-image (найнадійніший індикатор)
        try:
            vision_img = page.locator('img.vision-item-image').first
            if await vision_img.count() > 0:
                await vision_img.wait_for(state="visible", timeout=remaining_ms())
                handle = await vision_img.element_handle()
                if await element_ready(handle):
                    self.logger.info(
                        "Image upload ready",
                        worker_id=worker_id,
                        image=image_name,
                        detection="vision-item-image"
                    )
                    return
        except PlaywrightTimeout:
            pass
        except Exception:
            pass
        
        # Strategy 1: wait for image element that matches filename
        name_variants = {image_name}
        stem = Path(image_name).stem
        if stem != image_name:
            name_variants.add(stem)

        for variant in list(name_variants):
            if remaining_ms() == 0:
                break
            locator = build_specific_locator(variant)
            try:
                await locator.wait_for(state="visible", timeout=remaining_ms())
                handle = await locator.element_handle()
                if await element_ready(handle):
                    self.logger.info(
                        "Image upload ready",
                        worker_id=worker_id,
                        image=image_name,
                        detection="filename"
                    )
                    return
            except PlaywrightTimeout:
                continue
            except Exception:
                continue

        # Strategy 2: fallback to counting preview cards and checking their readiness
        cards_locator = page.locator(
            'div[class*="chat-prompt-upload"], '
            'div[class*="chat-attachment"], '
            'div[class*="chat-image-card"], '
            'div[class*="upload-card"], '
            'div[data-role="attachment"], '
            'img.vision-item-image'
        )

        async def latest_preview_ready() -> bool:
            preview_count = await cards_locator.count()
            if preview_count <= existing_previews:
                return False

            latest_idx = preview_count - 1
            candidate = cards_locator.nth(latest_idx)
            try:
                if not await candidate.is_visible():
                    return False
            except Exception:
                return False

            media = candidate.locator('img, video, canvas').first
            media_handle = await media.element_handle()
            if not await element_ready(media_handle):
                return False

            # Ensure there is no spinner inside the same preview card
            try:
                spinner_inside = await candidate.evaluate(
                    """container => {
                        if (!container) return false;
                        return !!container.querySelector('[aria-busy="true"], [data-loading="true"], .spinner, .loading');
                    }"""
                )
                if spinner_inside:
                    return False
            except Exception:
                pass

            return True

        while time.monotonic() < deadline:
            check_count += 1
            try:
                # Діагностика: що зараз на сторінці
                if check_count % 10 == 0:  # Кожні 5 секунд (10 * 500ms)
                    try:
                        current_previews = await cards_locator.count()
                        self.logger.info(
                            f"Upload check {check_count}: current_previews={current_previews}, existing={existing_previews} (worker {worker_id})"
                        )
                        # Перевіряємо всі можливі елементи
                        all_imgs = await page.locator('img').count()
                        blob_imgs = await page.locator('img[src*="blob"], img[src*="data:"]').count()
                        self.logger.info(
                            f"Total images: {all_imgs}, blob/data images: {blob_imgs} (worker {worker_id})"
                        )
                    except Exception as e:
                        self.logger.debug(f"Diagnostic check failed: {e} (worker {worker_id})")
                
                if await latest_preview_ready():
                    self.logger.info(
                        "Image upload ready",
                        worker_id=worker_id,
                        image=image_name,
                        detection="fallback"
                    )
                    return
            except Exception:
                pass
            await page.wait_for_timeout(500)

        # Фінальна діагностика перед таймаутом
        try:
            final_previews = await cards_locator.count()
            final_imgs = await page.locator('img').count()
            final_blob_imgs = await page.locator('img[src*="blob"], img[src*="data:"]').count()
            
            # Зберігаємо скріншот при помилці
            screenshot_path = Path(self.config.outputs_dir) / "qwen" / f"error_upload_timeout_W{worker_id}_{int(time.time())}.png"
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(screenshot_path), full_page=True)
            
            self.logger.error(
                "Timed out waiting for image upload confirmation",
                worker_id=worker_id,
                image=image_name,
                timeout=timeout,
                final_previews=final_previews,
                existing_previews=existing_previews,
                total_images=final_imgs,
                blob_images=final_blob_imgs,
                screenshot=str(screenshot_path)
            )
        except Exception as e:
            self.logger.warning(f"Failed to collect final diagnostics: {e} (worker {worker_id})")
            self.logger.warning(
                "Timed out waiting for image upload confirmation",
                worker_id=worker_id,
                image=image_name,
                timeout=timeout
            )
    
    async def _generate_video_with_page(
        self,
        page: Page,
        image_path: Path,
        prompt: str,
        output_dir: Path,
        worker_id: int = 1
    ) -> Optional[Path]:
        """
        Generate video using an existing page (for browser pool usage).
        
        Args:
            page: Existing Playwright Page instance
            image_path: Path to image file
            prompt: Text prompt for video generation
            output_dir: Directory to save output
            worker_id: Worker identifier
            
        Returns:
            Path to downloaded video or None if failed
        """
        result = await self._prepare_and_start_generation(
            page,
            image_path,
            prompt,
            output_dir,
            worker_id,
            wait_for_completion=True
        )

        if result is None:
            return None

        sanitized_result_path, _ = result
        return sanitized_result_path

    async def _prepare_and_start_generation(
        self,
        page: Page,
        image_path: Path,
        prompt: str,
        output_dir: Path,
        worker_id: int,
        wait_for_completion: bool = False
    ) -> Optional[Path]:
        """Navigate to Qwen, enable video mode, upload assets, and optionally wait for completion."""
        sanitized_path = sanitize_path(image_path)
        if not sanitized_path.exists():
            self.logger.error("Image not found", path=str(sanitized_path))
            return None
        
        try:
            self.logger.info("Navigating to Qwen", worker_id=worker_id, image=sanitized_path.name)
            await page.goto(
                self.QWEN_URL,
                wait_until="domcontentloaded",
                timeout=60000
            )
            await page.wait_for_timeout(1000)
            await self._handle_access_verification(page, worker_id, stage="direct_navigation", suppress_exceptions=True)
            try:
                await page.evaluate("window.scrollTo(0, 0)")
            except Exception:
                pass
            
            try:
                await page.wait_for_selector('textarea#chat-input, textarea[placeholder*="Describe"]', timeout=20000)
            except PlaywrightTimeout:
                self.logger.warning("Chat input not found, continuing anyway", worker_id=worker_id)
            
            result_path, stage2_task = await self._execute_video_generation_steps(
                page,
                sanitized_path,
                prompt,
                output_dir,
                worker_id,
                wait_for_completion=wait_for_completion
            )
            
            return result_path, stage2_task
        
        except Exception as e:
            self.logger.error(
                "Video generation failed during preparation",
                error=str(e),
                worker_id=worker_id,
                exc_info=True
            )
            
            if page and not page.is_closed():
                try:
                    screenshot_path = output_dir / f"error_W{worker_id}_{sanitized_path.stem}_screenshot.png"
                    await page.screenshot(path=str(screenshot_path), full_page=True)
                    self.logger.info("Screenshot saved", path=str(screenshot_path), worker_id=worker_id)
                except Exception:
                    pass
            
            return None
    
    async def _execute_video_generation_steps(
        self,
        page: Page,
        sanitized_path: Path,
        prompt: str,
        output_dir: Path,
        worker_id: int,
        wait_for_completion: bool = True
    ) -> Optional[Path]:
        """Execute video generation steps on an already-navigated page."""
        # Step 1: Click Video Generation button
        self.logger.info("Waiting for Video Generation button to appear", worker_id=worker_id)
        
        # Wait for page to be fully interactive first
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except:
            await page.wait_for_load_state("domcontentloaded", timeout=10000)
        
        # Try multiple selectors for Video Generation button
        video_gen_button = None
        video_gen_selectors = [
            # DIV selectors (most common on Qwen)
            'div.chat-prompt-suggest-button:has(img.chat-prompt-suggest-button-img):has(div:has-text("Video Generation"))',
            'div.chat-prompt-suggest-button:has(div:has-text("Video Generation"))',
            'div.chat-prompt-suggest-button.normal:has(div:has-text("Video Generation"))',
            'div.chat-prompt-suggest-button:has-text("Video Generation")',
            'div.chat-prompt-suggest-button:has(img.chat-prompt-suggest-button-img)',
            'div[class*="chat-prompt-suggest-button"]:has(div:has-text("Video"))',
            'div[class*="chat-prompt-suggest-button"]:has-text("Video Generation")',
            # Primary selectors with div[data-spm-anchor-id]
            'div[data-spm-anchor-id*="a2ty"]:has-text("Video Generation")',
            'div[data-spm-anchor-id]:has-text("Video Generation")',
            # Button with img and text (fallback)
            'button.chat-prompt-suggest-button:has(img.chat-prompt-suggest-button-img):has(div:has-text("Video Generation"))',
            'button.chat-prompt-suggest-button:has(img.chat-prompt-suggest-button-img)',
            # Standard button selectors (fallback)
            'button.chat-prompt-suggest-button:has(div:has-text("Video Generation"))',
            'button.chat-prompt-suggest-button.normal:has(div:has-text("Video Generation"))',
            'button.chat-prompt-suggest-button:has-text("Video Generation")',
            'button[class*="chat-prompt-suggest-button"]:has(div:has-text("Video"))',
            'button:has-text("Video Generation")',
            'button[class*="suggest"]:has-text("Video Generation")',
            'div[class*="suggest"] button:has-text("Video Generation")',
            'button:has-text("Video")',
            'div[role="button"]:has-text("Video Generation")',
            'a:has-text("Video Generation")'
        ]
        
        # ПЕРЕВІРКА: Чи Video Generation вже активовано?
        # Якщо є span.prompt-input-input-func-type-text з "Video Generation" - режим вже активний!
        already_active_span = page.locator('span.prompt-input-input-func-type-text:has-text("Video Generation")').first
        if await already_active_span.count() > 0:
            try:
                is_visible = await already_active_span.is_visible()
                if is_visible:
                    self.logger.info("✅ Video Generation already active (detected by span text) - skipping button click", worker_id=worker_id)
                    # Перевіримо чи є aspect ratio
                    aspect_ratio_check = page.locator('div.chat-ratio-selector, div[class*="ratio"], span.anticon.selector-icon').first
                    if await aspect_ratio_check.count() > 0:
                        is_ratio_visible = await aspect_ratio_check.is_visible()
                        if is_ratio_visible:
                            self.logger.info("✅ Aspect ratio selector present - Video Generation fully active", worker_id=worker_id)
                            # Режим вже активний, пропускаємо клік на кнопку
                            video_gen_button = None  # Ніякої кнопки не треба
                            found_button = True  # Вважаємо що "знайшли" (режим активний)
            except Exception:
                pass
        
        if not found_button:
            # Wait for at least one button selector to appear (optimized for faster startup)
            video_button_wait_attempts = 10  # faster attempts with correct selectors
            video_button_retry_interval_ms = 1000  # 1 second between attempts
            max_refresh_attempts = 2  # Reload the page once if needed
            for refresh_attempt in range(max_refresh_attempts):
                for attempt in range(video_button_wait_attempts):
                    # Refresh page state check periodically
                    if attempt > 0 and attempt % 5 == 0:
                        try:
                            await page.wait_for_load_state("networkidle", timeout=5000)
                        except:
                            try:
                                await page.wait_for_load_state("domcontentloaded", timeout=3000)
                            except:
                                pass
                        # Scroll to top to ensure buttons are in view
                        try:
                            await page.evaluate("window.scrollTo(0, 0)")
                            await page.wait_for_timeout(500)
                        except:
                            pass
                    
                    for selector in video_gen_selectors:
                        try:
                            button_locator = page.locator(selector).first
                            count = await button_locator.count()
                            if count > 0:
                                # Wait for it to be visible and clickable
                                try:
                                    await button_locator.wait_for(state="visible", timeout=1500)
                                    # Additional check: ensure button is actually clickable
                                    is_visible = await button_locator.is_visible()
                                    if is_visible:
                                        # CRITICAL: Перевіряємо що це КНОПКА, а не span з текстом
                                        try:
                                            tag_name = await button_locator.evaluate("el => el.tagName.toLowerCase()")
                                            class_name = await button_locator.evaluate("el => el.className || ''")
                                            
                                            if tag_name == "span" and "prompt-input-input-func-type-text" in class_name:
                                                self.logger.info("Skipping span.prompt-input-input-func-type-text (already active text)", worker_id=worker_id)
                                                continue
                                        except Exception:
                                            pass
                                        
                                        # ALWAYS click the button - don't trust "already active" checks
                                        # They can be false positives
                                        video_gen_button = button_locator
                                        found_button = True
                                        self.logger.info(f"Found Video Generation button with selector: {selector} (attempt {attempt + 1}, refresh {refresh_attempt + 1})", worker_id=worker_id)
                                        break
                                except PlaywrightTimeout:
                                    continue
                        except Exception:
                            continue
                    
                    if found_button:
                        break
                    
                    # Wait before next attempt
                    if attempt < video_button_wait_attempts - 1:
                        await page.wait_for_timeout(video_button_retry_interval_ms)
                
                if found_button:
                    break
                
                if refresh_attempt < max_refresh_attempts - 1:
                    self.logger.warning("Video Generation button not found, refreshing page and retrying", worker_id=worker_id, refresh_attempt=refresh_attempt + 1)
                    try:
                        await page.reload(wait_until="domcontentloaded", timeout=60000)
                        await page.wait_for_timeout(2000)
                        try:
                            await page.evaluate("window.scrollTo(0, 0)")
                        except Exception:
                            pass
                    except Exception as reload_err:
                        self.logger.error("Failed to reload page while searching for Video Generation button", worker_id=worker_id, error=str(reload_err))
                        # Continue to next attempt without reload success
        
        if not found_button:
            # Take screenshot to debug
            try:
                debug_screenshot = output_dir / f"debug_W{worker_id}_no_video_button.png"
                await page.screenshot(path=str(debug_screenshot), full_page=True)
                self.logger.warning(f"Video Generation button not found, screenshot saved to {debug_screenshot}", worker_id=worker_id)
            except Exception:
                pass
            raise Exception("Video Generation button not found after trying all selectors")
        
        # Check if Video Generation is already active (video_gen_button is None means already active)
        click_success = False
        
        # ALWAYS click the button - NEVER skip clicking!
        # The "already active" check is unreliable and causes photos to upload without Video Generation mode
        if video_gen_button is not None:
            # Try clicking with retries and STRICT verification
            video_click_retry_attempts = 10  # faster attempts with correct selectors
            video_click_retry_interval_ms = 1500  # 1.5 seconds between attempts
            for click_attempt in range(video_click_retry_attempts):
                try:
                    self.logger.info(
                        f"Clicking Video Generation button (attempt {click_attempt + 1}/{video_click_retry_attempts})",
                        worker_id=worker_id
                    )
                    
                    # Scroll to top to ensure button is in view
                    try:
                        await page.evaluate("window.scrollTo(0, 0)")
                        await page.wait_for_timeout(300)
                    except Exception:
                        pass
                    
                    # Ensure button is still visible and clickable
                    try:
                        await video_gen_button.scroll_into_view_if_needed()
                        await page.wait_for_timeout(300)
                    except Exception:
                        pass
                    
                    await self._safe_click(page, video_gen_button, worker_id, f"Video Generation button (attempt {click_attempt + 1})")
                    
                    # Wait for UI to update and page to stabilize
                    await page.wait_for_timeout(2000)  # optimized wait time
                    
                    # Wait for page to be ready
                    try:
                        await page.wait_for_load_state("networkidle", timeout=5000)
                    except:
                        try:
                            await page.wait_for_load_state("domcontentloaded", timeout=3000)
                        except:
                            pass
                    
                    # Scroll to top again after click
                    try:
                        await page.evaluate("window.scrollTo(0, 0)")
                        await page.wait_for_timeout(500)
                    except Exception:
                        pass
                    
                    # STRICT verification: Check that aspect ratio selector exists AND has ratio text
                    verification_passed = False
                    
                    # Try multiple selectors for aspect ratio
                    aspect_ratio_selectors = [
                        'div.chat-ratio-selector',
                        'div[class*="ratio"]',
                        'div[class*="aspect"]',
                        'div[data-spm-anchor-id*="ratio"]',
                        'div:has-text("16:9")',
                        'div:has-text("9:16")'
                    ]
                    
                    for ratio_selector in aspect_ratio_selectors:
                        aspect_ratio_check = page.locator(ratio_selector).first
                        if await aspect_ratio_check.count() > 0:
                            is_visible = await aspect_ratio_check.is_visible()
                            if is_visible:
                                # CRITICAL: Verify it's actually the video mode selector by checking for ratio text
                                try:
                                    ratio_text = await aspect_ratio_check.text_content()
                                    if ratio_text and ('16:9' in ratio_text or '9:16' in ratio_text or '1:1' in ratio_text or (':' in ratio_text and any(c.isdigit() for c in ratio_text))):
                                        verification_passed = True
                                        self.logger.info(
                                            f"Video Generation mode verified: aspect ratio selector found with ratio text '{ratio_text.strip()[:100]}'",
                                            worker_id=worker_id
                                        )
                                        break
                                except:
                                    pass
                    
                    # If still not verified, try waiting a bit more and checking again
                    if not verification_passed:
                        await page.wait_for_timeout(1000)
                        # Try one more time with all selectors
                        for ratio_selector in aspect_ratio_selectors:
                            aspect_ratio_check = page.locator(ratio_selector).first
                            if await aspect_ratio_check.count() > 0:
                                is_visible = await aspect_ratio_check.is_visible()
                                if is_visible:
                                    try:
                                        ratio_text = await aspect_ratio_check.text_content()
                                        if ratio_text and ('16:9' in ratio_text or '9:16' in ratio_text or '1:1' in ratio_text or (':' in ratio_text and any(c.isdigit() for c in ratio_text))):
                                            verification_passed = True
                                            self.logger.info(
                                                f"Video Generation mode verified (delayed): aspect ratio selector found with ratio text '{ratio_text.strip()[:100]}'",
                                                worker_id=worker_id
                                            )
                                            break
                                    except:
                                        pass
                    
                    if verification_passed:
                        click_success = True
                        self.logger.info("Video Generation button successfully clicked and verified", worker_id=worker_id)
                        break
                    else:
                        self.logger.warning(
                            f"Video Generation click attempt {click_attempt + 1}/{video_click_retry_attempts} - verification failed (no ratio text), retrying",
                            worker_id=worker_id
                        )
                        # Try to find button again in case it changed
                        if click_attempt < video_click_retry_attempts - 1:
                            try:
                                video_gen_button = page.locator('div.chat-prompt-suggest-button:has(div:has-text("Video Generation"))').first
                                if await video_gen_button.count() == 0:
                                    video_gen_button = page.locator('button.chat-prompt-suggest-button:has(div:has-text("Video Generation"))').first
                                if await video_gen_button.count() == 0:
                                    video_gen_button = page.locator('div[data-spm-anchor-id*="a2ty"]:has-text("Video Generation")').first
                            except:
                                pass
                            await page.wait_for_timeout(video_click_retry_interval_ms)
                except Exception as click_err:
                    self.logger.warning(
                        f"Click attempt {click_attempt + 1}/{video_click_retry_attempts} failed, retrying",
                        worker_id=worker_id,
                        error=str(click_err)
                    )
                    if click_attempt < video_click_retry_attempts - 1:
                        await page.wait_for_timeout(video_click_retry_interval_ms)
            
            if not click_success:
                # Take screenshot for debugging
                try:
                    debug_screenshot = output_dir / f"debug_W{worker_id}_video_gen_click_failed.png"
                    await page.screenshot(path=str(debug_screenshot), full_page=True)
                    self.logger.error(f"Video Generation button click failed after all attempts, screenshot: {debug_screenshot}", worker_id=worker_id)
                except:
                    pass
                raise Exception("Failed to activate Video Generation mode after multiple attempts")
        else:
            # video_gen_button is None - means Video Generation already active, no need to click
            self.logger.info("Video Generation already active (button not needed), proceeding...", worker_id=worker_id)
            click_success = True  # Consider it a success since mode is already active
        
        # Final wait to ensure UI is stable
        await page.wait_for_timeout(2000)
        
        # CRITICAL: Final verification before proceeding to aspect ratio selection
        # Verify Video Generation mode is ACTUALLY active (with ratio text)
        self.logger.info("Final verification: Video Generation mode must be active before proceeding", worker_id=worker_id)
        aspect_ratio_final_check = page.locator('div.chat-ratio-selector, div[class*="ratio"]').first
        if await aspect_ratio_final_check.count() == 0 or not await aspect_ratio_final_check.is_visible():
            # Take screenshot and raise error
            try:
                debug_screenshot = output_dir / f"debug_W{worker_id}_final_check_failed.png"
                await page.screenshot(path=str(debug_screenshot), full_page=True)
                self.logger.error(f"FINAL CHECK FAILED: Video Generation mode not active! Screenshot: {debug_screenshot}", worker_id=worker_id)
            except:
                pass
            raise Exception("Video Generation mode is NOT active - cannot proceed. Aspect ratio selector missing.")
        
        # Verify aspect ratio selector has ratio text
        try:
            ratio_text = await aspect_ratio_final_check.text_content()
            if not ratio_text or ':' not in ratio_text:
                self.logger.warning(f"Aspect ratio selector found but no ratio text (text: '{ratio_text}')", worker_id=worker_id)
                # This is suspicious - take screenshot
                try:
                    debug_screenshot = output_dir / f"debug_W{worker_id}_no_ratio_text.png"
                    await page.screenshot(path=str(debug_screenshot), full_page=True)
                    self.logger.error(f"No ratio text in aspect ratio selector! Screenshot: {debug_screenshot}", worker_id=worker_id)
                except:
                    pass
        except:
            pass
        
        stage2_task: Optional[asyncio.Task] = None
        if wait_for_completion:
            await self._complete_generation_after_ratio(page, sanitized_path, prompt, output_dir, worker_id)
            downloaded_path = await self._wait_and_download_video(page, output_dir, worker_id, sanitized_path)
            return downloaded_path, None

        stage2_task = asyncio.create_task(
            self._complete_generation_after_ratio(page, sanitized_path, prompt, output_dir, worker_id)
        )

        # When skipping wait, return sanitized path and keep the background task for later
        return sanitized_path, stage2_task
    
    async def _ensure_9_16_selected(self, page: Page, worker_id: int):
        """Ensure 9:16 aspect ratio is selected. If not, select it."""
        try:
            # Перевіряємо чи вже вибрано 9:16
            ratio_text_selectors = [
                'div.selector-text',
                'div[class*="selector-text"]',
                'div.chat-ratio-selector',
                'div[class*="ratio"]'
            ]
            
            for selector in ratio_text_selectors:
                ratio_check = page.locator(selector).first
                if await ratio_check.count() > 0:
                    is_visible = await ratio_check.is_visible()
                    if is_visible:
                        try:
                            text_content = await ratio_check.text_content()
                            if text_content and '9:16' in text_content:
                                self.logger.info(f"✅ 9:16 already selected (worker {worker_id})")
                                return  # Вже вибрано 9:16
                        except:
                            pass
            
            # Якщо не знайдено 9:16, вибираємо його
            self.logger.info(f"Selecting 9:16 aspect ratio (worker {worker_id})")
            
            # Знаходимо aspect ratio selector
            ratio_selector_options = [
                'div.chat-ratio-selector',
                'span.anticon.selector-icon',
                'div[class*="ratio"] .anticon',
                'div.selector-text',
                'div[class*="selector-text"]'
            ]
            
            ratio_selector = None
            for selector_option in ratio_selector_options:
                temp_selector = page.locator(selector_option).first
                if await temp_selector.count() > 0:
                    try:
                        is_visible = await temp_selector.is_visible()
                        if is_visible:
                            ratio_selector = temp_selector
                            break
                    except:
                        continue
            
            if ratio_selector is not None:
                await self._safe_click(page, ratio_selector, worker_id, "aspect ratio selector")
                await page.wait_for_timeout(1000)
                
                # Вибираємо 9:16 з dropdown
                nine_sixteen_found = False
                nine_sixteen_selectors = [
                    'div[role="menuitem"]:has-text("9:16")',
                    'div[data-melt-menu-item]:has-text("9:16")',
                    'div:has-text("9:16")[class*="menu"]'
                ]
                
                for selector in nine_sixteen_selectors:
                    option = page.locator(selector).first
                    if await option.count() > 0:
                        is_visible = await option.is_visible()
                        if is_visible:
                            await self._safe_click(page, option, worker_id, "aspect ratio option 9:16")
                            nine_sixteen_found = True
                            self.logger.info(f"✅ Selected 9:16 aspect ratio (worker {worker_id})")
                            await page.wait_for_timeout(1000)
                            break
                
                if not nine_sixteen_found:
                    # Try to find by searching all menu items
                    all_menu_items = page.locator('[role="menuitem"], div[data-melt-menu-item]')
                    count = await all_menu_items.count()
                    for i in range(count):
                        item = all_menu_items.nth(i)
                        text = await item.text_content()
                        if text and '9:16' in text:
                            await self._safe_click(page, item, worker_id, "aspect ratio option 9:16")
                            nine_sixteen_found = True
                            self.logger.info(f"✅ Selected 9:16 via text search (worker {worker_id})")
                            await page.wait_for_timeout(1000)
                            break
                
                if not nine_sixteen_found:
                    self.logger.warning(f"9:16 option not found, continuing anyway (worker {worker_id})")
            else:
                self.logger.warning(f"Aspect ratio selector not found, cannot select 9:16 (worker {worker_id})")
        except Exception as e:
            self.logger.warning(f"Failed to ensure 9:16 is selected (worker {worker_id})", error=str(e))
    
    async def _select_aspect_ratio_and_upload(self, page: Page, sanitized_path: Path, worker_id: int):
        """Select aspect ratio and upload image."""
        # CRITICAL: Verify Video Generation mode is active BEFORE uploading image
        # This prevents uploading photo without Video Generation mode
        self.logger.info("Verifying Video Generation mode is active before uploading image", worker_id=worker_id)
        
        # Використовуємо правильний селектор для перевірки тексту ratio
        ratio_text_selectors = [
            'div.selector-text',
            'div[class*="selector-text"]',
            'div.chat-ratio-selector',
            'div[class*="ratio"]'
        ]
        
        aspect_ratio_found = False
        ratio_text = None
        
        for selector in ratio_text_selectors:
            aspect_ratio_check = page.locator(selector).first
            if await aspect_ratio_check.count() > 0:
                is_visible = await aspect_ratio_check.is_visible()
                if is_visible:
                    try:
                        ratio_text = await aspect_ratio_check.text_content()
                        if ratio_text and (':' in ratio_text or '16:9' in ratio_text or '9:16' in ratio_text or '1:1' in ratio_text):
                            aspect_ratio_found = True
                            self.logger.info(f"Found aspect ratio text: '{ratio_text.strip()[:50]}' with selector {selector} (worker {worker_id})")
                            break
                    except:
                        continue
        
        if not aspect_ratio_found:
            # Take screenshot and raise error
            try:
                debug_screenshot = sanitized_path.parent / f"debug_W{worker_id}_no_ratio_before_upload.png"
                await page.screenshot(path=str(debug_screenshot), full_page=True)
                self.logger.error(f"CRITICAL: Video Generation mode NOT active before upload! Screenshot: {debug_screenshot}", worker_id=worker_id)
            except:
                pass
            raise Exception("Video Generation mode is NOT active - cannot upload image. Aspect ratio selector missing.")
        
        # Check if 9:16 is already selected
        if ratio_text and '9:16' in ratio_text:
            # 9:16 already selected, skip selection and proceed to upload
            self.logger.info(f"✅ 9:16 already selected, skipping aspect ratio selection (worker {worker_id})")
            # Wait a bit longer to ensure page is ready for upload
            await page.wait_for_timeout(1000)
            # Proceed directly to image upload
            self.logger.info(f"Uploading image (9:16 already selected) (worker {worker_id})")
            try:
                await self._upload_image_without_modal(page, sanitized_path, worker_id)
                self.logger.info(f"Image upload completed, returning from _select_aspect_ratio_and_upload (worker {worker_id})")
            except Exception as upload_err:
                self.logger.error(f"Failed to upload image (worker {worker_id})", error=str(upload_err), exc_info=True)
                raise
            return  # Return here is OK - we've done upload, rest is handled by _complete_generation_after_ratio
        
        # Step 2: Click aspect ratio selector (if 9:16 not already selected)
        self.logger.info("Selecting aspect ratio", worker_id=worker_id)
        
        # Try multiple selectors for the aspect ratio dropdown trigger
        ratio_selector_options = [
            'div.chat-ratio-selector:has-text("16:9")',  # Preferred: exact text match
            'div.chat-ratio-selector',  # Generic selector
            'div.chat-ratio-selector .anticon.selector-icon',  # Icon within ratio selector
            'span.anticon.selector-icon',  # Icon that opens dropdown
            'div[class*="ratio"] .anticon',  # Icon in ratio-related div
            'div.chat-ratio-selector svg',  # SVG icon within selector
        ]
        
        ratio_selector = None
        for selector_option in ratio_selector_options:
            temp_selector = page.locator(selector_option).first
            if await temp_selector.count() > 0:
                try:
                    is_visible = await temp_selector.is_visible()
                    if is_visible:
                        ratio_selector = temp_selector
                        self.logger.info(f"Found aspect ratio selector with: {selector_option}", worker_id=worker_id)
                        break
                except:
                    continue
        
        if ratio_selector is not None:
            await self._safe_click(page, ratio_selector, worker_id, "aspect ratio selector")
            await page.wait_for_timeout(1000)
        else:
            self.logger.warning("Aspect ratio selector not found, trying to continue", worker_id=worker_id)
        
        # Step 3: Select 9:16 from dropdown
        await page.wait_for_timeout(500)
        
        # Try multiple selectors for 9:16 option
        nine_sixteen_found = False
        nine_sixteen_selectors = [
            'div[role="menuitem"]:has-text("9:16")',
            'div[data-melt-menu-item]:has-text("9:16")',
            'div[data-melt-dropdown-menu-item]:has-text("9:16")',
            'div:has-text("9:16")[class*="menu"]'
        ]
        
        for selector in nine_sixteen_selectors:
            option = page.locator(selector).first
            if await option.count() > 0:
                is_visible = await option.is_visible()
                if is_visible:
                    await self._safe_click(page, option, worker_id, "aspect ratio option 9:16")
                    nine_sixteen_found = True
                    self.logger.info("Selected 9:16 aspect ratio", worker_id=worker_id)
                    break
        
        if not nine_sixteen_found:
            # Try to find by searching all menu items
            all_menu_items = page.locator('[role="menuitem"], div[data-melt-menu-item]')
            count = await all_menu_items.count()
            for i in range(count):
                item = all_menu_items.nth(i)
                text = await item.text_content()
                if text and '9:16' in text:
                    await self._safe_click(page, item, worker_id, "aspect ratio option 9:16")
                    nine_sixteen_found = True
                    self.logger.info("Selected 9:16 via text search", worker_id=worker_id)
                    break
        
        if not nine_sixteen_found:
            self.logger.warning("9:16 option not found, continuing", worker_id=worker_id)
        
        await page.wait_for_timeout(1000)
        
        # Step 4-6: Upload image without keeping modal open
        await self._upload_image_without_modal(page, sanitized_path, worker_id)

    async def _complete_generation_after_ratio(
        self,
        page: Page,
        sanitized_path: Path,
        prompt: str,
        output_dir: Path,
        worker_id: int
    ) -> None:
        """Upload, verify ratio, and send the prompt once Video Generation mode is active."""
        self.logger.info(f"Starting _complete_generation_after_ratio (worker {worker_id})")
        await self._select_aspect_ratio_and_upload(page, sanitized_path, worker_id)
        self.logger.info(f"_select_aspect_ratio_and_upload completed, continuing with prompt entry (worker {worker_id})")

        # Перевіряємо, чи фото завантажилося - це головний індикатор готовності
        self.logger.info("Checking if image is uploaded before entering prompt", worker_id=worker_id)
        image_uploaded = False
        
        # Перевіряємо наявність фото через різні селектори
        image_selectors = [
            'img.vision-item-image',
            'img[class*="vision"]',
            'div[class*="upload"] img',
            'div[class*="attachment"] img',
            'div[class*="image-card"] img'
        ]
        
        for selector in image_selectors:
            img = page.locator(selector).first
            if await img.count() > 0:
                is_visible = await img.is_visible()
                if is_visible:
                    self.logger.info(f"Image confirmed uploaded with selector: {selector} (worker {worker_id})")
                    image_uploaded = True
                    break
        
        if not image_uploaded:
            self.logger.warning(f"Image not found after upload, but proceeding anyway (worker {worker_id})")
        
        # Перевіряємо aspect ratio selector (не критично, якщо фото є)
        aspect_ratio_found = False
        aspect_ratio_final_check = page.locator('div.chat-ratio-selector, div[class*="ratio"], div.selector-text').first
        if await aspect_ratio_final_check.count() > 0 and await aspect_ratio_final_check.is_visible():
            aspect_ratio_found = True
            try:
                ratio_text = await aspect_ratio_final_check.text_content()
                self.logger.info(f"Aspect ratio selector found: '{ratio_text}' (worker {worker_id})")
            except:
                pass
        
        if not aspect_ratio_found:
            self.logger.warning(f"Aspect ratio selector not found, but continuing since image is uploaded (worker {worker_id})")
        
        # Якщо фото завантажилося, продовжуємо незалежно від aspect ratio selector
        if not image_uploaded and not aspect_ratio_found:
            try:
                debug_screenshot = output_dir / f"debug_W{worker_id}_final_check_failed.png"
                await page.screenshot(path=str(debug_screenshot), full_page=True)
                self.logger.error(f"FINAL CHECK FAILED: Neither image nor aspect ratio found! Screenshot: {debug_screenshot}", worker_id=worker_id)
            except:
                pass
            raise Exception("Video Generation mode is NOT active - cannot enter prompt. Image and aspect ratio selector missing.")

        # Step 7: Enter prompt
        self.logger.info("Entering prompt", worker_id=worker_id, prompt_length=len(prompt))
        
        # Чекаємо, поки textarea стане доступним (швидше)
        textarea = page.locator('textarea#chat-input, textarea[placeholder*="Describe"], textarea[placeholder*="describe"]').first
        await textarea.wait_for(state="visible", timeout=5000)  # Зменшено timeout
        
        # Очищаємо textarea перед введенням (швидко)
        try:
            await textarea.clear()
            await page.wait_for_timeout(50)  # Мінімальна затримка
        except Exception:
            pass
        
        # Вводимо промпт (швидко)
        await textarea.fill(prompt)
        await page.wait_for_timeout(100)  # Мінімальна затримка
        
        # Швидка перевірка промпта
        try:
            actual_value = await textarea.input_value()
            if actual_value != prompt:
                self.logger.warning(f"Prompt mismatch: expected {len(prompt)} chars, got {len(actual_value)} (worker {worker_id})")
                # Спробуємо через JavaScript
                await textarea.evaluate(f"(el) => {{ el.value = {repr(prompt)}; el.dispatchEvent(new Event('input', {{ bubbles: true }})); }}")
                await page.wait_for_timeout(50)
        except Exception as e:
            self.logger.warning(f"Failed to verify prompt: {e} (worker {worker_id})")
        
        await page.wait_for_timeout(200)  # Мінімальна затримка перед відправкою

        # Step 8: Click send button
        self.logger.info("Clicking send button", worker_id=worker_id)
        
        # Чекаємо, поки кнопка з'явиться (може зайняти час після введення тексту)
        send_button = None
        max_attempts = 20
        
        for attempt in range(max_attempts):
            # Шукаємо кнопку відправки через різні селектори
            send_button_selectors = [
                'button#send-message-button',
                'button._sendMessageButton_71e98_48',
                'button:has(i.icon-line-arrow-up)',
                'button:has(svg[class*="arrow"])',
                'button[aria-label*="send" i]',
                'button[aria-label*="Send" i]',
                'button:has-text("Send")',
                'button[type="submit"]',
                'button[class*="send"]',
                'button[class*="Send"]',
                'button:has(svg)',
                'div[class*="send"] button',
                'div[class*="Send"] button',
                # Спробуємо знайти через textarea та його батьківський контейнер
                'textarea[placeholder*="Describe"] ~ button',
                'textarea[placeholder*="describe"] ~ button',
                'textarea#chat-input ~ button',
                # Загальні селектори для кнопок біля textarea
                'div[class*="input"] button',
                'div[class*="chat-input"] button',
                'div[class*="prompt"] button'
            ]
            
            for selector in send_button_selectors:
                try:
                    btn = page.locator(selector).first
                    count = await btn.count()
                    if count > 0:
                        is_visible = await btn.is_visible()
                        if is_visible:
                            # Додаткова перевірка - кнопка не повинна бути disabled
                            try:
                                is_disabled = await btn.is_disabled()
                                if not is_disabled:
                                    send_button = btn
                                    self.logger.info(f"Found send button with selector: {selector} (worker {worker_id}, attempt {attempt + 1})")
                                    break
                            except:
                                # Якщо не можемо перевірити disabled, все одно використовуємо
                                send_button = btn
                                self.logger.info(f"Found send button with selector: {selector} (worker {worker_id}, attempt {attempt + 1})")
                                break
                except Exception as e:
                    continue
            
            if send_button is not None:
                break
            
            if attempt < max_attempts - 1:
                await page.wait_for_timeout(300)
        
        # Якщо все ще не знайдено, спробуємо через JavaScript
        if send_button is None:
            self.logger.warning(f"Send button not found with selectors, trying JavaScript approach (worker {worker_id})")
            try:
                # Шукаємо всі кнопки біля textarea
                send_button = await page.evaluate_handle("""
                    () => {
                        const textarea = document.querySelector('textarea#chat-input, textarea[placeholder*="Describe"]');
                        if (!textarea) return null;
                        
                        // Шукаємо в батьківському контейнері
                        let container = textarea.closest('div');
                        while (container && container !== document.body) {
                            const buttons = container.querySelectorAll('button');
                            for (const btn of buttons) {
                                // Перевіряємо, чи це кнопка відправки
                                const text = btn.textContent || '';
                                const ariaLabel = btn.getAttribute('aria-label') || '';
                                const id = btn.id || '';
                                const className = btn.className || '';
                                
                                if (id.includes('send') || 
                                    ariaLabel.toLowerCase().includes('send') ||
                                    className.toLowerCase().includes('send') ||
                                    btn.querySelector('svg') ||
                                    btn.querySelector('i[class*="arrow"]')) {
                                    if (!btn.disabled) {
                                        return btn;
                                    }
                                }
                            }
                            container = container.parentElement;
                        }
                        return null;
                    }
                """)
                
                if send_button:
                    self.logger.info(f"Found send button via JavaScript (worker {worker_id})")
            except Exception as e:
                self.logger.warning(f"JavaScript approach failed: {e} (worker {worker_id})")
        
        if send_button is None:
            # Остання спроба - клік через Enter в textarea
            self.logger.warning(f"Send button still not found, trying Enter key (worker {worker_id})")
            try:
                await textarea.press("Enter")
                self.logger.info(f"Pressed Enter key to send message (worker {worker_id})")
                return
            except Exception as e:
                self.logger.error(f"Enter key also failed: {e} (worker {worker_id})")
                raise Exception(f"Send button not found and Enter key failed (worker {worker_id})")
        
        try:
            await send_button.wait_for(state="visible", timeout=5000)
            await self._safe_click(page, send_button, worker_id, "send button")
            self.logger.info("Send button clicked successfully", worker_id=worker_id)
            # Check for captcha right after sending
            await page.wait_for_timeout(2000)  # Wait for captcha to appear
            await self._handle_access_verification(page, worker_id, stage="post_send", suppress_exceptions=True)
        except Exception as e:
            # Fallback - спробуємо Enter
            self.logger.warning(f"Click failed: {e}, trying Enter key (worker {worker_id})")
            await textarea.press("Enter")
            self.logger.info(f"Pressed Enter key to send message (worker {worker_id})")
            # Check for captcha after Enter key
            await page.wait_for_timeout(2000)
            await self._handle_access_verification(page, worker_id, stage="post_send", suppress_exceptions=True)
    
    async def _wait_and_download_video(
        self,
        page: Page,
        output_dir: Path,
        worker_id: int,
        sanitized_path: Path
    ) -> Optional[Path]:
        """Wait for video generation and download it."""
        # Step 9: Wait for video generation
        self.logger.info("Waiting for video generation", worker_id=worker_id)
        
        # Wait for initial response
        try:
            await page.wait_for_timeout(10000)  # Initial 10 second wait
        except Exception:
            if page.is_closed():
                self.logger.error("Page closed during initial wait", worker_id=worker_id)
                raise Exception("Page was closed during video generation wait")
            raise
        
        # Wait for video to appear or download button
        max_wait = 300  # 5 minutes max (як вказав користувач)
        waited = 10
        video_ready = False
        error_detected = False
        video_found = False
        
        # Нові селектори для кнопки з трьома крапками (меню) - через use xlink:href
        more_menu_icon_selectors = [
            'span.anticon.qwen-chat-package-comp-new-action-control-icon:has(svg use[xlink\\:href="#icon-line-more-01"])',
            'span.anticon.qwen-chat-package-comp-new-action-control-icon',
            'span[class*="qwen-chat-package-comp-new-action-control-icon"]:has(svg use[xlink\\:href="#icon-line-more-01"])',
            'span:has(svg use[xlink\\:href="#icon-line-more-01"])',
            'span.anticon[class*="qwen-chat-package-comp-new-action-control-icon"]'
        ]
        
        # Нові селектори для кнопки Download
        download_selectors = [
            'div.qwen-chat-package-comp-new-action-more-operation-text:has-text("Download")',
            'div.qwen-chat-package-comp-new-action-more-operation-items:has(div.qwen-chat-package-comp-new-action-more-operation-text:has-text("Download"))',
            'div.qwen-chat-package-comp-new-action-control-container-download',
            'div.qwen-chat-package-comp-new-action-more-operation-items:has(div.qwen-chat-package-comp-new-action-control-container-download)',
            'div.qwen-chat-package-comp-new-action-more-operation-text',
            'div[class*="more-operation-text"]:has-text("Download")',
            'div[class*="more-operation-items"]:has-text("Download")',
            'div:has-text("Download")'
        ]
        
        # Video element selectors to detect if video is ready
        video_element_selectors = [
            'video',
            'div[class*="video-player"]',
            'div[class*="video-container"]',
            'div.video-play-icon',
            'div:has(i.iconbigPauseMore)',
            'div[class*="message-footer"]',
            'div[class*="response-message"]'
        ]
        
        self.logger.info(f"Starting wait loop, checking every 30 seconds, max wait: {max_wait} seconds", worker_id=worker_id)
        
        while waited < max_wait:
            # Check if page is still open
            if page.is_closed():
                self.logger.warning("Page was closed during wait", worker_id=worker_id, waited=waited)
                break
            
            # Scroll page to ensure elements are in view
            try:
                if not page.is_closed():
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await page.wait_for_timeout(500)
            except Exception:
                if page.is_closed():
                    break
                pass
            
            # Спочатку перевіряємо наявність відео елементів
            if not video_found:
                try:
                    video_elements = await page.locator('video').all()
                    if len(video_elements) > 0:
                        # Також перевіряємо наявність qwen-video-control-time як індикатор готовності
                        video_control_time = page.locator('div.qwen-video-control-time').first
                        if await video_control_time.count() > 0:
                            video_found = True
                            self.logger.info(f"✅ Video element found with control time (worker {worker_id}), waited: {waited}s")
                        elif len(video_elements) > 0:
                            video_found = True
                            self.logger.info(f"✅ Video element found (worker {worker_id}), waited: {waited}s")
                except Exception as e:
                    self.logger.debug(f"Video check failed: {e} (worker {worker_id})")
            
            # Якщо відео знайдено, перевіряємо наявність qwen-video-control-time як індикатор готовності
            if video_found and not video_ready:
                try:
                    video_control_time = page.locator('div.qwen-video-control-time').first
                    if await video_control_time.count() > 0:
                        is_visible = await video_control_time.is_visible()
                        if is_visible:
                            self.logger.info(f"✅ Video control time found - video is ready (worker {worker_id})")
                        else:
                            self.logger.debug(f"Video control time exists but not visible yet (worker {worker_id})")
                except Exception as e:
                    self.logger.debug(f"Video control time check failed: {e} (worker {worker_id})")
            
            # Якщо відео знайдено, одразу перевіряємо наявність іконки з трьома крапками
            if video_found and not video_ready:
                self.logger.info(f"🎯 Video found! Immediately checking for more menu icon (worker {worker_id})")
                more_menu_icon = None
                more_menu_clicked = False
                
                # Шукаємо іконку з трьома крапками через різні селектори
                for selector in more_menu_icon_selectors:
                    try:
                        if page.is_closed():
                            break
                        more_menu_icon = page.locator(selector).first
                        count = await more_menu_icon.count()
                        self.logger.debug(f"Checking selector '{selector}': count={count} (worker {worker_id})")
                        if count > 0:
                            is_visible = await more_menu_icon.is_visible()
                            self.logger.debug(f"Selector '{selector}': visible={is_visible} (worker {worker_id})")
                            if is_visible:
                                self.logger.info(f"✅ More menu icon found with selector: {selector} (worker {worker_id})")
                                # Клікаємо на іконку з трьома крапками
                                try:
                                    await more_menu_icon.scroll_into_view_if_needed()
                                    await page.wait_for_timeout(200)
                                    await more_menu_icon.click()
                                    self.logger.info(f"✅ Clicked on more menu icon (worker {worker_id})")
                                    await page.wait_for_timeout(500)  # Чекаємо, поки меню відкриється
                                    more_menu_clicked = True
                                    break
                                except Exception as e:
                                    self.logger.warning(f"❌ Failed to click more menu icon: {e} (worker {worker_id})")
                                    continue
                    except Exception as e:
                        self.logger.debug(f"Selector '{selector}' check failed: {e} (worker {worker_id})")
                        continue
                
                if not more_menu_clicked:
                    self.logger.warning(f"⚠️ More menu icon not found or not clickable (worker {worker_id})")
                    # Спробуємо знайти через JavaScript
                    try:
                        result = await page.evaluate("""
                            () => {
                                const icons = document.querySelectorAll('span.anticon.qwen-chat-package-comp-new-action-control-icon');
                                for (let icon of icons) {
                                    const svg = icon.querySelector('svg use');
                                    if (svg && svg.getAttribute('xlink:href') === '#icon-line-more-01') {
                                        return icon.getBoundingClientRect();
                                    }
                                }
                                return null;
                            }
                        """)
                        if result:
                            self.logger.info(f"✅ Found icon via JavaScript, attempting click (worker {worker_id})")
                            clicked = await page.evaluate("""
                                () => {
                                    const icons = document.querySelectorAll('span.anticon.qwen-chat-package-comp-new-action-control-icon');
                                    for (let icon of icons) {
                                        const svg = icon.querySelector('svg use');
                                        if (svg && svg.getAttribute('xlink:href') === '#icon-line-more-01') {
                                            icon.click();
                                            return true;
                                        }
                                    }
                                    return false;
                                }
                            """)
                            if clicked:
                                await page.wait_for_timeout(500)
                                more_menu_clicked = True
                                self.logger.info(f"✅ Clicked via JavaScript (worker {worker_id})")
                            else:
                                self.logger.warning(f"⚠️ JavaScript click returned false (worker {worker_id})")
                    except Exception as e:
                        self.logger.warning(f"JavaScript click failed: {e} (worker {worker_id})")
                
                # Шукаємо кнопку Download (навіть якщо меню не відкрилося - можливо, воно вже відкрите)
                # Або спробуємо знайти кнопку Download безпосередньо
                self.logger.info(f"🔍 Searching for Download button (worker {worker_id}), more_menu_clicked={more_menu_clicked}")
                if more_menu_clicked:
                    await page.wait_for_timeout(300)  # Додаткова затримка після кліку
                
                download_button_found = None
                for selector in download_selectors:
                    try:
                        if page.is_closed():
                            break
                        download_button = page.locator(selector).first
                        count = await download_button.count()
                        self.logger.debug(f"Checking Download selector '{selector}': count={count} (worker {worker_id})")
                        if count > 0:
                            is_visible = await download_button.is_visible()
                            self.logger.debug(f"Download selector '{selector}': visible={is_visible} (worker {worker_id})")
                            if is_visible:
                                # Перевіряємо, чи текст містить "Download"
                                try:
                                    text_content = await download_button.text_content()
                                    self.logger.debug(f"Download button text: '{text_content}' (worker {worker_id})")
                                    if text_content and "Download" in text_content:
                                        # Try to scroll to button
                                        try:
                                            if not page.is_closed():
                                                await download_button.scroll_into_view_if_needed()
                                                await page.wait_for_timeout(200)
                                        except Exception:
                                            if page.is_closed():
                                                break
                                            pass
                                        
                                        if page.is_closed():
                                            break
                                        
                                        # Double check it's still visible
                                        is_visible = await download_button.is_visible()
                                        if is_visible:
                                            download_button_found = download_button
                                            video_ready = True
                                            self.logger.info(f"✅ Download button found (worker {worker_id}), selector: {selector}, waited: {waited}s")
                                            break
                                except Exception as e:
                                    self.logger.debug(f"Failed to get button text: {e} (worker {worker_id})")
                                    continue
                    except Exception as e:
                        if page.is_closed():
                            break
                        self.logger.debug(f"Download selector '{selector}' check failed: {e} (worker {worker_id})")
                        continue
                
                if not video_ready:
                    # Спробуємо знайти через JavaScript
                    self.logger.info(f"🔍 Trying to find Download button via JavaScript (worker {worker_id})")
                    try:
                        result = await page.evaluate("""
                            () => {
                                const items = document.querySelectorAll('div.qwen-chat-package-comp-new-action-more-operation-text');
                                for (let item of items) {
                                    if (item.textContent && item.textContent.trim() === 'Download') {
                                        return {found: true, text: item.textContent.trim()};
                                    }
                                }
                                return {found: false};
                            }
                        """)
                        if result and result.get('found'):
                            self.logger.info(f"✅ Found Download button via JavaScript (worker {worker_id})")
                            clicked = await page.evaluate("""
                                () => {
                                    const items = document.querySelectorAll('div.qwen-chat-package-comp-new-action-more-operation-text');
                                    for (let item of items) {
                                        if (item.textContent && item.textContent.trim() === 'Download') {
                                            item.click();
                                            return true;
                                        }
                                    }
                                    return false;
                                }
                            """)
                            if clicked:
                                video_ready = True
                                self.logger.info(f"✅ Clicked Download via JavaScript (worker {worker_id})")
                            else:
                                self.logger.warning(f"⚠️ JavaScript Download click returned false (worker {worker_id})")
                        else:
                            self.logger.debug(f"Download button not found via JavaScript (worker {worker_id})")
                    except Exception as e:
                        self.logger.warning(f"JavaScript Download click failed: {e} (worker {worker_id})")
                
                if video_ready:
                    self.logger.info(f"✅ Video ready for download (worker {worker_id})")
                    break
                else:
                    self.logger.debug(f"Download button not found yet (worker {worker_id})")
            
            if video_ready:
                break
            
            # Check if there's an error message or generation failed
            try:
                error_selectors = [
                    'div[class*="error"]',
                    'div[class*="failed"]',
                    'div[class*="Error"]',
                    'div[class*="Failed"]',
                    'div:has-text("error")',
                    'div:has-text("Error")',
                    'div:has-text("failed")',
                    'div:has-text("Failed")',
                    'div[role="alert"]',
                    '.error-message',
                    '.failure-message'
                ]
                for error_selector in error_selectors:
                    error_indicators = page.locator(error_selector).first
                    if await error_indicators.count() > 0:
                        is_visible = await error_indicators.is_visible()
                        if is_visible:
                            error_text = await error_indicators.text_content()
                            if error_text and len(error_text) < 500:
                                self.logger.error("Error indicator found", worker_id=worker_id, error=error_text[:200])
                                error_detected = True
                                break
            except Exception:
                # Ignore errors in error detection
                pass
            
            # Check for generation status indicators
            try:
                status_selectors = [
                    'div:has-text("Generating")',
                    'div:has-text("generating")',
                    'div:has-text("Processing")',
                    'div:has-text("processing")',
                    '[aria-busy="true"]',
                    '.loading',
                    '.spinner'
                ]
                has_status = False
                for status_selector in status_selectors:
                    status_elem = page.locator(status_selector).first
                    if await status_elem.count() > 0:
                        is_visible = await status_elem.is_visible()
                        if is_visible:
                            has_status = True
                            break
                
                # If no status indicators and no video, might be stuck
                if not has_status and not video_ready and waited > 120:
                    self.logger.warning("No generation status detected after 2 minutes", worker_id=worker_id, waited=waited)
            except Exception:
                pass
            
            if page.is_closed():
                break
            
            # If error detected, break early
            if error_detected:
                self.logger.error("Generation error detected, stopping wait", worker_id=worker_id, waited=waited)
                break
            
            # Якщо відео знайдено, перевіряємо частіше (кожні 5 секунд)
            # Якщо відео не знайдено, перевіряємо кожні 30 секунд
            if video_found:
                check_interval = 5000  # 5 секунд, якщо відео знайдено
            else:
                check_interval = 30000  # 30 секунд, якщо відео не знайдено
            
            try:
                await page.wait_for_timeout(check_interval)
            except Exception:
                if page.is_closed():
                    self.logger.warning("Page closed during timeout", worker_id=worker_id)
                    break
                raise
            
            waited += (check_interval // 1000)
            if not video_found:
                self.logger.info(f"Still waiting for video (worker {worker_id}), waited: {waited}s / {max_wait}s")
            elif not video_ready:
                self.logger.info(f"Video found, waiting for Download button (worker {worker_id}), waited: {waited}s / {max_wait}s")
        
        if error_detected:
            raise Exception("Video generation failed - error detected on page")
        
        # Якщо відео знайдено, але кнопка Download не знайдена, все одно спробуємо завантажити
        if video_found and not video_ready:
            self.logger.warning("Video found but Download button not ready, trying to download anyway", worker_id=worker_id, timeout=max_wait, waited=waited)
        elif not video_found:
            self.logger.warning("Video not found after timeout, trying to download anyway", worker_id=worker_id, timeout=max_wait, waited=waited)
        
        # Step 10: Download video
        # Передаємо знайдену кнопку Download
        download_button_found = None
        # Шукаємо кнопку Download (навіть якщо video_ready = False, але відео знайдено)
        if video_found:
            self.logger.info(f"🔍 Final search for Download button (worker {worker_id})")
            for selector in download_selectors:
                try:
                    download_button = page.locator(selector).first
                    count = await download_button.count()
                    if count > 0:
                        is_visible = await download_button.is_visible()
                        if is_visible:
                            text_content = await download_button.text_content()
                            if text_content and "Download" in text_content:
                                download_button_found = download_button
                                self.logger.info(f"✅ Found Download button in final search: {selector} (worker {worker_id})")
                                break
                except Exception as e:
                    self.logger.debug(f"Final search selector '{selector}' failed: {e} (worker {worker_id})")
                    continue
        
        return await self._download_video_file(page, output_dir, worker_id, sanitized_path, download_button_found, download_selectors)
    
    async def _download_video_file(
        self,
        page: Page,
        output_dir: Path,
        worker_id: int,
        sanitized_path: Path,
        download_button_found: Optional[Locator],
        download_selectors: List[str]
    ) -> Optional[Path]:
        """Download the video file using new Qwen interface."""
        self.logger.info("Downloading video", worker_id=worker_id)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # Extract character name from image path for better naming
        char_name = describe_media_name(sanitized_path).replace(" · ", "_").replace(" ", "_")
        filename = f"{timestamp}_W{worker_id}_qwen_{char_name}.mp4"
        save_path = output_dir / filename
        
        # Scroll to bottom to ensure elements are visible
        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1000)
        except Exception:
            pass
        
        # Якщо кнопка Download вже знайдена, спробуємо клікнути на неї одразу
        if download_button_found:
            try:
                # Перевіряємо, чи кнопка все ще видима
                if await download_button_found.count() > 0:
                    is_visible = await download_button_found.is_visible()
                    if is_visible:
                        self.logger.info("Download button already found and visible, clicking immediately", worker_id=worker_id)
                        try:
                            async with page.expect_download(timeout=60000) as download_info:
                                await download_button_found.click()
                                download = await download_info.value
                                await download.save_as(save_path)
                                self.logger.info(f"✅ Video downloaded successfully (worker {worker_id})")
                                return save_path
                        except Exception as e:
                            self.logger.warning(f"Direct click on found button failed: {e}, will try via three dots (worker {worker_id})")
            except Exception as e:
                self.logger.warning(f"Error checking found button: {e}, will try via three dots (worker {worker_id})")
        
        # Якщо кнопка не знайдена або клік не спрацював, клікаємо на три крапки
        # Завжди клікаємо на іконку з трьома крапками (крайня права кнопка під відео) перед Download
        # Це обов'язковий крок, навіть якщо меню вже відкрите
        self.logger.info("Clicking on more menu icon (three dots) - required step before download", worker_id=worker_id)
        more_menu_icon_selectors = [
            'span.anticon.qwen-chat-package-comp-new-action-control-icon:has(svg use[xlink\\:href="#icon-line-more-01"])',
            'span.anticon.qwen-chat-package-comp-new-action-control-icon',
            'span[class*="qwen-chat-package-comp-new-action-control-icon"]:has(svg use[xlink\\:href="#icon-line-more-01"])',
            'span:has(svg use[xlink\\:href="#icon-line-more-01"])',
            'span.anticon[class*="qwen-chat-package-comp-new-action-control-icon"]'
        ]
        
        more_menu_icon = None
        more_menu_clicked = False
        
        # Спочатку спробуємо знайти через селектори
        for selector in more_menu_icon_selectors:
            try:
                candidate = page.locator(selector).first
                if await candidate.count() > 0:
                    is_visible = await candidate.is_visible()
                    if is_visible:
                        more_menu_icon = candidate
                        self.logger.info(f"Found more menu icon with selector: {selector} (worker {worker_id})")
                        break
            except Exception:
                continue
        
        # Якщо не знайдено через селектори, спробуємо через JavaScript
        # Шукаємо всі іконки і вибираємо останню (найправішу) під відео
        if more_menu_icon is None or (more_menu_icon and await more_menu_icon.count() == 0):
            self.logger.info(f"More menu icon not found via selectors, trying JavaScript to find rightmost icon (worker {worker_id})")
            try:
                clicked = await page.evaluate("""
                    () => {
                        // Знаходимо всі іконки з трьома крапками
                        const icons = document.querySelectorAll('span.anticon.qwen-chat-package-comp-new-action-control-icon');
                        let rightmostIcon = null;
                        let rightmostX = -1;
                        
                        for (let icon of icons) {
                            const svg = icon.querySelector('svg use');
                            if (svg && svg.getAttribute('xlink:href') === '#icon-line-more-01') {
                                const rect = icon.getBoundingClientRect();
                                // Знаходимо найправішу іконку (найбільший X)
                                if (rect.right > rightmostX) {
                                    rightmostX = rect.right;
                                    rightmostIcon = icon;
                                }
                            }
                        }
                        
                        if (rightmostIcon) {
                            rightmostIcon.click();
                            return true;
                        }
                        return false;
                    }
                """)
                if clicked:
                    self.logger.info(f"✅ Clicked more menu icon (rightmost) via JavaScript (worker {worker_id})")
                    await page.wait_for_timeout(1000)  # Чекаємо, поки меню відкриється
                    more_menu_clicked = True
                else:
                    raise Exception("More menu icon not found via JavaScript")
            except Exception as e:
                raise Exception(f"More menu icon not found - cannot download video: {e}")
        else:
            # Клікаємо на іконку з трьома крапками
            try:
                await more_menu_icon.scroll_into_view_if_needed()
                await page.wait_for_timeout(300)
                await more_menu_icon.click()
                self.logger.info(f"✅ Clicked on more menu icon (worker {worker_id})")
                await page.wait_for_timeout(1000)  # Чекаємо, поки меню відкриється
                more_menu_clicked = True
            except Exception as e:
                raise Exception(f"Failed to click more menu icon: {e}")
        
        if not more_menu_clicked:
            raise Exception("Failed to click more menu icon - cannot proceed with download")
        
        # Чекаємо, поки меню відкриється (перевіряємо наявність кнопки Download)
        self.logger.info("Waiting for menu to open and searching for Download button", worker_id=worker_id)
        download_btn = None
        max_wait_for_menu = 10  # Максимум 10 секунд на відкриття меню (збільшено)
        waited_for_menu = 0
        
        while waited_for_menu < max_wait_for_menu and download_btn is None:
            # Спочатку перевіряємо, чи меню взагалі відкрилося (шукаємо контейнер меню)
            try:
                menu_container = page.locator('div.qwen-chat-package-comp-new-action-more-operation-items').first
                menu_visible = await menu_container.count() > 0 and await menu_container.is_visible()
                if not menu_visible:
                    self.logger.debug(f"Menu not visible yet, waiting... ({waited_for_menu}s / {max_wait_for_menu}s)", worker_id=worker_id)
            except Exception:
                pass
            
            # Шукаємо кнопку Download в меню
            for selector in download_selectors:
                try:
                    candidate = page.locator(selector).first
                    count = await candidate.count()
                    if count > 0:
                        # Перевіряємо текст
                        try:
                            text_content = await candidate.text_content()
                            if text_content and "Download" in text_content:
                                is_visible = await candidate.is_visible()
                                if is_visible:
                                    download_btn = candidate
                                    self.logger.info(f"✅ Found Download button with selector: {selector} (worker {worker_id})")
                                    # Одразу клікаємо на знайдену кнопку
                                    try:
                                        async with page.expect_download(timeout=60000) as download_info:
                                            await download_btn.click()
                                            download = await download_info.value
                                            await download.save_as(save_path)
                                            self.logger.info(f"✅ Video downloaded successfully (worker {worker_id})")
                                            return save_path
                                    except Exception as e:
                                        self.logger.warning(f"Click on found button failed: {e}, will continue search (worker {worker_id})")
                                        download_btn = None  # Скидаємо, щоб продовжити пошук
                                    break
                        except Exception:
                            # Якщо це контейнер, перевіряємо чи є всередині текст Download
                            try:
                                download_text = candidate.locator('div.qwen-chat-package-comp-new-action-more-operation-text')
                                if await download_text.count() > 0:
                                    text_content = await download_text.text_content()
                                    if text_content and "Download" in text_content:
                                        is_visible = await candidate.is_visible()
                                        if is_visible:
                                            download_btn = candidate  # Клікаємо на контейнер
                                            self.logger.info(f"✅ Found Download container with selector: {selector} (worker {worker_id})")
                                            break
                            except Exception:
                                continue
                except Exception as e:
                    continue
            
            if download_btn is None:
                await page.wait_for_timeout(500)  # Чекаємо 500ms перед наступною спробою
                waited_for_menu += 0.5
                if waited_for_menu % 2 == 0:  # Логуємо кожні 2 секунди
                    self.logger.debug(f"Download button not found yet, waiting... ({waited_for_menu}s / {max_wait_for_menu}s)", worker_id=worker_id)
        
        if download_btn is None:
            self.logger.warning("Download button not found immediately after clicking more menu, trying JavaScript", worker_id=worker_id)
            # Спробуємо знайти через JavaScript
            try:
                result = await page.evaluate("""
                    () => {
                        const items = document.querySelectorAll('div.qwen-chat-package-comp-new-action-more-operation-text');
                        for (let item of items) {
                            if (item.textContent && item.textContent.trim() === 'Download') {
                                return {found: true, visible: item.offsetParent !== null};
                            }
                        }
                        return {found: false};
                    }
                """)
                if result and result.get('found'):
                    # Знайдено через JavaScript, тепер знайдемо через селектор
                    for selector in download_selectors:
                        try:
                            candidate = page.locator(selector).first
                            if await candidate.count() > 0:
                                text_content = await candidate.text_content()
                                if text_content and "Download" in text_content:
                                    is_visible = await candidate.is_visible()
                                    if is_visible:
                                        download_btn = candidate
                                        self.logger.info(f"✅ Found Download button via JavaScript check (worker {worker_id})")
                                        break
                        except Exception:
                            continue
                    # Якщо не знайдено через селектор, але знайдено через JavaScript, одразу клікаємо через JavaScript
                    if download_btn is None and result.get('found'):
                        self.logger.info(f"Download button found via JavaScript but not via selector, clicking via JavaScript immediately (worker {worker_id})")
                        try:
                            async with page.expect_download(timeout=60000) as download_info:
                                clicked = await page.evaluate("""
                                    () => {
                                        // Шукаємо текст Download
                                        const textItems = document.querySelectorAll('div.qwen-chat-package-comp-new-action-more-operation-text');
                                        for (let item of textItems) {
                                            if (item.textContent && item.textContent.trim() === 'Download') {
                                                const rect = item.getBoundingClientRect();
                                                if (rect.width > 0 && rect.height > 0) {
                                                    item.scrollIntoView({ behavior: 'smooth', block: 'center' });
                                                    item.click();
                                                    return true;
                                                }
                                            }
                                        }
                                        return false;
                                    }
                                """)
                                if clicked:
                                    download = await download_info.value
                                    await download.save_as(save_path)
                                    self.logger.info(f"✅ Video downloaded successfully via JavaScript click (worker {worker_id})")
                                    return save_path
                                else:
                                    raise Exception("JavaScript click returned false")
                        except Exception as e:
                            self.logger.warning(f"JavaScript click failed: {e} (worker {worker_id})")
                            # Продовжуємо пошук через інші методи
            except Exception as e:
                self.logger.warning(f"JavaScript check failed: {e} (worker {worker_id})")
        
        if download_btn is None:
            # Last attempt: scroll and search again, also try clicking on container
            self.logger.warning("Download button not found, trying one more time with scroll and container click", worker_id=worker_id)
            try:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(2000)
                
                # Try all selectors one more time
                for selector in download_selectors:
                    try:
                        candidate = page.locator(selector).first
                        if await candidate.count() > 0:
                            await candidate.scroll_into_view_if_needed()
                            await page.wait_for_timeout(500)
                            is_visible = await candidate.is_visible()
                            if is_visible:
                                # Перевіряємо, чи це контейнер з Download
                                try:
                                    text_content = await candidate.text_content()
                                    if text_content and "Download" in text_content:
                                        download_btn = candidate
                                        self.logger.info(f"Found download button on retry: {selector}", worker_id=worker_id)
                                        break
                                    # Якщо це контейнер, перевіряємо чи є всередині текст Download
                                    download_text = candidate.locator('div.qwen-chat-package-comp-new-action-more-operation-text')
                                    if await download_text.count() > 0:
                                        text_content = await download_text.text_content()
                                        if text_content and "Download" in text_content:
                                            download_btn = candidate  # Клікаємо на контейнер
                                            self.logger.info(f"Found download container on retry: {selector}", worker_id=worker_id)
                                            break
                                except Exception:
                                    pass
                    except Exception:
                        continue
            except Exception:
                pass
        
        # Якщо кнопка не знайдена взагалі, спробуємо через JavaScript
        if download_btn is None:
            self.logger.warning("Download button not found via selectors, trying JavaScript click", worker_id=worker_id)
            try:
                # Спочатку налаштовуємо очікування завантаження
                async with page.expect_download(timeout=60000) as download_info:
                    # Спробуємо знайти і клікнути через JavaScript
                    # Спочатку пробуємо клікнути на текст
                    clicked = await page.evaluate("""
                        () => {
                            // Шукаємо текст Download
                            const textItems = document.querySelectorAll('div.qwen-chat-package-comp-new-action-more-operation-text');
                            for (let item of textItems) {
                                if (item.textContent && item.textContent.trim() === 'Download') {
                                    const rect = item.getBoundingClientRect();
                                    if (rect.width > 0 && rect.height > 0) {
                                        item.scrollIntoView({ behavior: 'smooth', block: 'center' });
                                        item.click();
                                        return true;
                                    }
                                }
                            }
                            // Якщо не знайшли текст, шукаємо контейнер
                            const containers = document.querySelectorAll('div.qwen-chat-package-comp-new-action-more-operation-items');
                            for (let container of containers) {
                                const text = container.querySelector('div.qwen-chat-package-comp-new-action-more-operation-text');
                                if (text && text.textContent && text.textContent.trim() === 'Download') {
                                    const rect = container.getBoundingClientRect();
                                    if (rect.width > 0 && rect.height > 0) {
                                        container.scrollIntoView({ behavior: 'smooth', block: 'center' });
                                        container.click();
                                        return true;
                                    }
                                }
                            }
                            // Якщо не знайшли, шукаємо контейнер з класом download
                            const downloadContainers = document.querySelectorAll('div.qwen-chat-package-comp-new-action-control-container-download');
                            for (let container of downloadContainers) {
                                const rect = container.getBoundingClientRect();
                                if (rect.width > 0 && rect.height > 0) {
                                    container.scrollIntoView({ behavior: 'smooth', block: 'center' });
                                    container.click();
                                    return true;
                                }
                            }
                            return false;
                        }
                    """)
                    if clicked:
                        self.logger.info(f"✅ Clicked Download button via JavaScript (worker {worker_id})")
                        download = await download_info.value
                        await download.save_as(save_path)
                        self.logger.info(f"✅ Video downloaded successfully via JavaScript click (worker {worker_id})")
                        return save_path
                    else:
                        self.logger.warning("JavaScript click returned false - Download button not found", worker_id=worker_id)
            except Exception as e:
                self.logger.warning(f"JavaScript click failed: {e} (worker {worker_id})")
        
        if download_btn is None:
            # Take screenshot before raising error
            try:
                debug_screenshot = output_dir / f"debug_W{worker_id}_no_download_button.png"
                await page.screenshot(path=str(debug_screenshot), full_page=True)
                self.logger.error(f"Download button not found, screenshot saved to {debug_screenshot}", worker_id=worker_id)
            except Exception:
                pass
            raise Exception("Download button not found after trying all selectors, scrolling, and JavaScript")
        
        # Verify the button is still valid and scroll to it (тільки для Locator)
        try:
            if await download_btn.count() == 0:
                raise Exception("Download button count is 0")
            
            # Ensure button is in view
            try:
                await download_btn.scroll_into_view_if_needed()
                await page.wait_for_timeout(1000)
            except Exception:
                pass
            
            # Final visibility check
            is_visible = await download_btn.is_visible()
            if not is_visible:
                self.logger.warning("Download button not visible, trying to scroll again", worker_id=worker_id)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1000)
                is_visible = await download_btn.is_visible()
            
            if not is_visible:
                raise Exception("Download button not visible after scrolling")
                
        except Exception as e:
            # Take screenshot before raising error
            try:
                debug_screenshot = output_dir / f"debug_W{worker_id}_no_download_button.png"
                await page.screenshot(path=str(debug_screenshot), full_page=True)
                self.logger.error(f"Download button invalid, screenshot saved to {debug_screenshot}", worker_id=worker_id, error=str(e))
            except Exception:
                pass
            raise Exception(f"Download button invalid: {e}")
        
        # Set up download with retry
        download_success = False
        for attempt in range(3):
            try:
                self.logger.info(f"Attempting download, attempt {attempt + 1}/3", worker_id=worker_id)
                async with page.expect_download(timeout=60000) as download_info:
                    # Click the button
                    await download_btn.click()
                    download = await download_info.value
                    await download.save_as(save_path)
                download_success = True
                break
            except Exception as e:
                if attempt < 2:
                    self.logger.warning(f"Download attempt {attempt + 1} failed, retrying", worker_id=worker_id, error=str(e))
                await page.wait_for_timeout(2000)
                # Try to find button again
                try:
                    download_btn = page.locator('div[aria-label="Download"] button').first
                    if await download_btn.count() > 0:
                        await download_btn.scroll_into_view_if_needed()
                        await page.wait_for_timeout(500)
                except Exception:
                    pass
            else:
                raise
        
        if not download_success:
            raise Exception("Failed to download after 3 attempts")
        
        # Wait for file to fully download (check file size stability)
        self.logger.info("Waiting for file to fully download", worker_id=worker_id, path=str(save_path))
        max_wait_seconds = 60  # Max 60 seconds to wait for file to stabilize
        check_interval = 2  # Check every 2 seconds
        waited = 0
        last_size = 0
        stable_count = 0
        required_stable_checks = 3  # File size must be stable for 3 checks (6 seconds)
        
        while waited < max_wait_seconds:
            if save_path.exists():
                current_size = save_path.stat().st_size
                if current_size == last_size and current_size > 0:
                    stable_count += 1
                    if stable_count >= required_stable_checks:
                        self.logger.info(
                            "File download stabilized",
                            worker_id=worker_id,
                            size=current_size,
                            waited=waited
                        )
                        break
                else:
                    stable_count = 0
                    last_size = current_size
            else:
                stable_count = 0
            
            await asyncio.sleep(check_interval)
            waited += check_interval
        
        if not save_path.exists() or save_path.stat().st_size == 0:
            self.logger.warning(
                "File may not have fully downloaded",
                worker_id=worker_id,
                exists=save_path.exists(),
                size=save_path.stat().st_size if save_path.exists() else 0
            )
        else:
            # Additional safety delay to ensure download is complete
            self.logger.info("Additional safety delay before closing browser", worker_id=worker_id)
            await asyncio.sleep(3)
        
        self.logger.info("Download complete", worker_id=worker_id, path=str(save_path))
        
        return save_path

    async def generate_video(
        self,
        image_path: Path,
        prompt: str,
        profile_name: str,
        output_dir: Path,
        worker_id: int = 1,
        browser_service: Optional[BrowserService] = None
    ) -> Optional[Path]:
        """
        Generate a video from an image using Qwen.
        
        Args:
            image_path: Path to image file
            prompt: Text prompt for video generation
            profile_name: Chrome profile name
            output_dir: Directory to save output
            worker_id: Worker identifier
            
        Returns:
            Path to downloaded video or None if failed
        """
        sanitized_path = sanitize_path(image_path)
        if not sanitized_path.exists():
            self.logger.error("Image not found", path=str(sanitized_path))
            return None
        
        owns_browser = browser_service is None
        ctx = None
        page = None
        
        try:
            if owns_browser:
                browser_service = BrowserService(self.config)
                await browser_service.start()
            assert browser_service is not None
            
            # Create dedicated context for this video task
            # Pass service_name="qwen" to get --disable-gpu argument for stability
            ctx = await browser_service.create_context(profile_name, headless=False, service_name="qwen")
            page = await ctx.new_page()
            
            self.logger.info("Navigating to Qwen", worker_id=worker_id, image=sanitized_path.name)
            await page.goto(
                self.QWEN_URL,
                wait_until="domcontentloaded",
                timeout=60000
            )
            await page.wait_for_timeout(1000)
            await self._handle_access_verification(page, worker_id, stage="direct_navigation", suppress_exceptions=True)
            try:
                await page.evaluate("window.scrollTo(0, 0)")
            except Exception:
                pass
            
            # Wait for main content to be ready - wait for first interactive element
            self.logger.info("Waiting for Qwen page elements to load", worker_id=worker_id)
            try:
                # Wait for either chat input or Video Generation button to appear
                await page.wait_for_selector(
                    'textarea#chat-input, textarea[placeholder*="Describe"], button.chat-prompt-suggest-button, button:has-text("Video Generation")',
                    timeout=30000,
                    state="visible"
                )
                self.logger.info("Qwen page elements loaded successfully", worker_id=worker_id)
            except PlaywrightTimeout:
                self.logger.warning("Main elements not found, waiting longer", worker_id=worker_id)
                # Additional wait for slow connections
                await page.wait_for_timeout(2000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=10000)
                except:
                    await page.wait_for_load_state("domcontentloaded", timeout=5000)
            await self._handle_access_verification(page, worker_id, stage="pre_video_button", suppress_exceptions=False)
            
            # Step 1: Click Video Generation button
            self.logger.info("Waiting for Video Generation button to appear", worker_id=worker_id)
            
            # Wait for page to be fully interactive first
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except:
                await page.wait_for_load_state("domcontentloaded", timeout=10000)
            
            # Try multiple selectors for Video Generation button
            # Based on actual HTML structure: <button class="chat-prompt-suggest-button normal">
            # with <div>Video Generation</div> inside or <div data-spm-anchor-id>Video Generation</div>
            video_gen_button = None
            video_gen_selectors = [
                # Primary selectors with div[data-spm-anchor-id]
                # DIV selectors (most common on Qwen) - MUST BE FIRST!
                'div.chat-prompt-suggest-button:has(img.chat-prompt-suggest-button-img):has(div:has-text("Video Generation"))',
                'div.chat-prompt-suggest-button:has(div:has-text("Video Generation"))',
                'div.chat-prompt-suggest-button.normal:has(div:has-text("Video Generation"))',
                'div.chat-prompt-suggest-button:has-text("Video Generation")',
                'div.chat-prompt-suggest-button:has(img.chat-prompt-suggest-button-img)',
                'div[class*="chat-prompt-suggest-button"]:has(div:has-text("Video"))',
                'div[class*="chat-prompt-suggest-button"]:has-text("Video Generation")',
                # Data attribute selectors
                'div[data-spm-anchor-id*="a2ty"]:has-text("Video Generation")',
                'div[data-spm-anchor-id]:has-text("Video Generation")',
                # Button with img and text (fallback)
                'button.chat-prompt-suggest-button:has(img.chat-prompt-suggest-button-img):has(div:has-text("Video Generation"))',
                'button.chat-prompt-suggest-button:has(img.chat-prompt-suggest-button-img)',
                # Standard button selectors (fallback)
                'button.chat-prompt-suggest-button:has(div:has-text("Video Generation"))',
                'button.chat-prompt-suggest-button.normal:has(div:has-text("Video Generation"))',
                'button.chat-prompt-suggest-button:has-text("Video Generation")',
                'button[class*="chat-prompt-suggest-button"]:has(div:has-text("Video"))',
                'button:has-text("Video Generation")',
                'button[class*="suggest"]:has-text("Video Generation")',
                'div[class*="suggest"] button:has-text("Video Generation")',
                'button:has-text("Video")',
                'div[role="button"]:has-text("Video Generation")',
                'a:has-text("Video Generation")'
            ]
            
            found_button = False
            max_wait_attempts = 40  # 40 seconds total for slow pages
            for attempt in range(max_wait_attempts):
                # Refresh page state check periodically
                if attempt > 0 and attempt % 5 == 0:
                    try:
                        await page.wait_for_load_state("networkidle", timeout=5000)
                    except:
                        try:
                            await page.wait_for_load_state("domcontentloaded", timeout=3000)
                        except:
                            pass
                    # Scroll to top to ensure buttons are in view
                    try:
                        await page.evaluate("window.scrollTo(0, 0)")
                        await page.wait_for_timeout(500)
                    except:
                        pass
                
                for selector in video_gen_selectors:
                    try:
                        button_locator = page.locator(selector).first
                        count = await button_locator.count()
                        if count > 0:
                            # Wait for it to be visible and clickable
                            try:
                                await button_locator.wait_for(state="visible", timeout=3000)
                                is_visible = await button_locator.is_visible()
                                if is_visible:
                                    # ALWAYS click the button - don't trust "already active" checks
                                    video_gen_button = button_locator
                                    found_button = True
                                    self.logger.info(f"Found Video Generation button with selector: {selector} (attempt {attempt + 1})", worker_id=worker_id)
                                    break
                            except PlaywrightTimeout:
                                continue
                    except Exception:
                        continue
                
                if found_button:
                    break
                
                # Wait before next attempt
                if attempt < max_wait_attempts - 1:
                    await page.wait_for_timeout(1000)
            
            if not found_button:
                # Take screenshot to debug
                try:
                    debug_screenshot = output_dir / f"debug_W{worker_id}_no_video_button.png"
                    await page.screenshot(path=str(debug_screenshot), full_page=True)
                    self.logger.warning(f"Video Generation button not found, screenshot saved to {debug_screenshot}", worker_id=worker_id)
                except Exception:
                    pass
                raise Exception("Video Generation button not found after trying all selectors")
            
            # ALWAYS click the button - don't trust the "already active" check
            # The check can be false positive if aspect ratio selector exists but Video Generation is not active
            if video_gen_button is not None:
                # Try clicking with retries and verification
                click_success = False
                for click_attempt in range(5):  # More attempts
                    try:
                        self.logger.info(f"Clicking Video Generation button (attempt {click_attempt + 1}/5)", worker_id=worker_id)
                        await self._safe_click(page, video_gen_button, worker_id, f"Video Generation button (attempt {click_attempt + 1})")
                        await page.wait_for_timeout(1500)  # Wait for UI to update
                        
                        # STRICT verification: Check multiple indicators that Video Generation is ACTUALLY active
                        verification_passed = False
                        
                        # 1. Check if aspect ratio selector is visible AND clickable
                        aspect_ratio_check = page.locator('div.chat-ratio-selector, div[class*="ratio"], div[class*="aspect"]').first
                        if await aspect_ratio_check.count() > 0:
                            is_visible = await aspect_ratio_check.is_visible()
                            if is_visible:
                                # 2. Try to verify it's actually the video mode selector by checking if it has text like "16:9" or "9:16"
                                try:
                                    ratio_text = await aspect_ratio_check.text_content()
                                    if ratio_text and ('16:9' in ratio_text or '9:16' in ratio_text or ':' in ratio_text):
                                        verification_passed = True
                                        self.logger.info("Video Generation mode verified: aspect ratio selector found with ratio text", worker_id=worker_id)
                                except:
                                    # If text check fails, check if we can interact with it
                                    try:
                                        is_enabled = await aspect_ratio_check.is_enabled()
                                        if is_enabled:
                                            verification_passed = True
                                            self.logger.info("Video Generation mode verified: aspect ratio selector is enabled", worker_id=worker_id)
                                    except:
                                        pass
                        
                        # 3. Additional check: Video Generation button should have active/selected class
                        if not verification_passed:
                            try:
                                for selector in ['div.chat-prompt-suggest-button:has(div:has-text("Video Generation"))',
                                               'button.chat-prompt-suggest-button:has(div:has-text("Video Generation"))', 
                                               'div[data-spm-anchor-id*="a2ty"]:has-text("Video Generation")']:
                                    btn_check = page.locator(selector).first
                                    if await btn_check.count() > 0:
                                        class_attr = await btn_check.get_attribute("class") or ""
                                        if "active" in class_attr.lower() or "selected" in class_attr.lower():
                                            # Still verify aspect ratio exists
                                            aspect_ratio_final = page.locator('div.chat-ratio-selector').first
                                            if await aspect_ratio_final.count() > 0 and await aspect_ratio_final.is_visible():
                                                verification_passed = True
                                                self.logger.info("Video Generation mode verified: button has active class and aspect ratio visible", worker_id=worker_id)
                                                break
                            except:
                                pass
                        
                        if verification_passed:
                            click_success = True
                            self.logger.info("Video Generation button successfully clicked and verified", worker_id=worker_id)
                            break
                        else:
                            self.logger.warning(f"Video Generation click attempt {click_attempt + 1} - verification failed, retrying", worker_id=worker_id)
                            await page.wait_for_timeout(2000)
                    except Exception as click_err:
                        self.logger.warning(f"Click attempt {click_attempt + 1} failed, retrying", worker_id=worker_id, error=str(click_err))
                        await page.wait_for_timeout(2000)
                
                if not click_success:
                    # Take screenshot for debugging
                    try:
                        debug_screenshot = output_dir / f"debug_W{worker_id}_video_gen_click_failed.png"
                        await page.screenshot(path=str(debug_screenshot), full_page=True)
                        self.logger.error(f"Video Generation button click failed after all attempts, screenshot: {debug_screenshot}", worker_id=worker_id)
                    except:
                        pass
                    raise Exception("Failed to activate Video Generation mode after multiple attempts")
            else:
                raise Exception("Video Generation button not found - cannot proceed")
            
            # Final wait to ensure UI is stable
            await page.wait_for_timeout(2000)
            
            # Step 2: Click aspect ratio selector (16:9)
            self.logger.info("Selecting aspect ratio", worker_id=worker_id)
            
            # Try multiple selectors for the aspect ratio dropdown trigger
            ratio_selector_options = [
                'div.chat-ratio-selector:has-text("16:9")',  # Preferred: exact text match
                'div.chat-ratio-selector',  # Generic selector
                'div.chat-ratio-selector .anticon.selector-icon',  # Icon within ratio selector
                'span.anticon.selector-icon',  # Icon that opens dropdown
                'div[class*="ratio"] .anticon',  # Icon in ratio-related div
                'div.chat-ratio-selector svg',  # SVG icon within selector
            ]
            
            ratio_selector = None
            for selector_option in ratio_selector_options:
                temp_selector = page.locator(selector_option).first
                if await temp_selector.count() > 0:
                    try:
                        is_visible = await temp_selector.is_visible()
                        if is_visible:
                            ratio_selector = temp_selector
                            self.logger.info(f"Found aspect ratio selector with: {selector_option}", worker_id=worker_id)
                            break
                    except:
                        continue
            
            if ratio_selector is not None:
                await self._safe_click(page, ratio_selector, worker_id, "aspect ratio selector")
                await page.wait_for_timeout(1000)
            else:
                self.logger.warning("Aspect ratio selector not found, trying to continue", worker_id=worker_id)
            
            # Step 3: Select 9:16 from dropdown
            # Wait for dropdown menu to appear
            await page.wait_for_timeout(500)
            
            # Try multiple selectors for 9:16 option
            nine_sixteen_found = False
            nine_sixteen_selectors = [
                'div[role="menuitem"]:has-text("9:16")',
                'div[data-melt-menu-item]:has-text("9:16")',
                'div[data-melt-dropdown-menu-item]:has-text("9:16")',
                'div:has-text("9:16")[class*="menu"]'
            ]
            
            for selector in nine_sixteen_selectors:
                option = page.locator(selector).first
                if await option.count() > 0:
                    is_visible = await option.is_visible()
                    if is_visible:
                        await self._safe_click(page, option, worker_id, "aspect ratio option 9:16")
                        nine_sixteen_found = True
                        self.logger.info("Selected 9:16 aspect ratio", worker_id=worker_id)
                        break
            
            if not nine_sixteen_found:
                # Try to find by searching all menu items
                all_menu_items = page.locator('[role="menuitem"], div[data-melt-menu-item]')
                count = await all_menu_items.count()
                for i in range(count):
                    item = all_menu_items.nth(i)
                    text = await item.text_content()
                    if text and '9:16' in text:
                        await self._safe_click(page, item, worker_id, "aspect ratio option 9:16")
                        nine_sixteen_found = True
                        self.logger.info("Selected 9:16 via text search", worker_id=worker_id)
                        break
            
            if not nine_sixteen_found:
                self.logger.warning("9:16 option not found, continuing", worker_id=worker_id)
            
            await page.wait_for_timeout(1000)
            
            # Step 4-6: Upload image without keeping modal open
            await self._handle_access_verification(page, worker_id, stage="pre_upload", suppress_exceptions=False)
            await self._upload_image_without_modal(page, sanitized_path, worker_id)
            
            # CRITICAL: Final verification before entering prompt
            # Verify Video Generation mode is ACTUALLY active
            self.logger.info("Final verification: Video Generation mode must be active before entering prompt", worker_id=worker_id)
            aspect_ratio_final_check = page.locator('div.chat-ratio-selector, div[class*="ratio"]').first
            if await aspect_ratio_final_check.count() == 0 or not await aspect_ratio_final_check.is_visible():
                # Take screenshot and raise error
                try:
                    debug_screenshot = output_dir / f"debug_W{worker_id}_final_check_failed.png"
                    await page.screenshot(path=str(debug_screenshot), full_page=True)
                    self.logger.error(f"FINAL CHECK FAILED: Video Generation mode not active! Screenshot: {debug_screenshot}", worker_id=worker_id)
                except:
                    pass
                raise Exception("Video Generation mode is NOT active - cannot enter prompt. Aspect ratio selector missing.")
            
            # Verify aspect ratio selector has ratio text
            try:
                ratio_text = await aspect_ratio_final_check.text_content()
                if not ratio_text or ':' not in ratio_text:
                    self.logger.warning(f"Aspect ratio selector found but no ratio text (text: '{ratio_text}')", worker_id=worker_id)
            except:
                pass
            
            # Step 7: Enter prompt
            await self._handle_access_verification(page, worker_id, stage="pre_prompt", suppress_exceptions=False)
            self.logger.info("Entering prompt", worker_id=worker_id, prompt_length=len(prompt))
            textarea = page.locator('textarea#chat-input, textarea[placeholder*="Describe"]').first
            await textarea.wait_for(state="visible", timeout=10000)
            await textarea.fill(prompt)
            await page.wait_for_timeout(200)  # Мінімальна затримка
            
            # Step 8: Click send button
            await self._handle_access_verification(page, worker_id, stage="pre_send", suppress_exceptions=False)
            self.logger.info("Clicking send button", worker_id=worker_id)
            send_button = page.locator(
                'button#send-message-button, '
                'button._sendMessageButton_71e98_48, '
                'button:has(i.icon-line-arrow-up)'
            ).first
            await send_button.wait_for(state="visible", timeout=10000)
            await self._safe_click(page, send_button, worker_id, "send button")
            
            # Check for captcha right after sending
            await page.wait_for_timeout(2000)  # Wait for captcha to appear
            await self._handle_access_verification(page, worker_id, stage="post_send", suppress_exceptions=True)
            
            # Step 9: Wait for video generation
            self.logger.info("Waiting for video generation", worker_id=worker_id)
            
            # Wait for initial response
            try:
                await page.wait_for_timeout(10000)  # Initial 10 second wait
            except Exception:
                if page.is_closed():
                    self.logger.error("Page closed during initial wait", worker_id=worker_id)
                    raise Exception("Page was closed during video generation wait")
                raise
            
            # Wait for video to appear or download button
            max_wait = 600  # 10 minutes max (videos can take longer)
            waited = 10
            video_ready = False
            download_button_found = None
            error_detected = False
            
            # Download button selectors - based on actual HTML structure
            # Also check for video element presence as indicator
            download_selectors = [
                'div[aria-label="Download"] button',
                'div[aria-label="Download"]',
                'button.message-footer-button-item:has(i.icon-line-download-02)',
                'button.message-footer-button-item:has(i.default-iconfont.icon-line-download-02)',
                'div[aria-label="Download"] button:has(i.icon-line-download-02)',
                'button:has(i.default-iconfont.icon-line-download-02)',
                'button.response-message-control-item-visible:has(i.icon-line-download-02)',
                'button.message-footer-button-item:has(i.default-iconfont)',
                'i.default-iconfont.icon-line-download-02',
                'i.icon-line-download-02',
                'button:has(i.icon-line-download-02)',
                'i[class*="download"]',
                'i[class*="icon-line-download"]',
                'button:has(i[class*="download"])',
                'div[role="button"]:has(i[class*="download"])',
                'a:has(i[class*="download"])',
                'button[aria-label*="download" i]',
                'button[aria-label*="Download" i]',
                '[data-testid*="download" i]',
                'button:has-text("Download")',
                'a:has-text("Download")'
            ]
            
            # Video element selectors to detect if video is ready
            video_element_selectors = [
                'video',
                'div[class*="video-player"]',
                'div[class*="video-container"]',
                'div.video-play-icon',
                'div:has(i.iconbigPauseMore)',
                'div[class*="message-footer"]',
                'div[class*="response-message"]'
            ]
            
            self.logger.info(f"Starting wait loop, max wait: {max_wait} seconds", worker_id=worker_id)
            
            while waited < max_wait:
                # Якщо раптом посеред очікування з'явився слайдер — пробуємо його пройти
                try:
                    await self._handle_access_verification(page, worker_id, stage="wait_loop", suppress_exceptions=True)
                except Exception:
                    # suppress_exceptions=True вже обробляє, але на всяк випадок не валимо цикл
                    pass
                # Check if page is still open
                if page.is_closed():
                    self.logger.warning("Page was closed during wait", worker_id=worker_id, waited=waited)
                    break
                
                # Scroll page to ensure elements are in view
                try:
                    if not page.is_closed():
                        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        await page.wait_for_timeout(500)
                except Exception:
                    if page.is_closed():
                        break
                    pass
                
                # Check for download button with multiple selectors
                if page.is_closed():
                    break
                    
                for selector in download_selectors:
                    try:
                        if page.is_closed():
                            break
                        download_button = page.locator(selector).first
                        count = await download_button.count()
                        if count > 0:
                            is_visible = await download_button.is_visible()
                            if is_visible:
                                # Try to scroll to button
                                try:
                                    if not page.is_closed():
                                        await download_button.scroll_into_view_if_needed()
                                        await page.wait_for_timeout(500)
                                except Exception:
                                    if page.is_closed():
                                        break
                                    pass
                                
                                if page.is_closed():
                                    break
                                
                                # Double check it's still visible
                                is_visible = await download_button.is_visible()
                                if is_visible:
                                    download_button_found = download_button
                                    video_ready = True
                                    self.logger.info("Download button appeared", worker_id=worker_id, selector=selector, waited=waited)
                                    break
                    except Exception as e:
                        if page.is_closed():
                            break
                        continue
                
                if video_ready:
                    break
                
                # Check for video element or any response message
                try:
                    if not page.is_closed():
                        # Look for response messages that might contain video
                        response_messages = page.locator('div[class*="message"], div[class*="response"], div[class*="chat-message"]').last
                        if await response_messages.count() > 0:
                            await response_messages.scroll_into_view_if_needed()
                            if not page.is_closed():
                                await page.wait_for_timeout(1000)
                except Exception:
                    if page.is_closed():
                        break
                    pass
                
                if page.is_closed():
                    break
                
                # Check for video elements using multiple selectors
                video_found = False
                video_element = None
                for video_selector in video_element_selectors:
                    try:
                        if page.is_closed():
                            break
                        candidate = page.locator(video_selector).first
                        if await candidate.count() > 0:
                            is_visible = await candidate.is_visible()
                            if is_visible:
                                video_found = True
                                video_element = candidate
                                break
                    except Exception:
                        continue
                
                if video_found and video_element and await video_element.count() > 0:
                    is_visible = await video_element.is_visible()
                    if is_visible:
                        self.logger.info("Video element appeared, waiting for download button", worker_id=worker_id, waited=waited)
                        # Scroll to video
                        try:
                            if not page.is_closed():
                                await video_element.scroll_into_view_if_needed()
                                await page.wait_for_timeout(1000)
                        except Exception:
                            if page.is_closed():
                                break
                            pass
                        
                        # Wait a bit more for download button to appear
                        for check_round in range(10):  # Check 10 times over 30 seconds
                            if page.is_closed():
                                self.logger.warning("Page closed while waiting for download button", worker_id=worker_id)
                                break
                            
                            try:
                                await page.wait_for_timeout(3000)
                            except Exception:
                                if page.is_closed():
                                    break
                                raise
                            
                            waited += 3
                            
                            if page.is_closed():
                                break
                            
                            # Check again for download button
                            for selector in download_selectors:
                                try:
                                    if page.is_closed():
                                        break
                                    download_button = page.locator(selector).first
                                    if await download_button.count() > 0:
                                        is_visible = await download_button.is_visible()
                                        if is_visible:
                                            try:
                                                if not page.is_closed():
                                                    await download_button.scroll_into_view_if_needed()
                                                    await page.wait_for_timeout(500)
                                            except Exception:
                                                if page.is_closed():
                                                    break
                                                pass
                                            if page.is_closed():
                                                break
                                            download_button_found = download_button
                                            video_ready = True
                                            self.logger.info("Download button appeared after video", worker_id=worker_id, selector=selector, waited=waited)
                                            break
                                except Exception:
                                    if page.is_closed():
                                        break
                                    continue
                            
                            if video_ready:
                                break
                            
                            # Log progress every 2 rounds
                            if check_round % 2 == 1:
                                self.logger.debug("Still waiting for download button", worker_id=worker_id, round=check_round + 1)
                        
                        if video_ready:
                            break
                
                # Check if there's an error message or generation failed
                try:
                    error_selectors = [
                        'div[class*="error"]',
                        'div[class*="failed"]',
                        'div[class*="Error"]',
                        'div[class*="Failed"]',
                        'div:has-text("error")',
                        'div:has-text("Error")',
                        'div:has-text("failed")',
                        'div:has-text("Failed")',
                        'div[role="alert"]',
                        '.error-message',
                        '.failure-message'
                    ]
                    for error_selector in error_selectors:
                        error_indicators = page.locator(error_selector).first
                        if await error_indicators.count() > 0:
                            is_visible = await error_indicators.is_visible()
                            if is_visible:
                                error_text = await error_indicators.text_content()
                                if error_text and len(error_text) < 500:
                                    self.logger.error("Error indicator found", worker_id=worker_id, error=error_text[:200])
                                    error_detected = True
                                    break
                except Exception:
                    # Ignore errors in error detection
                    pass
                
                # Check for generation status indicators
                try:
                    status_selectors = [
                        'div:has-text("Generating")',
                        'div:has-text("generating")',
                        'div:has-text("Processing")',
                        'div:has-text("processing")',
                        '[aria-busy="true"]',
                        '.loading',
                        '.spinner'
                    ]
                    has_status = False
                    for status_selector in status_selectors:
                        status_elem = page.locator(status_selector).first
                        if await status_elem.count() > 0:
                            is_visible = await status_elem.is_visible()
                            if is_visible:
                                has_status = True
                                break
                    
                    # If no status indicators and no video, might be stuck
                    if not has_status and not video_ready and waited > 120:
                        self.logger.warning("No generation status detected after 2 minutes", worker_id=worker_id, waited=waited)
                except Exception:
                    pass
                
                # Check if page is still open before waiting
                if page.is_closed():
                    self.logger.warning("Page was closed during wait loop", worker_id=worker_id, waited=waited)
                    break
                
                try:
                    await page.wait_for_timeout(3000)
                except Exception:
                    if page.is_closed():
                        self.logger.warning("Page closed during timeout", worker_id=worker_id)
                        break
                    raise
                
                waited += 3
                
                if (waited % 30) == 0:  # Log every 30 seconds
                    self.logger.info("Still waiting for video", worker_id=worker_id, waited=waited, max_wait=max_wait)
            
            if not video_ready:
                self.logger.warning("Video not ready after timeout, trying to download anyway", worker_id=worker_id, timeout=max_wait, waited=waited)
            
            # Step 10: Download video
            self.logger.info("Downloading video", worker_id=worker_id)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            # Extract character name from image path for better naming
            char_name = describe_media_name(sanitized_path).replace(" · ", "_").replace(" ", "_")
            filename = f"{timestamp}_W{worker_id}_qwen_{char_name}.mp4"
            save_path = output_dir / filename
            
            # Find download button with multiple selectors
            # Based on actual HTML: <div aria-label="Download"><button class="message-footer-button-item"><i class="default-iconfont icon-line-download-02"></i></button></div>
            download_btn = None
            download_selectors = [
                'button.message-footer-button-item:has(i.icon-line-download-02)',
                'div[aria-label="Download"] button',
                'div[aria-label="Download"] button:has(i.icon-line-download-02)',
                'button:has(i.default-iconfont.icon-line-download-02)',
                'button.response-message-control-item-visible:has(i.icon-line-download-02)',
                'button.message-footer-button-item:has(i.default-iconfont)',
                'i.default-iconfont.icon-line-download-02',
                'i.icon-line-download-02',
                'button:has(i.icon-line-download-02)',
                'i[class*="download"]',
                'i[class*="icon-line-download"]',
                'button:has(i[class*="download"])',
                'div[role="button"]:has(i[class*="download"])',
                'a:has(i[class*="download"])',
                'button[aria-label*="download" i]',
                'button[aria-label*="Download" i]',
                '[data-testid*="download" i]',
                'button:has-text("Download")',
                'a:has-text("Download")'
            ]
            
            # Scroll to bottom to ensure download button is visible
            try:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1000)
            except Exception:
                pass
            
            # Use found button if we already found it
            if download_button_found:
                download_btn = download_button_found
                self.logger.info("Using previously found download button", worker_id=worker_id)
            else:
                # Try to find it again with scrolling
                self.logger.info("Searching for download button", worker_id=worker_id)
                for selector in download_selectors:
                    try:
                        candidate = page.locator(selector).first
                        count = await candidate.count()
                        if count > 0:
                            # Scroll to candidate
                            try:
                                await candidate.scroll_into_view_if_needed()
                                await page.wait_for_timeout(500)
                            except Exception:
                                pass
                            
                            is_visible = await candidate.is_visible()
                            if is_visible:
                                download_btn = candidate
                                self.logger.info(f"Found download button with selector: {selector}", worker_id=worker_id)
                                break
                    except Exception as e:
                        continue
            
            if download_btn is None:
                # Last attempt: scroll and search again
                self.logger.warning("Download button not found, trying one more time with scroll", worker_id=worker_id)
                try:
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await page.wait_for_timeout(2000)
                    
                    # Try all selectors one more time
                    for selector in download_selectors[:5]:  # Try first 5 most specific
                        try:
                            candidate = page.locator(selector).first
                            if await candidate.count() > 0:
                                await candidate.scroll_into_view_if_needed()
                                await page.wait_for_timeout(500)
                                is_visible = await candidate.is_visible()
                                if is_visible:
                                    download_btn = candidate
                                    self.logger.info(f"Found download button on retry: {selector}", worker_id=worker_id)
                                    break
                        except Exception:
                            continue
                except Exception:
                    pass
            
            if download_btn is None:
                # Take screenshot before raising error
                try:
                    debug_screenshot = output_dir / f"debug_W{worker_id}_no_download_button.png"
                    await page.screenshot(path=str(debug_screenshot), full_page=True)
                    self.logger.error(f"Download button not found, screenshot saved to {debug_screenshot}", worker_id=worker_id)
                except Exception:
                    pass
                raise Exception("Download button not found after trying all selectors and scrolling")
            
            # Verify the button is still valid and scroll to it
            try:
                if await download_btn.count() == 0:
                    raise Exception("Download button count is 0")
                
                # Ensure button is in view
                try:
                    await download_btn.scroll_into_view_if_needed()
                    await page.wait_for_timeout(1000)
                except Exception:
                    pass
                
                # Final visibility check
                is_visible = await download_btn.is_visible()
                if not is_visible:
                    self.logger.warning("Download button not visible, trying to scroll again", worker_id=worker_id)
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await page.wait_for_timeout(1000)
                    is_visible = await download_btn.is_visible()
                
                if not is_visible:
                    raise Exception("Download button not visible after scrolling")
                    
            except Exception as e:
                # Take screenshot before raising error
                try:
                    debug_screenshot = output_dir / f"debug_W{worker_id}_no_download_button.png"
                    await page.screenshot(path=str(debug_screenshot), full_page=True)
                    self.logger.error(f"Download button invalid, screenshot saved to {debug_screenshot}", worker_id=worker_id, error=str(e))
                except Exception:
                    pass
                raise Exception(f"Download button invalid: {e}")
            
            # Set up download with retry
            download_success = False
            for attempt in range(3):
                try:
                    self.logger.info(f"Attempting download, attempt {attempt + 1}/3", worker_id=worker_id)
                    async with page.expect_download(timeout=60000) as download_info:
                        # Click the button
                        await download_btn.click()
                        download = await download_info.value
                        await download.save_as(save_path)
                    download_success = True
                    break
                except Exception as e:
                    if attempt < 2:
                        self.logger.warning(f"Download attempt {attempt + 1} failed, retrying", worker_id=worker_id, error=str(e))
                        await page.wait_for_timeout(2000)
                        # Try to find button again
                        try:
                            download_btn = page.locator('div[aria-label="Download"] button').first
                            if await download_btn.count() > 0:
                                await download_btn.scroll_into_view_if_needed()
                                await page.wait_for_timeout(500)
                        except Exception:
                            pass
                    else:
                        raise
            
            if not download_success:
                raise Exception("Failed to download after 3 attempts")
            
            self.logger.info("Download complete", worker_id=worker_id, path=str(save_path))
            
            return save_path
            
        except Exception as e:
            self.logger.error("Video generation failed", error=str(e), worker_id=worker_id, exc_info=True)
            
            # Take screenshot for debugging
            if page:
                try:
                    screenshot_path = output_dir / f"error_W{worker_id}_{sanitized_path.stem}_screenshot.png"
                    await page.screenshot(path=str(screenshot_path), full_page=True)
                    self.logger.info("Screenshot saved", path=str(screenshot_path), worker_id=worker_id)
                except Exception:
                    pass
            
            return None
        finally:
            if page and not page.is_closed():
                try:
                    await page.close()
                    self.logger.debug("Closed Qwen page", worker_id=worker_id)
                except Exception as close_err:
                    self.logger.warning(
                        "Failed to close Qwen page",
                        worker_id=worker_id,
                        error=str(close_err)
                    )
            if ctx:
                try:
                    for ctx_page in ctx.pages:
                        if ctx_page is not page and not ctx_page.is_closed():
                            await ctx_page.close()
                except Exception as extra_close_err:
                    self.logger.debug(
                        "Failed to close auxiliary page",
                        worker_id=worker_id,
                        error=str(extra_close_err)
                    )
                try:
                    await ctx.close()
                    self.logger.debug("Closed Qwen context", worker_id=worker_id)
                except Exception as context_err:
                    self.logger.warning(
                        "Failed to close Qwen context",
                        worker_id=worker_id,
                        error=str(context_err)
                    )
            if owns_browser and browser_service:
                try:
                    await browser_service.cleanup()
                except Exception as cleanup_err:
                    self.logger.warning(
                        "Failed to cleanup browser service",
                        worker_id=worker_id,
                        error=str(cleanup_err)
                    )
    
    async def _prepare_browser_and_activate_video_mode(
        self,
        profile_name: str,
        worker_id: int,
        output_dir: Path
    ) -> Optional[Tuple[BrowserContext, Page]]:
        """
        Підготовка браузера: заходить на Qwen, чекає 10 секунд, 
        намагається активувати Video Generation до появи aspect ratio.
        
        Повертає (ctx, page) якщо успішно, None якщо не вдалось.
        """
        browser_pool = await get_browser_pool()
        ctx: Optional[BrowserContext] = None
        page: Optional[Page] = None
        
        try:
            self.logger.info(f"Preparing browser {worker_id} for video generation", profile=profile_name)
            
            # Створюємо контекст браузера
            ctx = await browser_pool.get_context(profile_name, headless=False, service_name="qwen")
            page = await ctx.new_page()
            
            # Заходимо на сторінку Qwen
            self.logger.info(f"Navigating to Qwen (worker {worker_id})")
            await page.goto(
                self.QWEN_URL,
                wait_until="domcontentloaded",
                timeout=60000
            )
            await page.wait_for_timeout(1000)
            await self._handle_access_verification(page, worker_id, stage="direct_navigation", suppress_exceptions=True)
            
            # Чекаємо після завантаження
            self.logger.info(f"Waiting after page load (worker {worker_id})")
            await page.wait_for_timeout(3000)
            
            # Прокручуємо вгору
            try:
                await page.evaluate("window.scrollTo(0, 0)")
            except Exception:
                pass
            
            # ПЕРЕВІРКА: Чи Video Generation вже активовано?
            # Спочатку перевіряємо aspect ratio - найнадійніший індикатор активного режиму
            # Селектори для aspect ratio: div.selector-text, span.anticon.selector-icon, або елементи з текстом ratio
            aspect_ratio_selectors = [
                'div.selector-text',
                'div[class*="selector-text"]',
                'span.anticon.selector-icon',
                'div.chat-ratio-selector',
                'div[class*="ratio"]',
                'div[class*="aspect"]',
                'div:has-text("16:9")',
                'div:has-text("9:16")',
                'div:has-text("1:1")',
                'div:has-text("4:3")',
                'div:has-text("3:4")'
            ]
            
            for selector in aspect_ratio_selectors:
                aspect_ratio_check = page.locator(selector).first
                if await aspect_ratio_check.count() > 0:
                    is_visible = await aspect_ratio_check.is_visible()
                    if is_visible:
                        # Додаткова перевірка: чи є текст з ratio (16:9, 9:16 тощо)
                        try:
                            text_content = await aspect_ratio_check.text_content()
                            if text_content and (':' in text_content or '16:9' in text_content or '9:16' in text_content or '1:1' in text_content):
                                # Перевіряємо чи вже вибрано 9:16
                                if '9:16' in text_content:
                                    self.logger.info(f"✅ Aspect ratio selector already present with 9:16 ({selector}) - Video Generation fully active (worker {worker_id})")
                                    return (ctx, page)  # Повертаємо підготовлений браузер
                                else:
                                    # Aspect ratio є, але не 9:16 - потрібно вибрати 9:16
                                    self.logger.info(f"✅ Aspect ratio selector found ({selector}) but not 9:16, selecting 9:16 (worker {worker_id})")
                                    await self._ensure_9_16_selected(page, worker_id)
                                    return (ctx, page)  # Повертаємо підготовлений браузер
                        except:
                            # Якщо не вдалось отримати текст, але елемент видимий - перевіряємо чи вже вибрано 9:16
                            # Спробуємо знайти текст 9:16 в інших місцях
                            try:
                                ratio_text_check = page.locator('div.selector-text, div[class*="selector-text"]').first
                                if await ratio_text_check.count() > 0:
                                    ratio_text = await ratio_text_check.text_content()
                                    if ratio_text and '9:16' in ratio_text:
                                        self.logger.info(f"✅ Aspect ratio selector already present with 9:16 ({selector}) - Video Generation fully active (worker {worker_id})")
                                        return (ctx, page)
                                    else:
                                        # Aspect ratio є, але не 9:16 - потрібно вибрати 9:16
                                        self.logger.info(f"✅ Aspect ratio selector found ({selector}) but not 9:16, selecting 9:16 (worker {worker_id})")
                                        await self._ensure_9_16_selected(page, worker_id)
                                        return (ctx, page)
                            except:
                                # Якщо не вдалось перевірити, вважаємо що потрібно вибрати 9:16
                                self.logger.info(f"✅ Aspect ratio selector found ({selector}), ensuring 9:16 is selected (worker {worker_id})")
                                await self._ensure_9_16_selected(page, worker_id)
                                return (ctx, page)  # Повертаємо підготовлений браузер
            
            # Додаткова перевірка: Якщо є span.prompt-input-input-func-type-text з "Video Generation" - режим вже активний!
            already_active_span = page.locator('span.prompt-input-input-func-type-text:has-text("Video Generation")').first
            if await already_active_span.count() > 0 and await already_active_span.is_visible():
                self.logger.info(f"✅ Video Generation already active (detected by span text) - checking aspect ratio (worker {worker_id})")
                # Перевіримо чи є aspect ratio
                for selector in aspect_ratio_selectors:
                    aspect_ratio_check = page.locator(selector).first
                    if await aspect_ratio_check.count() > 0:
                        is_visible = await aspect_ratio_check.is_visible()
                        if is_visible:
                            # Перевіряємо чи вже вибрано 9:16
                            try:
                                text_content = await aspect_ratio_check.text_content()
                                if text_content and '9:16' in text_content:
                                    self.logger.info(f"✅ Aspect ratio selector present with 9:16 ({selector}) - Video Generation fully active (worker {worker_id})")
                                    return (ctx, page)  # Повертаємо підготовлений браузер
                                else:
                                    # Aspect ratio є, але не 9:16 - потрібно вибрати 9:16
                                    self.logger.info(f"✅ Aspect ratio selector found ({selector}) but not 9:16, selecting 9:16 (worker {worker_id})")
                                    await self._ensure_9_16_selected(page, worker_id)
                                    return (ctx, page)  # Повертаємо підготовлений браузер
                            except:
                                # Якщо не вдалось отримати текст, перевіряємо інші місця
                                try:
                                    ratio_text_check = page.locator('div.selector-text, div[class*="selector-text"]').first
                                    if await ratio_text_check.count() > 0:
                                        ratio_text = await ratio_text_check.text_content()
                                        if ratio_text and '9:16' in ratio_text:
                                            self.logger.info(f"✅ Aspect ratio selector present with 9:16 ({selector}) - Video Generation fully active (worker {worker_id})")
                                            return (ctx, page)
                                        else:
                                            self.logger.info(f"✅ Aspect ratio selector found ({selector}) but not 9:16, selecting 9:16 (worker {worker_id})")
                                            await self._ensure_9_16_selected(page, worker_id)
                                            return (ctx, page)
                                except:
                                    # Якщо не вдалось перевірити, вважаємо що потрібно вибрати 9:16
                                    self.logger.info(f"✅ Aspect ratio selector found ({selector}), ensuring 9:16 is selected (worker {worker_id})")
                                    await self._ensure_9_16_selected(page, worker_id)
                                    return (ctx, page)  # Повертаємо підготовлений браузер
            
            # Намагаємося знайти та клікнути Video Generation кнопку
            video_gen_selectors = [
                # DIV selectors (most common on Qwen) - MUST BE FIRST!
                'div.chat-prompt-suggest-button:has(img.chat-prompt-suggest-button-img):has(div:has-text("Video Generation"))',
                'div.chat-prompt-suggest-button:has(div:has-text("Video Generation"))',
                'div.chat-prompt-suggest-button.normal:has(div:has-text("Video Generation"))',
                'div.chat-prompt-suggest-button:has-text("Video Generation")',
                'div.chat-prompt-suggest-button:has(img.chat-prompt-suggest-button-img)',
                'div[class*="chat-prompt-suggest-button"]:has(div:has-text("Video"))',
                'div[class*="chat-prompt-suggest-button"]:has-text("Video Generation")',
                # Data attribute selectors
                'div[data-spm-anchor-id*="a2ty"]:has-text("Video Generation")',
                'div[data-spm-anchor-id]:has-text("Video Generation")',
                # Button selectors (fallback)
                'button.chat-prompt-suggest-button:has(img.chat-prompt-suggest-button-img):has(div:has-text("Video Generation"))',
                'button.chat-prompt-suggest-button:has(img.chat-prompt-suggest-button-img)',
                'button.chat-prompt-suggest-button:has(div:has-text("Video Generation"))',
                'button.chat-prompt-suggest-button.normal:has(div:has-text("Video Generation"))',
                'button.chat-prompt-suggest-button:has-text("Video Generation")',
                'button[class*="chat-prompt-suggest-button"]:has(div:has-text("Video"))',
                'button:has-text("Video Generation")',
                'button[class*="suggest"]:has-text("Video Generation")',
                'div[class*="suggest"] button:has-text("Video Generation")',
                'button:has-text("Video")',
                'div[role="button"]:has-text("Video Generation")',
                'a:has-text("Video Generation")'
            ]
            
            max_click_attempts = 10  # До 10 спроб клікнути
            click_success = False
            
            for attempt in range(max_click_attempts):
                # ПЕРЕВІРКА: Чи aspect ratio вже з'явився? Якщо так - не клікаємо!
                for selector in aspect_ratio_selectors:
                    aspect_ratio_check = page.locator(selector).first
                    if await aspect_ratio_check.count() > 0:
                        is_visible = await aspect_ratio_check.is_visible()
                        if is_visible:
                            try:
                                text_content = await aspect_ratio_check.text_content()
                                if text_content and (':' in text_content or '16:9' in text_content or '9:16' in text_content or '1:1' in text_content):
                                    # Перевіряємо чи вже вибрано 9:16
                                    if '9:16' in text_content:
                                        self.logger.info(f"✅ Aspect ratio selector found with 9:16 during attempt {attempt + 1} ({selector}) - Video Generation already active (worker {worker_id})")
                                        click_success = True
                                        break
                                    else:
                                        # Aspect ratio є, але не 9:16 - потрібно вибрати 9:16
                                        self.logger.info(f"✅ Aspect ratio selector found but not 9:16 during attempt {attempt + 1} ({selector}), selecting 9:16 (worker {worker_id})")
                                        await self._ensure_9_16_selected(page, worker_id)
                                        click_success = True
                                        break
                            except:
                                # Якщо не вдалось отримати текст, перевіряємо інші місця
                                try:
                                    ratio_text_check = page.locator('div.selector-text, div[class*="selector-text"]').first
                                    if await ratio_text_check.count() > 0:
                                        ratio_text = await ratio_text_check.text_content()
                                        if ratio_text and '9:16' in ratio_text:
                                            self.logger.info(f"✅ Aspect ratio selector found with 9:16 during attempt {attempt + 1} ({selector}) - Video Generation already active (worker {worker_id})")
                                            click_success = True
                                            break
                                        else:
                                            self.logger.info(f"✅ Aspect ratio selector found but not 9:16 during attempt {attempt + 1} ({selector}), selecting 9:16 (worker {worker_id})")
                                            await self._ensure_9_16_selected(page, worker_id)
                                            click_success = True
                                            break
                                except:
                                    # Якщо не вдалось перевірити, вважаємо що потрібно вибрати 9:16
                                    self.logger.info(f"✅ Aspect ratio selector found during attempt {attempt + 1} ({selector}), ensuring 9:16 is selected (worker {worker_id})")
                                    await self._ensure_9_16_selected(page, worker_id)
                                    click_success = True
                                    break
                
                if click_success:
                    break
                
                self.logger.info(f"Attempting to click Video Generation button (attempt {attempt + 1}/{max_click_attempts}, worker {worker_id})")
                
                # Оновлюємо стан сторінки періодично
                if attempt > 0 and attempt % 3 == 0:
                    try:
                        await page.wait_for_load_state("networkidle", timeout=5000)
                    except:
                        try:
                            await page.wait_for_load_state("domcontentloaded", timeout=3000)
                        except:
                            pass
                    try:
                        await page.evaluate("window.scrollTo(0, 0)")
                        await page.wait_for_timeout(500)
                    except:
                        pass
                
                # Шукаємо кнопку
                video_gen_button = None
                found_selector = None
                for selector in video_gen_selectors:
                    try:
                        button_locator = page.locator(selector).first
                        count = await button_locator.count()
                        if count > 0:
                            try:
                                await button_locator.wait_for(state="visible", timeout=2000)
                                is_visible = await button_locator.is_visible()
                                if is_visible:
                                    # CRITICAL: Перевіряємо що це КНОПКА, а не span з текстом "Video Generation"
                                    # Якщо це span.prompt-input-input-func-type-text - це вже активований текст, не кнопка!
                                    tag_name = await button_locator.evaluate("el => el.tagName.toLowerCase()")
                                    class_name = await button_locator.evaluate("el => el.className || ''")
                                    
                                    if tag_name == "span" and "prompt-input-input-func-type-text" in class_name:
                                        self.logger.info(f"Skipping span.prompt-input-input-func-type-text (already active text, not button)", worker_id=worker_id)
                                        continue
                                    
                                    video_gen_button = button_locator
                                    found_selector = selector
                                    self.logger.info(f"Found Video Generation button with selector: {selector} (attempt {attempt + 1})", worker_id=worker_id)
                                    break
                            except PlaywrightTimeout:
                                continue
                    except Exception:
                        continue
                
                # Якщо НЕ знайшли кнопку - логуємо це
                if video_gen_button is None:
                    self.logger.warning(f"Video Generation button NOT found (attempt {attempt + 1}/{max_click_attempts})", worker_id=worker_id)
                    # Після останньої спроби - зробимо скриншот
                    if attempt == max_click_attempts - 1:
                        try:
                            debug_screenshot = output_dir / f"debug_W{worker_id}_video_gen_failed.png"
                            await page.screenshot(path=str(debug_screenshot), full_page=True)
                            self.logger.error(f"Failed to activate Video Generation after {max_click_attempts} attempts (worker {worker_id})")
                            self.logger.info(f"Screenshot saved: {debug_screenshot}", worker_id=worker_id)
                        except Exception:
                            pass
                    else:
                        # Чекаємо перед наступною спробою
                        await page.wait_for_timeout(1000)
                    continue  # Пробуємо ще раз
                
                # Якщо знайшли кнопку - клікаємо
                if video_gen_button is not None:
                    try:
                        await self._safe_click(page, video_gen_button, worker_id, f"Video Generation button (attempt {attempt + 1})")
                        await page.wait_for_timeout(1500)  # Чекаємо після кліку
                        
                        # Перевіряємо чи з'явився aspect ratio (індикатор успіху)
                        aspect_ratio_check = page.locator('div.chat-ratio-selector, div[class*="ratio"], div[class*="aspect"]').first
                        if await aspect_ratio_check.count() > 0:
                            is_visible = await aspect_ratio_check.is_visible()
                            if is_visible:
                                # Додаткова перевірка: чи є текст з ratio
                                try:
                                    ratio_text = await aspect_ratio_check.text_content()
                                    if ratio_text and (':' in ratio_text or '16:9' in ratio_text or '9:16' in ratio_text):
                                        click_success = True
                                        self.logger.info(f"✅ Video Generation activated! Aspect ratio found: '{ratio_text.strip()[:50]}' (worker {worker_id})")
                                        break
                                except:
                                    # Якщо не вдалось отримати текст, але елемент видимий - вважаємо успіхом
                                    click_success = True
                                    self.logger.info(f"✅ Video Generation activated! Aspect ratio selector visible (worker {worker_id})")
                                    break
                    except Exception as click_err:
                        self.logger.warning(f"Click attempt {attempt + 1} failed (worker {worker_id})", error=str(click_err))
                
                # Якщо не вдалось - чекаємо перед наступною спробою
                if not click_success:
                    wait_time = 2000 if attempt < max_click_attempts - 1 else 0
                    if wait_time > 0:
                        await page.wait_for_timeout(wait_time)
            
            if not click_success:
                self.logger.error(f"Failed to activate Video Generation after {max_click_attempts} attempts (worker {worker_id})")
                try:
                    debug_screenshot = output_dir / f"debug_W{worker_id}_video_gen_failed.png"
                    await page.screenshot(path=str(debug_screenshot), full_page=True)
                    self.logger.info(f"Screenshot saved: {debug_screenshot}")
                except Exception:
                    pass
                return None
            
            # Фінальна перевірка aspect ratio перед поверненням
            await page.wait_for_timeout(1000)
            final_check = page.locator('div.chat-ratio-selector, div[class*="ratio"]').first
            if await final_check.count() == 0 or not await final_check.is_visible():
                self.logger.error(f"Aspect ratio selector disappeared after activation (worker {worker_id})")
                return None
            
            self.logger.info(f"✅ Browser {worker_id} ready for video generation!")
            return (ctx, page)
            
        except Exception as e:
            self.logger.error(f"Error preparing browser {worker_id}", error=str(e), exc_info=True)
            # Cleanup
            try:
                if page and not page.is_closed():
                    await page.close()
            except Exception:
                pass
            try:
                if ctx:
                    await ctx.close()
            except Exception:
                pass
            return None

    async def batch_generate_videos(
        self,
        image_paths: List[Path],
        prompts: List[str],
        profile_names: List[str],
        output_dir: Optional[Path] = None
    ) -> List[Optional[Path]]:
        """
        Generate videos from multiple images with sequential browser preparation
        and parallel video generation.
        
        Алгоритм:
        1. Послідовно підготовлюємо браузери (один за одним)
        2. Кожен браузер після успішної підготовки (aspect ratio з'явився) дозволяє запустити наступний
        3. Всі підготовлені браузери паралельно виконують генерацію відео
        
        Args:
            image_paths: List of image paths
            prompts: List of prompts (one per image, or single prompt for all)
            profile_names: List of Chrome profile names
            output_dir: Output directory (defaults to config)
            
        Returns:
            List of output file paths (None for failed videos)
        """
        output_dir = output_dir or self.config.qwen_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # If single prompt provided, use for all images
        if len(prompts) == 1 and len(image_paths) > 1:
            prompts = prompts * len(image_paths)
        
        if len(prompts) != len(image_paths):
            raise ValueError("Number of prompts must match number of images")
        
        self.logger.info("Starting batch video generation", image_count=len(image_paths))

        # Підготовка браузерів: зберігаємо готові (ctx, page, img_path, prompt, worker_id)
        prepared_browsers: List[Tuple[BrowserContext, Page, Path, str, int]] = []
        
        # Послідовно підготовлюємо браузери
        for idx, (img_path, prompt) in enumerate(zip(image_paths, prompts)):
            profile = profile_names[idx % len(profile_names)]
            worker_id = idx + 1
            
            self.logger.info(f"Preparing browser {worker_id}/{len(image_paths)}")
            
            result = await self._prepare_browser_and_activate_video_mode(
                profile,
                worker_id,
                output_dir
            )
            
            if result is None:
                self.logger.warning(f"Failed to prepare browser {worker_id}, skipping")
                continue
            
            ctx, page = result
            prepared_browsers.append((ctx, page, img_path, prompt, worker_id))
            self.logger.info(f"✅ Browser {worker_id} prepared! Total prepared: {len(prepared_browsers)}/{len(image_paths)}")
        
        if not prepared_browsers:
            self.logger.error("No browsers were successfully prepared")
            return [None] * len(image_paths)
        
        self.logger.info(f"All {len(prepared_browsers)} browsers prepared. Starting parallel video generation...")
        
        # Тепер паралельно виконуємо генерацію відео для всіх підготовлених браузерів
        async def generate_video_for_browser(
            ctx: BrowserContext,
            page: Page,
            img_path: Path,
            prompt: str,
            worker_id: int
        ) -> Optional[Path]:
            """Генерує відео в підготовленому браузері (Video Generation вже активований)."""
            self.logger.info(f"🚀 Starting video generation for worker {worker_id}, image: {img_path.name}")
            try:
                sanitized_path = sanitize_path(img_path)
                self.logger.info(f"Sanitized path: {sanitized_path.name} (worker {worker_id})")
                
                # Перевіряємо що Video Generation все ще активний
                aspect_ratio_check = page.locator('div.chat-ratio-selector, div[class*="ratio"]').first
                if await aspect_ratio_check.count() == 0 or not await aspect_ratio_check.is_visible():
                    self.logger.warning(f"Video Generation mode lost, reactivating (worker {worker_id})")
                    # Спробуємо реактивувати
                    try:
                        video_gen_button = page.locator('div.chat-prompt-suggest-button:has(div:has-text("Video Generation"))').first
                        if await video_gen_button.count() == 0:
                            video_gen_button = page.locator('button.chat-prompt-suggest-button:has(div:has-text("Video Generation"))').first
                        if await video_gen_button.count() > 0:
                            await self._safe_click(page, video_gen_button, worker_id, "Video Generation button (reactivation)")
                            await page.wait_for_timeout(1500)
                    except Exception:
                        pass
                
                # Виконуємо генерацію відео (завантаження зображення, введення промпту, очікування)
                # Використовуємо _complete_generation_after_ratio оскільки Video Generation вже активний
                await self._complete_generation_after_ratio(page, sanitized_path, prompt, output_dir, worker_id)
                
                # Очікуємо завершення генерації та завантаження
                final_path = await self._wait_and_download_video(page, output_dir, worker_id, sanitized_path)
                return final_path
                
            except Exception as exc:
                self.logger.error(f"Video generation failed for worker {worker_id}", error=str(exc), exc_info=True)
                return None
            finally:
                # Cleanup
                try:
                    if page and not page.is_closed():
                        await page.close()
                except Exception as page_err:
                    self.logger.debug(f"Failed to close page (worker {worker_id})", error=str(page_err))
                try:
                    if ctx:
                        await ctx.close()
                        self.logger.debug(f"Closed context (worker {worker_id})")
                except Exception as ctx_err:
                    self.logger.warning(f"Failed to close context (worker {worker_id})", error=str(ctx_err))
        
        # Запускаємо всі генерації паралельно
        # Зберігаємо мапінг worker_id -> індекс в image_paths для правильного розподілу результатів
        worker_to_index = {}
        generation_tasks = []
        
        self.logger.info(f"Creating generation tasks for {len(prepared_browsers)} browsers")
        for ctx, page, img_path, prompt, worker_id in prepared_browsers:
            # Знаходимо індекс цього зображення в оригінальному списку
            try:
                idx = image_paths.index(img_path)
            except ValueError:
                # Якщо не знайдено (не повинно бути), використовуємо worker_id - 1
                idx = worker_id - 1
            
            worker_to_index[worker_id] = idx
            self.logger.info(f"Creating task for worker {worker_id}, image: {img_path.name}")
            generation_tasks.append(
                generate_video_for_browser(ctx, page, img_path, prompt, worker_id)
            )
        
        self.logger.info(f"Starting {len(generation_tasks)} parallel generation tasks")
        # Очікуємо завершення всіх генерацій
        results = await asyncio.gather(*generation_tasks, return_exceptions=True)
        self.logger.info(f"All generation tasks completed, processing results")
        
        # Формуємо результат (з урахуванням того, що не всі браузери могли бути підготовлені)
        output_paths: List[Optional[Path]] = [None] * len(image_paths)
        for i, (ctx, page, img_path, prompt, worker_id) in enumerate(prepared_browsers):
            idx = worker_to_index[worker_id]
            if idx < len(output_paths):
                result = results[i]
                if isinstance(result, Exception):
                    self.logger.error(f"Task exception for worker {worker_id}", error=str(result))
                    output_paths[idx] = None
                else:
                    output_paths[idx] = result
        
        successful = sum(1 for p in output_paths if p is not None)
        self.logger.info(
            "Batch video generation complete",
            successful=successful,
            failed=len(output_paths) - successful,
            total=len(output_paths),
            prepared_browsers=len(prepared_browsers)
        )
        
        return output_paths

