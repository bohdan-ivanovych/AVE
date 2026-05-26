"""Unit tests for ImageService."""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from PIL import Image
import io

from src.services.image_service import ImageService
from src.config import AppConfig


class TestImageService:
    """Test cases for ImageService."""
    
    @pytest.fixture
    def mock_config(self):
        """Create a mock configuration."""
        config = Mock(spec=AppConfig)
        config.supported_formats = [".jpg", ".jpeg", ".png", ".webp"]
        config.max_size_mb = 50
        config.max_images_per_task = 4
        return config
    
    @pytest.fixture
    def image_service(self, mock_config):
        """Create ImageService instance with mock config."""
        return ImageService(config=mock_config)
    
    @pytest.fixture
    def temp_image_file(self, tmp_path):
        """Create a temporary valid image file."""
        img_path = tmp_path / "test_image.png"
        # Create a simple 1x1 PNG image
        img = Image.new('RGB', (1, 1), color='red')
        img.save(img_path)
        return img_path
    
    def test_validate_image_valid(self, image_service, temp_image_file):
        """Test validation of a valid image."""
        is_valid, error = image_service.validate_image(temp_image_file)
        assert is_valid is True
        assert error is None
    
    def test_validate_image_not_exists(self, image_service):
        """Test validation of non-existent image."""
        non_existent = Path("/nonexistent/image.png")
        is_valid, error = image_service.validate_image(non_existent)
        assert is_valid is False
        assert error is not None
        assert "not found" in error.lower()
    
    def test_validate_image_invalid_format(self, image_service, tmp_path):
        """Test validation of unsupported format."""
        invalid_file = tmp_path / "test.txt"
        invalid_file.write_text("not an image")
        is_valid, error = image_service.validate_image(invalid_file)
        assert is_valid is False
    
    def test_validate_image_group_valid(self, image_service, temp_image_file):
        """Test validation of a valid image group."""
        images = [temp_image_file]
        is_valid, error, sanitized = image_service.validate_image_group(images)
        assert is_valid is True
        assert error is None
        assert len(sanitized) == 1
    
    def test_validate_image_group_too_few(self, image_service):
        """Test validation with too few images."""
        images = []
        is_valid, error, sanitized = image_service.validate_image_group(images, min_images=1)
        assert is_valid is False
        assert error is not None
    
    def test_validate_image_group_too_many(self, image_service, temp_image_file):
        """Test validation with too many images."""
        images = [temp_image_file] * 10  # More than max_images_per_task
        is_valid, error, sanitized = image_service.validate_image_group(images)
        assert is_valid is False
        assert error is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

