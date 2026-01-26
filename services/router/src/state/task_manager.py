"""
Task Manager - centralized state tracking for router operations (graph building).

Tracks:
- Graph builds (processing, complete)
- Real-time progress with ETA
"""

import uuid
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from enum import Enum
from loguru import logger

class TaskPhase(str, Enum):
    """Task execution phases."""
    PENDING = "pending"
    BUILDING_GRAPH = "building_graph"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class TaskState:
    """State of a single task."""
    task_id: str
    task_type: str  # "graph_build"
    phase: TaskPhase = TaskPhase.PENDING
    progress: float = 0.0  # 0-100
    message: str = ""
    
    # Timing
    started_at: datetime = None
    updated_at: datetime = None
    completed_at: Optional[datetime] = None
    eta: Optional[datetime] = None
    
    # Error tracking
    error: Optional[str] = None
    
    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        data = asdict(self)
        # Convert datetime to ISO strings
        for key in ["started_at", "updated_at", "completed_at", "eta"]:
            if data[key]:
                data[key] = data[key].isoformat()
        return data


class TaskManager:
    """Manages all active and recent tasks for Router Service."""
    
    def __init__(self):
        self.tasks: Dict[str, TaskState] = {}
        self._completed_tasks: List[TaskState] = []
        self._max_completed = 100
        self._log_intervals: Dict[str, datetime] = {} # task_id -> last_log_time
        self.default_log_interval_seconds = 5.0
    
    def create_task(self, task_type: str = "graph_build") -> str:
        """Create new task and return task_id."""
        task_id = str(uuid.uuid4())
        now = datetime.now()
        
        task = TaskState(
            task_id=task_id,
            task_type=task_type,
            phase=TaskPhase.PENDING,
            started_at=now,
            updated_at=now
        )
        
        self.tasks[task_id] = task
        self._log_intervals[task_id] = now
        logger.info(f"Created task {task_id} type={task_type}")
        return task_id
    
    def update_progress(
        self,
        task_id: str,
        progress: float,
        phase: Optional[TaskPhase] = None,
        message: str = "",
        log_interval_seconds: Optional[float] = None
    ) -> None:
        """
        Update task progress and log periodically.
        """
        if task_id not in self.tasks:
            return
        
        task = self.tasks[task_id]
        task.progress = progress
        task.message = message
        task.updated_at = datetime.now()
        
        if phase:
            task.phase = phase
            
        # Periodic logging check
        interval = log_interval_seconds or self.default_log_interval_seconds
        last_log = self._log_intervals.get(task_id)
        if last_log and (datetime.now() - last_log).total_seconds() >= interval:
            logger.debug(f"Task {task_id}: {progress:.1f}% - {message}")
            self._log_intervals[task_id] = datetime.now()

    def mark_complete(self, task_id: str, message: str = "Completed successfully") -> None:
        """Mark task as completed."""
        if task_id not in self.tasks:
            return
        
        task = self.tasks[task_id]
        task.phase = TaskPhase.COMPLETE
        task.progress = 100.0
        task.message = message
        task.completed_at = datetime.now()
        task.updated_at = datetime.now()
        
        logger.info(f"Task {task_id} completed: {message}")
        
        # Cleanup log tracker
        if task_id in self._log_intervals:
            del self._log_intervals[task_id]
        
        # Move to completed list
        self._completed_tasks.append(task)
        if len(self._completed_tasks) > self._max_completed:
            self._completed_tasks.pop(0)
        
        del self.tasks[task_id]
    
    def mark_failed(self, task_id: str, error: str) -> None:
        """Mark task as failed."""
        if task_id not in self.tasks:
            return
        
        task = self.tasks[task_id]
        task.phase = TaskPhase.FAILED
        task.error = error
        task.updated_at = datetime.now()
        task.completed_at = datetime.now()
        
        logger.error(f"Task {task_id} failed: {error}")

        if task_id in self._log_intervals:
            del self._log_intervals[task_id]
            
        self._completed_tasks.append(task)
        if len(self._completed_tasks) > self._max_completed:
            self._completed_tasks.pop(0)
            
        del self.tasks[task_id]

    def get_task(self, task_id: str) -> Optional[dict]:
        """Get task state by ID."""
        if task_id in self.tasks:
            return self.tasks[task_id].to_dict()
        
        for task in self._completed_tasks:
            if task.task_id == task_id:
                return task.to_dict()
        
        return None

# Global instance
task_manager = TaskManager()
