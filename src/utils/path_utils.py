"""Safe path utilities to prevent path injection attacks."""

import os
from pathlib import Path
from typing import List, Optional


def sanitize_path(path: str | Path, base_dir: Optional[Path] = None) -> Path:
    """
    Sanitize and validate a file path to prevent directory traversal attacks.
    
    Args:
        path: The path to sanitize
        base_dir: Optional base directory to resolve relative paths against
        
    Returns:
        Resolved, sanitized Path object
        
    Raises:
        ValueError: If path contains dangerous patterns or is outside base_dir
    """
    path_obj = Path(path)
    
    # Check for dangerous patterns
    path_str = str(path_obj)
    dangerous_patterns = ["..", "~", "\x00"]
    for pattern in dangerous_patterns:
        if pattern in path_str:
            raise ValueError(f"Path contains dangerous pattern: {pattern}")
    
    # Resolve to absolute path
    if path_obj.is_absolute():
        resolved = path_obj.resolve()
    else:
        if base_dir:
            resolved = (base_dir / path_obj).resolve()
        else:
            resolved = Path.cwd() / path_obj.resolve()
    
    # If base_dir is specified, ensure path is within it
    if base_dir:
        base_resolved = base_dir.resolve()
        try:
            resolved.relative_to(base_resolved)
        except ValueError:
            raise ValueError(f"Path {resolved} is outside base directory {base_resolved}")
    
    return resolved


def validate_image_path(path: Path, allowed_extensions: List[str], max_size_mb: int) -> bool:
    """
    Validate that a path points to a valid image file.
    
    Args:
        path: Path to validate
        allowed_extensions: List of allowed file extensions (e.g., [".jpg", ".png"])
        max_size_mb: Maximum file size in MB
        
    Returns:
        True if valid, False otherwise
    """
    if not path.exists():
        return False
    
    if not path.is_file():
        return False
    
    # Check extension
    if path.suffix.lower() not in [ext.lower() for ext in allowed_extensions]:
        return False
    
    # Check file size
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > max_size_mb:
        return False
    
    return True


def ensure_directory(path: Path) -> Path:
    """Ensure a directory exists, creating it if necessary."""
    path.mkdir(parents=True, exist_ok=True)
    return path

