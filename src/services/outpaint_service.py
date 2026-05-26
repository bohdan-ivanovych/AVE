"""Outpaint service for batch image outpainting using Pixelcut."""

import asyncio
from pathlib import Path
from typing import List, Optional
from datetime import datetime
from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from src.config import get_config
from src.services.logger import get_logger_service
from src.services.browser_service import BrowserService
from src.services.browser_pool import get_browser_pool
from src.utils.path_utils import sanitize_path
from src.utils.name_utils import describe_media_name


class OutpaintService:
    """Service for batch outpainting images to 9:16 aspect ratio using Pixelcut."""
    
    PIXELCUT_URL = "https://www.pixelcut.ai/uncrop/ai-outpainting"
    
    def __init__(self, config=None):
        self.config = config or get_config()
        self.logger = get_logger_service().get_logger("outpaint")
        self.browser_service = BrowserService(self.config)
    
    async def outpaint_single_image(
        self,
        image_path: Path,
        profile_name: str,
        output_dir: Path,
        worker_id: int = 1
    ) -> Optional[Path]:
        """
        Outpaint a single image to 9:16 aspect ratio.
        
        Args:
            image_path: Path to image file
            profile_name: Chrome profile name
            output_dir: Directory to save output
            worker_id: Worker identifier
            
        Returns:
            Path to downloaded image or None if failed
        """
        sanitized_path = sanitize_path(image_path)
        if not sanitized_path.exists():
            self.logger.error("Image not found", path=str(sanitized_path))
            return None
        
        browser_pool = None
        ctx = None
        page = None
        
        try:
            await self.browser_service.start()
            
            # Get browser context from pool
            browser_pool = await get_browser_pool()
            ctx = await browser_pool.get_context(profile_name, headless=False)
            page = await ctx.new_page()
            
            self.logger.info("Navigating to Pixelcut", worker_id=worker_id, image=sanitized_path.name)
            
            # Navigate to Pixelcut
            await page.goto(
                self.PIXELCUT_URL,
                wait_until="domcontentloaded",
                timeout=60000
            )
            
            # Wait for page to be fully loaded
            self.logger.info("Waiting for Pixelcut page to load", worker_id=worker_id)
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except:
                await page.wait_for_load_state("domcontentloaded", timeout=10000)
            
            await page.wait_for_timeout(3000)
            
            # Upload image
            self.logger.info("Waiting for upload element to appear", worker_id=worker_id)
            
            # Wait for first interactive element (upload button or file input) to appear
            upload_element_found = False
            max_wait_attempts = 30  # 30 seconds total
            
            for attempt in range(max_wait_attempts):
                # Try to find file input directly first (might be hidden but present)
                file_input = page.locator('input[type="file"]').first
                file_input_count = await file_input.count()
                
                if file_input_count > 0:
                    try:
                        await file_input.wait_for(state="attached", timeout=2000)
                        upload_element_found = True
                        self.logger.info("File input found", worker_id=worker_id, attempt=attempt + 1)
                        break
                    except:
                        pass
                
                # If file input not found, check for upload button
                upload_button = page.locator('button:has-text("Upload image"), button:has-text("Upload"), button[aria-label*="upload" i]').first
                upload_button_count = await upload_button.count()
                
                if upload_button_count > 0:
                    try:
                        is_visible = await upload_button.is_visible()
                        if is_visible:
                            upload_element_found = True
                            self.logger.info("Upload button found, will click it", worker_id=worker_id, attempt=attempt + 1)
                            break
                    except:
                        pass
                
                # Wait before next attempt
                if attempt < max_wait_attempts - 1:
                    await page.wait_for_timeout(1000)
            
            if not upload_element_found:
                raise Exception("Upload element (file input or button) not found after waiting")
            
            # Try to find file input directly first (might be hidden but present)
            file_input = page.locator('input[type="file"]').first
            file_input_count = await file_input.count()
            
            # If file input not found or not attached, click upload button to trigger it
            if file_input_count == 0:
                self.logger.info("File input not found, clicking upload button", worker_id=worker_id)
                # Use .first to avoid strict mode violation (there might be multiple buttons)
                upload_button = page.locator('button:has-text("Upload image"), button:has-text("Upload"), button[aria-label*="upload" i]').first
                await upload_button.wait_for(state="visible", timeout=30000)
                await upload_button.click()
                await page.wait_for_timeout(2000)  # Increased wait after clicking
                # Try to find file input again after clicking
                file_input = page.locator('input[type="file"]').first
                file_input_count = await file_input.count()
            
            if file_input_count == 0:
                raise Exception("File input not found after clicking upload button")
            
            # Wait for file input to be attached to DOM
            try:
                await file_input.wait_for(state="attached", timeout=5000)
            except Exception:
                # If wait_for fails, try to use it anyway
                self.logger.warning("File input wait_for failed, proceeding anyway", worker_id=worker_id)
            
            await file_input.set_input_files(str(sanitized_path.absolute()))
            self.logger.info("Image uploaded, waiting for processing", worker_id=worker_id)
            await page.wait_for_timeout(5000)  # Wait for image to load
            
            # Select aspect ratio 9:16
            self.logger.info("Selecting 9:16 aspect ratio", worker_id=worker_id)
            
            # Click on the aspect ratio selector (custom dropdown)
            # The selector has class with "text-left focus:outline-none" and role="combobox"
            aspect_selector = page.locator('div[role="combobox"]').first
            if await aspect_selector.count() > 0:
                await aspect_selector.click()
                await page.wait_for_timeout(1500)
            
            # Wait for dropdown content wrapper with better error handling
            nine_sixteen_found = False
            popper_wrapper = page.locator('[data-radix-popper-content-wrapper]')
            
            try:
                # Try to wait for dropdown with timeout
                await popper_wrapper.wait_for(state="visible", timeout=10000)
                await page.wait_for_timeout(500)
            except Exception as e:
                self.logger.warning(
                    "Dropdown did not appear, trying alternative methods",
                    worker_id=worker_id,
                    error=str(e)
                )
                # Try clicking the selector again
                try:
                    await aspect_selector.click()
                    await page.wait_for_timeout(2000)
                    # Try waiting again with shorter timeout
                    try:
                        await popper_wrapper.wait_for(state="visible", timeout=5000)
                    except:
                        pass
                except:
                    pass
            
            # Find and click 9:16 option
            # Try multiple selectors for 9:16
            
            # Method 1: Check if dropdown is visible and try direct text match
            if await popper_wrapper.count() > 0:
                try:
                    is_visible = await popper_wrapper.is_visible()
                    if is_visible:
                        nine_sixteen_option = page.locator('text=/9:16|9 : 16|9\\/16/i').first
                        if await nine_sixteen_option.count() > 0:
                            await nine_sixteen_option.click()
                            nine_sixteen_found = True
                            self.logger.info("Selected 9:16 via text match", worker_id=worker_id)
                except:
                    pass
            
            # Method 2: Search in all options (even if dropdown not visible, options might be in DOM)
            if not nine_sixteen_found:
                try:
                    all_options = page.locator('[role="option"]')
                    count = await all_options.count()
                    for i in range(count):
                        option = all_options.nth(i)
                        try:
                            text = await option.text_content()
                            if text and ('9:16' in text or '9 : 16' in text or '9/16' in text or text.strip() == '9:16'):
                                await option.click()
                                nine_sixteen_found = True
                                self.logger.info("Selected 9:16 via option search", worker_id=worker_id)
                                break
                        except:
                            continue
                except Exception as e:
                    self.logger.debug("Option search failed", worker_id=worker_id, error=str(e))
            
            # Method 3: Try to find by aria-label or data attributes
            if not nine_sixteen_found:
                try:
                    # Look for any element containing 9:16
                    candidates = page.locator('*:has-text("9:16"), *:has-text("9 : 16")')
                    if await candidates.count() > 0:
                        await candidates.first.click()
                        nine_sixteen_found = True
                        self.logger.info("Selected 9:16 via fallback", worker_id=worker_id)
                except:
                    pass
            
            # Method 4: Try clicking selector multiple times and retry
            if not nine_sixteen_found:
                self.logger.warning("9:16 option not found, retrying dropdown click", worker_id=worker_id)
                try:
                    # Retry clicking the selector
                    for retry in range(2):
                        await aspect_selector.click()
                        await page.wait_for_timeout(2000)
                        # Check if dropdown appeared
                        if await popper_wrapper.count() > 0 and await popper_wrapper.is_visible():
                            # Try finding 9:16 again
                            nine_sixteen_option = page.locator('text=/9:16|9 : 16|9\\/16/i').first
                            if await nine_sixteen_option.count() > 0:
                                await nine_sixteen_option.click()
                                nine_sixteen_found = True
                                self.logger.info("Selected 9:16 after retry", worker_id=worker_id)
                                break
                except Exception as e:
                    self.logger.debug("Retry failed", worker_id=worker_id, error=str(e))
            
            if not nine_sixteen_found:
                self.logger.warning("9:16 option not found, continuing anyway", worker_id=worker_id)
            
            await page.wait_for_timeout(2000)
            
            # Resize image to approximately 78% using resize handles
            self.logger.info("Resizing image to 78% using resize handles", worker_id=worker_id)
            
            # Wait a bit for the image to be fully loaded in the editor
            await page.wait_for_timeout(2000)
            
            # Find the konvajs-content container
            konvajs_container = page.locator('div.konvajs-content[role="presentation"]').first
            if await konvajs_container.count() == 0:
                self.logger.warning("Konvajs container not found, trying alternative selectors", worker_id=worker_id)
                konvajs_container = page.locator('div[class*="konvajs"]').first
            
            if await konvajs_container.count() > 0:
                # Get container dimensions
                container_box = await konvajs_container.bounding_box()
                if container_box:
                    # Find resize handles (circles at corners)
                    # They typically have cursor classes like cursor-nw-resize, cursor-ne-resize, etc.
                    # Or they might be in a separate container with z-index
                    resize_handles = page.locator(
                        'div[class*="cursor-nw-resize"], '
                        'div[class*="cursor-ne-resize"], '
                        'div[class*="cursor-sw-resize"], '
                        'div[class*="cursor-se-resize"], '
                        'div[class*="resize"], '
                        'div[style*="cursor"][style*="resize"], '
                        'div[class*="handle"]'
                    )
                    
                    # Try to find handles by looking for elements with resize cursor styles
                    # Or look for the container with resize handles (from user's description)
                    handles_container = page.locator(
                        'div[style*="position: absolute"][style*="z-index: 10"]'
                    ).first
                    
                    if await handles_container.count() > 0:
                        self.logger.info("Found resize handles container", worker_id=worker_id)
                        handles_box = await handles_container.bounding_box()
                        
                        if handles_box:
                            # Calculate 78% of current size
                            # We need to drag the corner handles inward
                            # Let's use the top-left corner (nw-resize) or bottom-right (se-resize)
                            
                            # Find the corner handles
                            nw_handle = handles_container.locator('div[class*="cursor-nw-resize"], div[class*="nw"]').first
                            se_handle = handles_container.locator('div[class*="cursor-se-resize"], div[class*="se"]').first
                            
                            # Try to drag bottom-right corner (se-resize) inward to reduce size
                            if await se_handle.count() > 0:
                                self.logger.info("Using SE resize handle to reduce size", worker_id=worker_id)
                                se_box = await se_handle.bounding_box()
                                if se_box:
                                    # Calculate new position (reduce by 22% to get 78%)
                                    # Move handle inward by 11% from each side
                                    reduction = 0.22
                                    new_x = se_box['x'] - (handles_box['width'] * reduction)
                                    new_y = se_box['y'] - (handles_box['height'] * reduction)
                                    
                                    # Drag the handle
                                    await se_handle.hover()
                                    await page.wait_for_timeout(200)
                                    await page.mouse.down()
                                    await page.wait_for_timeout(100)
                                    await page.mouse.move(new_x, new_y, steps=10)
                                    await page.wait_for_timeout(200)
                                    await page.mouse.up()
                                    await page.wait_for_timeout(500)
                            elif await nw_handle.count() > 0:
                                self.logger.info("Using NW resize handle to reduce size", worker_id=worker_id)
                                nw_box = await nw_handle.bounding_box()
                                if nw_box:
                                    # Move top-left corner outward (down and right) to reduce visible size
                                    reduction = 0.22
                                    new_x = nw_box['x'] + (handles_box['width'] * reduction)
                                    new_y = nw_box['y'] + (handles_box['height'] * reduction)
                                    
                                    await nw_handle.hover()
                                    await page.wait_for_timeout(200)
                                    await page.mouse.down()
                                    await page.wait_for_timeout(100)
                                    await page.mouse.move(new_x, new_y, steps=10)
                                    await page.wait_for_timeout(200)
                                    await page.mouse.up()
                                    await page.wait_for_timeout(500)
                            else:
                                # Fallback: try to drag from center of handles container
                                self.logger.info("Using fallback drag method", worker_id=worker_id)
                                center_x = handles_box['x'] + handles_box['width'] / 2
                                center_y = handles_box['y'] + handles_box['height'] / 2
                                
                                # Drag inward
                                reduction = 0.11
                                new_x = center_x - (handles_box['width'] * reduction)
                                new_y = center_y - (handles_box['height'] * reduction)
                                
                                await page.mouse.move(center_x, center_y)
                                await page.wait_for_timeout(200)
                                await page.mouse.down()
                                await page.wait_for_timeout(100)
                                await page.mouse.move(new_x, new_y, steps=10)
                                await page.wait_for_timeout(200)
                                await page.mouse.up()
                                await page.wait_for_timeout(500)
                    else:
                        self.logger.warning("Resize handles container not found, trying keyboard shortcuts", worker_id=worker_id)
                        # Fallback to keyboard shortcuts
                        for _ in range(6):
                            await page.keyboard.press('Control+-')
                            await page.wait_for_timeout(400)
            else:
                self.logger.warning("Konvajs container not found, using keyboard shortcuts", worker_id=worker_id)
                # Fallback to keyboard shortcuts
                for _ in range(6):
                    await page.keyboard.press('Control+-')
                    await page.wait_for_timeout(400)
            
            await page.wait_for_timeout(2000)
            
            # Click Generate button
            self.logger.info("Clicking Generate button", worker_id=worker_id)
            # Use more specific selector based on the HTML provided
            generate_button = page.locator(
                'button.inline-flex.items-center:has-text("Generate"), '
                'button:has-text("Generate")[class*="bg-ui-selected"]'
            ).first
            
            # Wait for button to be visible and enabled (data-state should not be "closed" or disabled)
            await generate_button.wait_for(state="visible", timeout=30000)
            
            # Check if button is enabled (data-state should not be "closed" or button should not be disabled)
            is_enabled = await generate_button.is_enabled()
            if not is_enabled:
                self.logger.warning("Generate button not enabled, waiting...", worker_id=worker_id)
                # Wait a bit more for button to become enabled
                await page.wait_for_timeout(2000)
                is_enabled = await generate_button.is_enabled()
            
            if is_enabled:
                await generate_button.click()
            else:
                # Try to click anyway (might be a false negative)
                self.logger.warning("Generate button appears disabled, clicking anyway", worker_id=worker_id)
                await generate_button.click(force=True)
            
            # Wait for generation to complete
            self.logger.info("Waiting for outpainting to complete", worker_id=worker_id)
            await page.wait_for_timeout(10000)  # Initial wait
            
            # Wait for result image to appear (check for loading indicators to disappear)
            max_wait = 120  # 2 minutes max
            waited = 0
            image_ready = False
            
            while waited < max_wait:
                # Check for loading indicators to disappear
                loading = page.locator('[class*="loading"], [class*="spinner"], [aria-busy="true"]')
                loading_count = await loading.count()
                
                if loading_count == 0:
                    # No loading indicators, check if result image is visible
                    # The result should be in the canvas or as an img element
                    result_canvas = page.locator('div.konvajs-content canvas, canvas[width], img[src*="data:"], img[src*="blob:"]').first
                    if await result_canvas.count() > 0:
                        is_visible = await result_canvas.is_visible()
                        if is_visible:
                            image_ready = True
                            self.logger.info("Result image is ready", worker_id=worker_id)
                            break
                
                await page.wait_for_timeout(3000)
                waited += 3
            
            if not image_ready:
                self.logger.warning("Result image not ready after timeout, proceeding anyway", worker_id=worker_id, timeout=max_wait)
            
            # Wait a bit more for image to fully render
            await page.wait_for_timeout(2000)
            
            # Download the image using dropdown menu
            self.logger.info("Downloading outpainted image", worker_id=worker_id)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            # Extract character name from image path for better naming
            char_name = describe_media_name(sanitized_path).replace(" · ", "_").replace(" ", "_")
            filename = f"{timestamp}_W{worker_id}_outpaint_{char_name}.png"
            save_path = output_dir / filename
            
            # Step 1: Click the first Download button (opens dropdown menu)
            # Button with id="radix-_r_a_" and aria-haspopup="menu"
            download_dropdown_button = page.locator(
                'button#radix-_r_a_[aria-haspopup="menu"], '
                'button[aria-haspopup="menu"]:has-text("Download")[class*="bg-ui-selected"]'
            ).first
            
            if await download_dropdown_button.count() == 0:
                # Fallback: try to find by class and text
                download_dropdown_button = page.locator(
                    'button:has-text("Download")[class*="bg-ui-selected"][aria-haspopup="menu"]'
                ).first
            
            if await download_dropdown_button.count() == 0:
                raise Exception("Download dropdown button not found")
            
            self.logger.info("Clicking Download dropdown button", worker_id=worker_id)
            await download_dropdown_button.click()
            await page.wait_for_timeout(1000)  # Wait for dropdown menu to open
            
            # Step 2: Click the Download option in the dropdown menu
            # Button with class bg-ui-quaternary
            download_menu_option = page.locator(
                'button:has-text("Download")[class*="bg-ui-quaternary"], '
                'button:has-text("Download")[class*="bg-ui-secondaryDark"]'
            ).first
            
            if await download_menu_option.count() == 0:
                raise Exception("Download menu option not found")
            
            self.logger.info("Clicking Download menu option", worker_id=worker_id)
            
            # Set up download and click
            async with page.expect_download(timeout=60000) as download_info:
                await download_menu_option.click()
                download = await download_info.value
                await download.save_as(save_path)
            
            self.logger.info("Download complete", worker_id=worker_id, path=str(save_path))
            
            return save_path
            
        except Exception as e:
            self.logger.error("Outpaint failed", error=str(e), worker_id=worker_id, exc_info=True)
            
            # Take screenshot for debugging if page is available
            if page:
                try:
                    screenshot_path = output_dir / f"error_W{worker_id}_{sanitized_path.stem}_screenshot.png"
                    await page.screenshot(path=str(screenshot_path), full_page=True)
                    self.logger.info("Screenshot saved for debugging", path=str(screenshot_path), worker_id=worker_id)
                except Exception as screenshot_err:
                    self.logger.warning("Failed to save screenshot", error=str(screenshot_err), worker_id=worker_id)
            
            return None
        finally:
            if page and not page.is_closed():
                try:
                    await page.close()
                    self.logger.debug("Closed Pixelcut page", worker_id=worker_id)
                except Exception as close_err:
                    self.logger.warning(
                        "Failed to close Pixelcut page",
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
                        "Failed to close auxiliary outpaint page",
                        worker_id=worker_id,
                        error=str(extra_close_err)
                    )
                try:
                    await ctx.close()
                    self.logger.debug("Closed Pixelcut context", worker_id=worker_id)
                except Exception as context_err:
                    self.logger.warning(
                        "Failed to close Pixelcut context",
                        worker_id=worker_id,
                        error=str(context_err)
                    )
    
    async def batch_outpaint(
        self,
        image_paths: List[Path],
        profile_names: List[str],
        output_dir: Optional[Path] = None
    ) -> List[Optional[Path]]:
        """
        Outpaint multiple images in parallel, opening one browser per image.
        
        Args:
            image_paths: List of image paths to outpaint
            profile_names: List of Chrome profile names (will cycle if needed)
            output_dir: Output directory (defaults to config.outpaint_dir)
            
        Returns:
            List of output file paths (None for failed images)
        """
        output_dir = output_dir or self.config.outpaint_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        
        self.logger.info("Starting batch outpaint", image_count=len(image_paths))

        parallel_limit = max(
            1,
            getattr(self.config, "max_parallel_browsers", self.config.max_concurrent_browser_launches),
        )
        semaphore = asyncio.Semaphore(parallel_limit)

        async def run_task(idx: int, img_path: Path):
            profile = profile_names[idx % len(profile_names)]
            worker_id = idx + 1
            async with semaphore:
                return await self.outpaint_single_image(
                    img_path,
                    profile,
                    output_dir,
                    worker_id
                )

        tasks = [run_task(idx, img_path) for idx, img_path in enumerate(image_paths)]
        
        # Run all tasks with throttled concurrency
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Convert exceptions to None
        output_paths = []
        for result in results:
            if isinstance(result, Exception):
                self.logger.error("Task exception", error=str(result))
                output_paths.append(None)
            else:
                output_paths.append(result)
        
        successful = sum(1 for p in output_paths if p is not None)
        self.logger.info(
            "Batch outpaint complete",
            successful=successful,
            failed=len(output_paths) - successful,
            total=len(output_paths)
        )
        
        return output_paths

