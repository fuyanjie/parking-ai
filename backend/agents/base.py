"""Base agent class with logging and lifecycle management."""
import asyncio
import time
from typing import Callable, Optional
from datetime import datetime
from models.schemas import AgentLogEntry, AgentStatus


class BaseAgent:
    """Base class for all data collection and analysis agents."""

    name: str = "BaseAgent"
    description: str = ""

    def __init__(self, log_callback: Optional[Callable] = None):
        self.status = AgentStatus.PENDING
        self.log_callback = log_callback
        self.start_time = None
        self.end_time = None
        self.results = {}

    async def log(self, action: str, message: str, data: dict = None):
        """Send a log entry to the frontend via callback."""
        entry = AgentLogEntry(
            agent=self.name,
            action=action,
            message=message,
            data=data,
            timestamp=datetime.now().strftime("%H:%M:%S"),
        )
        if self.log_callback:
            await self.log_callback(entry)

    async def run(self, **kwargs):
        """Execute the agent's task. Override in subclasses."""
        self.status = AgentStatus.RUNNING
        self.start_time = time.time()
        await self.log("START", f"{self.name} starting...")

        try:
            result = await self.execute(**kwargs)
            self.status = AgentStatus.COMPLETED
            self.end_time = time.time()
            duration = round(self.end_time - self.start_time, 2)
            await self.log("COMPLETE", f"{self.name} finished in {duration}s")
            return result
        except Exception as e:
            self.status = AgentStatus.FAILED
            self.end_time = time.time()
            await self.log("ERROR", f"{self.name} failed: {str(e)}")
            raise

    async def execute(self, **kwargs):
        """Override this method in subclasses."""
        raise NotImplementedError

    @property
    def duration(self) -> float:
        if self.start_time and self.end_time:
            return round(self.end_time - self.start_time, 2)
        return 0.0
