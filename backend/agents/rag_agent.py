"""
RAG Agent - Chunks paper texts, embeds them, and ranks them by cosine similarity to the topic.
"""
import logging
from typing import List, Dict
import numpy as np

logger = logging.getLogger(__name__)

# To avoid reloading model on every request, load lazily
_embedding_model = None

def get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        try:
            from sentence_transformers import SentenceTransformer
            # using a fast, lightweight model
            logger.info("Loading sentence-transformers model...")
            _embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
            logger.info("Model loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load sentence-transformers: {e}")
            raise RuntimeError("sentence-transformers not available")
    return _embedding_model


def chunk_text(text: str, chunk_size: int = 1500, overlap: int = 300) -> List[str]:
    """Split text into overlapping chunks."""
    if not text:
        return []
    
    chunks = []
    start = 0
    text_len = len(text)
    
    while start < text_len:
        end = min(start + chunk_size, text_len)
        
        # If we're not at the very end, try to find a nice breaking point (newline or period)
        if end < text_len:
            # Look backwards for a double newline
            break_idx = text.rfind("\n\n", start, end)
            if break_idx == -1 or break_idx < start + chunk_size // 2:
                # Fall back to single newline
                break_idx = text.rfind("\n", start, end)
            if break_idx == -1 or break_idx < start + chunk_size // 2:
                # Fall back to period
                break_idx = text.rfind(". ", start, end)
                
            if break_idx != -1 and break_idx > start + chunk_size // 2:
                end = break_idx + 1 # Include the period or newline
        
        chunks.append(text[start:end].strip())
        
        if end == text_len:
            break
            
        start = end - overlap
        
    return chunks

async def run_rag_agent(papers: List[Dict], topic: str, max_chunks: int = 25, job_id: str = None, state_manager = None) -> List[Dict]:
    """
    Chunks all papers, embeds them, and finds the most relevant chunks using cosine similarity.
    Returns the top K highest-scoring text chunks mapped contextually to their papers.
    """
    if state_manager and job_id:
        state_manager.update(job_id, current_agent="🧩 RAG Agent", progress=35)
        state_manager.add_log(job_id, "Chunking and embedding paper texts...")

    model = get_embedding_model()
    from sklearn.metrics.pairwise import cosine_similarity
    
    all_chunks_info = []
    
    # 1. Chunk texts
    for p_idx, paper in enumerate(papers):
        title = paper.get("title", f"Paper {p_idx}")
        authors = paper.get("authors", [])
        author_str = ", ".join(authors[:2]) + " et al." if len(authors) > 2 else ", ".join(authors)
        full_text = paper.get("full_text", "")
        abstract = paper.get("abstract", "")
        
        # Merge abstract and full text, preferring full text
        content = f"Title: {title}\nAbstract: {abstract}\n{full_text}"
        
        chunks = chunk_text(content)
        for i, chunk in enumerate(chunks):
            if len(chunk) > 100: # Ignore very short chunks
                all_chunks_info.append({
                    "paper_idx": p_idx,
                    "paper_title": title,
                    "paper_authors": author_str,
                    "paper_year": paper.get("year", "N/A"),
                    "chunk_idx": i,
                    "text": chunk
                })

    if not all_chunks_info:
        logger.warning("No chunks generated from papers.")
        return []

    if state_manager and job_id:
        state_manager.add_log(job_id, f"Generated {len(all_chunks_info)} text chunks. Calculating embeddings...")
        state_manager.update(job_id, progress=40)

    # 2. Embed topic
    query_embedding = model.encode([topic])
    
    # 3. Embed chunks (batch processing)
    texts_to_embed = [c["text"] for c in all_chunks_info]
    chunk_embeddings = model.encode(texts_to_embed, show_progress_bar=False)

    # 4. Compute similarity
    if state_manager and job_id:
        state_manager.update(job_id, progress=50)
        
    similarities = cosine_similarity(query_embedding, chunk_embeddings)[0]
    
    # Add score to each chunk
    for i, chunk_info in enumerate(all_chunks_info):
        chunk_info["similarity_score"] = float(similarities[i])
        
    # 5. Sort by relevance
    all_chunks_info.sort(key=lambda x: x["similarity_score"], reverse=True)
    
    # 6. Deduplicate slightly by paper title to ensure fairness/diversity (optional but good)
    selected_chunks = []
    paper_chunk_counts = {}
    
    for chunk in all_chunks_info:
        p_title = chunk["paper_title"]
        # Allow max 4 chunks per paper to guarantee diverse synthesis
        if paper_chunk_counts.get(p_title, 0) < 4:
            selected_chunks.append(chunk)
            paper_chunk_counts[p_title] = paper_chunk_counts.get(p_title, 0) + 1
            
        if len(selected_chunks) >= max_chunks:
            break

    if state_manager and job_id:
        state_manager.add_log(job_id, f"Selected top {len(selected_chunks)} most relevant chunks for synthesis.", "success")
        state_manager.update(job_id, progress=55)

    return selected_chunks
