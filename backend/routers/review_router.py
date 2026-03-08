"""
Review Router - FastAPI routes for the literature review API
"""
import uuid
import asyncio
import logging
from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from typing import Optional

from utils.state_manager import state_manager
from agents.planner_agent import run_pipeline

logger = logging.getLogger(__name__)
router = APIRouter()


class ReviewRequest(BaseModel):
    topic: str = Field(..., min_length=3, max_length=200, description="Research topic for literature review")
    max_papers: int = Field(default=10, ge=3, le=20, description="Maximum papers to include")


class ReviewResponse(BaseModel):
    job_id: str
    status: str
    message: str


@router.post("/review", response_model=ReviewResponse)
async def create_review(request: ReviewRequest, background_tasks: BackgroundTasks):
    """Start an autonomous literature review generation job."""
    job_id = str(uuid.uuid4())
    
    # Create job
    state_manager.create_job(job_id, request.topic, request.max_papers)
    
    # Run pipeline in background
    background_tasks.add_task(
        run_pipeline,
        job_id=job_id,
        topic=request.topic,
        max_papers=request.max_papers,
        state_manager=state_manager,
    )
    
    logger.info(f"Created job {job_id} for topic: {request.topic}")
    
    return ReviewResponse(
        job_id=job_id,
        status="queued",
        message=f"Literature review generation started for: {request.topic}"
    )


@router.get("/review/{job_id}/status")
async def get_review_status(job_id: str):
    """Get the current status and logs of a review job."""
    status = state_manager.get_status(job_id)
    if not status:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Return status without full result (for polling)
    return {
        "job_id": job_id,
        "status": status["status"],
        "progress": status["progress"],
        "current_agent": status["current_agent"],
        "papers_found": status["papers_found"],
        "logs": status["logs"][-20:],  # Last 20 logs
        "error": status.get("error"),
    }


@router.get("/review/{job_id}/result")
async def get_review_result(job_id: str):
    """Get the completed literature review."""
    status = state_manager.get_status(job_id)
    if not status:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if status["status"] != "completed":
        raise HTTPException(
            status_code=202,
            detail=f"Job not complete. Current status: {status['status']}, progress: {status['progress']}%"
        )
    
    return {
        "job_id": job_id,
        "topic": status["topic"],
        "markdown": status["result"],
        "latex": status["latex"],
        "papers_count": len(status["papers_found"]),
        "papers": status["papers_found"],
    }


@router.get("/review/{job_id}/markdown", response_class=PlainTextResponse)
async def download_markdown(job_id: str):
    """Download the literature review as raw Markdown."""
    status = state_manager.get_status(job_id)
    if not status or status["status"] != "completed":
        raise HTTPException(status_code=404, detail="Result not ready")
    return PlainTextResponse(
        content=status["result"],
        headers={"Content-Disposition": f"attachment; filename=literature_review_{job_id[:8]}.md"}
    )


@router.get("/review/{job_id}/latex", response_class=PlainTextResponse)
async def download_latex(job_id: str):
    """Download the literature review as LaTeX."""
    status = state_manager.get_status(job_id)
    if not status or status["status"] != "completed":
        raise HTTPException(status_code=404, detail="Result not ready")
    return PlainTextResponse(
        content=status["latex"],
        headers={"Content-Disposition": f"attachment; filename=literature_review_{job_id[:8]}.tex"}
    )
