"""History service for tracking batch jobs and generation runs."""

import json
import asyncio
from pathlib import Path
from typing import List, Optional, Dict
from datetime import datetime
from dataclasses import dataclass, asdict

from src.config import get_config
from src.services.logger import get_logger_service


@dataclass
class HistoryEntry:
    """Single history entry for a batch job."""
    job_id: str
    timestamp: str
    task_count: int
    completed: int
    failed: int
    duration_seconds: float
    pairing_mode: Optional[str] = None
    output_dir: Optional[str] = None
    notes: Optional[str] = None


class HistoryService:
    """Service for managing generation history."""
    
    def __init__(self, config=None):
        self.config = config or get_config()
        self.logger = get_logger_service().get_logger("history")
        self.history_file = self.config.logs_dir / "history.json"
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        self._history: List[HistoryEntry] = []
        self._load_history()
    
    def _load_history(self):
        """Load history from disk."""
        if not self.history_file.exists():
            return
        
        try:
            with open(self.history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                self._history = [
                    HistoryEntry(**entry) for entry in data.get("entries", [])
                ]
            self.logger.info("History loaded", count=len(self._history))
        except Exception as e:
            self.logger.error("Failed to load history", error=str(e))
            self._history = []
    
    def _save_history(self):
        """Save history to disk."""
        try:
            data = {
                "entries": [asdict(entry) for entry in self._history],
                "updated_at": datetime.now().isoformat()
            }
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logger.error("Failed to save history", error=str(e))
    
    def add_entry(
        self,
        job_id: str,
        task_count: int,
        completed: int,
        failed: int,
        duration_seconds: float,
        pairing_mode: Optional[str] = None,
        output_dir: Optional[str] = None,
        notes: Optional[str] = None
    ) -> HistoryEntry:
        """
        Add a new history entry.
        
        Args:
            job_id: Job identifier
            task_count: Total number of tasks
            completed: Number of completed tasks
            failed: Number of failed tasks
            duration_seconds: Total duration in seconds
            pairing_mode: Pairing mode used
            output_dir: Output directory
            notes: Optional notes
            
        Returns:
            Created HistoryEntry
        """
        entry = HistoryEntry(
            job_id=job_id,
            timestamp=datetime.now().isoformat(),
            task_count=task_count,
            completed=completed,
            failed=failed,
            duration_seconds=duration_seconds,
            pairing_mode=pairing_mode,
            output_dir=output_dir,
            notes=notes
        )
        
        self._history.append(entry)
        # Keep only last 100 entries
        if len(self._history) > 100:
            self._history = self._history[-100:]
        
        self._save_history()
        self.logger.info("History entry added", job_id=job_id)
        return entry
    
    def get_history(self, limit: int = 50) -> List[HistoryEntry]:
        """
        Get history entries.
        
        Args:
            limit: Maximum number of entries to return
            
        Returns:
            List of history entries (most recent first)
        """
        return list(reversed(self._history[-limit:]))
    
    def get_entry(self, job_id: str) -> Optional[HistoryEntry]:
        """Get a specific history entry by job ID."""
        for entry in self._history:
            if entry.job_id == job_id:
                return entry
        return None
    
    def clear_history(self):
        """Clear all history."""
        self._history = []
        self._save_history()
        self.logger.info("History cleared")
    
    def get_stats(self) -> Dict:
        """Get statistics from history."""
        if not self._history:
            return {
                "total_jobs": 0,
                "total_tasks": 0,
                "total_completed": 0,
                "total_failed": 0,
                "average_duration": 0.0
            }
        
        total_jobs = len(self._history)
        total_tasks = sum(e.task_count for e in self._history)
        total_completed = sum(e.completed for e in self._history)
        total_failed = sum(e.failed for e in self._history)
        avg_duration = sum(e.duration_seconds for e in self._history) / total_jobs
        
        return {
            "total_jobs": total_jobs,
            "total_tasks": total_tasks,
            "total_completed": total_completed,
            "total_failed": total_failed,
            "average_duration": avg_duration,
            "success_rate": (total_completed / total_tasks * 100) if total_tasks > 0 else 0
        }


# Global history service instance
_history_service = None


def get_history_service() -> HistoryService:
    """Get or create global history service."""
    global _history_service
    if _history_service is None:
        _history_service = HistoryService()
    return _history_service

