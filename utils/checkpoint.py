"""Pipeline checkpoint management for incremental processing.

Tracks completion status of first-level folders to enable resumable pipeline execution.
Folders are marked as completed only when all documents within them are successfully processed.
"""

import json
import logging
from pathlib import Path
from typing import Set, Dict, List, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

CHECKPOINT_FILENAME = ".pipeline_checkpoint.json"


class CheckpointManager:
    """
    Manages pipeline checkpoint state for first-level folders.
    
    Checkpoint file structure:
    {
        "version": "1.0",
        "last_updated": "2025-10-13T10:30:00",
        "completed_folders": ["IPR123", "IPR456"],
        "folder_details": {
            "IPR123": {
                "completed_at": "2025-10-13T10:25:00",
                "file_count": 5,
                "success_count": 5
            }
        }
    }
    """
    
    def __init__(self, output_dir: str):
        """
        Initialize checkpoint manager.
        
        Args:
            output_dir: Output directory path where checkpoint file will be stored
        """
        self.output_dir = Path(output_dir)
        self.checkpoint_file = self.output_dir / CHECKPOINT_FILENAME
        self.completed_folders: Set[str] = set()
        self.folder_details: Dict[str, dict] = {}
        self._load_checkpoint()
    
    def _load_checkpoint(self):
        """Load checkpoint data from file if it exists."""
        if not self.checkpoint_file.exists():
            logger.info("No checkpoint file found - starting fresh")
            return
        
        try:
            with open(self.checkpoint_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self.completed_folders = set(data.get("completed_folders", []))
            self.folder_details = data.get("folder_details", {})
            
            logger.info(f"Loaded checkpoint: {len(self.completed_folders)} completed folders")
            for folder in sorted(self.completed_folders):
                details = self.folder_details.get(folder, {})
                logger.info(f"  - {folder}: {details.get('success_count', 0)} files completed")
        
        except Exception as e:
            logger.error(f"Failed to load checkpoint file: {e}")
            logger.info("Starting with empty checkpoint")
    
    def _save_checkpoint(self):
        """Save current checkpoint state to file."""
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            
            data = {
                "version": "1.0",
                "last_updated": datetime.now().isoformat(),
                "completed_folders": sorted(list(self.completed_folders)),
                "folder_details": self.folder_details
            }
            
            with open(self.checkpoint_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            logger.debug(f"Checkpoint saved: {len(self.completed_folders)} folders")
        
        except Exception as e:
            logger.error(f"Failed to save checkpoint: {e}")
    
    def is_folder_completed(self, folder_name: str) -> bool:
        """
        Check if a first-level folder has been completed.
        
        Args:
            folder_name: Name of the first-level folder
            
        Returns:
            True if folder is marked as completed
        """
        return folder_name in self.completed_folders
    
    def mark_folder_completed(self, folder_name: str, file_count: int, success_count: int):
        """
        Mark a first-level folder as completed.
        
        Args:
            folder_name: Name of the first-level folder
            file_count: Total number of files processed
            success_count: Number of successfully processed files
        """
        self.completed_folders.add(folder_name)
        self.folder_details[folder_name] = {
            "completed_at": datetime.now().isoformat(),
            "file_count": file_count,
            "success_count": success_count
        }
        self._save_checkpoint()
        logger.info(f"Marked folder '{folder_name}' as completed ({success_count}/{file_count} files)")
    
    def filter_pending_files(
        self, 
        input_file_tuples: List[Tuple[Path, Path]]
    ) -> Tuple[List[Tuple[Path, Path]], int]:
        """
        Filter out files from completed folders.
        
        Args:
            input_file_tuples: List of (file_path, relative_path) tuples
            
        Returns:
            Tuple of (filtered file list, skipped count)
        """
        pending_files = []
        skipped_count = 0
        skipped_folders = set()
        
        for file_path, relative_path in input_file_tuples:
            # Extract first-level folder name from relative path
            parts = relative_path.parts
            
            if len(parts) > 1:
                first_level_folder = parts[0]
                
                if self.is_folder_completed(first_level_folder):
                    skipped_count += 1
                    skipped_folders.add(first_level_folder)
                    continue
            
            pending_files.append((file_path, relative_path))
        
        if skipped_folders:
            logger.info(f"Skipping {skipped_count} files from {len(skipped_folders)} completed folders:")
            for folder in sorted(skipped_folders):
                details = self.folder_details.get(folder, {})
                logger.info(f"  - {folder} (completed: {details.get('completed_at', 'unknown')})")
        
        return pending_files, skipped_count
    
    def get_folder_statistics(self, input_file_tuples: List[Tuple[Path, Path]]) -> Dict[str, int]:
        """
        Get file count statistics per first-level folder.
        
        Args:
            input_file_tuples: List of (file_path, relative_path) tuples
            
        Returns:
            Dictionary mapping folder names to file counts
        """
        folder_counts: Dict[str, int] = {}
        
        for _, relative_path in input_file_tuples:
            parts = relative_path.parts
            
            if len(parts) > 1:
                first_level_folder = parts[0]
                folder_counts[first_level_folder] = folder_counts.get(first_level_folder, 0) + 1
        
        return folder_counts
    
    def clear_checkpoint(self):
        """Clear all checkpoint data (for testing or full reprocessing)."""
        self.completed_folders.clear()
        self.folder_details.clear()
        
        if self.checkpoint_file.exists():
            self.checkpoint_file.unlink()
            logger.info("Checkpoint cleared")
    
    def get_completed_folders(self) -> List[str]:
        """
        Get list of completed folder names.
        
        Returns:
            Sorted list of completed folder names
        """
        return sorted(list(self.completed_folders))
