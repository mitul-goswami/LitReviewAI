"""
Planner Agent — orchestrates the pipeline with stage checkpoints for recovery.

Checkpoints
───────────
  0 → nothing done yet
  1 → search complete   (_papers_raw saved)
  2 → pdf complete      (_papers_extracted saved)
  3 → summarize done    (_papers_summarized saved)
  4 → analysis done     (_analysis saved)
  5 → writing done      (completed)

run_pipeline()  — called on new job (always starts from checkpoint 0)
resume_pipeline() — called on retry, reads checkpoint and jumps to correct stage
Both call _execute_from_stage() internally.
"""
from __future__ import annotations

import logging
from agents.search_agent      import run_search_agent
from agents.pdf_agent         import run_pdf_agent
from agents.summarization_agent import run_summarization_agent
from agents.comparison_agent  import run_comparison_agent
from agents.writer_agent      import run_writer_agent

logger = logging.getLogger(__name__)


async def _execute_from_stage(
    job_id:        str,
    topic:         str,
    max_papers:    int,
    state_manager,
    start_stage:   int,
) -> None:
    """
    Core pipeline execution. start_stage controls which stage to begin from.
    Loads checkpoint data for any stage already completed.
    """
    sm = state_manager
    sm.update(job_id, status="running", current_agent="🗺️ Planner Agent")

    try:
        # ── Resolve already-completed stages ──────────────────────────────────
        papers_raw        = sm.get_checkpoint_data(job_id, "_papers_raw")
        papers_extracted  = sm.get_checkpoint_data(job_id, "_papers_extracted")
        papers_summarized = sm.get_checkpoint_data(job_id, "_papers_summarized")
        analysis          = sm.get_checkpoint_data(job_id, "_analysis")

        # ── Stage 1: Search ────────────────────────────────────────────────────
        if start_stage <= 1:
            sm.add_log(job_id, f"▶ Stage 1/5: Paper Search  (topic: '{topic}')")
            sm.update(job_id, progress=2)
            papers_raw = await run_search_agent(topic, max_papers, job_id, sm)
            if not papers_raw:
                raise ValueError(
                    "No papers found for this topic. "
                    "Try a broader or different topic."
                )
            sm.save_checkpoint(job_id, 1, "_papers_raw", papers_raw)
            sm.add_log(job_id, f"✅ Stage 1 complete: {len(papers_raw)} papers found", "success")
        else:
            sm.add_log(job_id, f"⏭ Stage 1 skipped (checkpoint {sm.get_checkpoint(job_id)})")

        # ── Stage 2: PDF Extraction ────────────────────────────────────────────
        if start_stage <= 2:
            sm.add_log(job_id, "▶ Stage 2/5: PDF Extraction")
            papers_extracted = await run_pdf_agent(papers_raw, job_id, sm)
            if not papers_extracted:
                raise ValueError("Failed to extract usable content from any papers.")
            sm.save_checkpoint(job_id, 2, "_papers_extracted", papers_extracted)
            sm.add_log(job_id, f"✅ Stage 2 complete: {len(papers_extracted)} papers extracted", "success")
        else:
            sm.add_log(job_id, "⏭ Stage 2 skipped")

        # ── Stage 3: Summarization ─────────────────────────────────────────────
        if start_stage <= 3:
            sm.add_log(job_id, "▶ Stage 3/5: Summarization")
            papers_summarized = await run_summarization_agent(papers_extracted, job_id, sm)
            sm.save_checkpoint(job_id, 3, "_papers_summarized", papers_summarized)
            sm.add_log(job_id, f"✅ Stage 3 complete: {len(papers_summarized)} papers summarized", "success")
        else:
            sm.add_log(job_id, "⏭ Stage 3 skipped")

        # ── Stage 4: Comparison / Analysis ────────────────────────────────────
        if start_stage <= 4:
            sm.add_log(job_id, "▶ Stage 4/5: Comparative Analysis")
            analysis = await run_comparison_agent(papers_summarized, topic, job_id, sm)
            sm.save_checkpoint(job_id, 4, "_analysis", analysis)
            sm.add_log(job_id, "✅ Stage 4 complete: Analysis done", "success")
        else:
            sm.add_log(job_id, "⏭ Stage 4 skipped")

        # ── Stage 5: Write ─────────────────────────────────────────────────────
        sm.add_log(job_id, "▶ Stage 5/5: Writing literature review")
        markdown, latex, apa = await run_writer_agent(
            topic, papers_summarized, analysis, job_id, sm
        )

        sm.set_result(job_id, markdown, latex, apa)
        sm.add_log(
            job_id,
            f"🎉 Pipeline complete! "
            f"{len(papers_summarized)} papers · {len(markdown):,} chars",
            "success",
        )

    except Exception as exc:
        logger.error(f"Pipeline failed for job {job_id}: {exc}", exc_info=True)
        sm.set_error(job_id, str(exc))
        sm.add_log(job_id, f"❌ Pipeline failed: {exc}", "error")

        # Log which stage can be retried from
        cp = sm.get_checkpoint(job_id)
        if cp > 0:
            stage_names = {
                0: "beginning",
                1: "PDF extraction (stage 2)",
                2: "Summarization (stage 3)",
                3: "Comparative analysis (stage 4)",
                4: "Writing (stage 5)",
            }
            resume_from = stage_names.get(cp, "beginning")
            sm.add_log(
                job_id,
                f"💡 You can retry — pipeline will resume from {resume_from}",
                "info",
            )


async def run_pipeline(job_id: str, topic: str, max_papers: int, state_manager) -> None:
    """Entry point for a brand-new job. Always starts from stage 1."""
    await _execute_from_stage(
        job_id, topic, max_papers, state_manager, start_stage=1
    )


async def resume_pipeline(job_id: str, state_manager) -> None:
    """
    Entry point for retrying a failed job.
    Reads the saved checkpoint and resumes from the next stage.
    """
    job = state_manager.get_status(job_id)
    if not job:
        return

    topic      = job["topic"]
    max_papers = job["max_papers"]
    checkpoint = job.get("checkpoint", 0)

    # Resume from the stage AFTER the last successful one
    resume_stage = checkpoint + 1

    state_manager.add_log(
        job_id,
        f"🔄 Resuming pipeline from stage {resume_stage} "
        f"(last checkpoint: stage {checkpoint})",
    )

    await _execute_from_stage(
        job_id, topic, max_papers, state_manager, start_stage=resume_stage
    )
