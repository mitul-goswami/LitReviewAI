"""
Autonomous Research Paper Literature Review Generator
FastAPI Backend - Main Entry Point
"""
import os
import uuid
import asyncio
from pathlib import Path
from dotenv import load_dotenv  # new dependency for environment files
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from typing import Optional
import logging

from routers import review_router
from utils.state_manager import state_manager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Autonomous Literature Review Generator",
    description="AI-powered multi-agent system for generating academic literature reviews",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Determine project root and static/template paths
# load .env variables early so other modules can access them
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

STATIC_DIR = BASE_DIR / "frontend" / "static"
TEMPLATE_DIR = BASE_DIR / "frontend" / "templates"

# Mount static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Include routers
app.include_router(review_router.router, prefix="/api", tags=["review"])


@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    # Use absolute path based on BASE_DIR to locate the template regardless of cwd
    index_path = TEMPLATE_DIR / "index.html"
    with open(index_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get("/health")
async def health_check():
    return {"status": "healthy", "version": "1.0.0"}


@app.get("/api/status/{job_id}")
async def get_job_status(job_id: str):
    status = state_manager.get_status(job_id)
    if not status:
        raise HTTPException(status_code=404, detail="Job not found")
    return status


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
