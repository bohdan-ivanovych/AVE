"""Custom exceptions for the application."""

from typing import Optional


class AppError(Exception):
    """Base exception for application errors."""
    
    def __init__(self, message: str, details: Optional[str] = None):
        self.message = message
        self.details = details
        super().__init__(self.message)
    
    def __str__(self) -> str:
        if self.details:
            return f"{self.message}\nDetails: {self.details}"
        return self.message


class ConfigError(AppError):
    """Configuration-related errors."""
    pass


class ImageValidationError(AppError):
    """Image validation errors."""
    pass


class BrowserError(AppError):
    """Browser automation errors."""
    pass


class GenerationError(AppError):
    """Generation task errors."""
    pass


class CancellationError(AppError):
    """Operation cancellation errors."""
    pass


class ProfileError(AppError):
    """Chrome profile errors."""
    pass


class TemplateError(AppError):
    """Template-related errors."""
    pass

