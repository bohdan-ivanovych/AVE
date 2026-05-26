"""Simple prompt library service for saving prompts to a JSON file."""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List

from src.services.logger import get_logger_service
from src.config import get_config


@dataclass
class PromptEntry:
    prompt: str
    created_at: str  # ISO timestamp


class PromptLibraryService:
    """Persists prompts to a JSON file under assets/prompts.json."""

    def __init__(self, storage_path: Path | None = None):
        self.config = get_config()
        self.logger = get_logger_service().get_logger("prompt_library")
        default_path = (self.config.assets_dir / "prompts.json")
        self.storage_path = storage_path or default_path
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

    def _load_all(self) -> List[PromptEntry]:
        if not self.storage_path.exists():
            return []
        try:
            data = json.loads(self.storage_path.read_text(encoding="utf-8"))
            entries: List[PromptEntry] = []
            for item in data if isinstance(data, list) else []:
                if isinstance(item, dict) and "prompt" in item:
                    entries.append(PromptEntry(prompt=item["prompt"], created_at=item.get("created_at", "")))
            return entries
        except Exception as e:
            self.logger.warning("Failed to read prompts.json", error=str(e))
            return []

    def _save_all(self, entries: List[PromptEntry]) -> None:
        try:
            serializable = [entry.__dict__ for entry in entries]
            self.storage_path.write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            self.logger.error("Failed to write prompts.json", error=str(e))

    def add_prompt(self, prompt: str) -> None:
        """Append a prompt to the library if non-empty."""
        prompt_text = (prompt or "").strip()
        if not prompt_text:
            return
        entries = self._load_all()
        entries.append(PromptEntry(prompt=prompt_text, created_at=datetime.utcnow().isoformat()))
        self._save_all(entries)
        self.logger.info("Prompt saved to library")


_svc: PromptLibraryService | None = None


def get_prompt_library_service() -> PromptLibraryService:
    global _svc
    if _svc is None:
        _svc = PromptLibraryService()
    return _svc


