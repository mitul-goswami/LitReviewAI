"""
Planner Agent - Orchestrates the entire pipeline
"""
import asyncio
import logging
from typing import Dict
from utils.groq_client import groq_json
from agents.search_agent import run_search_agent
from agents.pdf_agent import run_pdf_agent
from agents.summarization_agent import run_summarization_agent
from agents.comparison_agent import run_comparison_agent
from agents.writer_agent import run_writer_agent

logger = logging.getLogger(__name__)


async def run_pipeline(job_id: str, topic: str, max_papers: int, state_manager):
    """
    Master pipeline orchestrator.
    Runs all agents in sequence and stores results.
    """
    try:
        state_manager.update(job_id, status="running", current_agent="🗺️ Planner Agent", progress=2)
        state_manager.add_log(job_id, f"Starting literature review pipeline for: '{topic}'")
        state_manager.add_log(job_id, f"Target papers: {max_papers}")

        # Stage 1: Search
        papers_raw = await run_search_agent(topic, max_papers, job_id, state_manager)
        if not papers_raw:
            raise ValueError("No papers found for the given topic. Try a different or broader topic.")

        # Stage 2: PDF Extraction
        papers_extracted = await run_pdf_agent(papers_raw, job_id, state_manager)
        if not papers_extracted:
            raise ValueError("Failed to extract content from any papers.")

        # Stage 3: Summarization
        papers_summarized = await run_summarization_agent(papers_extracted, job_id, state_manager)

        # Stage 4: Comparison
        analysis = await run_comparison_agent(papers_summarized, topic, job_id, state_manager)

        # Stage 5: Write
        markdown, latex = await run_writer_agent(topic, papers_summarized, analysis, job_id, state_manager)

        # Save results
        state_manager.set_result(job_id, markdown, latex)
        state_manager.add_log(job_id, f"Pipeline complete! Generated {len(markdown)} chars of literature review.", "success")

    except Exception as e:
        logger.error(f"Pipeline failed for job {job_id}: {e}", exc_info=True)
        state_manager.set_error(job_id, str(e))
        state_manager.add_log(job_id, f"Pipeline failed: {str(e)}", "error")
