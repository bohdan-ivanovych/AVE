"""Settings service for GUI preferences."""

import json
from pathlib import Path
from typing import List, Optional, Dict, Any
from src.services.logger import get_logger_service


class SettingsService:
    """Service for managing GUI settings and preferences."""
    
    def __init__(self, settings_file: Optional[Path] = None):
        """
        Initialize settings service.
        
        Args:
            settings_file: Path to settings file (defaults to ave_gui_settings.json)
        """
        self.logger = get_logger_service().get_logger("settings")
        self.settings_file = settings_file or Path("ave_gui_settings.json")
        self._settings: Dict[str, Any] = {}
        self._load_settings()
    
    def _load_settings(self):
        """Load settings from file."""
        if not self.settings_file.exists():
            self._settings = self._get_default_settings()
            self._save_settings()
            return
        
        try:
            with open(self.settings_file, "r", encoding="utf-8") as f:
                self._settings = json.load(f)
            
            # Ensure all default keys exist
            defaults = self._get_default_settings()
            for key, value in defaults.items():
                if key not in self._settings:
                    self._settings[key] = value
            
            self.logger.debug("Settings loaded", file=str(self.settings_file))
        except Exception as e:
            self.logger.error("Failed to load settings", error=str(e))
            self._settings = self._get_default_settings()
            self._save_settings()
    
    def _save_settings(self):
        """Save settings to file."""
        try:
            with open(self.settings_file, "w", encoding="utf-8") as f:
                json.dump(self._settings, f, indent=2, ensure_ascii=False)
            self.logger.debug("Settings saved", file=str(self.settings_file))
        except Exception as e:
            self.logger.error("Failed to save settings", error=str(e))
    
    def _get_default_settings(self) -> Dict[str, Any]:
        """Get default settings."""
        return {
            "selected_profiles": [],  # Empty means use all from config
            "available_profiles": [],  # List of available profiles (custom + default)
            "appearance_mode": "dark",
            "ui_scale": 1.0,
            "window_geometry": None,
            "last_directories": {},
            # Browser settings
            "max_concurrent_browser_launches": 2,  # Browsers per wave (keep at 2 as requested)
            "max_parallel_browsers": 6,  # Max simultaneously open browsers
            "browser_launch_delay_ms": 1000,  # Faster delay after browser launch
            "browser_stagger_delay_ms": 500,  # Faster delay between browser launches
            "wave_delay_ms": 1000,  # Faster wave cadence
            "qwen_browser_delay_ms": 2000,  # Much faster gap between Qwen browser launches
            # Timeout settings
            "browser_timeout": 60000,  # Browser launch timeout
            "navigation_timeout": 45000,  # Navigation timeout
            "button_wait_seconds": 60,  # Wait for Create button
            "notification_timeout_seconds": 240,  # Wait for notification
            # Upload settings
            "upload_delay": 800,  # Delay between uploads
            "upload_delay_last": 400,  # Delay after last upload
            "create_click_delay": 1500,  # Delay after clicking Create
            # Batch settings
            "max_concurrent_tasks": 10,  # Max concurrent tasks
            "max_variants_per_task": 2,  # Max variants to download
            "semaphore_limit": 10,  # Semaphore limit
            # Other delays
            "scroll_delay": 200,  # Scroll delay
            "download_timeout": 30000,  # Download timeout
            "navigation_retries": 3  # Navigation retry attempts
        }
    
    def get_selected_profiles(self) -> List[str]:
        """
        Get selected profiles.
        
        Returns:
            List of selected profile names, or empty list if all should be used
        """
        return self._settings.get("selected_profiles", [])
    
    def set_selected_profiles(self, profiles: List[str]):
        """Set selected profiles."""
        self._settings["selected_profiles"] = profiles
        self._save_settings()
        self.logger.info("Selected profiles updated", count=len(profiles))
    
    def get_appearance_mode(self) -> str:
        """Get appearance mode."""
        return self._settings.get("appearance_mode", "dark")
    
    def set_appearance_mode(self, mode: str):
        """Set appearance mode."""
        self._settings["appearance_mode"] = mode.lower()
        self._save_settings()
    
    def get_ui_scale(self) -> float:
        """Get UI scale."""
        return self._settings.get("ui_scale", 1.0)
    
    def set_ui_scale(self, scale: float):
        """Set UI scale."""
        self._settings["ui_scale"] = scale
        self._save_settings()
    
    def get_last_directory(self, key: str) -> Optional[str]:
        """Get last used directory for a key."""
        return self._settings.get("last_directories", {}).get(key)
    
    def set_last_directory(self, key: str, path: str):
        """Set last used directory for a key."""
        if "last_directories" not in self._settings:
            self._settings["last_directories"] = {}
        self._settings["last_directories"][key] = path
        self._save_settings()
    
    def get_window_geometry(self) -> Optional[str]:
        """Get saved window geometry."""
        return self._settings.get("window_geometry")
    
    def set_window_geometry(self, geometry: str):
        """Set window geometry."""
        self._settings["window_geometry"] = geometry
        self._save_settings()
    
    def get_available_profiles(self) -> List[str]:
        """Get available profiles list."""
        return self._settings.get("available_profiles", [])
    
    def set_available_profiles(self, profiles: List[str]):
        """Set available profiles list."""
        self._settings["available_profiles"] = profiles
        self._save_settings()
        self.logger.info("Available profiles updated", count=len(profiles))
    
    # Browser settings
    def get_browser_setting(self, key: str, default: Any = None) -> Any:
        """Get browser setting value."""
        return self._settings.get(key, default)
    
    def set_browser_setting(self, key: str, value: Any):
        """Set browser setting value."""
        self._settings[key] = value
        self._save_settings()
        self.logger.info("Browser setting updated", key=key, value=value)
    
    def get_max_concurrent_browser_launches(self) -> int:
        """Get max concurrent browser launches (browsers per wave)."""
        return self._settings.get("max_concurrent_browser_launches", 2)
    
    def set_max_concurrent_browser_launches(self, value: int):
        """Set max concurrent browser launches."""
        self._settings["max_concurrent_browser_launches"] = max(1, min(value, 10))  # Limit 1-10
        self._save_settings()
        self.logger.info("Max concurrent browser launches updated", value=self._settings["max_concurrent_browser_launches"])
    
    def get_max_parallel_browsers(self) -> int:
        """Get max parallel browsers."""
        return self._settings.get("max_parallel_browsers", 6)
    
    def set_max_parallel_browsers(self, value: int):
        """Set max parallel browsers."""
        self._settings["max_parallel_browsers"] = max(1, min(value, 20))  # Limit 1-20
        self._save_settings()
        self.logger.info("Max parallel browsers updated", value=self._settings["max_parallel_browsers"])
    
    def get_timeout_setting(self, key: str, default: int) -> int:
        """Get timeout setting."""
        return self._settings.get(key, default)
    
    def set_timeout_setting(self, key: str, value: int):
        """Set timeout setting."""
        self._settings[key] = max(1000, value)  # Minimum 1 second
        self._save_settings()
        self.logger.info("Timeout setting updated", key=key, value=self._settings[key])
    
    def get_delay_setting(self, key: str, default: int) -> int:
        """Get delay setting."""
        return self._settings.get(key, default)
    
    def set_delay_setting(self, key: str, value: int):
        """Set delay setting."""
        self._settings[key] = max(0, value)  # Minimum 0
        self._save_settings()
        self.logger.info("Delay setting updated", key=key, value=self._settings[key])
    
    def get_batch_setting(self, key: str, default: int) -> int:
        """Get batch setting."""
        return self._settings.get(key, default)
    
    def set_batch_setting(self, key: str, value: int):
        """Set batch setting."""
        self._settings[key] = max(1, value)  # Minimum 1
        self._save_settings()
        self.logger.info("Batch setting updated", key=key, value=self._settings[key])


# Global instance
_settings_service: Optional[SettingsService] = None


def get_settings_service() -> SettingsService:
    """Get or create global settings service instance."""
    global _settings_service
    if _settings_service is None:
        _settings_service = SettingsService()
    return _settings_service

