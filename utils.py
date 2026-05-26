# utils.py

import os
import time
import queue
from datetime import datetime
from pathlib import Path

LOG_QUEUE = queue.Queue()

def kill_chrome():
    """
    Kill all Chrome windows to avoid session bugs.
    """
    os.system("taskkill /F /IM chrome.exe >nul 2>&1")
    time.sleep(2)

def glob_images(directory: Path, extensions: list) -> list:
    """
    Return all images in directory with given extensions.
    """
    images = []
    for ext in extensions:
        images.extend(sorted(directory.glob(f"*{ext}")))
    return images

def log_worker(worker_id, message):
    """
    Prints + queues log for a specific worker (for file ops, browser steps etc).
    """
    timestamp = datetime.now().strftime("%H:%M:%S")
    entry = f"[{timestamp}] [W{worker_id}] {message}"
    print(entry)
    LOG_QUEUE.put(entry + "\n")

def gui_log(msg):
    """
    Puts general messages into global queue, used by GUI console polling.
    """
    print(msg)
    LOG_QUEUE.put(msg + "\n")

def handle_error(error, context=None, page=None):
    """
    Log error, optionally take a screenshot for debug (if Playwright page object provided).
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    entry = f"[{ts}] [ERROR] {context}: {error}"
    print(entry)
    LOG_QUEUE.put(entry + "\n")
    if page:
        debug_dir = Path("outputs/debug")
        debug_dir.mkdir(exist_ok=True)
        screenshot_path = debug_dir / f"err_{ts}.png"
        try:
            page.screenshot(path=str(screenshot_path))
            LOG_QUEUE.put(f"Screenshot: {screenshot_path}\n")
        except Exception as e:
            LOG_QUEUE.put(f"Screenshot ERROR: {e}\n")
