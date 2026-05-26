"""Windows toast notifications wrapper (best-effort)."""

import contextlib
import io
import platform
import warnings
from typing import Optional

from src.services.logger import get_logger_service


class NotificationService:
    """Provides basic Windows notifications via win10toast if available."""

    def __init__(self):
        self.logger = get_logger_service().get_logger("notifications")
        self._toast = None
        self._enabled = platform.system() == "Windows"

        if not self._enabled:
            self.logger.info("Notifications disabled: non-Windows platform")
            return

        try:
            # Suppress pkg_resources deprecation warning
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=UserWarning, module="win10toast")
                from win10toast import ToastNotifier  # type: ignore

                self._toast = ToastNotifier()
                self._enabled = True
                self.logger.info("win10toast loaded for notifications")
        except Exception as e:
            self._toast = None
            self._enabled = False
            self.logger.warning("win10toast not available; notifications will be no-op", error=str(e))

    def notify(self, title: str, msg: str, duration: int = 6, icon_path: Optional[str] = None) -> bool:
        """
        Show a toast if possible; otherwise log and return False.

        Returns:
            True if a toast was triggered, False otherwise.
        """
        if not self._enabled:
            self.logger.debug("Notification skipped: not enabled or not Windows", title=title)
            return False

        if not self._toast:
            self.logger.debug("Notification skipped: toast backend unavailable", title=title)
            return False

        try:
            # Suppress stderr to hide WNDPROC/WPARAM errors from win10toast
            # These errors occur in background threads and can't be caught normally
            with contextlib.redirect_stderr(io.StringIO()):
                try:
                    self._toast.show_toast(
                        title,
                        msg,
                        duration=duration,
                        icon_path=icon_path,
                        threaded=True,
                    )
                    self.logger.debug("Notification shown", title=title)
                    return True
                except (TypeError, ValueError, Exception) as e:
                    # Ignore WNDPROC/WPARAM errors from win10toast
                    self.logger.debug("Toast notification error (ignored)", error=str(e), title=title)
                    return False
        except Exception as e:
            # Silently ignore all notification errors but log for diagnostics
            self.logger.debug("Notification failed", error=str(e), title=title)
            return False


_notifications: Optional[NotificationService] = None


def get_notification_service() -> NotificationService:
    """Return a singleton notification service instance."""
    global _notifications
    if _notifications is None:
        _notifications = NotificationService()
    return _notifications


