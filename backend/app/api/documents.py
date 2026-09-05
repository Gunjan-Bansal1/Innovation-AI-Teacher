"""
Document upload and management API endpoints.
"""
import uuid
import os
import re
from pathlib import Path
from datetime import datetime, timezone

from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.config import settings
from app.services.mongodb_service import mongodb_service
from app.rag.document_parser import document_parser
from app.rag.chunker import chunker
from app.rag.embeddings import embed_chunks
from app.rag.vector_store import store_chunks, delete_chunks_for_document
from app.rag.retriever import retrieve_context
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".txt"}
MAX_SIZE_BYTES = settings.max_upload_size_mb * 1024 * 1024


def sanitize_filename(filename: str) -> str:
    """Remove path traversal and dangerous characters."""
    name = Path(filename).name
    name = re.sub(r"[^\w\s\-.]", "", name)
    return name[:200]


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5


@router.post("/api/documents/upload")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    """
    Upload and parse a document. Starts background embedding pipeline.
    """
    # Validate filename
    if not file.filename:
        raise HTTPException(400, "No filename provided")

    safe_name = sanitize_filename(file.filename)
    ext = Path(safe_name).suffix.lower()

    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            400,
            f"Unsupported file type: {ext}. Supported: {list(ALLOWED_EXTENSIONS)}"
        )

    # Read file content
    content = await file.read()

    if len(content) == 0:
        raise HTTPException(400, "Empty file uploaded")

    if len(content) > MAX_SIZE_BYTES:
        raise HTTPException(
            413,
            f"File too large. Maximum size: {settings.max_upload_size_mb}MB"
        )

    # Save to disk
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    document_id = str(uuid.uuid4())
    file_path = upload_dir / f"{document_id}{ext}"
    file_path.write_bytes(content)

    # Parse document immediately
    try:
        parsed = document_parser.parse(file_path, safe_name)
    except Exception as e:
        file_path.unlink(missing_ok=True)
        raise HTTPException(422, f"Failed to parse document: {str(e)}")

    now = datetime.now(timezone.utc).isoformat()

    # Store document metadata in MongoDB
    doc_record = {
        "_id": document_id,
        "filename": safe_name,
        "file_type": ext.lstrip("."),
        "file_path": str(file_path),
        "file_size_bytes": len(content),
        "total_pages": parsed.total_pages,
        "word_count": parsed.word_count,
        "detected_chapters": parsed.detected_chapters,
        "detected_sections": parsed.detected_sections,
        "embedding_status": "pending",
        "chunk_count": 0,
        "created_at": now,
        "updated_at": now,
    }
    await mongodb_service.documents.insert_one(doc_record)

    # Schedule background embedding
    background_tasks.add_task(
        _embed_document_background,
        document_id=document_id,
        parsed=parsed,
        file_path=str(file_path),
    )

    return {
        "document_id": document_id,
        "filename": safe_name,
        "file_type": ext.lstrip("."),
        "total_pages": parsed.total_pages,
        "word_count": parsed.word_count,
        "detected_chapters": parsed.detected_chapters,
        "detected_sections": parsed.detected_sections,
        "embedding_status": "processing",
        "message": "Document uploaded. Embedding in background.",
    }


async def _embed_document_background(
    document_id: str,
    parsed,
    file_path: str,
) -> None:
    """Background task: chunk → embed → store in MongoDB."""
    try:
        logger.info(f"Starting background embedding for {document_id}")

        # Chunk document
        chunks = chunker.chunk_document(parsed, document_id)

        # Embed all chunks
        embedded_chunks = await embed_chunks(chunks)

        # Store in MongoDB
        await store_chunks(embedded_chunks, document_id)

        # Update document record
        await mongodb_service.documents.update_one(
            {"_id": document_id},
            {
                "$set": {
                    "embedding_status": "complete",
                    "chunk_count": len(embedded_chunks),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            },
        )
        logger.info(f"Embedding complete for {document_id}: {len(embedded_chunks)} chunks")

    except Exception as e:
        logger.error(f"Background embedding failed for {document_id}: {e}")
        await mongodb_service.documents.update_one(
            {"_id": document_id},
            {
                "$set": {
                    "embedding_status": "error",
                    "embedding_error": str(e)[:200],
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            },
        )


@router.get("/api/documents/{document_id}")
async def get_document(document_id: str):
    """Get document metadata."""
    doc = await mongodb_service.documents.find_one(
        {"_id": document_id},
        {"file_path": 0},  # Don't expose internal path
    )
    if not doc:
        raise HTTPException(404, f"Document {document_id} not found")
    doc["_id"] = str(doc["_id"])
    return doc


@router.post("/api/documents/{document_id}/search")
async def search_document(document_id: str, body: SearchRequest):
    """
    Search document for relevant chunks.
    Returns actual retrieved chunks — NOT Gemma's answer.
    This verifies RAG retrieval accuracy independently of the LLM.
    """
    # Verify document exists and is embedded
    doc = await mongodb_service.documents.find_one({"_id": document_id})
    if not doc:
        raise HTTPException(404, f"Document {document_id} not found")

    if doc.get("embedding_status") != "complete":
        raise HTTPException(
            409,
            f"Document embedding not complete. Status: {doc.get('embedding_status', 'unknown')}"
        )

    if not body.query.strip():
        raise HTTPException(400, "Query cannot be empty")

    top_k = max(1, min(body.top_k, 20))
    context_result = await retrieve_context(
        query=body.query,
        document_id=document_id,
        top_k=top_k,
    )

    return {
        "query": body.query,
        "document_id": document_id,
        "has_sufficient_context": context_result["has_sufficient_context"],
        "chunk_count": len(context_result["chunks"]),
        "chunks": context_result["chunks"],
        "source_refs": context_result["source_refs"],
    }
