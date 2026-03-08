"""
Summarization Agent - Summarizes each paper using Groq LLM
"""
import asyncio
import logging
from typing import Dict, List
from utils.groq_client import groq_json

logger = logging.getLogger(__name__)


async def summarize_paper(paper: Dict) -> Dict:
    """Use Groq to extract structured information from a paper."""
    title = paper.get("title", "Unknown")
    abstract = paper.get("abstract", "")
    full_text = paper.get("full_text", "")
    
    # Combine abstract + beginning of full text for context
    content = f"Title: {title}\n\nAbstract: {abstract}"
    if full_text and full_text != abstract:
        # Add intro/methods section if available
        content += f"\n\nExtracted Content:\n{full_text[:3000]}"

    try:
        summary = await groq_json(
            system_prompt="""You are an expert academic researcher who reads papers and extracts structured information for literature reviews.
Always respond with valid JSON containing the requested fields.""",
            user_prompt=f"""Analyze this paper and extract structured information:

{content}

Return JSON with these exact fields:
{{
  "key_contribution": "The main contribution or novelty in 2-3 sentences",
  "methodology": "The methods, algorithms, or approaches used",
  "datasets_benchmarks": "Datasets, benchmarks, or experimental setups used (or 'Not specified')",
  "results": "Key quantitative or qualitative results and findings",
  "limitations": "Limitations acknowledged or apparent from the work",
  "research_gaps": "What problems remain unsolved or future work directions",
  "keywords": ["keyword1", "keyword2", "keyword3", "keyword4", "keyword5"],
  "paper_type": "empirical|theoretical|survey|system|position",
  "domain": "The specific research domain or subfield"
}}""",
            max_tokens=1500,
        )
        return {**paper, "summary": summary}
    except Exception as e:
        logger.error(f"Failed to summarize paper '{title}': {e}")
        return {**paper, "summary": {
            "key_contribution": abstract[:300] if abstract else "See abstract",
            "methodology": "Not extracted",
            "datasets_benchmarks": "Not specified",
            "results": "See abstract",
            "limitations": "Not specified",
            "research_gaps": "Not specified",
            "keywords": [],
            "paper_type": "unknown",
            "domain": "Unknown"
        }}


async def run_summarization_agent(papers: List[Dict], job_id: str, state_manager) -> List[Dict]:
    """
    Summarization Agent: summarizes all papers using Groq.
    """
    state_manager.update(job_id, current_agent="🧠 Summarization Agent", progress=35)
    state_manager.add_log(job_id, f"Summarizing {len(papers)} papers with Groq LLM")

    # Groq rate limit: process in batches with delays
    semaphore = asyncio.Semaphore(2)  # 2 concurrent requests
    
    async def process_one(paper, idx):
        async with semaphore:
            result = await summarize_paper(paper)
            state_manager.add_log(job_id, f"[{idx+1}/{len(papers)}] Summarized: {paper.get('title', '')[:60]}")
            progress = 35 + int(20 * (idx + 1) / len(papers))
            state_manager.update(job_id, progress=progress)
            await asyncio.sleep(0.3)  # courtesy delay
            return result
    
    tasks = [process_one(p, i) for i, p in enumerate(papers)]
    summarized = await asyncio.gather(*tasks)
    
    state_manager.add_log(job_id, "All papers summarized successfully", "success")
    state_manager.update(job_id, progress=55)
    
    return summarized
