"""
Review Router — HTTP + WebSocket endpoints.

WebSocket endpoint
──────────────────
  GET /api/ws/{job_id}

  The client connects immediately after starting a job. The server:
    1. Sends a full "snapshot" of current job state on connect
       (catches any events that fired before the WS was open)
    2. Pushes every subsequent update as it happens (via state_manager broadcasts)
    3. On job completion or failure, sends the terminal event and the
       client can close the connection

  Message types sent by server → client:
    snapshot  — full current state on connect
    progress  — {progress, current_agent, status}
    log       — {timestamp, level, message}
    papers    — {papers: [...]}
    completed — triggers frontend to fetch /result
    failed    — {error: "..."}

HTTP endpoints (unchanged + new /retry)
────────────────────────────────────────
  POST   /api/review               — start new job
  GET    /api/review/{id}/status   — polling fallback
  GET    /api/review/{id}/result   — fetch completed review
  POST   /api/review/{id}/retry    — resume failed job from checkpoint
  GET    /api/review/{id}/markdown — download
  GET    /api/review/{id}/latex    — download
  GET    /api/review/{id}/apa      — download APA references
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from agents.planner_agent import run_pipeline, resume_pipeline
from utils.state_manager import state_manager, ws_subscribe, ws_unsubscribe

logger = logging.getLogger(__name__)
router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────────────────

class ReviewRequest(BaseModel):
    topic:      str = Field(..., min_length=3, max_length=200)
    max_papers: int = Field(default=10, ge=3, le=20)

class ReviewResponse(BaseModel):
    job_id:  str
    status:  str
    message: str


# ─────────────────────────────────────────────────────────────────────────────
# HTTP: start / status / result / retry / downloads
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/review", response_model=ReviewResponse)
async def create_review(request: ReviewRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    state_manager.create_job(job_id, request.topic, request.max_papers)
    background_tasks.add_task(
        run_pipeline,
        job_id=job_id,
        topic=request.topic,
        max_papers=request.max_papers,
        state_manager=state_manager,
    )
    logger.info(f"Job {job_id} started: {request.topic}")
    return ReviewResponse(
        job_id=job_id,
        status="queued",
        message=f"Literature review started for: {request.topic}",
    )


@router.post("/review/{job_id}/retry", response_model=ReviewResponse)
async def retry_review(job_id: str, background_tasks: BackgroundTasks):
    """
    Resume a failed job from its last successful checkpoint.
    Returns 409 if the job is not in a failed state.
    """
    job = state_manager.get_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] not in ("failed",):
        raise HTTPException(
            status_code=409,
            detail=f"Job is in '{job['status']}' state — only failed jobs can be retried.",
        )

    ok = state_manager.reset_for_retry(job_id)
    if not ok:
        raise HTTPException(status_code=409, detail="Could not reset job for retry")

    background_tasks.add_task(
        resume_pipeline,
        job_id=job_id,
        state_manager=state_manager,
    )
    cp = job.get("checkpoint", 0)
    stage_names = {0: "start", 1: "PDF extraction", 2: "summarization",
                   3: "analysis", 4: "writing"}
    resume_from = stage_names.get(cp, "beginning")
    logger.info(f"Job {job_id} retrying from checkpoint {cp} ({resume_from})")
    return ReviewResponse(
        job_id=job_id,
        status="queued",
        message=f"Retrying from {resume_from} (stage {cp + 1})",
    )


@router.get("/review/{job_id}/status")
async def get_review_status(job_id: str):
    """Polling fallback — still works for clients that can't use WebSockets."""
    status = state_manager.get_status(job_id)
    if not status:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id":        job_id,
        "status":        status["status"],
        "progress":      status["progress"],
        "current_agent": status["current_agent"],
        "papers_found":  status["papers_found"],
        "logs":          status["logs"][-20:],
        "error":         status.get("error"),
        "checkpoint":    status.get("checkpoint", 0),
    }


@router.get("/review/{job_id}/result")
async def get_review_result(job_id: str):
    status = state_manager.get_status(job_id)
    if not status:
        raise HTTPException(status_code=404, detail="Job not found")
    if status["status"] != "completed":
        raise HTTPException(
            status_code=202,
            detail=f"Not complete. Status: {status['status']}, progress: {status['progress']}%",
        )
    return {
        "job_id":       job_id,
        "topic":        status["topic"],
        "markdown":     status["result"],
        "latex":        status["latex"],
        "apa":          status.get("apa", ""),
        "papers_count": len(status["papers_found"]),
        "papers":       status["papers_found"],
    }


@router.get("/review/{job_id}/markdown", response_class=PlainTextResponse)
async def download_markdown(job_id: str):
    status = state_manager.get_status(job_id)
    if not status or status["status"] != "completed":
        raise HTTPException(status_code=404, detail="Result not ready")
    return PlainTextResponse(
        content=status["result"],
        headers={"Content-Disposition": f"attachment; filename=literature_review_{job_id[:8]}.md"},
    )


@router.get("/review/{job_id}/latex", response_class=PlainTextResponse)
async def download_latex(job_id: str):
    status = state_manager.get_status(job_id)
    if not status or status["status"] != "completed":
        raise HTTPException(status_code=404, detail="Result not ready")
    return PlainTextResponse(
        content=status["latex"],
        headers={"Content-Disposition": f"attachment; filename=literature_review_{job_id[:8]}.tex"},
    )


@router.get("/review/{job_id}/apa", response_class=PlainTextResponse)
async def download_apa(job_id: str):
    status = state_manager.get_status(job_id)
    if not status or status["status"] != "completed":
        raise HTTPException(status_code=404, detail="Result not ready")
    apa = status.get("apa", "")
    if not apa:
        raise HTTPException(status_code=404, detail="APA references not available")
    return PlainTextResponse(
        content=apa,
        headers={"Content-Disposition": f"attachment; filename=references_apa_{job_id[:8]}.md"},
    )


# ─────────────────────────────────────────────────────────────────────────────
# WebSocket: real-time progress stream
# ─────────────────────────────────────────────────────────────────────────────

@router.websocket("/ws/{job_id}")
async def websocket_progress(websocket: WebSocket, job_id: str):
    """
    Push-based progress stream for a single job.

    Protocol:
    1. Server accepts the connection
    2. Server immediately sends a "snapshot" message with the full current state
       (so clients that connect late get caught up instantly)
    3. Server registers the WS in the registry so state_manager broadcasts land here
    4. Server sends heartbeat pings every 20 s to keep proxies/load-balancers alive
    5. Server closes cleanly on job completion/failure or client disconnect
    """
    await websocket.accept()
    logger.info(f"WS connected: job {job_id}")

    # ── 1. Send snapshot of current state ────────────────────────────────────
    job = state_manager.get_status(job_id)
    if not job:
        await websocket.send_text(json.dumps({
            "type":  "error",
            "error": f"Job {job_id} not found",
        }))
        await websocket.close()
        return

    await websocket.send_text(json.dumps({
        "type":          "snapshot",
        "status":        job["status"],
        "progress":      job["progress"],
        "current_agent": job["current_agent"],
        "papers_found":  job["papers_found"],
        "logs":          job["logs"],
        "error":         job.get("error"),
        "checkpoint":    job.get("checkpoint", 0),
    }))

    # If job already finished, send terminal event and close
    if job["status"] == "completed":
        await websocket.send_text(json.dumps({"type": "completed"}))
        await websocket.close()
        return
    if job["status"] == "failed":
        await websocket.send_text(json.dumps({
            "type":  "failed",
            "error": job.get("error", "Unknown error"),
            "checkpoint": job.get("checkpoint", 0),
        }))
        await websocket.close()
        return

    # ── 2. Register for live broadcasts ──────────────────────────────────────
    ws_subscribe(job_id, websocket)

    # ── 3. Keep connection alive; close when job finishes ────────────────────
    try:
        while True:
            # Re-check job status every 20 s (heartbeat interval)
            await asyncio.sleep(20)

            # Send a heartbeat ping so the connection doesn't timeout
            try:
                await websocket.send_text(json.dumps({"type": "ping"}))
            except Exception:
                break   # client disconnected

            # Check if the job has finished
            current = state_manager.get_status(job_id)
            if not current:
                break
            if current["status"] in ("completed", "failed"):
                break   # terminal event was already broadcast by state_manager

    except WebSocketDisconnect:
        logger.info(f"WS disconnected: job {job_id}")
    except Exception as exc:
        logger.warning(f"WS error for job {job_id}: {exc}")
    finally:
        ws_unsubscribe(job_id, websocket)
        logger.info(f"WS unregistered: job {job_id}")
