"""
Learner profile management API.
"""
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from app.schemas.learner import LearnerProfileCreate, LearnerProfile, LearningPreferences
from app.services.mongodb_service import mongodb_service
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


@router.post("/api/learners")
async def create_learner_profile(body: LearnerProfileCreate):
    """Create or update a learner profile."""
    learner_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    profile_doc = {
        "_id": learner_id,
        "learner_id": learner_id,
        "name": body.name,
        "preferences": body.preferences.model_dump(),
        "created_at": now,
        "updated_at": now,
    }
    await mongodb_service.learner_profiles.insert_one(profile_doc)

    return {
        "learner_id": learner_id,
        "name": body.name,
        "preferences": body.preferences.model_dump(),
        "created_at": now,
    }


@router.get("/api/learners/{learner_id}")
async def get_learner_profile(learner_id: str):
    """Get a learner profile."""
    profile = await mongodb_service.learner_profiles.find_one({"learner_id": learner_id})
    if not profile:
        raise HTTPException(404, f"Learner {learner_id} not found")
    profile["_id"] = str(profile["_id"])
    return profile


@router.put("/api/learners/{learner_id}")
async def update_learner_profile(learner_id: str, body: LearnerProfileCreate):
    """Update a learner profile."""
    result = await mongodb_service.learner_profiles.update_one(
        {"learner_id": learner_id},
        {
            "$set": {
                "name": body.name,
                "preferences": body.preferences.model_dump(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        },
    )
    if result.matched_count == 0:
        raise HTTPException(404, f"Learner {learner_id} not found")
    return {"learner_id": learner_id, "updated": True}
