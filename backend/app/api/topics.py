"""
Topics API — analyze topics for learning.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.agents.content_agent import content_agent
from app.services.mongodb_service import mongodb_service
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


class TopicAnalyzeRequest(BaseModel):
    topic: str
    document_id: Optional[str] = None
    level: str = "beginner"
    custom_question: Optional[str] = None


@router.post("/api/topics/analyze")
async def analyze_topic(body: TopicAnalyzeRequest):
    """
    Analyze a topic or document to extract concepts for learning.
    """
    focus_topic = (body.custom_question or body.topic).strip()
    if not focus_topic:
        raise HTTPException(400, "Topic cannot be empty")

    if body.document_id:
        # Document-based analysis
        doc = await mongodb_service.documents.find_one({"_id": body.document_id})
        if not doc:
            raise HTTPException(404, f"Document {body.document_id} not found")

        # Get a text sample from the first few chunks
        cursor = mongodb_service.document_chunks.find(
            {"document_id": body.document_id},
            {"text": 1},
        ).limit(5)
        chunks = await cursor.to_list(5)
        text_sample = "\n\n".join(c["text"] for c in chunks)

        analysis = await content_agent.analyze_document(
            text_sample=text_sample,
            filename=doc.get("filename", "document"),
            chapters=doc.get("detected_chapters", []),
            sections=doc.get("detected_sections", []),
            focus_question=focus_topic if focus_topic != "General Learning" else None,
        )
    else:
        # Pure topic-based analysis
        analysis = await content_agent.analyze_topic(
            topic=focus_topic,
            level=body.level,
        )

    return {
        "topic": body.topic,
        "document_id": body.document_id,
        "subject": analysis.subject,
        "main_topics": analysis.main_topics,
        "concepts": [c.model_dump() for c in analysis.concepts],
        "difficulty_level": analysis.difficulty_level,
        "document_type": analysis.document_type,
    }
