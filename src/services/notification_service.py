"""Windows notification service using win10toast."""

import contextlib
import io
import platform
import warnings
from typing import Optional

from src.config import get_config
from src.services.logger import get_logger_service


class NotificationService:
    """Service for Windows push notifications."""
    
    def __init__(self, config=None):
        self.config = config or get_config()
        self.logger = get_logger_service().get_logger("notification")
        self._notifier: Optional[object] = None
        self._enabled = self.config.notifications_enabled and platform.system() == "Windows"
        
        if self._enabled:
            try:
                # Suppress pkg_resources deprecation warning
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore", category=UserWarning, module="win10toast")
                    from win10toast import ToastNotifier  # type: ignore
                    self._notifier = ToastNotifier()
            except Exception as e:
                self.logger.warning("Failed to initialize notification service", error=str(e))
                self._enabled = False
    
    def notify(
        self,
        title: str,
        message: str,
        duration: int = 5,
        icon_path: Optional[str] = None
    ) -> bool:
        """
        Show a Windows notification.
        
        Args:
            title: Notification title
            message: Notification message
            duration: Display duration in seconds
            icon_path: Optional path to icon file
            
        Returns:
            True if notification shown, False otherwise
        """
        if not self._enabled or not self._notifier:
            return False
        
        try:
            # Suppress stderr to hide WNDPROC/WPARAM errors from win10toast
            # These errors occur in background threads and can't be caught normally
            with contextlib.redirect_stderr(io.StringIO()):
                try:
                    self._notifier.show_toast(
                        title=title,
                        msg=message,
                        duration=duration,
                        icon_path=icon_path,
                        threaded=True
                    )
                    self.logger.debug("Notification shown", title=title)
                    return True
                except (TypeError, ValueError, Exception) as e:
                    # Ignore WNDPROC/WPARAM errors from win10toast
                    self.logger.debug("Toast notification error (ignored)", error=str(e))
                    return False
        except Exception as e:
            self.logger.debug("Notification failed", error=str(e))
            return False
    
    def notify_task_complete(
        self,
        task_name: str,
        output_count: int
    ) -> bool:
        """Notify when a task completes."""
        if not self.config.notify_on_task_complete:
            return False
        
        return self.notify(
            title="Task Complete",
            message=f"{task_name}: {output_count} variant(s) generated"
        )
    
    def notify_batch_complete(
        self,
        total_tasks: int,
        successful: int,
        failed: int
    ) -> bool:
        """Notify when a batch job completes."""
        if not self.config.notify_on_batch_complete:
            return False
        
        return self.notify(
            title="Batch Complete",
            message=f"Completed {successful}/{total_tasks} tasks ({failed} failed)"
        )
    
    def notify_error(
        self,
        error_message: str,
        context: Optional[str] = None
    ) -> bool:
        """Notify when an error occurs."""
        if not self.config.notify_on_error:
            return False
        
        message = error_message
        if context:
            message = f"{context}: {message}"
        
        return self.notify(
            title="Error",
            message=message,
            duration=10
        )


# Global notification service instance
_notification_service = None


def get_notification_service() -> NotificationService:
    """Get or create global notification service."""
    global _notification_service
    if _notification_service is None:
        _notification_service = NotificationService()
    return _notification_service

