"""Image service for validation, processing, and management."""

from pathlib import Path
from typing import List, Optional, Tuple
from PIL import Image
import aiofiles
import asyncio

from src.config import get_config
from src.services.logger import get_logger_service
from src.utils.path_utils import sanitize_path, validate_image_path, ensure_directory


class ImageService:
    """Service for image operations and validation."""
    
    def __init__(self, config=None):
        self.config = config or get_config()
        self.logger = get_logger_service().get_logger("image")
    
    def validate_image(
        self,
        image_path: Path,
        check_exists: bool = True
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate an image file.
        
        Args:
            image_path: Path to image file
            check_exists: Whether to check if file exists
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            sanitized = sanitize_path(image_path)
            
            if check_exists and not sanitized.exists():
                return False, f"Image file not found: {sanitized}"
            
            if not validate_image_path(
                sanitized,
                self.config.supported_formats,
                self.config.max_size_mb
            ):
                return False, f"Image validation failed: invalid format or size > {self.config.max_size_mb}MB"
            
            # Try to open with PIL to verify it's a valid image
            try:
                with Image.open(sanitized) as img:
                    img.verify()
            except Exception as e:
                return False, f"Image file is corrupted: {str(e)}"
            
            return True, None
            
        except ValueError as e:
            return False, f"Invalid path: {str(e)}"
        except Exception as e:
            return False, f"Validation error: {str(e)}"
    
    def validate_image_group(
        self,
        image_paths: List[Path],
        min_images: int = 1,
        max_images: Optional[int] = None
    ) -> Tuple[bool, Optional[str], List[Path]]:
        """
        Validate a group of images.
        
        Args:
            image_paths: List of image paths
            min_images: Minimum number of images required
            max_images: Maximum number of images allowed (defaults to config)
            
        Returns:
            Tuple of (is_valid, error_message, sanitized_paths)
        """
        max_images = max_images or self.config.max_images_per_task
        
        if len(image_paths) < min_images:
            return False, f"At least {min_images} image(s) required, got {len(image_paths)}", []
        
        if len(image_paths) > max_images:
            return False, f"Maximum {max_images} image(s) allowed, got {len(image_paths)}", []
        
        sanitized_paths = []
        for img_path in image_paths:
            is_valid, error = self.validate_image(img_path)
            if not is_valid:
                return False, error, []
            
            try:
                sanitized = sanitize_path(img_path)
                sanitized_paths.append(sanitized)
            except ValueError as e:
                return False, f"Invalid path: {str(e)}", []
        
        return True, None, sanitized_paths
    
    async def get_image_info(self, image_path: Path) -> Optional[dict]:
        """
        Get image metadata asynchronously.
        
        Args:
            image_path: Path to image file
            
        Returns:
            Dictionary with image info or None if error
        """
        try:
            sanitized = sanitize_path(image_path)
            if not sanitized.exists():
                return None
            
            # Use asyncio to run blocking PIL operations
            loop = asyncio.get_event_loop()
            with Image.open(sanitized) as img:
                info = await loop.run_in_executor(
                    None,
                    lambda: {
                        "width": img.width,
                        "height": img.height,
                        "format": img.format,
                        "mode": img.mode,
                        "size_bytes": sanitized.stat().st_size,
                        "size_mb": round(sanitized.stat().st_size / (1024 * 1024), 2)
                    }
                )
            return info
        except Exception as e:
            self.logger.warning("Failed to get image info", error=str(e), path=str(image_path))
            return None
    
    def glob_images(self, directory: Path, extensions: Optional[List[str]] = None) -> List[Path]:
        """
        Find all images in a directory.
        
        Args:
            directory: Directory to search
            extensions: List of extensions to search for (defaults to config)
            
        Returns:
            List of image paths, sorted
        """
        extensions = extensions or self.config.supported_formats
        images = []
        
        try:
            sanitized_dir = sanitize_path(directory)
            if not sanitized_dir.exists() or not sanitized_dir.is_dir():
                return images
            
            for ext in extensions:
                pattern = f"*{ext}"
                images.extend(sorted(sanitized_dir.glob(pattern)))
                # Also try uppercase
                images.extend(sorted(sanitized_dir.glob(pattern.upper())))
            
            # Remove duplicates and sort
            images = sorted(set(images))
            self.logger.debug("Found images", directory=str(directory), count=len(images))
            return images
            
        except Exception as e:
            self.logger.error("Error globbing images", error=str(e), directory=str(directory))
            return []

