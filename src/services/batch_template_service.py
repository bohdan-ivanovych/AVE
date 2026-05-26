"""Batch template service for saving and loading batch configurations."""

import json
import uuid
from pathlib import Path
from typing import List, Optional, Dict
from datetime import datetime

from src.config import get_config
from src.services.logger import get_logger_service
from src.dto import ImagePair


class BatchTemplate:
    """Batch template configuration."""
    
    def __init__(
        self,
        template_id: str,
        name: str,
        image_pairs: List[Dict],
        pairing_mode: str,
        created_at: str,
        updated_at: Optional[str] = None,
        notes: Optional[str] = None
    ):
        self.template_id = template_id
        self.name = name
        self.image_pairs = image_pairs  # List of dict representations of ImagePair
        self.pairing_mode = pairing_mode
        self.created_at = created_at
        self.updated_at = updated_at
        self.notes = notes
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "template_id": self.template_id,
            "name": self.name,
            "image_pairs": self.image_pairs,
            "pairing_mode": self.pairing_mode,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "notes": self.notes
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "BatchTemplate":
        """Create from dictionary."""
        return cls(
            template_id=data["template_id"],
            name=data["name"],
            image_pairs=data["image_pairs"],
            pairing_mode=data["pairing_mode"],
            created_at=data["created_at"],
            updated_at=data.get("updated_at"),
            notes=data.get("notes")
        )


class BatchTemplateService:
    """Service for managing batch templates."""
    
    def __init__(self, config=None):
        self.config = config or get_config()
        self.logger = get_logger_service().get_logger("batch_template")
        self.templates_file = self.config.profiles_dir / "batch_templates.json"
        self.templates_file.parent.mkdir(parents=True, exist_ok=True)
        self._templates: Dict[str, BatchTemplate] = {}
        self._load_templates()
    
    def _load_templates(self):
        """Load templates from disk."""
        if not self.templates_file.exists():
            return
        
        try:
            with open(self.templates_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                for template_data in data.get("templates", []):
                    template = BatchTemplate.from_dict(template_data)
                    self._templates[template.template_id] = template
            self.logger.info("Batch templates loaded", count=len(self._templates))
        except Exception as e:
            self.logger.error("Failed to load templates", error=str(e))
            self._templates = {}
    
    def _save_templates(self):
        """Save templates to disk."""
        try:
            data = {
                "templates": [t.to_dict() for t in self._templates.values()],
                "updated_at": datetime.now().isoformat()
            }
            with open(self.templates_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logger.error("Failed to save templates", error=str(e))
    
    def create_template(
        self,
        name: str,
        image_pairs: List[ImagePair],
        pairing_mode: str,
        notes: Optional[str] = None
    ) -> BatchTemplate:
        """
        Create a new batch template.
        
        Args:
            name: Template name
            image_pairs: List of ImagePair objects
            pairing_mode: Pairing mode used
            notes: Optional notes
            
        Returns:
            Created BatchTemplate
        """
        template_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        
        # Convert ImagePair to dict
        pairs_data = []
        for pair in image_pairs:
            pairs_data.append({
                "images": [str(img) for img in pair.images],
                "prompt": pair.prompt,
                "enabled": pair.enabled
            })
        
        template = BatchTemplate(
            template_id=template_id,
            name=name,
            image_pairs=pairs_data,
            pairing_mode=pairing_mode,
            created_at=now,
            notes=notes
        )
        
        self._templates[template_id] = template
        self._save_templates()
        self.logger.info("Template created", template_id=template_id, name=name)
        return template
    
    def get_template(self, template_id: str) -> Optional[BatchTemplate]:
        """Get a template by ID."""
        return self._templates.get(template_id)
    
    def get_all_templates(self) -> List[BatchTemplate]:
        """Get all templates."""
        return list(self._templates.values())
    
    def delete_template(self, template_id: str) -> bool:
        """Delete a template."""
        if template_id not in self._templates:
            return False
        
        del self._templates[template_id]
        self._save_templates()
        self.logger.info("Template deleted", template_id=template_id)
        return True
    
    def load_template_to_pairs(self, template_id: str) -> tuple[List[ImagePair], str]:
        """
        Load template and convert to ImagePair list.
        
        Returns:
            Tuple of (image_pairs, pairing_mode)
        """
        template = self.get_template(template_id)
        if not template:
            raise ValueError(f"Template not found: {template_id}")
        
        pairs = []
        for pair_data in template.image_pairs:
            pairs.append(ImagePair(
                images=[Path(img) for img in pair_data["images"]],
                prompt=pair_data.get("prompt", ""),
                enabled=pair_data.get("enabled", True)
            ))
        
        return pairs, template.pairing_mode


# Global service instance
_template_service = None


def get_batch_template_service() -> BatchTemplateService:
    """Get or create global batch template service."""
    global _template_service
    if _template_service is None:
        _template_service = BatchTemplateService()
    return _template_service

