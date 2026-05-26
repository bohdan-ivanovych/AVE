"""Error handling utilities for GUI components."""

from tkinter import messagebox
from typing import Optional, Callable, Tuple
import traceback
from pathlib import Path

from src.services.logger import get_logger_service


def show_error(
    title: str,
    message: str,
    details: Optional[str] = None,
    exc_info: Optional[Exception] = None,
    logger=None
):
    """
    Show user-friendly error message with optional details.
    
    Args:
        title: Error title
        message: Main error message
        details: Optional detailed error information
        exc_info: Optional exception for logging
        logger: Optional logger instance
    """
    if logger and exc_info:
        logger.error(title, error=str(exc_info), exc_info=exc_info)
    elif logger:
        logger.error(title, message=message)
    
    # Build full message
    full_message = message
    if details:
        full_message += f"\n\nDetails:\n{details}"
    
    # Truncate if too long
    if len(full_message) > 1000:
        full_message = full_message[:1000] + "\n\n... (truncated)"
    
    messagebox.showerror(title, full_message, icon="error")


def show_warning(title: str, message: str, logger=None):
    """Show warning message."""
    if logger:
        logger.warning(title, message=message)
    messagebox.showwarning(title, message, icon="warning")


def show_info(title: str, message: str, logger=None):
    """Show info message."""
    if logger:
        logger.info(title, message=message)
    messagebox.showinfo(title, message, icon="info")


def validate_path(path: Path, must_exist: bool = True, must_be_file: bool = False, must_be_dir: bool = False) -> Tuple[bool, Optional[str]]:
    """
    Validate a file path.
    
    Args:
        path: Path to validate
        must_exist: Whether path must exist
        must_be_file: Whether path must be a file
        must_be_dir: Whether path must be a directory
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        if must_exist and not path.exists():
            return False, f"Path does not exist: {path}"
        
        if must_be_file and not path.is_file():
            return False, f"Path is not a file: {path}"
        
        if must_be_dir and not path.is_dir():
            return False, f"Path is not a directory: {path}"
        
        return True, None
    except Exception as e:
        return False, f"Path validation error: {str(e)}"


def safe_execute(
    func: Callable,
    error_title: str = "Error",
    error_message: str = "An error occurred",
    logger=None,
    default_return=None
):
    """
    Safely execute a function with error handling.
    
    Args:
        func: Function to execute
        error_title: Title for error message
        error_message: Base error message
        logger: Optional logger instance
        default_return: Value to return on error
        
    Returns:
        Function result or default_return on error
    """
    try:
        return func()
    except Exception as e:
        if logger:
            logger.error(error_title, error=str(e), exc_info=e)
        show_error(error_title, error_message, details=str(e), exc_info=e, logger=logger)
        return default_return

