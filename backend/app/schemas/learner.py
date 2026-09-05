"""
Pydantic schemas for learner profiles and preferences.
"""
from typing import Optional
from pydantic import BaseModel, Field
from enum import Enum


class EducationLevel(str, Enum):
    beginner = "beginner"
    intermediate = "intermediate"
    advanced = "advanced"


class Language(str, Enum):
    english = "english"
    hindi = "hindi"
    hinglish = "hinglish"


class AvailableTime(str, Enum):
    five = "5"
    ten = "10"
    twenty = "20"
    thirty = "30"
    sixty = "60"


class LearningObjective(str, Enum):
    concept_understanding = "concept_understanding"
    exam_preparation = "exam_preparation"
    interview_preparation = "interview_preparation"
    revision = "revision"
    practice = "practice"


class TeachingStyle(str, Enum):
    simple = "simple"
    visual = "visual"
    practical = "practical"
    technical = "technical"
    analogy_based = "analogy_based"
    story_based = "story_based"


class Depth(str, Enum):
    quick = "quick"
    standard = "standard"
    deep_dive = "deep_dive"


class LearningPreferences(BaseModel):
    level: EducationLevel = EducationLevel.beginner
    language: Language = Language.english
    available_time_minutes: int = Field(10, ge=1, le=120)
    objective: LearningObjective = LearningObjective.concept_understanding
    teaching_style: TeachingStyle = TeachingStyle.simple
    depth: Depth = Depth.standard
    prior_knowledge: Optional[str] = None


class LearnerProfile(BaseModel):
    learner_id: str
    name: Optional[str] = None
    preferences: LearningPreferences
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class LearnerProfileCreate(BaseModel):
    name: Optional[str] = None
    preferences: LearningPreferences = Field(default_factory=LearningPreferences)
