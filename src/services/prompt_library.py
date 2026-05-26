"""Prompt library service with SQLite backend for templates, search, tags, and favorites."""

import asyncio
import json
import aiosqlite
import uuid
from pathlib import Path
from typing import List, Optional
from datetime import datetime

from src.config import get_config
from src.services.logger import get_logger_service
from src.dto import PromptTemplate


class PromptLibrary:
    """Service for managing prompt templates with SQLite storage."""
    
    def __init__(self, config=None, db_path: Optional[Path] = None):
        self.config = config or get_config()
        self.logger = get_logger_service().get_logger("prompt_library")
        self.db_path = db_path or Path("prompts.db")
        self._init_db_task = None
    
    async def _ensure_db_initialized(self):
        """Ensure database is initialized (lazy initialization)."""
        if self._init_db_task is None:
            self._init_db_task = asyncio.create_task(self._init_database())
            await self._init_db_task
    
    async def _init_database(self):
        """Initialize SQLite database with schema."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS prompt_templates (
                    template_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tags TEXT,  -- JSON array
                    is_favorite INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT
                )
            """)
            
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_name ON prompt_templates(name)
            """)
            
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_favorite ON prompt_templates(is_favorite)
            """)
            
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_created ON prompt_templates(created_at)
            """)
            
            # Full-text search index (SQLite FTS5)
            await db.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS prompt_templates_fts USING fts5(
                    template_id,
                    name,
                    content,
                    tags,
                    content_rowid='template_id'
                )
            """)
            
            await db.commit()
            self.logger.info("Prompt library database initialized")
    
    async def create_template(
        self,
        name: str,
        content: str,
        tags: Optional[List[str]] = None,
        is_favorite: bool = False
    ) -> PromptTemplate:
        """
        Create a new prompt template.
        
        Args:
            name: Template name
            content: Template content/prompt text
            tags: Optional list of tags
            is_favorite: Whether template is favorited
            
        Returns:
            Created PromptTemplate instance
        """
        await self._ensure_db_initialized()
        
        template_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        tags_json = json.dumps(tags or [])
        
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO prompt_templates 
                (template_id, name, content, tags, is_favorite, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (template_id, name, content, tags_json, 1 if is_favorite else 0, now))
            
            # Update FTS index
            await db.execute("""
                INSERT INTO prompt_templates_fts 
                (template_id, name, content, tags)
                VALUES (?, ?, ?, ?)
            """, (template_id, name, content, tags_json))
            
            await db.commit()
        
        template = PromptTemplate(
            template_id=template_id,
            name=name,
            content=content,
            tags=tags or [],
            is_favorite=is_favorite,
            created_at=datetime.fromisoformat(now)
        )
        
        self.logger.info("Template created", template_id=template_id, name=name)
        return template
    
    async def get_template(self, template_id: str) -> Optional[PromptTemplate]:
        """Get a template by ID."""
        await self._ensure_db_initialized()
        
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM prompt_templates WHERE template_id = ?",
                (template_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
                
                return self._row_to_template(row)
    
    async def search_templates(
        self,
        query: str,
        tags: Optional[List[str]] = None,
        favorites_only: bool = False,
        limit: int = 50
    ) -> List[PromptTemplate]:
        """
        Search templates by text query and optional filters.
        
        Args:
            query: Text search query
            tags: Optional list of tags to filter by
            favorites_only: Only return favorited templates
            limit: Maximum number of results
            
        Returns:
            List of matching PromptTemplate instances
        """
        await self._ensure_db_initialized()
        
        templates = []
        
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            
            # Build query
            conditions = []
            params = []
            
            if query:
                # Use FTS5 for full-text search
                conditions.append("""
                    template_id IN (
                        SELECT template_id FROM prompt_templates_fts 
                        WHERE prompt_templates_fts MATCH ?
                    )
                """)
                params.append(query)
            
            if favorites_only:
                conditions.append("is_favorite = 1")
            
            if tags:
                # Search for templates containing any of the specified tags
                tag_conditions = []
                for tag in tags:
                    tag_conditions.append("tags LIKE ?")
                    params.append(f'%"{tag}"%')
                conditions.append(f"({' OR '.join(tag_conditions)})")
            
            where_clause = " AND ".join(conditions) if conditions else "1=1"
            
            sql = f"""
                SELECT * FROM prompt_templates 
                WHERE {where_clause}
                ORDER BY is_favorite DESC, created_at DESC
                LIMIT ?
            """
            params.append(limit)
            
            async with db.execute(sql, params) as cursor:
                async for row in cursor:
                    templates.append(self._row_to_template(row))
        
        self.logger.debug("Template search", query=query, results=len(templates))
        return templates
    
    async def get_all_templates(
        self,
        favorites_only: bool = False,
        limit: int = 100
    ) -> List[PromptTemplate]:
        """Get all templates, optionally filtered by favorites."""
        await self._ensure_db_initialized()
        
        templates = []
        
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            
            sql = """
                SELECT * FROM prompt_templates
                WHERE ? = 0 OR is_favorite = 1
                ORDER BY is_favorite DESC, created_at DESC
                LIMIT ?
            """
            
            async with db.execute(sql, (0 if not favorites_only else 1, limit)) as cursor:
                async for row in cursor:
                    templates.append(self._row_to_template(row))
        
        return templates
    
    async def update_template(
        self,
        template_id: str,
        name: Optional[str] = None,
        content: Optional[str] = None,
        tags: Optional[List[str]] = None,
        is_favorite: Optional[bool] = None
    ) -> Optional[PromptTemplate]:
        """Update a template."""
        await self._ensure_db_initialized()
        
        # Get existing template
        existing = await self.get_template(template_id)
        if not existing:
            return None
        
        # Merge updates
        new_name = name if name is not None else existing.name
        new_content = content if content is not None else existing.content
        new_tags = tags if tags is not None else existing.tags
        new_favorite = is_favorite if is_favorite is not None else existing.is_favorite
        
        tags_json = json.dumps(new_tags)
        updated_at = datetime.now().isoformat()
        
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE prompt_templates
                SET name = ?, content = ?, tags = ?, is_favorite = ?, updated_at = ?
                WHERE template_id = ?
            """, (new_name, new_content, tags_json, 1 if new_favorite else 0, updated_at, template_id))
            
            # Update FTS index
            await db.execute("""
                UPDATE prompt_templates_fts
                SET name = ?, content = ?, tags = ?
                WHERE template_id = ?
            """, (new_name, new_content, tags_json, template_id))
            
            await db.commit()
        
        template = PromptTemplate(
            template_id=template_id,
            name=new_name,
            content=new_content,
            tags=new_tags,
            is_favorite=new_favorite,
            created_at=existing.created_at,
            updated_at=datetime.fromisoformat(updated_at)
        )
        
        self.logger.info("Template updated", template_id=template_id)
        return template
    
    async def delete_template(self, template_id: str) -> bool:
        """Delete a template."""
        await self._ensure_db_initialized()
        
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM prompt_templates WHERE template_id = ?",
                (template_id,)
            )
            await db.execute(
                "DELETE FROM prompt_templates_fts WHERE template_id = ?",
                (template_id,)
            )
            await db.commit()
            
            deleted = cursor.rowcount > 0
        
        if deleted:
            self.logger.info("Template deleted", template_id=template_id)
        
        return deleted
    
    async def toggle_favorite(self, template_id: str) -> Optional[PromptTemplate]:
        """Toggle favorite status of a template."""
        template = await self.get_template(template_id)
        if not template:
            return None
        
        return await self.update_template(template_id, is_favorite=not template.is_favorite)
    
    def _row_to_template(self, row: aiosqlite.Row) -> PromptTemplate:
        """Convert database row to PromptTemplate."""
        tags = []
        if row["tags"]:
            try:
                tags = json.loads(row["tags"])
            except Exception:
                tags = []
        
        created_at = datetime.fromisoformat(row["created_at"])
        updated_at = None
        if row["updated_at"]:
            updated_at = datetime.fromisoformat(row["updated_at"])
        
        return PromptTemplate(
            template_id=row["template_id"],
            name=row["name"],
            content=row["content"],
            tags=tags,
            is_favorite=bool(row["is_favorite"]),
            created_at=created_at,
            updated_at=updated_at
        )


# Global prompt library instance
_prompt_library = None


def get_prompt_library() -> PromptLibrary:
    """Get or create global prompt library."""
    global _prompt_library
    if _prompt_library is None:
        _prompt_library = PromptLibrary()
    return _prompt_library

