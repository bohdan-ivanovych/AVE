"""Data Transfer Objects for type-safe data passing between layers."""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
from datetime import datetime
from enum import Enum


class TaskStatus(str, Enum):
    """Task execution status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PairingMode(str, Enum):
    """Image pairing mode."""
    SEQUENTIAL = "sequential"
    RANDOM = "random"
    MANUAL = "manual"


@dataclass
class ImagePair:
    """Represents a pair of images for generation."""
    images: List[Path]  # 1-4 images
    prompt: str
    enabled: bool = True
    task_id: Optional[str] = None
    last_status: Optional[str] = None


@dataclass
class GenerationTask:
    """Represents a single generation task."""
    task_id: str
    worker_id: int
    profile_name: str
    images: List[Path]
    prompt: str
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    output_files: List[Path] = None
    error_message: Optional[str] = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.output_files is None:
            self.output_files = []


@dataclass
class BatchJob:
    """Represents a batch of generation tasks."""
    job_id: str
    tasks: List[GenerationTask]
    pairing_mode: PairingMode
    created_at: datetime = None
    status: TaskStatus = TaskStatus.PENDING
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()


@dataclass
class UserProfile:
    """User profile with workspace isolation."""
    user_id: str
    username: str
    chrome_profile: str
    workspace_dir: Path
    created_at: datetime = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()


@dataclass
class PromptTemplate:
    """Prompt template for the prompt library."""
    template_id: str
    name: str
    content: str
    tags: List[str] = None
    is_favorite: bool = False
    created_at: datetime = None
    updated_at: Optional[datetime] = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.tags is None:
            self.tags = []

