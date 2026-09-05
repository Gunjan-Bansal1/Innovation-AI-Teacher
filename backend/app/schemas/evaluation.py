"""
Pydantic schemas for evaluation, misconception detection, and adaptation.
"""
from typing import Optional
from pydantic import BaseModel, Field
from enum import Enum


class EvaluationStatus(str, Enum):
    correct = "correct"
    partially_correct = "partially_correct"
    incorrect = "incorrect"
    unclear = "unclear"


class Understanding(str, Enum):
    strong = "strong"
    moderate = "moderate"
    weak = "weak"
    none = "none"


class AdaptationAction(str, Enum):
    CONTINUE = "CONTINUE"
    RETEACH = "RETEACH"
    SIMPLIFY = "SIMPLIFY"
    USE_ANALOGY = "USE_ANALOGY"
    SHOW_VISUAL = "SHOW_VISUAL"
    GIVE_EXAMPLE = "GIVE_EXAMPLE"
    ASK_EASIER_QUESTION = "ASK_EASIER_QUESTION"
    INCREASE_DIFFICULTY = "INCREASE_DIFFICULTY"
    DECREASE_DIFFICULTY = "DECREASE_DIFFICULTY"


class EvaluationResult(BaseModel):
    """Output from EvaluatorAgent — validated Pydantic schema."""
    status: EvaluationStatus
    score: float = Field(ge=0.0, le=1.0)
    concept: str
    confidence: float = Field(ge=0.0, le=1.0)
    understanding: Understanding
    misconception_detected: bool
    misconception: Optional[str] = None
    recommended_action: AdaptationAction
    feedback: Optional[str] = None


class MisconceptionResult(BaseModel):
    """Output from MisconceptionAgent."""
    misconception_type: str
    explanation: str
    evidence: str
    confidence: float = Field(ge=0.0, le=1.0)
    suggested_correction: Optional[str] = None


class AdaptationDecision(BaseModel):
    """Output from AdaptationAgent — validated before execution."""
    action: AdaptationAction
    reason: str
    strategy_description: Optional[str] = None
