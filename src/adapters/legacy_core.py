"""Adapter for legacy core.py functionality to work with new architecture."""

import os
import time
from pathlib import Path
from datetime import datetime
from playwright.sync_api import sync_playwright
from typing import Optional

from src.config import get_config
from src.services.logger import get_logger_service
from src.utils.path_utils import sanitize_path

_logger = get_logger_service().get_logger("legacy_core")


def run_one_generation_legacy(
    worker_id: int,
    profile_name: str,
    primary_img: Path,
    second_img: Path,
    prompt: str,
    log_queue=None
) -> bool:
    """
    Legacy single-task generation function.

    Accepts exactly two reference images (primary + secondary), uploads them to
    Sora, injects the prompt via native React setter, and downloads up to two
    generated variants.

    Returns:
        True if at least one variant was downloaded successfully.
    """
    config = get_config()
    logger = get_logger_service().get_logger("legacy_core")
    
    def log(msg: str):
        logger.info(msg, worker_id=worker_id)
        if log_queue:
            log_queue.put(f"[W{worker_id}] {msg}\n")
        print(f"[W{worker_id}] {msg}")
    
    primary_name = primary_img.stem
    second_name = second_img.stem
    log(f"Starting: {primary_name} + {second_name}")
    log(f"Profile: {profile_name}")
    
    # Check existing files
    existing_pattern = f"*_{worker_id}_{primary_name}_{second_name}_*.webp"
    existing_files = sorted(config.outputs_dir.glob(existing_pattern))
    if len(existing_files) >= 2:
        log(f"✓ SKIPPING - Already have {len(existing_files)} variants")
        return True
    elif len(existing_files) == 1:
        log(f"⚠ Found 1 variant, will generate 1 more")
    
    playwright = None
    ctx = None
    
    try:
        playwright = sync_playwright().start()
        
        # Sanitize profile path
        chrome_base = sanitize_path(config.chrome_base)
        profile_path = sanitize_path(profile_name, base_dir=chrome_base)
        
        if not profile_path.exists():
            log(f"ERROR: Profile path not found: {profile_path}")
            return False
        
        log("Launching browser...")
        ctx = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_path),
            headless=False,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
            timeout=120000
        )
        
        page = ctx.new_page()
        log("Navigating to Sora...")
        
        for nav_attempt in range(config.navigation_retries):
            try:
                page.goto(config.sora_url, wait_until="domcontentloaded", timeout=120000)
                page.wait_for_timeout(3000)
                break
            except Exception as e:
                if nav_attempt < config.navigation_retries - 1:
                    log(f"Navigation failed (attempt {nav_attempt + 1}/{config.navigation_retries}), retrying...")
                    time.sleep(3)
                else:
                    log(f"Navigation failed (final attempt): {e}")
                    return False
        
        if "login" in page.url.lower() or "auth" in page.url.lower():
            log("ERROR: Not logged in! Run Login Mode first.")
            return False
        
        try:
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(1000)
            log("✓ Page loaded")
        except Exception as e:
            log(f"Scroll warning: {e}")
        
        # Upload primary image
        log(f"Uploading primary image: {primary_name}")
        try:
            primary_path = sanitize_path(primary_img)
            file_input = page.locator('input[type="file"]').first
            file_input.set_input_files(str(primary_path.absolute()))
            log("✓ Primary image uploaded")
            page.wait_for_timeout(4000)
        except Exception as e:
            log(f"ERROR uploading primary image: {e}")
            return False
        
        # Upload secondary image
        log(f"Uploading secondary image: {second_name}")
        try:
            second_path = sanitize_path(second_img)
            file_input2 = page.locator('input[type="file"]').first
            file_input2.set_input_files(str(second_path.absolute()))
            log("✓ Secondary image uploaded")
            page.wait_for_timeout(4000)
        except Exception as e:
            log(f"ERROR uploading secondary image: {e}")
            return False
        
        # Wait for Create button
        log("Waiting for Create button (max 60 sec)...")
        button_ready = False
        for attempt in range(config.button_wait_seconds):
            try:
                disabled = page.evaluate("""
                    () => {
                        const btn = Array.from(document.querySelectorAll('button'))
                            .find(b => b.textContent.includes('Remix') || b.textContent.includes('Create'));
                        return btn ? btn.getAttribute('data-disabled') : 'notfound';
                    }
                """)
                if disabled == 'false':
                    log("✓ Button ready!")
                    button_ready = True
                    break
                if (attempt + 1) % 10 == 0:
                    log(f"Waiting... {attempt + 1}/{config.button_wait_seconds}")
                time.sleep(1)
            except Exception as e:
                log(f"Button poll error: {e}")
                time.sleep(1)
        
        if not button_ready:
            log("ERROR: Button never became ready")
            return False
        
        log("Waiting for files to fully process...")
        page.wait_for_timeout(3000)
        
        # Set prompt and click
        log("Clicking Create...")
        create_clicked = False
        for attempt in range(20):
            try:
                result = page.evaluate(
                    """
                    (prompt) => {
                        const buttons = Array.from(document.querySelectorAll('button'));
                        const createBtn = buttons.find(b => b.textContent.includes('Remix') || b.textContent.includes('Create'));
                        if (!createBtn) return {found: false};
                        const disabled = createBtn.getAttribute('data-disabled');
                        if (disabled === 'false') {
                            const textarea = document.querySelector('textarea[placeholder*="Describe"]');
                            if (!textarea) return {found: true, clicked: false, error: "notextarea"};
                            const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
                            nativeInputValueSetter.call(textarea, prompt);
                            textarea.dispatchEvent(new Event('input', { bubbles: true }));
                            textarea.dispatchEvent(new Event('change', { bubbles: true }));
                            const actualValue = textarea.value;
                            createBtn.click();
                            return {found: true, clicked: true, promptLength: actualValue.length};
                        }
                        return {found: true, clicked: false, disabled};
                    }
                    """,
                    prompt
                )
                if result.get('clicked'):
                    log(f"✓ Prompt set ({result.get('promptLength')} chars) + clicked!")
                    create_clicked = True
                    page.wait_for_timeout(7000)
                    break
                if (attempt + 1) % 5 == 0:
                    log(f"Waiting... {attempt + 1}/20 (disabled={result.get('disabled')})")
                time.sleep(1)
            except Exception as e:
                log(f"Prompt injection error: {e}")
                time.sleep(1)
        
        if not create_clicked:
            log("ERROR: Could not click Create button")
            return False
        
        # Wait for generation completion
        log("Waiting for Sora generation to complete (up to 4 min)...")
        notified = wait_for_sora_notification(page, timeout=240)
        if not notified:
            log("WARNING: Sora notification not detected (fallback to tile polling)")
        else:
            log("✓ Sora image notification detected, proceeding to download")
        
        # Download generated variants
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        downloaded = 0
        try:
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(1000)
            # Check initial tiles count (like in old code)
            try:
                initial_tiles = page.locator('div.group\\/tile').count()
                log(f"Initial tiles: {initial_tiles}")
            except Exception as e:
                initial_tiles = 0
                log(f"Tile counter error: {e}")
            
            tiles = page.locator('div.group\\/tile')
            total = tiles.count()
            log(f"Found {total} total tiles, taking top 2")
            for idx in range(min(2, total)):
                try:
                    tile = tiles.nth(idx)
                    log(f"Downloading variant {idx + 1}...")
                    tile.scroll_into_view_if_needed()
                    page.wait_for_timeout(500)
                    tile.hover()
                    page.wait_for_timeout(1000)
                    log("✓ Hovered")
                    menu_button = tile.locator('button[aria-haspopup="menu"]')
                    menu_button.wait_for(state="visible", timeout=5000)
                    menu_button.click()
                    page.wait_for_timeout(800)
                    log("✓ Menu opened")
                    download_item = page.locator('div[role="menuitem"]:has-text("Download")')
                    download_item.wait_for(state="visible", timeout=5000)
                    with page.expect_download(timeout=30000) as download_info:
                        download_item.click()
                        download = download_info.value
                        filename = f"{timestamp}_W{worker_id}_{primary_name}_{second_name}_v{idx + 1}.webp"
                        config.outputs_dir.mkdir(parents=True, exist_ok=True)
                        save_path = config.outputs_dir / filename
                        download.save_as(str(save_path))
                        log(f"✓ Downloaded: {filename}")
                        downloaded += 1
                        page.wait_for_timeout(1000)
                except Exception as e:
                    log(f"ERROR downloading variant {idx + 1}: {e}")
                    # Take screenshot for debugging
                    try:
                        debug_dir = config.outputs_dir / "debug"
                        debug_dir.mkdir(parents=True, exist_ok=True)
                        screenshot_path = debug_dir / f"debug_W{worker_id}_fail_{idx}.png"
                        page.screenshot(path=str(screenshot_path))
                        log(f"Screenshot: {screenshot_path}")
                    except Exception as e2:
                        log(f"Screenshot fail: {e2}")
                    continue
            log(f"✅ Completed! {downloaded}/2 variants downloaded")
            return downloaded > 0
        except Exception as e:
            log(f"Download error: {e}")
            return False
        finally:
            if ctx:
                try:
                    ctx.close()
                    log("Browser closed")
                except Exception as e:
                    log(f"Error closing context: {e}")
            if playwright:
                try:
                    playwright.stop()
                except:
                    pass
    
    except Exception as e:
        log(f"FATAL ERROR: {e}")
        import traceback
        log(f"Traceback: {traceback.format_exc()}")
        return False


def wait_for_sora_notification(page, timeout: int = 240) -> bool:
    """Poll Sora's library page for generation-complete indicators.

    Tries an exact DOM selector first, then falls back to any image whose
    alt attribute contains 'Sora' or 'generation'.

    Args:
        page: Playwright Page object.
        timeout: Maximum wait time in seconds.

    Returns:
        True if a completion indicator was detected before the timeout.
    """
    waited = 0
    while waited < timeout:
        try:
            # Try exact selector from old code
            img = page.query_selector('img[alt="Sora generation"].object-cover')
            if img:
                src = img.get_attribute("src")
                _logger.debug("Sora generation image notification detected", src=src)
                return True
            # Broader fallback: any image whose alt suggests generation
            notification_elements = page.query_selector_all('img[alt*="Sora"], img[alt*="generation"]')
            if notification_elements:
                _logger.debug("Potential notification images found", count=len(notification_elements))
            time.sleep(2)
            waited += 2
        except Exception as e:
            if waited % 10 == 0:
                _logger.warning("Exception while polling for notification", error=str(e))
            time.sleep(2)
            waited += 2
    _logger.debug("Notification wait timed out")
    return False

