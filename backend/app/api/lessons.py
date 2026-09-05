"""
Lessons API — plan and retrieve lessons.
"""
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.schemas.lesson import LessonPlanCreate
from app.schemas.learner import LearnerProfile, LearningPreferences
from app.agents.lesson_planner_agent import lesson_planner_agent
from app.agents.content_agent import content_agent
from app.services.mongodb_service import mongodb_service
from app.rag.retriever import retrieve_context
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


class LessonPlanRequest(BaseModel):
    learner_id: str
    topic: str
    subject: Optional[str] = None
    document_id: Optional[str] = None
    selected_concepts: Optional[list[str]] = None
    level: str = "beginner"
    language: str = "english"
    teaching_style: str = "simple"
    depth: str = "standard"
    available_time_minutes: int = 10
    prior_knowledge: Optional[str] = None


@router.post("/api/lessons/plan")
async def plan_lesson(body: LessonPlanRequest):
    """Plan a lesson using LessonPlannerAgent."""
    if not body.topic.strip():
        raise HTTPException(400, "Topic cannot be empty")

    # Load or create learner profile
    profile_doc = await mongodb_service.learner_profiles.find_one(
        {"learner_id": body.learner_id}
    )

    if profile_doc:
        prefs_data = profile_doc.get("preferences", {})
        # Override with request params if provided
        prefs = LearningPreferences(
            level=body.level,
            language=body.language,
            teaching_style=body.teaching_style,
            depth=body.depth,
            available_time_minutes=body.available_time_minutes,
            prior_knowledge=body.prior_knowledge,
        )
        profile = LearnerProfile(
            learner_id=body.learner_id,
            preferences=prefs,
        )
    else:
        prefs = LearningPreferences(
            level=body.level,
            language=body.language,
            teaching_style=body.teaching_style,
            depth=body.depth,
            available_time_minutes=body.available_time_minutes,
            prior_knowledge=body.prior_knowledge,
        )
        profile = LearnerProfile(learner_id=body.learner_id, preferences=prefs)

    # Get source context for lesson planning
    source_context = ""
    if body.document_id:
        query = body.topic
        if body.selected_concepts:
            query += " " + " ".join(body.selected_concepts[:3])
        ctx = await retrieve_context(
            query=query,
            document_id=body.document_id,
            top_k=6,
        )
        source_context = ctx["context_text"]

    # Determine subject
    subject = body.subject or "general"
    if body.document_id and not body.subject:
        doc = await mongodb_service.documents.find_one({"_id": body.document_id})
        if doc:
            subject = doc.get("subject", "general")

    # Plan the lesson
    lesson_plan = await lesson_planner_agent.plan_lesson(
        topic=body.topic,
        subject=subject,
        profile=profile,
        source_context=source_context,
        selected_concepts=body.selected_concepts or [],
    )

    # Store lesson in MongoDB
    lesson_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    lesson_doc = {
        "_id": lesson_id,
        "learner_id": body.learner_id,
        "topic": body.topic,
        "subject": subject,
        "document_id": body.document_id,
        "title": lesson_plan.title,
        "duration_seconds": lesson_plan.duration_seconds,
        "language": lesson_plan.language,
        "teaching_style": lesson_plan.teaching_style,
        "level": body.level,
        "concept_keys": lesson_plan.concept_keys,
        "learning_objectives": lesson_plan.learning_objectives,
        "segments": lesson_plan.segments,
        "segment_count": len(lesson_plan.segments),
        "status": "ready",
        "created_at": now,
        "updated_at": now,
    }
    await mongodb_service.lessons.insert_one(lesson_doc)

    return {
        "lesson_id": lesson_id,
        "title": lesson_plan.title,
        "topic": body.topic,
        "duration_seconds": lesson_plan.duration_seconds,
        "duration_minutes": round(lesson_plan.duration_seconds / 60, 1),
        "language": lesson_plan.language,
        "teaching_style": lesson_plan.teaching_style,
        "concept_keys": lesson_plan.concept_keys,
        "learning_objectives": lesson_plan.learning_objectives,
        "segments": lesson_plan.segments,
        "segment_count": len(lesson_plan.segments),
    }


@router.get("/api/lessons/{lesson_id}")
async def get_lesson(lesson_id: str):
    """Get a lesson by ID."""
    lesson = await mongodb_service.lessons.find_one({"_id": lesson_id})
    if not lesson:
        raise HTTPException(404, f"Lesson {lesson_id} not found")
    lesson["_id"] = str(lesson["_id"])
    return lesson
