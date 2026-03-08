"""
State Manager - Tracks job progress and stores results
"""
import threading
from typing import Dict, Optional, Any
from datetime import datetime


class StateManager:
    def __init__(self):
        self._jobs: Dict[str, Dict] = {}
        self._lock = threading.Lock()

    def create_job(self, job_id: str, topic: str, max_papers: int) -> Dict:
        with self._lock:
            job = {
                "job_id": job_id,
                "topic": topic,
                "max_papers": max_papers,
                "status": "queued",
                "progress": 0,
                "current_agent": "",
                "logs": [],
                "papers_found": [],
                "result": None,
                "latex": None,
                "error": None,
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            }
            self._jobs[job_id] = job
            return job

    def get_status(self, job_id: str) -> Optional[Dict]:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **kwargs):
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].update(kwargs)
                self._jobs[job_id]["updated_at"] = datetime.utcnow().isoformat()

    def add_log(self, job_id: str, message: str, level: str = "info"):
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id]["logs"].append({
                    "timestamp": datetime.utcnow().isoformat(),
                    "level": level,
                    "message": message
                })
                self._jobs[job_id]["updated_at"] = datetime.utcnow().isoformat()

    def set_papers(self, job_id: str, papers: list):
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id]["papers_found"] = papers

    def set_result(self, job_id: str, markdown: str, latex: str):
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id]["result"] = markdown
                self._jobs[job_id]["latex"] = latex
                self._jobs[job_id]["status"] = "completed"
                self._jobs[job_id]["progress"] = 100

    def set_error(self, job_id: str, error: str):
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id]["status"] = "failed"
                self._jobs[job_id]["error"] = error


state_manager = StateManager()
