"""
PDF Extraction Agent - Extracts text from open-access PDFs
Falls back to abstract if PDF unavailable
"""
import httpx
import asyncio
import logging
from typing import Dict, Optional, List
import io

logger = logging.getLogger(__name__)


def extract_text_from_pdf_bytes(pdf_bytes: bytes, max_chars: int = 8000) -> str:
    """Extract text from PDF bytes using pypdf."""
    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        text_parts = []
        for page in reader.pages[:15]:  # first 15 pages
            try:
                text_parts.append(page.extract_text() or "")
            except Exception:
                continue
        full_text = "\n".join(text_parts)
        return full_text[:max_chars]
    except Exception as e:
        logger.warning(f"PDF extraction failed: {e}")
        return ""


async def fetch_pdf_text(url: str) -> Optional[str]:
    """Download and extract text from a PDF URL."""
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; LitReviewBot/1.0)",
        "Accept": "application/pdf,*/*",
    }
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        try:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200 and "pdf" in resp.headers.get("content-type", "").lower():
                return extract_text_from_pdf_bytes(resp.content)
            return None
        except Exception as e:
            logger.warning(f"Failed to fetch PDF from {url}: {e}")
            return None


async def try_arxiv_fetch(paper: Dict) -> Optional[str]:
    """Try to get paper text from ArXiv."""
    external_ids = paper.get("externalIds") or {}
    arxiv_id = external_ids.get("ArXiv")
    if not arxiv_id:
        return None
    
    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    logger.info(f"Trying ArXiv PDF: {pdf_url}")
    return await fetch_pdf_text(pdf_url)


async def extract_paper_content(paper: Dict) -> Dict:
    """
    Extract full text from a paper. Tries:
    1. Open access PDF link from Semantic Scholar
    2. ArXiv PDF
    3. Falls back to abstract
    """
    paper_id = paper.get("paperId", "unknown")
    title = paper.get("title", "Unknown Title")
    abstract = paper.get("abstract", "") or ""
    
    full_text = None
    source = "abstract"
    
    # Try open access PDF
    oa_pdf = paper.get("openAccessPdf") or {}
    pdf_url = oa_pdf.get("url") if isinstance(oa_pdf, dict) else None
    
    if pdf_url:
        logger.info(f"Attempting OA PDF for: {title[:50]}")
        full_text = await fetch_pdf_text(pdf_url)
        if full_text and len(full_text) > 500:
            source = "pdf"
    
    # Try ArXiv
    if not full_text or len(full_text) < 500:
        arxiv_text = await try_arxiv_fetch(paper)
        if arxiv_text and len(arxiv_text) > 500:
            full_text = arxiv_text
            source = "arxiv"
    
    # Fallback to abstract
    if not full_text or len(full_text) < 100:
        full_text = abstract
        source = "abstract"
    
    authors = paper.get("authors") or []
    author_names = [a.get("name", "") for a in authors[:5]]
    
    return {
        "paperId": paper_id,
        "title": title,
        "abstract": abstract,
        "full_text": full_text,
        "text_source": source,
        "authors": author_names,
        "year": paper.get("year"),
        "venue": paper.get("venue", ""),
        "citationCount": paper.get("citationCount", 0),
        "url": paper.get("url", ""),
        "externalIds": paper.get("externalIds") or {},
    }


async def run_pdf_agent(papers: List[Dict], job_id: str, state_manager) -> List[Dict]:
    """
    PDF Extraction Agent: processes all papers concurrently.
    """
    state_manager.update(job_id, current_agent="📄 PDF Extraction Agent", progress=20)
    state_manager.add_log(job_id, f"Extracting content from {len(papers)} papers")

    # Process papers with some concurrency
    semaphore = asyncio.Semaphore(3)

    async def process_one(paper, idx):
        async with semaphore:
            result = await extract_paper_content(paper)
            source_label = {"pdf": "✅ PDF", "arxiv": "📋 ArXiv", "abstract": "📝 Abstract"}.get(result["text_source"], "📝 Abstract")
            state_manager.add_log(job_id, f"[{idx+1}/{len(papers)}] {source_label}: {result['title'][:60]}")
            progress = 20 + int(15 * (idx + 1) / len(papers))
            state_manager.update(job_id, progress=progress)
            return result

    tasks = [process_one(p, i) for i, p in enumerate(papers)]
    extracted = await asyncio.gather(*tasks)
    
    # Filter out papers with too little content
    valid = [p for p in extracted if len(p.get("full_text", "") + p.get("abstract", "")) > 50]
    
    state_manager.add_log(job_id, f"Extracted content from {len(valid)} papers", "success")
    state_manager.update(job_id, progress=35)
    
    return valid
