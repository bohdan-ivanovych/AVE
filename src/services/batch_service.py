"""Async batch processing service with concurrency control."""

import asyncio
import uuid
from pathlib import Path
from typing import List, Optional
from datetime import datetime

from src.config import get_config
from src.services.logger import get_logger_service
from src.services.browser_service import BrowserService
from src.services.browser_pool import get_browser_pool
from src.services.notification_service import get_notification_service
from src.dto import GenerationTask, BatchJob, TaskStatus, ImagePair


class BatchService:
    """Service for processing batches of generation tasks asynchronously."""
    
    def __init__(self, config=None):
        self.config = config or get_config()
        self.logger = get_logger_service().get_logger("batch")
        self.notification_service = get_notification_service()
        slot_limit = max(
            1,
            min(
                self.config.semaphore_limit,
                getattr(self.config, "max_parallel_browsers", self.config.semaphore_limit),
            ),
        )
        self._semaphore = asyncio.Semaphore(slot_limit)
        self._active_tasks: dict[str, GenerationTask] = {}
    
    async def process_batch(
        self,
        image_pairs: List[ImagePair],
        profile_names: List[str],
        output_dir: Optional[Path] = None
    ) -> BatchJob:
        """
        Process a batch of image pairs asynchronously.
        
        Args:
            image_pairs: List of image pairs to process
            profile_names: List of Chrome profile names to use
            output_dir: Output directory (defaults to config)
            
        Returns:
            BatchJob instance with all tasks
        """
        output_dir = output_dir or self.config.outputs_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        # Clamp concurrency to available profiles for this batch to avoid profile lockups
        profile_limit = max(1, len(profile_names))
        slot_limit = max(
            1,
            min(
                self.config.semaphore_limit,
                getattr(self.config, "max_parallel_browsers", self.config.semaphore_limit),
                profile_limit,
            ),
        )
        self._semaphore = asyncio.Semaphore(slot_limit)
        
        job_id = str(uuid.uuid4())
        tasks = []
        
        # Create tasks for each enabled pair
        worker_id = 1
        for pair in image_pairs:
            if not pair.enabled:
                continue
            
            # Cycle through profiles
            profile_index = (worker_id - 1) % len(profile_names)
            profile_name = profile_names[profile_index]
            
            task = GenerationTask(
                task_id=str(uuid.uuid4()),
                worker_id=worker_id,
                profile_name=profile_name,
                images=pair.images,
                prompt=pair.prompt,
                status=TaskStatus.PENDING
            )
            tasks.append(task)
            worker_id += 1
        
        batch_job = BatchJob(
            job_id=job_id,
            tasks=tasks,
            pairing_mode=None,  # Will be set by caller
            status=TaskStatus.PENDING
        )
        
        self.logger.info("Batch job created", job_id=job_id, task_count=len(tasks))
        
        # Process tasks asynchronously
        asyncio.create_task(self._process_batch_tasks(batch_job, output_dir))
        
        return batch_job
    
    async def _process_batch_tasks(
        self,
        batch_job: BatchJob,
        output_dir: Path
    ):
        """Process all tasks in a batch job."""
        batch_job.status = TaskStatus.RUNNING
        
        # Create tasks with semaphore for concurrency control
        task_coroutines = [
            self._process_task_with_semaphore(task, output_dir, batch_job)
            for task in batch_job.tasks
        ]
        
        # Wait for all tasks to complete
        results = await asyncio.gather(*task_coroutines, return_exceptions=True)
        
        # Update batch status
        completed = sum(1 for r in results if not isinstance(r, Exception) and r.status == TaskStatus.COMPLETED)
        failed = sum(1 for r in results if isinstance(r, Exception) or (not isinstance(r, Exception) and r.status == TaskStatus.FAILED))
        
        if failed == 0:
            batch_job.status = TaskStatus.COMPLETED
        elif completed > 0:
            batch_job.status = TaskStatus.COMPLETED  # Partial success
        else:
            batch_job.status = TaskStatus.FAILED
        
        self.logger.info(
            "Batch job completed",
            job_id=batch_job.job_id,
            completed=completed,
            failed=failed,
            total=len(batch_job.tasks)
        )
        
        # Send notification
        self.notification_service.notify_batch_complete(
            total_tasks=len(batch_job.tasks),
            successful=completed,
            failed=failed
        )
    
    async def _process_task_with_semaphore(
        self,
        task: GenerationTask,
        output_dir: Path,
        batch_job: BatchJob
    ) -> GenerationTask:
        """Process a single task with semaphore-based concurrency control."""
        async with self._semaphore:
            return await self._process_single_task(task, output_dir)
    
    async def _process_single_task(
        self,
        task: GenerationTask,
        output_dir: Path
    ) -> GenerationTask:
        """Process a single generation task."""
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now()
        self._active_tasks[task.task_id] = task
        
        self.logger.info(
            "Task started",
            task_id=task.task_id,
            worker_id=task.worker_id,
            profile=task.profile_name,
            image_count=len(task.images)
        )
        
        browser_pool = None
        ctx = None
        page = None
        browser: Optional[BrowserService] = None
        try:
            # Use browser service for sequential launches
            # This ensures each browser loads before the next one starts
            browser = BrowserService(self.config)
            await browser.start()
            
            # Create context, page, and navigate in one go
            # This ensures the page is loaded before semaphore is released
            # (allowing next browser to start)
            ctx, page = await browser.create_context_and_navigate(
                task.profile_name,
                headless=False
            )
            
            # Check login
            if not await browser.check_login_status(page):
                raise Exception("Not logged in - please run login mode first")
            
            # Upload images
            if not await browser.upload_images(page, task.images):
                raise Exception("Failed to upload images")
            
            # Wait for Create button
            if not await browser.wait_for_create_button(page):
                raise Exception("Create button never became ready")
            
            # Set prompt and click
            if not await browser.set_prompt_and_click(page, task.prompt):
                raise Exception("Failed to set prompt and click Create")
            
            # Wait for notification
            await browser.wait_for_sora_notification(page)
            
            # Download variants
            task_name = f"{task.images[0].stem}_{task.images[1].stem if len(task.images) > 1 else ''}"
            output_files = await browser.download_generated_variants(
                page,
                output_dir,
                task.worker_id,
                task_name,
                max_variants=self.config.max_variants_per_task
            )
            
            if not output_files:
                raise Exception("No variants were downloaded")
            
            task.output_files = output_files
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now()
            
            self.logger.info(
                "Task completed",
                task_id=task.task_id,
                output_count=len(output_files)
            )
            
            # Send notification
            self.notification_service.notify_task_complete(
                task_name=task_name,
                output_count=len(output_files)
            )
            
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error_message = str(e)
            task.completed_at = datetime.now()
            
            self.logger.error(
                "Task failed",
                task_id=task.task_id,
                error=str(e),
                exc_info=True
            )
            
            # Send error notification
            self.notification_service.notify_error(
                error_message=str(e),
                context=f"Task {task.task_id}"
            )
            
        finally:
            if page and not page.is_closed():
                try:
                    await page.close()
                    self.logger.debug("Closed Sora page", task_id=task.task_id)
                except Exception as close_err:
                    self.logger.warning(
                        "Failed to close Sora page",
                        task_id=task.task_id,
                        error=str(close_err)
                    )
            if ctx:
                try:
                    for ctx_page in ctx.pages:
                        if ctx_page is not page and not ctx_page.is_closed():
                            await ctx_page.close()
                except Exception as extra_close_err:
                    self.logger.debug(
                        "Failed to close auxiliary Sora page",
                        task_id=task.task_id,
                        error=str(extra_close_err)
                    )
                try:
                    await ctx.close()
                    self.logger.debug("Closed Sora context", task_id=task.task_id)
                except Exception as context_err:
                    self.logger.warning(
                        "Failed to close Sora context",
                        task_id=task.task_id,
                        error=str(context_err)
                    )
            if browser:
                try:
                    await browser.cleanup()
                except Exception as browser_err:
                    self.logger.debug("Browser cleanup failed", task_id=task.task_id, error=str(browser_err))
            if task.task_id in self._active_tasks:
                del self._active_tasks[task.task_id]
        
        return task
    
    def get_active_tasks(self) -> List[GenerationTask]:
        """Get list of currently active tasks."""
        return list(self._active_tasks.values())
    
    def get_task(self, task_id: str) -> Optional[GenerationTask]:
        """Get a task by ID."""
        return self._active_tasks.get(task_id)

