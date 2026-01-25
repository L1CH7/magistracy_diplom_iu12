"""
Task Manager - centralized state tracking for all operations.

Tracks:
- Tile downloads (downloading, saving, complete, failed)
- Graph builds (processing, complete)
- Real-time progress with ETA
"""

import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from enum import Enum


class TaskPhase(str, Enum):
    """Task execution phases."""
    PENDING = "pending"
    DOWNLOADING = "downloading"
    SAVING = "saving"
    BUILDING_GRAPH = "building_graph"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class TaskState:
    """State of a single task."""
    task_id: str
    task_type: str  # "tile_download" | "graph_build"
    tile_key: Optional[str] = None
    phase: TaskPhase = TaskPhase.PENDING
    progress: float = 0.0  # 0-100
    message: str = ""
    
    # Metrics
    items_total: int = 0
    items_processed: int = 0
    
    # Timing
    started_at: datetime = None
    updated_at: datetime = None
    completed_at: Optional[datetime] = None
    eta: Optional[datetime] = None
    
    # Error tracking
    error: Optional[str] = None
    retry_count: int = 0
    
    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        data = asdict(self)
        # Convert datetime to ISO strings
        for key in ["started_at", "updated_at", "completed_at", "eta"]:
            if data[key]:
                data[key] = data[key].isoformat()
        return data


class TaskManager:
    """Manages all active and recent tasks."""
    
    def __init__(self):
        self.tasks: Dict[str, TaskState] = {}
        self._completed_tasks: List[TaskState] = []
        self._max_completed = 100  # Keep last 100 completed tasks
    
    def create_task(
        self,
        task_type: str,
        tile_key: Optional[str] = None,
        items_total: int = 0
    ) -> str:
        """
        Create new task and return task_id.
        
        Args:
            task_type: "tile_download" | "graph_build"
            tile_key: Optional tile identifier
            items_total: Total items to process
        
        Returns:
            task_id: Unique task identifier
        """
        task_id = str(uuid.uuid4())
        now = datetime.now()
        
        task = TaskState(
            task_id=task_id,
            task_type=task_type,
            tile_key=tile_key,
            phase=TaskPhase.PENDING,
            items_total=items_total,
            started_at=now,
            updated_at=now
        )
        
        self.tasks[task_id] = task
        return task_id
    
    def update_progress(
        self,
        task_id: str,
        progress: float,
        phase: Optional[TaskPhase] = None,
        message: str = "",
        items_processed: Optional[int] = None,
        items_total: Optional[int] = None
    ) -> None:
        """
        Update task progress.
        
        Args:
            task_id: Task identifier
            progress: Progress percentage (0-100)
            phase: Optional phase update
            message: Status message
            items_processed: Items completed so far
            items_total: Total items to process
        """
        if task_id not in self.tasks:
            return
        
        task = self.tasks[task_id]
        task.progress = progress
        task.message = message
        task.updated_at = datetime.now()
        
        if phase:
            task.phase = phase
        
        if items_processed is not None:
            task.items_processed = items_processed
        
        if items_total is not None:
            task.items_total = items_total
        
        # Calculate ETA
        if task.items_total > 0 and task.items_processed > 0:
            elapsed = (datetime.now() - task.started_at).total_seconds()
            rate = task.items_processed / elapsed  # items/sec
            remaining = task.items_total - task.items_processed
            eta_seconds = remaining / rate if rate > 0 else 0
            task.eta = datetime.now() + timedelta(seconds=eta_seconds)
    
    def mark_complete(
        self,
        task_id: str,
        message: str = "Completed successfully"
    ) -> None:
        """Mark task as completed."""
        if task_id not in self.tasks:
            return
        
        task = self.tasks[task_id]
        task.phase = TaskPhase.COMPLETE
        task.progress = 100.0
        task.message = message
        task.completed_at = datetime.now()
        task.updated_at = datetime.now()
        
        # Move to completed list
        self._completed_tasks.append(task)
        if len(self._completed_tasks) > self._max_completed:
            self._completed_tasks.pop(0)
        
        # Remove from active tasks
        del self.tasks[task_id]
    
    def mark_failed(
        self,
        task_id: str,
        error: str,
        retry: bool = False
    ) -> None:
        """Mark task as failed."""
        if task_id not in self.tasks:
            return
        
        task = self.tasks[task_id]
        task.phase = TaskPhase.FAILED
        task.error = error
        task.updated_at = datetime.now()
        
        if retry:
            task.retry_count += 1
        else:
            task.completed_at = datetime.now()
            
            # Move to completed list
            self._completed_tasks.append(task)
            if len(self._completed_tasks) > self._max_completed:
                self._completed_tasks.pop(0)
            
            # Remove from active tasks
            del self.tasks[task_id]
    
    def get_task(self, task_id: str) -> Optional[dict]:
        """Get task state by ID."""
        if task_id in self.tasks:
            return self.tasks[task_id].to_dict()
        
        # Check completed tasks
        for task in self._completed_tasks:
            if task.task_id == task_id:
                return task.to_dict()
        
        return None
    
    def get_all_tasks(self) -> dict:
        """
        Get all tasks grouped by phase.
        
        Returns:
            {
                "downloading": [...],
                "saving": [...],
                "building_graph": [...],
                "complete": [...],
                "failed": [...]
            }
        """
        result = {
            "pending": [],
            "downloading": [],
            "saving": [],
            "building_graph": [],
            "complete": [],
            "failed": []
        }
        
        # Active tasks
        for task in self.tasks.values():
            phase_key = task.phase.value
            if phase_key in result:
                result[phase_key].append(task.to_dict())
        
        # Recent completed/failed
        for task in self._completed_tasks[-20:]:  # Last 20
            phase_key = task.phase.value
            if phase_key in result:
                result[phase_key].append(task.to_dict())
        
        return result
    
    def get_stats(self) -> dict:
        """Get task statistics."""
        active_count = len(self.tasks)
        complete_count = sum(
            1 for t in self._completed_tasks
            if t.phase == TaskPhase.COMPLETE
        )
        failed_count = sum(
            1 for t in self._completed_tasks
            if t.phase == TaskPhase.FAILED
        )
        
        return {
            "active": active_count,
            "completed": complete_count,
            "failed": failed_count,
            "total": active_count + len(self._completed_tasks)
        }
    
    def cleanup_old_tasks(self, hours: int = 24) -> int:
        """
        Remove old completed tasks.
        
        Args:
            hours: Remove tasks older than N hours
        
        Returns:
            Number of tasks removed
        """
        cutoff = datetime.now() - timedelta(hours=hours)
        before = len(self._completed_tasks)
        
        self._completed_tasks = [
            t for t in self._completed_tasks
            if t.completed_at and t.completed_at > cutoff
        ]
        
        removed = before - len(self._completed_tasks)
        return removed
