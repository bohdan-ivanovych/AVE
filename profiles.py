import os
from pathlib import Path
from utils import LOG_QUEUE
from src.config import get_config

# Get default values from config (will be overridden if passed to __init__)
def _get_default_chrome_base():
    """Get default Chrome base path from config."""
    try:
        config = get_config()
        return config.chrome_base
    except Exception:
        # Fallback to common Windows path if config fails
        user = os.getenv("USERNAME", "User")
        return Path(os.getenv("CHROME_BASE_PATH", rf"C:\Users\{user}\AppData\Local\Google\Chrome\User Data"))

def _get_default_profiles():
    """Get default profiles from config."""
    try:
        config = get_config()
        return config.default_profiles
    except Exception:
        # Fallback to default range if config fails
        return [f"Profile {i}" for i in range(3, 10)]

class LoginManager:
    def __init__(self, chrome_base=None, profile_names=None):
        """Initialize LoginManager with config values or provided values.
        
        Args:
            chrome_base: Chrome base directory path (defaults to config value)
            profile_names: List of profile names (defaults to config value)
        """
        if chrome_base is None:
            chrome_base = _get_default_chrome_base()
        if profile_names is None:
            profile_names = _get_default_profiles()
        
        self.chrome_base = Path(chrome_base)
        self.profile_names = profile_names
        self.status = {p: "unknown" for p in profile_names}

    def validate_all(self):
        found = 0
        not_found = 0
        for pname in self.profile_names:
            pdir = self.chrome_base / pname
            if pdir.exists():
                self.status[pname] = "available"
                LOG_QUEUE.put(f"✓ Profile {pname}: available\n")
                found += 1
            else:
                self.status[pname] = "NOT FOUND"
                LOG_QUEUE.put(f"✗ Profile {pname}: NOT FOUND\n")
                not_found += 1
        LOG_QUEUE.put(f"Checked {len(self.profile_names)} profiles: {found} available, {not_found} missing\n")
        return self.status

    def auto_login_profiles(self):
        """
        Dummy action for future development:
        Could run Playwright login check for each profile, update status if session works/needs manual login.
        """
        LOG_QUEUE.put("Auto-login for all profiles not implemented here (handled in core/login_mode_sequential)\n")
        return self.status

    def manual_login_flow(self, profile_name):
        """
        Open browser for manual login: Call Playwright browser launch, open Sora, wait for user, verify cookie/session.
        """
        LOG_QUEUE.put(f"Manual login required for {profile_name}.\nPlease use Login Mode button in GUI and login in opened browser, then press Enter in terminal.\n")

def main():
    mgr = LoginManager()
    print("Validating Chrome profiles for Sora Automation...")
    mgr.validate_all()
    for prof in mgr.status:
        print(f"{prof}: {mgr.status[prof]}")

if __name__ == "__main__":
    main()
