"""
Paper Search Agent - Searches Semantic Scholar, ArXiv, and OpenAlex for relevant papers
"""
import httpx
import asyncio
import logging
from typing import List, Dict, Optional
import feedparser
from utils.groq_client import groq_json

logger = logging.getLogger(__name__)

# how long to wait between query batches to avoid throttling
SEARCH_DELAY = 5.0  # seconds

SEMANTIC_SCHOLAR_BASE = "https://api.semanticscholar.org/graph/v1"
FIELDS = "paperId,title,abstract,authors,year,citationCount,externalIds,openAccessPdf,venue,url"


def normalize_semantic_scholar_paper(paper: Dict) -> Dict:
    """Normalize Semantic Scholar paper to common format."""
    return {
        "paperId": paper.get("paperId"),
        "title": paper.get("title", ""),
        "abstract": paper.get("abstract", ""),
        "authors": paper.get("authors", []),  # Already list of dicts
        "year": paper.get("year"),
        "citationCount": paper.get("citationCount", 0),
        "externalIds": paper.get("externalIds", {}),
        "openAccessPdf": paper.get("openAccessPdf"),
        "venue": paper.get("venue", ""),
        "url": paper.get("url", ""),
        "source": "semantic_scholar"
    }


async def search_semantic_scholar(query: str, limit: int = 20) -> List[Dict]:
    """Search Semantic Scholar API for papers with simple retry logic."""
    params = {
        "query": query,
        "limit": limit,
        "fields": FIELDS,
    }
    headers = {"User-Agent": "LitReviewBot/1.0 (research tool)"}
    # allow longer timeout when we add inter-request delays
    async with httpx.AsyncClient(timeout=60.0) as client:
        for attempt in range(2):
            try:
                resp = await client.get(
                    f"{SEMANTIC_SCHOLAR_BASE}/paper/search",
                    params=params,
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
                results = data.get("data", [])
                logger.debug(f"Semantic Scholar returned {len(results)} papers for '{query}'")
                return results
            except Exception as e:
                logger.warning(f"Semantic Scholar search attempt {attempt+1} failed for '{query}': {e}")
                if attempt == 0:
                    await asyncio.sleep(2)
        return []


async def search_arxiv(query: str, limit: int = 20) -> List[Dict]:
    """Search ArXiv API for papers with retry and proper looping."""
    params = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": limit,
        "sortBy": "relevance"
    }
    headers = {
        "Accept": "application/atom+xml",
        "User-Agent": "AutoScholar-Agent"
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        for attempt in range(2):
            try:
                resp = await client.get(
                    "http://export.arxiv.org/api/query",
                    params=params,
                    headers=headers,
                )
                resp.raise_for_status()
                feed = feedparser.parse(resp.text)
                papers = []
                for entry in feed.entries:
                    paper_id = entry.id.split('/')[-1] if '/' in entry.id else entry.id
                    papers.append({
                        "paperId": entry.id,
                        "title": entry.title,
                        "abstract": entry.summary,
                        "authors": [{"name": author.name} for author in entry.authors] if hasattr(entry, 'authors') else [],
                        "year": int(entry.published[:4]) if entry.published else None,
                        "citationCount": 0,
                        "externalIds": {"ArXiv": paper_id},
                        "openAccessPdf": {"url": f"https://arxiv.org/pdf/{paper_id}.pdf"},
                        "venue": "ArXiv",
                        "url": entry.id,
                        "source": "arxiv"
                    })
                logger.debug(f"ArXiv returned {len(papers)} papers for '{query}'")
                return papers
            except Exception as e:
                logger.warning(f"ArXiv search attempt {attempt+1} failed for '{query}': {e}")
                if attempt == 0:
                    await asyncio.sleep(2)
        return []


async def search_openalex(query: str, limit: int = 20) -> List[Dict]:
    """Search OpenAlex API for papers with retry and logging."""
    params = {
        "search": query,
        "per-page": limit
    }
    headers = {
        "Accept": "application/json",
        "User-Agent": "AutoScholar-Agent"
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        for attempt in range(2):
            try:
                resp = await client.get(
                    "https://api.openalex.org/works",
                    params=params,
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
                papers = []
                for work in data.get("results", []):
                    # Reconstruct abstract from inverted index if available
                    abstract = ""
                    if work.get("abstract_inverted_index"):
                        inverted = work["abstract_inverted_index"]
                        max_pos = max(inverted.values()) if inverted else 0
                        words = [None] * (max_pos + 1)
                        for word, positions in inverted.items():
                            for pos in positions:
                                words[pos] = word
                        abstract = " ".join(w for w in words if w)
                    
                    papers.append({
                        "paperId": work.get("id"),
                        "title": work.get("display_name", ""),
                        "abstract": abstract,
                        "authors": [{"name": authorship["author"]["display_name"]} for authorship in work.get("authorships", [])],
                        "year": work.get("publication_year"),
                        "citationCount": work.get("cited_by_count", 0),
                        "externalIds": {"DOI": work.get("doi")} if work.get("doi") else {},
                        "openAccessPdf": None,
                        "venue": "",
                        "url": work.get("doi"),
                        "source": "openalex"
                    })
                logger.debug(f"OpenAlex returned {len(papers)} papers for '{query}'")
                return papers
            except Exception as e:
                logger.warning(f"OpenAlex search attempt {attempt+1} failed for '{query}': {e}")
                if attempt == 0:
                    await asyncio.sleep(2)
        return []


async def get_paper_details(paper_id: str) -> Optional[Dict]:
    """Fetch detailed info for a single paper."""
    headers = {"User-Agent": "LitReviewBot/1.0"}
    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            resp = await client.get(
                f"{SEMANTIC_SCHOLAR_BASE}/paper/{paper_id}",
                params={"fields": FIELDS + ",references,citations"},
                headers=headers,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Failed to get paper {paper_id}: {str(e)}")
            return None


async def expand_search_queries(topic: str) -> List[str]:
    """Use Groq to generate multiple search queries for comprehensive coverage."""
    try:
        result = await groq_json(
            system_prompt="You are a research librarian expert at finding academic papers.",
            user_prompt=f"""Generate 5 diverse search queries to find papers about: "{topic}"
            
Return JSON: {{"queries": ["query1", "query2", "query3", "query4", "query5"]}}

Make queries specific, varied, covering: core topic, methods, applications, related work, recent advances."""
        )
        return result.get("queries", [topic])
    except Exception as e:
        logger.warning(f"Failed to expand queries via Groq: {e}. Using topic only.")
        return [topic]


async def run_search_agent(topic: str, max_papers: int, job_id: str, state_manager) -> List[Dict]:
    """
    Main search agent: expands queries, searches, deduplicates, ranks papers.
    """
    state_manager.update(job_id, current_agent="🔍 Paper Search Agent", progress=5)
    state_manager.add_log(job_id, f"Generating search queries for: {topic}")

    # Expand search queries
    queries = await expand_search_queries(topic)
    state_manager.add_log(job_id, f"Generated {len(queries)} search queries: {queries}")

    # Search with all queries
    all_papers = {}
    for i, query in enumerate(queries):
        state_manager.add_log(job_id, f"Searching: '{query}'")
        # Search Semantic Scholar
        ss_results = await search_semantic_scholar(query, limit=15)
        logger.debug(f"Semantic Scholar returned {len(ss_results)} papers")
        for paper in ss_results:
            normalized = normalize_semantic_scholar_paper(paper)
            key = normalized["title"].lower().strip()
            if key not in all_papers:
                all_papers[key] = normalized
        
        # Search ArXiv
        arxiv_results = await search_arxiv(query, limit=15)
        logger.debug(f"ArXiv returned {len(arxiv_results)} papers")
        for paper in arxiv_results:
            key = paper["title"].lower().strip()
            if key not in all_papers:
                all_papers[key] = paper
        
        # Search OpenAlex
        openalex_results = await search_openalex(query, limit=15)
        logger.debug(f"OpenAlex returned {len(openalex_results)} papers")
        for paper in openalex_results:
            key = paper["title"].lower().strip()
            if key not in all_papers:
                all_papers[key] = paper
        
        # Rate limit courtesy (small pause between queries)
        await asyncio.sleep(SEARCH_DELAY)
        state_manager.update(job_id, progress=5 + int(10 * (i + 1) / len(queries)))

    if not all_papers:
        logger.warning("No papers found via expanded queries, falling back to single-topic search")
        # try a simple search without expansion
        basic = await search_semantic_scholar(topic, limit=max_papers)
        for paper in basic:
            normalized = normalize_semantic_scholar_paper(paper)
            all_papers[normalized["title"].lower().strip()] = normalized

    state_manager.add_log(job_id, f"Found {len(all_papers)} unique papers before filtering")

    # Filter: must have abstract, published in last 10 years
    filtered = [
        p for p in all_papers.values()
        if p.get("abstract") and len(p.get("abstract", "")) > 100
        and p.get("year") and p.get("year", 0) >= 2015
    ]

    # Rank by citation count + recency
    filtered.sort(key=lambda p: (p.get("citationCount", 0) * 0.7 + (p.get("year", 2015) - 2015) * 5), reverse=True)

    # Use Groq to select the most relevant papers
    if len(filtered) > max_papers:
        paper_summaries = [
            {"title": p.get("title", ""), "abstract": (p.get("abstract") or "")[:200], "year": p.get("year"), "citations": p.get("citationCount", 0)}
            for p in filtered[:40]
        ]
        try:
            selection = await groq_json(
                system_prompt="You are a research expert selecting the most relevant papers for a literature review.",
                user_prompt=f"""Topic: "{topic}"
                
Papers (index 0-{len(paper_summaries)-1}):
{paper_summaries}

Select the {max_papers} most relevant and diverse papers for a comprehensive literature review.
Return JSON: {{"selected_indices": [0, 1, 2, ...]}}"""
            )
            indices = selection.get("selected_indices", list(range(min(max_papers, len(filtered)))))
            filtered = [filtered[i] for i in indices if i < len(filtered)]
        except Exception as e:
            logger.warning(f"AI paper selection failed, using top-ranked: {e}")
            filtered = filtered[:max_papers]
    
    papers = filtered[:max_papers]
    state_manager.set_papers(job_id, [{"title": p.get("title"), "year": p.get("year"), "paperId": p.get("paperId")} for p in papers])
    state_manager.add_log(job_id, f"Selected {len(papers)} papers for review", "success")
    state_manager.update(job_id, progress=20)
    
    return papers
