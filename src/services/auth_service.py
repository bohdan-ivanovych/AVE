"""Authentication and user profile management service."""

from pathlib import Path
from typing import List, Optional, Dict
import json

from src.config import get_config
from src.services.logger import get_logger_service
from src.utils.path_utils import sanitize_path, ensure_directory
from src.dto import UserProfile


class AuthService:
    """Service for managing user authentication and profiles."""
    
    def __init__(self, config=None):
        self.config = config or get_config()
        self.logger = get_logger_service().get_logger("auth")
        self.profiles_file = self.config.profiles_dir / "users.json"
        ensure_directory(self.config.profiles_dir)
        self._profiles: Dict[str, UserProfile] = {}
        self._load_profiles()
    
    def _load_profiles(self):
        """Load user profiles from disk."""
        if not self.profiles_file.exists():
            # Create default profiles from config
            for profile_name in self.config.default_profiles:
                user_id = f"user_{profile_name.replace(' ', '_').lower()}"
                workspace_dir = self.config.profiles_dir / user_id
                profile = UserProfile(
                    user_id=user_id,
                    username=profile_name,
                    chrome_profile=profile_name,
                    workspace_dir=workspace_dir
                )
                self._profiles[user_id] = profile
            self._save_profiles()
            return
        
        try:
            with open(self.profiles_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                for user_data in data.get("profiles", []):
                    profile = UserProfile(
                        user_id=user_data["user_id"],
                        username=user_data["username"],
                        chrome_profile=user_data["chrome_profile"],
                        workspace_dir=Path(user_data["workspace_dir"])
                    )
                    self._profiles[profile.user_id] = profile
        except Exception as e:
            self.logger.error("Failed to load profiles", error=str(e))
    
    def _save_profiles(self):
        """Save user profiles to disk."""
        try:
            data = {
                "profiles": [
                    {
                        "user_id": p.user_id,
                        "username": p.username,
                        "chrome_profile": p.chrome_profile,
                        "workspace_dir": str(p.workspace_dir)
                    }
                    for p in self._profiles.values()
                ]
            }
            with open(self.profiles_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            self.logger.error("Failed to save profiles", error=str(e))
    
    def get_profile(self, user_id: str) -> Optional[UserProfile]:
        """Get a user profile by ID."""
        return self._profiles.get(user_id)
    
    def get_all_profiles(self) -> List[UserProfile]:
        """Get all user profiles."""
        return list(self._profiles.values())
    
    def create_profile(
        self,
        username: str,
        chrome_profile: str,
        user_id: Optional[str] = None
    ) -> UserProfile:
        """
        Create a new user profile.
        
        Args:
            username: Display name for the user
            chrome_profile: Chrome profile name
            user_id: Optional custom user ID (auto-generated if not provided)
            
        Returns:
            Created UserProfile instance
        """
        if user_id is None:
            user_id = f"user_{username.lower().replace(' ', '_')}"
        
        if user_id in self._profiles:
            raise ValueError(f"User ID already exists: {user_id}")
        
        # Validate Chrome profile path
        chrome_base = sanitize_path(self.config.chrome_base)
        profile_path = sanitize_path(chrome_profile, base_dir=chrome_base)
        
        if not profile_path.exists():
            self.logger.warning("Chrome profile path does not exist", path=str(profile_path))
        
        workspace_dir = self.config.profiles_dir / user_id
        ensure_directory(workspace_dir)
        
        profile = UserProfile(
            user_id=user_id,
            username=username,
            chrome_profile=chrome_profile,
            workspace_dir=workspace_dir
        )
        
        self._profiles[user_id] = profile
        self._save_profiles()
        self.logger.info("Profile created", user_id=user_id, username=username)
        
        return profile
    
    def update_profile(self, user_id: str, **kwargs) -> Optional[UserProfile]:
        """Update a user profile."""
        profile = self._profiles.get(user_id)
        if not profile:
            return None
        
        if "username" in kwargs:
            profile.username = kwargs["username"]
        if "chrome_profile" in kwargs:
            profile.chrome_profile = kwargs["chrome_profile"]
        
        self._save_profiles()
        self.logger.info("Profile updated", user_id=user_id)
        return profile
    
    def delete_profile(self, user_id: str) -> bool:
        """Delete a user profile."""
        if user_id not in self._profiles:
            return False
        
        del self._profiles[user_id]
        self._save_profiles()
        self.logger.info("Profile deleted", user_id=user_id)
        return True
    
    def get_workspace_dir(self, user_id: str) -> Optional[Path]:
        """Get workspace directory for a user."""
        profile = self.get_profile(user_id)
        if profile:
            ensure_directory(profile.workspace_dir)
            return profile.workspace_dir
        return None
    
    def validate_chrome_profile(self, profile_name: str) -> bool:
        """Validate that a Chrome profile exists."""
        try:
            chrome_base = sanitize_path(self.config.chrome_base)
            profile_path = sanitize_path(profile_name, base_dir=chrome_base)
            return profile_path.exists()
        except Exception:
            return False


# Global auth service instance
_auth_service = None


def get_auth_service() -> AuthService:
    """Get or create global auth service."""
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
    return _auth_service

