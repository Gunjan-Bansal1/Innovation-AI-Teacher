"""
Embedding service - generates document/query embeddings via Ollama.

By default this uses the same Ollama model as teaching (`gemma4:31b-cloud`),
so the prototype needs only one model pull.
"""
from typing import Optional

from app.services.ollama_service import (
    ollama_service,
    OllamaConnectionError,
    OllamaModelUnavailableError,
)
from app.rag.chunker import DocumentChunk
from app.core.logging import get_logger

logger = get_logger(__name__)

_embedding_model_available: Optional[bool] = None


async def check_embedding_model() -> bool:
    """Check if the configured embedding model is available. Caches result."""
    global _embedding_model_available
    if _embedding_model_available is not None:
        return _embedding_model_available
    try:
        emb = await ollama_service.embed("test")
        _embedding_model_available = len(emb) > 0
    except (OllamaConnectionError, OllamaModelUnavailableError):
        _embedding_model_available = False
    return _embedding_model_available


async def embed_text(text: str) -> list[float]:
    """Generate embedding for a single text string."""
    return await ollama_service.embed(text)


async def embed_chunks(chunks: list[DocumentChunk]) -> list[DocumentChunk]:
    """
    Embed all chunks in-place using the configured Ollama embedding model.
    Logs progress every 10 chunks.
    """
    total = len(chunks)
    for i, chunk in enumerate(chunks):
        if i % 10 == 0:
            logger.info(f"Embedding chunks {i}/{total}...")
        chunk.embedding = await ollama_service.embed(chunk.text)

    logger.info(f"Embedded {total} chunks with {ollama_service.model}")
    return chunks
