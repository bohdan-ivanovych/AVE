"""Structured logging service with file rotation and error aggregation."""

import logging
import sys
from pathlib import Path
from typing import Optional
from logging.handlers import RotatingFileHandler
import structlog
from structlog.stdlib import LoggerFactory


class LoggerService:
    """Centralized logging service with structured logging."""
    
    def __init__(self, config=None):
        # Lazy import to avoid circular dependency
        if config is None:
            try:
                from src.config import get_config
                config = get_config()
            except (RecursionError, RuntimeError):
                # Fallback to defaults if config loading causes recursion
                # This happens during initial config loading
                config = None
        
        self.config = config
        if config is not None:
            self.log_dir = self.config.logs_dir
            self.log_dir.mkdir(parents=True, exist_ok=True)
        else:
            # Use default values when config is not available
            self.log_dir = Path("logs")
            self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Configure structlog
        file_logging = self.config.file_logging if self.config is not None else False
        structlog.configure(
            processors=[
                structlog.stdlib.filter_by_level,
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                structlog.stdlib.PositionalArgumentsFormatter(),
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.processors.UnicodeDecoder(),
                structlog.processors.JSONRenderer() if file_logging else structlog.dev.ConsoleRenderer(),
            ],
            wrapper_class=structlog.stdlib.BoundLogger,
            context_class=dict,
            logger_factory=LoggerFactory(),
            cache_logger_on_first_use=True,
        )
        
        # Setup standard logging
        self._setup_standard_logging()
        
        # Error aggregation
        self.error_count = 0
        self.warning_count = 0
    
    def _setup_standard_logging(self):
        """Setup standard Python logging with file rotation."""
        log_level_str = self.config.log_level if self.config is not None else "INFO"
        log_level = getattr(logging, log_level_str.upper(), logging.INFO)
        
        # Root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(log_level)
        
        # Check if handlers already exist to prevent duplicates
        has_console_handler = any(
            isinstance(h, logging.StreamHandler) and h.stream == sys.stdout
            for h in root_logger.handlers
        )
        has_file_handler = any(
            isinstance(h, RotatingFileHandler)
            for h in root_logger.handlers
        )
        
        # Console handler
        if not has_console_handler:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(log_level)
            console_formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            console_handler.setFormatter(console_formatter)
            root_logger.addHandler(console_handler)
        
        # File handler with rotation
        file_logging = self.config.file_logging if self.config is not None else False
        if file_logging and not has_file_handler:
            log_file = self.log_dir / "app.log"
            log_file_size_mb = self.config.log_file_size_mb if self.config is not None else 10
            max_log_files = self.config.max_log_files if self.config is not None else 5
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=log_file_size_mb * 1024 * 1024,
                backupCount=max_log_files,
                encoding="utf-8"
            )
            file_handler.setLevel(log_level)
            file_formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            file_handler.setFormatter(file_formatter)
            root_logger.addHandler(file_handler)
    
    def get_logger(self, name: str = "app"):
        """Get a structured logger instance."""
        return structlog.get_logger(name)
    
    def log_error(self, error: Exception, context: Optional[str] = None):
        """Log an error and increment error counter."""
        self.error_count += 1
        logger = self.get_logger("error")
        logger.error(
            "Error occurred",
            error=str(error),
            error_type=type(error).__name__,
            context=context,
            exc_info=True
        )
    
    def log_warning(self, message: str, context: Optional[str] = None):
        """Log a warning and increment warning counter."""
        self.warning_count += 1
        logger = self.get_logger("warning")
        logger.warning("Warning", message=message, context=context)
    
    def get_stats(self) -> dict:
        """Get logging statistics."""
        return {
            "error_count": self.error_count,
            "warning_count": self.warning_count
        }


# Global logger service instance
_logger_service: Optional[LoggerService] = None
_initializing: bool = False


def get_logger_service() -> LoggerService:
    """Get or create global logger service."""
    global _logger_service, _initializing
    
    if _logger_service is not None:
        return _logger_service
    
    # Prevent recursion during initialization
    if _initializing:
        # Return a minimal logger service with defaults
        return LoggerService(config=None)
    
    try:
        _initializing = True
        _logger_service = LoggerService()
        return _logger_service
    except RecursionError:
        # If recursion occurs, return a minimal logger
        return LoggerService(config=None)
    finally:
        _initializing = False

