"""Video montage service for combining video clips with audio."""

from pathlib import Path
from typing import List, Optional, Callable
from dataclasses import dataclass
from enum import Enum
import threading

from src.services.logger import get_logger_service


def _import_moviepy():
    """Lazy import moviepy to avoid import errors at module load time."""
    try:
        from moviepy import VideoFileClip, AudioFileClip, CompositeVideoClip
        from moviepy.compositing.concatenate import concatenate_videoclips
        return VideoFileClip, AudioFileClip, CompositeVideoClip, concatenate_videoclips
    except ImportError:
        try:
            # Fallback for older moviepy versions
            from moviepy.editor import VideoFileClip, AudioFileClip, CompositeVideoClip, concatenate_videoclips
            return VideoFileClip, AudioFileClip, CompositeVideoClip, concatenate_videoclips
        except ImportError as e:
            raise ImportError("moviepy is required. Install with: pip install moviepy") from e


class AudioFitMode(Enum):
    """Audio fitting modes."""
    TRIM = "trim"  # Trim audio to match video length
    LOOP = "loop"  # Loop audio to match video length
    FIT = "fit"  # Fit video to audio length


@dataclass
class AudioSettings:
    """Audio configuration for montage."""
    audio_path: Optional[Path] = None
    volume: float = 1.0  # 0.0 to 2.0
    mute_original: bool = True
    fit_mode: AudioFitMode = AudioFitMode.TRIM
    loop_audio: bool = False


@dataclass
class MontageProgress:
    """Progress information for montage rendering."""
    current_step: str
    current_clip: int
    total_clips: int
    percentage: float


class MontageService:
    """Service for creating video montages from clips and audio."""
    
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.logger = get_logger_service().get_logger("montage")
        self._rendering = False
        self._cancel_requested = False
    
    def create_montage(
        self,
        video_paths: List[Path],
        audio_settings: AudioSettings,
        output_filename: str,
        progress_callback: Optional[Callable[[MontageProgress], None]] = None
    ) -> Optional[Path]:
        """Create a video montage from selected clips with audio overlay.
        
        Args:
            video_paths: List of video file paths in desired order
            audio_settings: Audio configuration
            output_filename: Name for output file
            progress_callback: Optional callback for progress updates
            
        Returns:
            Path to output video file, or None if failed
        """
        if not video_paths:
            self.logger.error("No video paths provided")
            return None
        
        if self._rendering:
            self.logger.warning("Montage already in progress")
            return None
        
        # Lazy import moviepy only when needed
        try:
            VideoFileClip, AudioFileClip, CompositeVideoClip, concatenate_videoclips = _import_moviepy()
        except ImportError as e:
            self.logger.error(f"Failed to import moviepy: {e}")
            return None
        
        self._rendering = True
        self._cancel_requested = False
        
        try:
            self.logger.info(f"Starting montage with {len(video_paths)} clips")
            
            # Step 1: Load video clips
            if progress_callback:
                progress_callback(MontageProgress(
                    current_step="Loading video clips",
                    current_clip=0,
                    total_clips=len(video_paths),
                    percentage=5.0
                ))
            
            clips = []
            for i, video_path in enumerate(video_paths):
                if self._cancel_requested:
                    self.logger.info("Montage cancelled")
                    return None
                
                if not video_path.exists():
                    self.logger.error(f"Video file not found: {video_path}")
                    continue
                
                try:
                    clip = VideoFileClip(str(video_path))
                    clips.append(clip)
                    self.logger.debug(f"Loaded clip {i+1}/{len(video_paths)}: {video_path.name}")
                    
                    if progress_callback:
                        progress_callback(MontageProgress(
                            current_step="Loading video clips",
                            current_clip=i + 1,
                            total_clips=len(video_paths),
                            percentage=5.0 + (i / len(video_paths)) * 15.0
                        ))
                except Exception as e:
                    self.logger.error(f"Failed to load video clip {video_path}: {e}")
                    continue
            
            if not clips:
                self.logger.error("No valid video clips loaded")
                return None
            
            # Step 2: Concatenate clips
            if progress_callback:
                progress_callback(MontageProgress(
                    current_step="Concatenating clips",
                    current_clip=0,
                    total_clips=len(clips),
                    percentage=20.0
                ))
            
            final_video = concatenate_videoclips(clips, method="compose")
            video_duration = final_video.duration
            self.logger.info(f"Concatenated video duration: {video_duration:.2f}s")
            
            if progress_callback:
                progress_callback(MontageProgress(
                    current_step="Concatenating clips",
                    current_clip=len(clips),
                    total_clips=len(clips),
                    percentage=30.0
                ))
            
            # Step 3: Process audio
            if audio_settings.audio_path and audio_settings.audio_path.exists():
                if progress_callback:
                    progress_callback(MontageProgress(
                        current_step="Processing audio",
                        current_clip=0,
                        total_clips=1,
                        percentage=35.0
                    ))
                
                try:
                    audio_clip = AudioFileClip(str(audio_settings.audio_path))
                    
                    # Apply volume (direct multiplication instead of fx)
                    if audio_settings.volume != 1.0:
                        audio_clip = audio_clip * audio_settings.volume
                    
                    # Handle audio fitting
                    if audio_settings.fit_mode == AudioFitMode.TRIM:
                        # Trim audio to video length
                        if audio_clip.duration > video_duration:
                            audio_clip = audio_clip.subclip(0, video_duration)
                    elif audio_settings.fit_mode == AudioFitMode.LOOP:
                        # Loop audio to match video length
                        if audio_clip.duration < video_duration:
                            loops_needed = int(video_duration / audio_clip.duration) + 1
                            audio_clips = [audio_clip] * loops_needed
                            audio_clip = concatenate_videoclips(audio_clips).subclip(0, video_duration)
                    elif audio_settings.fit_mode == AudioFitMode.FIT:
                        # Fit video to audio length (not implemented for now)
                        pass
                    
                    # Mute original audio if requested
                    if audio_settings.mute_original:
                        final_video = final_video.without_audio()
                    
                    # Add audio to video
                    final_video = final_video.set_audio(audio_clip)
                    
                    self.logger.info(f"Audio processed: {audio_settings.audio_path.name}")
                    
                    if progress_callback:
                        progress_callback(MontageProgress(
                            current_step="Processing audio",
                            current_clip=1,
                            total_clips=1,
                            percentage=45.0
                        ))
                except Exception as e:
                    self.logger.error(f"Failed to process audio: {e}")
                    # Continue without audio
            else:
                self.logger.info("No audio file provided, using video audio only")
            
            # Step 4: Render final video
            if progress_callback:
                progress_callback(MontageProgress(
                    current_step="Rendering final video",
                    current_clip=0,
                    total_clips=1,
                    percentage=50.0
                ))
            
            output_path = self.output_dir / output_filename
            
            # Use a separate thread for rendering to avoid blocking
            def render_with_progress():
                try:
                    final_video.write_videofile(
                        str(output_path),
                        codec='libx264',
                        audio_codec='aac',
                        preset='medium',
                        threads=4,
                        logger=None  # Disable moviepy's logger
                    )
                except Exception as e:
                    self.logger.error(f"Rendering failed: {e}")
                    raise
                finally:
                    # Cleanup
                    for clip in clips:
                        try:
                            clip.close()
                        except:
                            pass
                    try:
                        final_video.close()
                    except:
                        pass
            
            # Run rendering in thread with progress simulation
            render_thread = threading.Thread(target=render_with_progress)
            render_thread.start()
            
            # Simulate progress while rendering
            while render_thread.is_alive():
                if self._cancel_requested:
                    self.logger.info("Render cancelled")
                    return None
                
                import time
                time.sleep(0.5)
                # Simulate progress from 50% to 95%
                if progress_callback:
                    import random
                    simulated_progress = min(95.0, 50.0 + random.random() * 5.0)
                    progress_callback(MontageProgress(
                        current_step="Rendering final video",
                        current_clip=0,
                        total_clips=1,
                        percentage=simulated_progress
                    ))
            
            render_thread.join(timeout=30)
            
            if output_path.exists():
                self.logger.info(f"Montage completed successfully: {output_path}")
                if progress_callback:
                    progress_callback(MontageProgress(
                        current_step="Complete",
                        current_clip=len(video_paths),
                        total_clips=len(video_paths),
                        percentage=100.0
                    ))
                return output_path
            else:
                self.logger.error("Output file not created")
                return None
                
        except Exception as e:
            self.logger.error(f"Montage failed: {e}", exc_info=True)
            return None
        finally:
            self._rendering = False
    
    def cancel_render(self):
        """Cancel the current render operation."""
        self._cancel_requested = True
        self.logger.info("Render cancel requested")
    
    def is_rendering(self) -> bool:
        """Check if a render is currently in progress."""
        return self._rendering
    
    def get_video_info(self, video_path: Path) -> dict:
        """Get information about a video file.
        
        Args:
            video_path: Path to video file
            
        Returns:
            Dictionary with video info (duration, size, fps, resolution)
        """
        try:
            clip = VideoFileClip(str(video_path))
            info = {
                "duration": clip.duration,
                "size": clip.size,
                "fps": clip.fps,
                "width": clip.w,
                "height": clip.h,
                "has_audio": clip.audio is not None
            }
            clip.close()
            return info
        except Exception as e:
            self.logger.error(f"Failed to get video info: {e}")
            return {}
