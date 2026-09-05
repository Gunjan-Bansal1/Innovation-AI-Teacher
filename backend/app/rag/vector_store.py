"""
Vector store — saves/retrieves document chunks with embeddings from MongoDB.

Uses MongoDB Atlas $vectorSearch if available.
Falls back to Python-side cosine similarity retrieval if not on Atlas.
"""
import math
from typing import Optional
from bson import ObjectId
from datetime import datetime, timezone

from app.services.mongodb_service import mongodb_service
from app.rag.chunker import DocumentChunk
from app.core.logging import get_logger

logger = get_logger(__name__)

_atlas_vector_search_available: Optional[bool] = None


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Pure-Python cosine similarity between two vectors."""
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


async def store_chunks(
    chunks: list[DocumentChunk],
    document_id: str,
) -> list[str]:
    """
    Store embedded chunks into MongoDB document_chunks collection.
    Returns list of inserted IDs.
    """
    if not chunks:
        return []

    docs = []
    for chunk in chunks:
        doc = {
            "document_id": document_id,
            "filename": chunk.filename,
            "page_number": chunk.page_number,       # None if not available
            "chapter": chunk.chapter,               # None if not available
            "section": chunk.section,               # None if not available
            "chunk_index": chunk.chunk_index,
            "text": chunk.text,
            "word_count": chunk.word_count,
            "embedding": chunk.embedding,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        docs.append(doc)

    result = await mongodb_service.document_chunks.insert_many(docs)
    inserted_ids = [str(oid) for oid in result.inserted_ids]
    logger.info(f"Stored {len(inserted_ids)} chunks for document {document_id}")
    return inserted_ids


async def retrieve_similar_chunks(
    query_embedding: list[float],
    document_id: str,
    top_k: int = 5,
) -> list[dict]:
    """
    Retrieve the top-k most similar chunks for a query embedding.

    Attempts Atlas $vectorSearch first.
    Falls back to Python cosine similarity if not available.
    """
    global _atlas_vector_search_available

    if _atlas_vector_search_available is None:
        _atlas_vector_search_available = await _test_atlas_vector_search(
            document_id, query_embedding
        )

    if _atlas_vector_search_available:
        return await _atlas_vector_search(query_embedding, document_id, top_k)
    else:
        return await _python_cosine_search(query_embedding, document_id, top_k)


async def _atlas_vector_search(
    query_embedding: list[float],
    document_id: str,
    top_k: int,
) -> list[dict]:
    """Use MongoDB Atlas $vectorSearch aggregation."""
    try:
        pipeline = [
            {
                "$vectorSearch": {
                    "index": "chunk_embedding_index",
                    "path": "embedding",
                    "queryVector": query_embedding,
                    "numCandidates": top_k * 10,
                    "limit": top_k,
                    "filter": {"document_id": document_id},
                }
            },
            {
                "$project": {
                    "_id": {"$toString": "$_id"},
                    "document_id": 1,
                    "filename": 1,
                    "page_number": 1,
                    "chapter": 1,
                    "section": 1,
                    "chunk_index": 1,
                    "text": 1,
                    "score": {"$meta": "vectorSearchScore"},
                }
            },
        ]
        cursor = mongodb_service.document_chunks.aggregate(pipeline)
        return await cursor.to_list(top_k)
    except Exception as e:
        logger.warning(f"Atlas vectorSearch failed, switching to Python fallback: {e}")
        global _atlas_vector_search_available
        _atlas_vector_search_available = False
        return await _python_cosine_search(query_embedding, document_id, top_k)


async def _python_cosine_search(
    query_embedding: list[float],
    document_id: str,
    top_k: int,
) -> list[dict]:
    """
    Python-side cosine similarity search.
    Fetches all chunks for document_id, computes similarity in-memory.
    Note: Not efficient for very large documents but functionally correct.
    """
    logger.debug(f"Using Python cosine search for document {document_id}")

    cursor = mongodb_service.document_chunks.find(
        {"document_id": document_id},
        {
            "_id": 1, "document_id": 1, "filename": 1,
            "page_number": 1, "chapter": 1, "section": 1,
            "chunk_index": 1, "text": 1, "embedding": 1,
        }
    )
    all_chunks = await cursor.to_list(None)

    if not all_chunks:
        return []

    scored = []
    for chunk in all_chunks:
        emb = chunk.get("embedding")
        if emb:
            score = _cosine_similarity(query_embedding, emb)
            scored.append((score, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:top_k]

    results = []
    for score, chunk in top:
        results.append({
            "_id": str(chunk["_id"]),
            "document_id": chunk["document_id"],
            "filename": chunk.get("filename"),
            "page_number": chunk.get("page_number"),
            "chapter": chunk.get("chapter"),
            "section": chunk.get("section"),
            "chunk_index": chunk.get("chunk_index"),
            "text": chunk["text"],
            "score": round(score, 4),
        })

    return results


async def _test_atlas_vector_search(
    document_id: str,
    query_embedding: list[float],
) -> bool:
    """Test if Atlas Vector Search is available on this MongoDB instance."""
    try:
        pipeline = [
            {
                "$vectorSearch": {
                    "index": "chunk_embedding_index",
                    "path": "embedding",
                    "queryVector": query_embedding,
                    "numCandidates": 1,
                    "limit": 1,
                    "filter": {"document_id": document_id},
                }
            },
            {"$limit": 1},
        ]
        cursor = mongodb_service.document_chunks.aggregate(pipeline)
        await cursor.to_list(1)
        logger.info("MongoDB Atlas Vector Search is available")
        return True
    except Exception:
        logger.info("MongoDB Atlas Vector Search not available — using Python cosine similarity")
        return False


async def delete_chunks_for_document(document_id: str) -> int:
    """Delete all chunks for a given document."""
    result = await mongodb_service.document_chunks.delete_many(
        {"document_id": document_id}
    )
    return result.deleted_count
