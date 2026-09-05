"""
Retriever — high-level interface for RAG retrieval.

Converts query text → embedding → vector search → returns source context.
"""
from typing import Optional

from app.rag.embeddings import embed_text
from app.rag.vector_store import retrieve_similar_chunks
from app.core.logging import get_logger

logger = get_logger(__name__)

INSUFFICIENT_EVIDENCE_MSG = (
    "The uploaded material does not provide enough information to explain this confidently."
)


async def retrieve_context(
    query: str,
    document_id: str,
    top_k: int = 5,
    min_score: float = 0.0,
) -> dict:
    """
    Retrieve relevant context chunks for a query.

    Returns:
        {
            "chunks": [...],
            "context_text": "combined text",
            "has_sufficient_context": bool,
            "source_refs": [...]
        }
    """
    try:
        query_embedding = await embed_text(query)
        chunks = await retrieve_similar_chunks(
            query_embedding=query_embedding,
            document_id=document_id,
            top_k=top_k,
        )

        # Filter by minimum score
        if min_score > 0:
            chunks = [c for c in chunks if c.get("score", 0) >= min_score]

        if not chunks:
            logger.info(f"No relevant chunks found for query: {query[:50]}")
            return {
                "chunks": [],
                "context_text": INSUFFICIENT_EVIDENCE_MSG,
                "has_sufficient_context": False,
                "source_refs": [],
            }

        # Build combined context text
        context_parts = []
        source_refs = []

        for chunk in chunks:
            text = chunk.get("text", "").strip()
            if text:
                context_parts.append(text)

            # Build source reference (only real metadata)
            ref: dict = {"chunk_index": chunk.get("chunk_index")}
            if chunk.get("page_number") is not None:
                ref["page"] = chunk["page_number"]
            if chunk.get("chapter"):
                ref["chapter"] = chunk["chapter"]
            if chunk.get("section"):
                ref["section"] = chunk["section"]
            ref["score"] = chunk.get("score", 0)
            source_refs.append(ref)

        context_text = "\n\n---\n\n".join(context_parts)
        has_sufficient = len(context_text.strip()) > 100

        return {
            "chunks": chunks,
            "context_text": context_text if has_sufficient else INSUFFICIENT_EVIDENCE_MSG,
            "has_sufficient_context": has_sufficient,
            "source_refs": source_refs,
        }

    except Exception as e:
        logger.error(f"Retrieval error: {e}")
        return {
            "chunks": [],
            "context_text": INSUFFICIENT_EVIDENCE_MSG,
            "has_sufficient_context": False,
            "source_refs": [],
        }


async def retrieve_topic_context(
    query: str,
    document_id: Optional[str],
    top_k: int = 5,
) -> dict:
    """
    Retrieve context for topic-based (no document) learning.
    Returns empty context — Gemma uses its own knowledge.
    """
    if document_id:
        return await retrieve_context(query, document_id, top_k)
    return {
        "chunks": [],
        "context_text": "",
        "has_sufficient_context": False,
        "source_refs": [],
    }
