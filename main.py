"""Main entry point for Autonomous Video Engine - AVE."""

import asyncio
import sys
from pathlib import Path
from tkinter import messagebox
import traceback

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.config import get_config, load_config, ConfigError
from src.services.logger import get_logger_service
from src.gui.app import AVEApp
from src.exceptions import AppError


def main():
    """Main entry point with comprehensive error handling.
    
    Handles configuration errors, initialization errors, and runtime errors
    with user-friendly messages.
    """
    try:
        # Load configuration
        try:
            config = load_config()
        except ConfigError as e:
            # Configuration errors - show to user before GUI is initialized
            error_msg = f"Configuration Error:\n\n{e.message}"
            if e.details:
                error_msg += f"\n\n{e.details}"
            print(error_msg, file=sys.stderr)
            # Try to show messagebox if possible
            try:
                import tkinter as tk
                root = tk.Tk()
                root.withdraw()
                messagebox.showerror("Configuration Error", error_msg)
                root.destroy()
            except Exception:
                pass
            sys.exit(1)
        except Exception as e:
            error_msg = f"Failed to load configuration:\n{str(e)}"
            print(error_msg, file=sys.stderr)
            traceback.print_exc()
            sys.exit(1)
        
        # Initialize logger
        try:
            logger_service = get_logger_service()
            logger = logger_service.get_logger("main")
            logger.info("Starting Autonomous Video Engine - AVE", version="2.0.0")
        except Exception as e:
            print(f"Warning: Failed to initialize logger: {e}", file=sys.stderr)
            logger = None
        
        # Create and run GUI
        try:
            app = AVEApp(config)
            app.run()
        except KeyboardInterrupt:
            if logger:
                logger.info("Application interrupted by user")
            print("\nApplication interrupted by user.", file=sys.stderr)
            sys.exit(0)
        except Exception as e:
            if logger:
                logger.error("Fatal error in GUI", error=str(e), exc_info=e)
            else:
                print(f"Fatal error: {e}", file=sys.stderr)
                traceback.print_exc()
            sys.exit(1)
        
    except AppError as e:
        # Application-specific errors
        error_msg = f"Application Error:\n\n{e.message}"
        if e.details:
            error_msg += f"\n\nDetails:\n{e.details}"
        print(error_msg, file=sys.stderr)
        try:
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Application Error", error_msg)
            root.destroy()
        except Exception:
            pass
        sys.exit(1)
    except Exception as e:
        # Unexpected errors
        error_msg = f"Unexpected error: {e}"
        print(error_msg, file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

