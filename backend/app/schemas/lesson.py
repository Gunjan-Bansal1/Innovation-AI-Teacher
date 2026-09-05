"""
Pydantic schemas for lesson plans and segments.
"""
from typing import Optional, Union, Literal
from pydantic import BaseModel, Field, model_validator


class IntroductionSegment(BaseModel):
    type: Literal["introduction"]
    title: str
    duration_seconds: int = Field(ge=10)
    key_points: list[str] = Field(default_factory=list)


class ConceptSegment(BaseModel):
    type: Literal["concept"]
    title: str
    concept_key: str
    duration_seconds: int = Field(ge=10)
    description: Optional[str] = None


class ExampleSegment(BaseModel):
    type: Literal["example"]
    title: str
    duration_seconds: int = Field(ge=10)
    example_description: Optional[str] = None


class AnalogySegment(BaseModel):
    type: Literal["analogy"]
    title: str
    duration_seconds: int = Field(ge=10)
    analogy_description: Optional[str] = None


class FormulaSegment(BaseModel):
    type: Literal["formula"]
    title: str
    duration_seconds: int = Field(ge=10)
    formula: Optional[str] = None


class DiagramSegment(BaseModel):
    type: Literal["diagram"]
    title: str
    duration_seconds: int = Field(ge=10)
    diagram_description: Optional[str] = None


class GraphSegment(BaseModel):
    type: Literal["graph"]
    title: str
    duration_seconds: int = Field(ge=10)
    graph_description: Optional[str] = None


class CodeSegment(BaseModel):
    type: Literal["code"]
    title: str
    duration_seconds: int = Field(ge=10)
    language: Optional[str] = "python"


class QuestionSegment(BaseModel):
    type: Literal["question"]
    title: str
    duration_seconds: int = Field(ge=10)
    question_type: Optional[str] = "mcq"
    concept_key: Optional[str] = None


class ReteachSegment(BaseModel):
    type: Literal["reteach"]
    title: str
    duration_seconds: int = Field(ge=10)
    concept_key: Optional[str] = None
    strategy: Optional[str] = None


class SummarySegment(BaseModel):
    type: Literal["summary"]
    title: str
    duration_seconds: int = Field(ge=10)


class AssessmentSegment(BaseModel):
    type: Literal["assessment"]
    title: str
    duration_seconds: int = Field(ge=30)
    question_count: int = Field(default=5, ge=1, le=20)


AnySegment = Union[
    IntroductionSegment,
    ConceptSegment,
    ExampleSegment,
    AnalogySegment,
    FormulaSegment,
    DiagramSegment,
    GraphSegment,
    CodeSegment,
    QuestionSegment,
    ReteachSegment,
    SummarySegment,
    AssessmentSegment,
]


class LessonPlan(BaseModel):
    """
    Validated lesson plan produced by LessonPlannerAgent.
    Total duration is enforced by the backend.
    """
    title: str
    topic: str
    subject: Optional[str] = None
    duration_seconds: int = Field(ge=60)
    language: str = "english"
    teaching_style: str = "simple"
    segments: list[dict] = Field(default_factory=list)  # raw dicts from Gemma
    concept_keys: list[str] = Field(default_factory=list)
    learning_objectives: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_duration(self) -> "LessonPlan":
        if self.segments:
            total = sum(s.get("duration_seconds", 60) for s in self.segments)
            # Allow ±20% variance from declared duration
            tolerance = self.duration_seconds * 0.20
            if abs(total - self.duration_seconds) > tolerance + 60:
                # Correct the total rather than rejecting
                self.duration_seconds = total
        return self


class LessonPlanCreate(BaseModel):
    learner_id: str
    topic: str
    document_id: Optional[str] = None
    selected_concepts: Optional[list[str]] = None
    preferences_override: Optional[dict] = None
