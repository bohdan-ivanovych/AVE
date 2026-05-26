"""Configuration management with YAML and environment variables."""

import os
from pathlib import Path
from typing import List, Optional
try:
    import yaml
except ImportError:
    yaml = None
from dotenv import load_dotenv
try:
    from pydantic_settings import BaseSettings
except ImportError:
    from pydantic import BaseSettings

from src.exceptions import ConfigError

# Load environment variables
load_dotenv()


class AppConfig(BaseSettings):
    """Application configuration with validation."""
    
    # Paths
    chrome_base: Path
    edge_base: Optional[Path] = None  # Optional Edge profile base path
    assets_dir: Path
    subjects_dir: Path
    references_dir: Path
    outputs_dir: Path
    outpaint_dir: Path
    qwen_dir: Path
    montage_dir: Path
    profiles_dir: Path
    logs_dir: Path
    
    # Sora settings
    sora_url: str
    default_profiles: List[str]
    timeout_seconds: int
    navigation_retries: int
    button_wait_seconds: int
    notification_timeout_seconds: int
    notification_check_interval: int = 1
    browser_timeout: int = 60000
    navigation_timeout: int = 45000
    scroll_delay: int = 200
    upload_delay: int = 800
    upload_delay_last: int = 400
    create_click_delay: int = 1500
    download_timeout: int = 30000
    max_concurrent_browser_launches: int = 2  # Limit concurrent browser launches (reduced for slow computers)
    browser_launch_delay_ms: int = 2000  # Delay after browser launch completes
    browser_stagger_delay_ms: int = 1000  # Delay between browser launches (stagger)
    max_parallel_browsers: int = 6  # Global cap for simultaneously open browsers
    
    # Batch settings
    max_concurrent_tasks: int
    max_variants_per_task: int
    semaphore_limit: int
    
    # Image settings
    supported_formats: List[str]
    max_size_mb: int
    max_images_per_task: int
    
    # Outpaint removed
    
    # Notification settings
    notifications_enabled: bool
    notify_on_task_complete: bool
    notify_on_batch_complete: bool
    notify_on_error: bool

    # Network
    proxies: List[str] = []
    
    # Logging settings
    log_level: str
    file_logging: bool
    max_log_files: int
    log_file_size_mb: int

    # Browser overrides
    browser_channel: str = "chrome"
    browser_user_agent: Optional[str] = None
    browser_executable_path: Optional[Path] = None
    enable_browser_stealth: bool = False
    browser_extra_args: List[str] = []
    qwen_browser_extra_args: List[str] = []
    max_contexts_per_profile: int = 1
    profile_lock_timeout_seconds: int = 45
    
    class Config:
        env_file = ".env"
        case_sensitive = False


def _discover_browser_profiles(base_path: Path) -> List[str]:
    """Auto-discover Chrome/Edge profiles in the given base path."""
    if not base_path or not base_path.exists():
        return ["Default"]
        
    profiles = []
    try:
        for item in base_path.iterdir():
            if item.is_dir() and (item / "Preferences").exists():
                name = item.name
                if "System" not in name and "Guest" not in name:
                    profiles.append(name)
        
        if not profiles:
            profiles = ["Default"]
            
        # Sort so Default is first, then Profile 1, Profile 2, etc.
        profiles.sort(key=lambda x: (x != "Default", x))
        return profiles
    except Exception:
        return ["Default"]


def load_config(config_path: Path = Path("config.yaml")) -> AppConfig:
    """Load configuration from YAML file with environment variable substitution."""
    if not config_path.exists():
        # Create default config if it doesn't exist
        _create_default_config(config_path)
    
    with open(config_path, "r", encoding="utf-8") as f:
        config_data = yaml.safe_load(f)
    
    # Substitute environment variables in paths
    def substitute_env(value: str) -> str:
        """Substitute ${VAR:default} patterns with environment variables."""
        if not isinstance(value, str):
            return value
        if value.startswith("${") and value.endswith("}"):
            var_part = value[2:-1]
            if ":" in var_part:
                var_name, default = var_part.split(":", 1)
            else:
                var_name, default = var_part, ""
            return os.getenv(var_name, default)
        return value
    
    def process_dict(d: dict) -> dict:
        """Recursively process dictionary values."""
        result = {}
        for k, v in d.items():
            if isinstance(v, dict):
                result[k] = process_dict(v)
            elif isinstance(v, list):
                result[k] = [substitute_env(item) if isinstance(item, str) else item for item in v]
            elif isinstance(v, str):
                result[k] = substitute_env(v)
            else:
                result[k] = v
        return result
    
    processed = process_dict(config_data)
    
    # Flatten nested structure for Pydantic (remove section prefixes)
    flat_config = {}
    for section, values in processed.items():
        if isinstance(values, dict):
            for key, value in values.items():
                # Map section prefixes to field names
                if section == "paths":
                    # paths.chrome_base -> chrome_base
                    # paths.assets_dir -> assets_dir
                    flat_config[key] = value
                elif section == "sora":
                    # sora.url -> sora_url
                    # sora.default_profiles -> default_profiles
                    if key == "url":
                        flat_config["sora_url"] = value
                    else:
                        # Map all sora settings
                        flat_config[key] = value
                elif section == "batch":
                    # batch.max_concurrent_tasks -> max_concurrent_tasks
                    flat_config[key] = value
                elif section == "images":
                    # images.supported_formats -> supported_formats
                    flat_config[key] = value
                # outpaint section removed
                elif section == "notifications":
                    # notifications.enabled -> notifications_enabled
                    # notifications.on_task_complete -> notify_on_task_complete
                    if key == "enabled":
                        flat_config["notifications_enabled"] = value
                    elif key == "on_task_complete":
                        flat_config["notify_on_task_complete"] = value
                    elif key == "on_batch_complete":
                        flat_config["notify_on_batch_complete"] = value
                    elif key == "on_error":
                        flat_config["notify_on_error"] = value
                elif section == "logging":
                    # logging.level -> log_level
                    # logging.file_logging -> file_logging
                    if key == "level":
                        flat_config["log_level"] = value
                    else:
                        flat_config[key] = value
                elif section == "network":
                    flat_config[key] = value
                elif section == "browser":
                    if key == "channel":
                        flat_config["browser_channel"] = value
                    elif key == "enable_stealth":
                        flat_config["enable_browser_stealth"] = value
                    elif key == "extra_args":
                        flat_config["browser_extra_args"] = value or []
                    elif key == "qwen_extra_args":
                        flat_config["qwen_browser_extra_args"] = value or []
                    elif key == "user_agent":
                        flat_config["browser_user_agent"] = value or None
                    elif key == "executable_path":
                        flat_config["browser_executable_path"] = value or None
                    elif key == "max_contexts_per_profile":
                        flat_config["max_contexts_per_profile"] = int(value) if value is not None else 1
                    elif key == "profile_lock_timeout_seconds":
                        flat_config["profile_lock_timeout_seconds"] = int(value) if value is not None else 45
                    else:
                        flat_config[key] = value
    
    # Convert paths to Path objects
    path_keys = [k for k in flat_config.keys() if k.endswith("_dir") or k.endswith("_base") or k.endswith("_path")]
    for key in path_keys:
        if isinstance(flat_config[key], str):
            flat_config[key] = Path(flat_config[key])
    
    # Ensure outpaint_dir exists (create if not in config)
    if "outpaint_dir" not in flat_config:
        # Default to outputs/outpaint if not specified
        outputs_dir = flat_config.get("outputs_dir", Path("outputs"))
        if isinstance(outputs_dir, str):
            outputs_dir = Path(outputs_dir)
        flat_config["outpaint_dir"] = outputs_dir / "outpaint"
    
    # Ensure qwen_dir exists (create if not in config)
    if "qwen_dir" not in flat_config:
        # Default to outputs/qwen if not specified
        outputs_dir = flat_config.get("outputs_dir", Path("outputs"))
        if isinstance(outputs_dir, str):
            outputs_dir = Path(outputs_dir)
        flat_config["qwen_dir"] = outputs_dir / "qwen"
    
    # Ensure montage_dir exists (create if not in config)
    if "montage_dir" not in flat_config:
        # Default to outputs/montage if not specified
        outputs_dir = flat_config.get("outputs_dir", Path("outputs"))
        if isinstance(outputs_dir, str):
            outputs_dir = Path(outputs_dir)
        flat_config["montage_dir"] = outputs_dir / "montage"
    
    # Auto-discover browser profiles
    chrome_base_val = flat_config.get("chrome_base")
    if isinstance(chrome_base_val, str):
        chrome_base_val = Path(chrome_base_val)
    if chrome_base_val and chrome_base_val.exists():
        auto_profiles = _discover_browser_profiles(chrome_base_val)
        if auto_profiles:
            flat_config["default_profiles"] = auto_profiles

    # Create config instance
    try:
        config = AppConfig(**flat_config)
    except Exception as e:
        raise ConfigError(
            f"Invalid configuration: {str(e)}",
            details="Please check your config.yaml file for errors."
        )
    
    # Validate configuration
    validate_config(config)
    
    return config


def validate_config(config: AppConfig) -> None:
    """Validate configuration values and paths.
    
    Args:
        config: Configuration instance to validate
        
    Raises:
        ConfigError: If validation fails
    """
    # Try to get logger, but don't fail if it causes recursion
    logger = None
    try:
        from src.services.logger import get_logger_service
        logger = get_logger_service().get_logger("config")
    except (RecursionError, RuntimeError):
        # Logger not available during initial config loading - skip logging
        pass
    
    errors = []
    warnings = []
    
    # Validate Chrome base path
    if not config.chrome_base.exists():
        errors.append(f"Chrome base path does not exist: {config.chrome_base}")
    elif not config.chrome_base.is_dir():
        errors.append(f"Chrome base path is not a directory: {config.chrome_base}")

    if config.browser_executable_path:
        if not config.browser_executable_path.exists():
            errors.append(f"Browser executable path does not exist: {config.browser_executable_path}")
        elif not config.browser_executable_path.is_file():
            errors.append(f"Browser executable path is not a file: {config.browser_executable_path}")
    
    # Validate and create directories
    dirs_to_check = {
        "assets_dir": config.assets_dir,
        "subjects_dir": config.subjects_dir,
        "references_dir": config.references_dir,
        "outputs_dir": config.outputs_dir,
        "outpaint_dir": config.outpaint_dir,
        "qwen_dir": config.qwen_dir,
        "montage_dir": config.montage_dir,
        "profiles_dir": config.profiles_dir,
        "logs_dir": config.logs_dir,
    }
    
    for name, path in dirs_to_check.items():
        try:
            path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            errors.append(f"Cannot create {name} directory '{path}': {str(e)}")
    
    # Validate Sora URL
    if not config.sora_url or not config.sora_url.startswith(("http://", "https://")):
        errors.append(f"Invalid Sora URL: {config.sora_url}")
    
    # Validate profiles
    if not config.default_profiles:
        warnings.append("No default profiles specified")
    else:
        # Check if profile directories exist
        missing_profiles = []
        for profile in config.default_profiles:
            profile_path = config.chrome_base / profile
            if not profile_path.exists():
                missing_profiles.append(profile)
        
        if missing_profiles:
            warnings.append(
                f"Some Chrome profiles not found: {', '.join(missing_profiles)}"
            )
    
    # Validate numeric values
    if config.max_concurrent_tasks < 1:
        errors.append("max_concurrent_tasks must be at least 1")
    
    if config.max_variants_per_task < 1:
        errors.append("max_variants_per_task must be at least 1")
    
    if config.timeout_seconds < 1:
        errors.append("timeout_seconds must be at least 1")
    
    if config.max_size_mb < 1:
        errors.append("max_size_mb must be at least 1")
    
    if config.max_images_per_task < 1 or config.max_images_per_task > 4:
        errors.append("max_images_per_task must be between 1 and 4")

    if config.max_parallel_browsers < 1:
        errors.append("max_parallel_browsers must be at least 1")

    if config.max_contexts_per_profile < 1:
        errors.append("max_contexts_per_profile must be at least 1")

    if config.profile_lock_timeout_seconds < 5:
        warnings.append("profile_lock_timeout_seconds is very low; using values under 5s can cause flapping")
    
    # Validate image formats
    valid_formats = {".jpg", ".jpeg", ".png", ".webp"}
    invalid_formats = [f for f in config.supported_formats if f.lower() not in valid_formats]
    if invalid_formats:
        errors.append(f"Unsupported image formats: {', '.join(invalid_formats)}")
    
    # Log warnings (if logger is available)
    if logger:
        for warning in warnings:
            logger.warning("Configuration warning", warning=warning)
    
    # Raise error if critical issues found
    if errors:
        error_msg = "Configuration validation failed:\n\n" + "\n".join(f"• {e}" for e in errors)
        if logger:
            logger.error("Configuration validation failed", errors=errors)
        raise ConfigError(error_msg, details="Please fix the errors in config.yaml")
    
    # Only log success message once to avoid spam
    global _validation_logged
    if logger and not _validation_logged:
        logger.info("Configuration validated successfully")
        _validation_logged = True


def _create_default_config(config_path: Path):
    """Create a default config file if it doesn't exist."""
    default_config = {
        "app": {"name": "Autonomous Video Engine - AVE", "version": "2.0.0"},
        "paths": {
            "chrome_base": os.getenv("CHROME_BASE_PATH", r"C:\Users\User\AppData\Local\Google\Chrome\User Data"),
            "assets_dir": "assets",
            "subjects_dir": "assets/subjects",
            "references_dir": "assets/references",
            "outputs_dir": "outputs",
            "outpaint_dir": "outputs/outpaint",
            "qwen_dir": "outputs/qwen",
            "montage_dir": "outputs/montage",
            "profiles_dir": "profiles",
            "logs_dir": "logs"
        },
        "sora": {
            "url": "https://sora.chatgpt.com/library",
            "default_profiles": ["Profile 3", "Profile 4", "Profile 5", "Profile 6", "Profile 7", "Profile 8", "Profile 9"],
            "timeout_seconds": 240,
            "navigation_retries": 3,
            "button_wait_seconds": 60,
            "notification_timeout_seconds": 240,
            "max_concurrent_browser_launches": 2,
            "browser_launch_delay_ms": 2000,
            "browser_stagger_delay_ms": 1000
        },
        "batch": {
            "max_concurrent_tasks": 10,
            "max_variants_per_task": 2,
            "semaphore_limit": 10,
            "max_parallel_browsers": 6
        },
        "images": {
            "supported_formats": [".jpg", ".jpeg", ".png", ".webp"],
            "max_size_mb": 50,
            "max_images_per_task": 4
        },
        "notifications": {
            "enabled": True,
            "on_task_complete": True,
            "on_batch_complete": True,
            "on_error": True
        },
        "logging": {
            "level": "INFO",
            "file_logging": True,
            "max_log_files": 10,
            "log_file_size_mb": 10
        },
        "network": {
            "proxies": []
        }
    }
    
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(default_config, f, default_flow_style=False, sort_keys=False)


# Global config instance
_config: Optional[AppConfig] = None
_validation_logged: bool = False


def get_config() -> AppConfig:
    """Get or create global configuration instance."""
    global _config
    if _config is None:
        _config = load_config()
    return _config

