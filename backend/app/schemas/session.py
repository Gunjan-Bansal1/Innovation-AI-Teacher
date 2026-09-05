"""
Pydantic schemas for learning sessions.
"""
from typing import Optional, Any
from pydantic import BaseModel, Field
from enum import Enum
from datetime import datetime


class SessionStatus(str, Enum):
    initializing = "initializing"
    teaching = "teaching"
    waiting_for_answer = "waiting_for_answer"
    evaluating = "evaluating"
    adapting = "adapting"
    reteaching = "reteaching"
    assessment = "assessment"
    completed = "completed"
    paused = "paused"
    error = "error"


class BoardType(str, Enum):
    text = "text"
    bullets = "bullets"
    formula = "formula"
    mermaid = "mermaid"
    code = "code"
    key_takeaways = "key_takeaways"
    timeline = "timeline"
    table = "table"
    image_description = "image_description"
    steps = "steps"  # ordered step-by-step working (math/problem solving)


class BoardContent(BaseModel):
    type: BoardType
    content: str
    caption: Optional[str] = None
    language: Optional[str] = None  # for code blocks


class TeacherOutput(BaseModel):
    spoken_text: str
    board: Optional[BoardContent] = None
    source_refs: list[dict] = Field(default_factory=list)
    segment_type: Optional[str] = None
    segment_title: Optional[str] = None
    # Avatar video — best-effort. None means the client should keep showing
    # the idle avatar loop instead of a talking clip (never blocks teaching).
    avatar_video_url: Optional[str] = None
    avatar_status: str = "disabled"  # disabled | generating_failed | timeout | generated


class SessionState(BaseModel):
    session_id: str
    learner_id: str
    lesson_id: str
    status: SessionStatus
    current_segment_index: int = 0
    total_segments: int = 0
    current_concept: Optional[str] = None
    teacher_output: Optional[TeacherOutput] = None
    current_question: Optional[dict] = None
    adaptation_message: Optional[str] = None
    mastery_snapshot: dict[str, float] = Field(default_factory=dict)
    elapsed_seconds: int = 0
    progress_pct: float = 0.0
    language: str = "english"
    last_strategy_used: Optional[str] = None


class SessionCreate(BaseModel):
    learner_id: str
    lesson_id: str


class AnswerSubmit(BaseModel):
    answer: str = Field(min_length=1, max_length=2000)
    time_taken_seconds: Optional[int] = None


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)


class SwitchLanguageRequest(BaseModel):
    language: str = Field(pattern="^(english|hindi|hinglish)$")
