"""
Semantic chunker — splits parsed document pages into overlapping chunks.

Each chunk preserves real metadata from the source.
Never fabricates page numbers, chapter names, or section headers.
"""
from dataclasses import dataclass, field
from typing import Optional
import re

from app.rag.document_parser import ParsedDocument, ParsedPage
from app.core.logging import get_logger

logger = get_logger(__name__)

CHUNK_SIZE_WORDS = 250      # ~500 tokens at average word length
CHUNK_OVERLAP_WORDS = 40    # overlap to preserve context across chunks


@dataclass
class DocumentChunk:
    """A single chunk ready for embedding and storage."""
    document_id: str
    filename: str
    page_number: Optional[int]      # Real page number or None
    chapter: Optional[str]          # Real chapter/heading or None
    section: Optional[str]          # Real section or None
    chunk_index: int
    text: str
    word_count: int
    embedding: Optional[list[float]] = None  # Filled after embedding


class Chunker:
    """Split parsed documents into overlapping chunks with real metadata."""

    def chunk_document(
        self,
        document: ParsedDocument,
        document_id: str,
    ) -> list[DocumentChunk]:
        """
        Chunk a parsed document. Preserves page/chapter/section metadata.
        Returns a flat list of DocumentChunk objects.
        """
        chunks: list[DocumentChunk] = []
        chunk_index = 0

        for page in document.pages:
            page_chunks = self._chunk_page(
                page=page,
                document_id=document_id,
                filename=document.filename,
                chunk_index_start=chunk_index,
            )
            chunks.extend(page_chunks)
            chunk_index += len(page_chunks)

        logger.info(
            f"Chunked document",
            extra={
                "document_id": document_id,
                "total_chunks": len(chunks),
                "doc_filename": document.filename,
            },
        )
        return chunks

    def _chunk_page(
        self,
        page: ParsedPage,
        document_id: str,
        filename: str,
        chunk_index_start: int,
    ) -> list[DocumentChunk]:
        """Split a single page into word-window chunks with overlap."""
        words = page.text.split()
        if not words:
            return []

        chunks = []
        start = 0
        local_index = 0

        while start < len(words):
            end = min(start + CHUNK_SIZE_WORDS, len(words))
            chunk_words = words[start:end]
            chunk_text = " ".join(chunk_words).strip()

            if chunk_text:
                chunks.append(DocumentChunk(
                    document_id=document_id,
                    filename=filename,
                    page_number=page.page_number,   # Real or None
                    chapter=page.heading,            # Real or None
                    section=page.section,            # Real or None
                    chunk_index=chunk_index_start + local_index,
                    text=chunk_text,
                    word_count=len(chunk_words),
                ))
                local_index += 1

            # Move forward with overlap
            next_start = start + CHUNK_SIZE_WORDS - CHUNK_OVERLAP_WORDS
            if next_start <= start:
                break
            start = next_start

        return chunks


chunker = Chunker()
