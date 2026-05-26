import os
import time
import random
import threading
import requests
from pathlib import Path
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from utils import log_worker, handle_error, glob_images, kill_chrome, LOG_QUEUE
from src.config import get_config
from src.services.logger import get_logger_service
from src.utils.name_utils import describe_media_name

_logger = get_logger_service().get_logger("core")

# ========== CONFIGURATION ==========
# Load config - will be initialized on first use
_config = None

def get_core_config():
    """Get configuration for core module."""
    global _config
    if _config is None:
        _config = get_config()
    return _config

# Initialize constants from config
def _init_constants():
    """Initialize module-level constants from config."""
    global SORA_URL, CHROME_BASE, PROFILES, OUTPUTS_DIR
    config = get_core_config()
    SORA_URL = config.sora_url
    CHROME_BASE = config.chrome_base
    PROFILES = config.default_profiles
    OUTPUTS_DIR = config.outputs_dir
    OUTPUTS_DIR.mkdir(exist_ok=True)

# Initialize constants
_init_constants()



# ======= Sora Notification Detection =======
def _collect_top_tile_sources(page, limit: int = 6):
    """Collect current src/currentSrc URLs from the top N tiles (img/video)."""
    sources = set()
    try:
        tiles = page.locator('div.group\\/tile')
        total = tiles.count()
        for idx in range(min(limit, total)):
            try:
                media = tiles.nth(idx).locator('img, video').first
                if media.count() == 0:
                    continue
                src = media.get_attribute('src')
                if not src:
                    src = media.evaluate("el => el.currentSrc || el.src || el.querySelector('source')?.src")
                if src:
                    sources.add(src)
            except Exception:
                pass
    except Exception:
        pass
    return sources


def wait_for_sora_img_notification(page, timeout=None, baseline_sources=None):
    """Wait for Sora generation completion using multiple strategies.
    1) Direct notification element
    2) Tile media sources changed vs baseline
    3) Tile count increased
    """
    config = get_core_config()
    if timeout is None:
        timeout = config.notification_timeout_seconds
    check_interval = config.notification_check_interval
    waited = 0
    # Establish baseline if not provided
    if baseline_sources is None:
        baseline_sources = _collect_top_tile_sources(page)
    try:
        baseline_tile_count = page.locator('div.group\\/tile').count()
    except Exception:
        baseline_tile_count = 0
    
    while waited < timeout:
        try:
            # Strategy 1: explicit notification selector(s)
            # Try a few likely variants (alt text, aria-label, role)
            sel_candidates = [
                'img[alt="Sora generation"].object-cover',
                'img[alt*="generation"]',
                '[aria-label*="generated"] img',
            ]
            for sel in sel_candidates:
                node = page.query_selector(sel)
                if node:
                    _logger.debug("Notification detected via selector", selector=sel)
                    return True

            # Strategy 2: tile sources changed
            current_sources = _collect_top_tile_sources(page)
            new_sources = [s for s in current_sources if s not in baseline_sources and isinstance(s, str) and not s.startswith('data:')]
            if new_sources:
                _logger.debug("New media sources detected", count=len(new_sources))
                return True

            # Strategy 3: tile count increased
            try:
                current_tile_count = page.locator('div.group\\/tile').count()
                if current_tile_count > baseline_tile_count:
                    _logger.debug("Tile count increased", before=baseline_tile_count, after=current_tile_count)
                    return True
            except Exception:
                pass

            time.sleep(check_interval)
            waited += check_interval
        except Exception:
            time.sleep(check_interval)
            waited += check_interval
    _logger.debug("Notification wait timed out")
    return False

# ========== CORE AUTOMATION ==========
def run_one_generation(worker_id, profile_name, image_paths, second_img=None, prompt=None, log_queue=None, max_variants=2):
    """
    Run one generation task with flexible image support (1-4 images).

    Args:
        worker_id: Worker identifier.
        profile_name: Chrome profile directory name (e.g. "Profile 1").
        image_paths: List of 1-4 image Paths **or** a single Path (legacy).
        second_img: Deprecated — pass a list via ``image_paths`` instead.
        prompt: Generation prompt string.
        log_queue: Optional ``queue.Queue`` for GUI log streaming.
        max_variants: Maximum variants to download per task (default 2).
    """
    # Normalise input — support list, single path, and legacy two-arg call.
    if second_img is not None:
        image_paths = [Path(image_paths), Path(second_img)]
    elif isinstance(image_paths, (list, tuple)):
        image_paths = [Path(x) for x in image_paths]
    else:
        image_paths = [Path(image_paths)]
    def log(msg):
        log_worker(worker_id, msg)
        if log_queue:
            log_queue.put(f"[W{worker_id}] {msg}\n")

    # Validate and prepare images
    if not image_paths or len(image_paths) < 1 or len(image_paths) > 4:
        log(f"ERROR: Invalid number of images: {len(image_paths) if image_paths else 0}. Need 1-4 images.")
        return
    
    # Validate each image (format, size, existence)
    validated_paths = []
    for img_path in image_paths:
        img_path = Path(img_path)
        if not img_path.exists():
            log(f"ERROR: Image not found: {img_path}")
            return
        
        # Check format
        valid_extensions = {'.jpg', '.jpeg', '.png', '.webp'}
        if img_path.suffix.lower() not in valid_extensions:
            log(f"ERROR: Invalid image format: {img_path.suffix}. Supported: {valid_extensions}")
            return
        
        # Check size (max 50MB)
        file_size_mb = img_path.stat().st_size / (1024 * 1024)
        if file_size_mb > 50:
            log(f"ERROR: Image too large: {file_size_mb:.2f}MB (max 50MB): {img_path}")
            return
        
        validated_paths.append(img_path)
    
    image_paths = validated_paths
    image_names = [img.stem for img in image_paths]
    # Extract character names for better naming
    char_names = [describe_media_name(img).replace(" · ", "_").replace(" ", "_") for img in image_paths[:2]]
    log(f"Starting: {', '.join(image_names)} ({len(image_paths)} images)")
    log(f"Profile: {profile_name}")

    # Check existing files (duplicate detection) - use character names
    name_part = "_".join(char_names[:2]) if char_names else "_".join(image_names[:2])
    existing_pattern = f"*_{worker_id}_{name_part}_*.webp"
    existing_files = sorted(OUTPUTS_DIR.glob(existing_pattern))
    if len(existing_files) >= max_variants:
        log(f"✓ SKIPPING - Already have {len(existing_files)} variants (duplicate detected)")
        return
    elif len(existing_files) > 0:
        log(f"⚠ Found {len(existing_files)} variant(s), will generate {max_variants - len(existing_files)} more")

    playwright = None
    ctx = None

    try:
        playwright = sync_playwright().start()
        # Sanitize profile path to prevent path traversal
        profile_name_safe = os.path.basename(profile_name)  # Remove any path components
        profile_path = os.path.join(CHROME_BASE, profile_name_safe)
        if not os.path.exists(profile_path):
            log(f"ERROR: Profile path not found: {profile_path}")
            return

        log("Launching browser...")
        config = get_core_config()
        ctx = playwright.chromium.launch_persistent_context(
            user_data_dir=profile_path,
            headless=False,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"],
            ignore_default_args=["--enable-automation"],
            timeout=config.browser_timeout,
            accept_downloads=True
        )

        page = ctx.new_page()
        log("Navigating to Sora...")
        config = get_core_config()
        for nav_attempt in range(config.navigation_retries):
            try:
                page.goto(SORA_URL, wait_until="domcontentloaded", timeout=config.navigation_timeout)
                page.wait_for_load_state("domcontentloaded", timeout=5000)
                page.wait_for_timeout(config.scroll_delay)
                break
            except Exception as e:
                if nav_attempt < config.navigation_retries - 1:
                    log(f"Navigation failed (attempt {nav_attempt + 1}/{config.navigation_retries}), retrying...")
                    time.sleep(1)
                else:
                    log(f"Navigation failed (final attempt): {e}")
                    handle_error(e, "goto Sora", page)
                    return

        if "login" in page.url.lower() or "auth" in page.url.lower():
            log("ERROR: Not logged in! Run Login Mode first.")
            return

        try:
            config = get_core_config()
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(config.scroll_delay)
            log("✓ Page loaded")
        except Exception as e:
            log(f"Scroll warning: {e}")

        try:
            initial_tiles = page.locator('div.group\\/tile').count()
            log(f"Initial tiles: {initial_tiles}")
        except Exception as e:
            initial_tiles = 0
            log(f"Tile counter error: {e}")

        # Upload all images (1-4)
        for idx, img_path in enumerate(image_paths, 1):
            img_name = Path(img_path).stem
            log(f"Uploading image {idx}/{len(image_paths)}: {img_name}")
            try:
                file_input = page.locator('input[type="file"]').first
                # Validate and sanitize path
                abs_path = Path(img_path).resolve()  # Resolve to absolute path
                if not abs_path.exists():
                    log(f"ERROR: Image path does not exist: {abs_path}")
                    return
                file_input.set_input_files(str(abs_path))
                log(f"✓ Image {idx} uploaded")
                # Очікуємо поки файл обробиться
                config = get_core_config()
                delay = config.upload_delay if idx < len(image_paths) else config.upload_delay_last
                page.wait_for_timeout(delay)
            except Exception as e:
                log(f"ERROR uploading image {idx}: {e}")
                handle_error(e, f"upload image {idx}", page)
                return

        log("Waiting for Create button (max 60 sec)...")
        button_ready = False
        for attempt in range(60):
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
                    log(f"Waiting... {attempt + 1}/60")
                time.sleep(1)
            except Exception as e:
                log(f"Button poll error: {e}")
                time.sleep(1)
        if not button_ready:
            log("ERROR: Button never became ready")
            return

        log("Waiting for files to fully process...")
        page.wait_for_timeout(800)  # Оптимізовано

        log("Clicking Create...")
        create_clicked = False
        for attempt in range(20):
            try:
                # First, set the prompt
                set_result = page.evaluate(
                    """
                    (prompt) => {
                        const textarea = document.querySelector('textarea[placeholder*="Describe"]');
                        if (!textarea) return {success: false, error: "notextarea"};
                        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
                        nativeInputValueSetter.call(textarea, prompt);
                        textarea.dispatchEvent(new Event('input', { bubbles: true }));
                        textarea.dispatchEvent(new Event('change', { bubbles: true }));
                        const actualValue = textarea.value;
                        return {success: true, promptLength: actualValue.length};
                    }
                    """, prompt
                )
                
                if not set_result.get('success'):
                    log(f"Failed to set prompt: {set_result.get('error')}")
                    time.sleep(0.5)
                    continue
                
                # Wait a bit for Sora to process the input (may temporarily disable button)
                time.sleep(0.3)
                
                # Now try to click the button - check if it's enabled after setting prompt
                click_result = page.evaluate(
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
                    log(f"✓ Prompt set ({set_result.get('promptLength')} chars) + clicked!")
                    create_clicked = True
                    config = get_core_config()
                    page.wait_for_timeout(config.create_click_delay)
                    break
                
                if not click_result.get('found'):
                    log(f"Create button not found, attempt {attempt + 1}/20")
                    time.sleep(0.5)
                    continue
                
                if (attempt + 1) % 5 == 0:
                    log(f"Waiting... {attempt + 1}/20 (disabled={click_result.get('disabled')})")
                time.sleep(1)
            except Exception as e:
                log(f"Prompt injection error: {e}")
                time.sleep(1)
        if not create_clicked:
            log("ERROR: Could not click Create button")
            return

        log("Waiting for Sora image notification...")
        config = get_core_config()
        # Capture baseline sources before waiting
        baseline_sources = _collect_top_tile_sources(page)
        notified = wait_for_sora_img_notification(page, timeout=config.notification_timeout_seconds, baseline_sources=baseline_sources)
        if not notified:
            log("WARNING: Sora notification not detected (fallback to tile polling)")
        else:
            log("✓ Sora image notification detected, proceeding to download")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        downloaded = 0
        try:
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(300)
            tiles = page.locator('div.group\\/tile')
            total = tiles.count()
            log(f"Found {total} total tiles, taking top {max_variants}")
            for idx in range(min(max_variants, total)):
                try:
                    tile = tiles.nth(idx)
                    log(f"Downloading variant {idx + 1}...")
                    tile.scroll_into_view_if_needed()
                    page.wait_for_timeout(200)
                    tile.hover()
                    page.wait_for_timeout(300)
                    log("✓ Hovered")
                    
                    # Знаходимо зображення всередині tile
                    img = tile.locator('img, video').first
                    img.wait_for(state="visible", timeout=5000)
                    
                    # Отримуємо URL зображення/відео
                    img_url = img.get_attribute('src')
                    if not img_url:
                        img_url = img.evaluate("el => el.currentSrc || el.src || el.querySelector('source')?.src")
                    
                    if img_url and not img_url.startswith('data:'):
                        # Завантажуємо напряму через URL (найшвидший метод)
                        log(f"Downloading from URL...")
                        config = get_core_config()
                        try:
                            response = requests.get(img_url, timeout=config.download_timeout // 1000, stream=True)
                            response.raise_for_status()
                            # Use character names for better naming
                            name_part = "_".join(char_names[:2]) if char_names else "_".join(image_names[:2])
                            filename = f"{timestamp}_W{worker_id}_{name_part}_v{idx + 1}.webp"
                            save_path = OUTPUTS_DIR / filename
                            with open(save_path, 'wb') as f:
                                for chunk in response.iter_content(chunk_size=8192):
                                    f.write(chunk)
                            log(f"✓ Downloaded: {filename}")
                            downloaded += 1
                        except Exception as url_err:
                            log(f"URL download failed: {url_err}, trying right click...")
                            img_url = None
                    
                    if not img_url or img_url.startswith('data:'):
                        # Якщо URL не працює, використовуємо right click + Save As
                        log("Using right click + Save As...")
                        config = get_core_config()
                        try:
                            with page.expect_download(timeout=config.download_timeout) as download_info:
                                img.click(button="right")
                                page.wait_for_timeout(300)
                                # В Chrome "Save image as" зазвичай на клавіші "v"
                                page.keyboard.press("v")
                                page.wait_for_timeout(500)
                            download = download_info.value
                            # Use character names for better naming
                            name_part = "_".join(char_names[:2]) if char_names else "_".join(image_names[:2])
                            filename = f"{timestamp}_W{worker_id}_{name_part}_v{idx + 1}.webp"
                            save_path = OUTPUTS_DIR / filename
                            download.save_as(save_path)
                            log(f"✓ Downloaded (right click): {filename}")
                            downloaded += 1
                        except Exception as right_click_err:
                            log(f"Right click also failed: {right_click_err}")
                            raise right_click_err
                    
                    page.wait_for_timeout(200)
                except Exception as e:
                    log(f"ERROR downloading variant {idx + 1}: {e}")
                    handle_error(e, f"download_{idx+1}", page)
                    try:
                        screenshot_path = OUTPUTS_DIR / f"debug_W{worker_id}_fail_{idx}.png"
                        page.screenshot(path=str(screenshot_path))
                        log(f"Screenshot: {screenshot_path}")
                    except Exception as e2:
                        log(f"Screenshot fail: {e2}")
                    continue
            log(f"✅ Completed! {downloaded}/{max_variants} variants downloaded")
            return []
        except Exception as e:
            log(f"Download error: {e}")
            handle_error(e, "final download", page)
        finally:
            # Proper cleanup to prevent memory leaks
            if ctx:
                try:
                    # Close all pages first to prevent leaks
                    pages_to_close = list(ctx.pages)
                    for p in pages_to_close:
                        try:
                            p.close()
                        except:
                            pass
                    ctx.close()
                    log("Browser closed")
                except Exception as e:
                    handle_error(e, "core cleanup")
            if playwright:
                try:
                    playwright.stop()
                    log("Playwright stopped")
                except Exception as e:
                    handle_error(e, "playwright stop")
    except Exception as e:
        log(f"FATAL ERROR: {e}")
        handle_error(e, "run_one_generation")

