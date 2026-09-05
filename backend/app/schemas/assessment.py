"""
Pydantic schemas for assessments and results.
"""
from typing import Optional
from pydantic import BaseModel, Field
from enum import Enum


class QuestionType(str, Enum):
    mcq = "mcq"
    short_answer = "short_answer"
    conceptual = "conceptual"
    application = "application"
    problem_solving = "problem_solving"
    explain_own_words = "explain_own_words"


class Difficulty(str, Enum):
    easy = "easy"
    medium = "medium"
    hard = "hard"


class AssessmentQuestion(BaseModel):
    question_id: str
    question_text: str
    question_type: QuestionType
    difficulty: Difficulty = Difficulty.medium
    concept_key: str
    options: Optional[list[str]] = None  # For MCQ
    correct_answer: Optional[str] = None
    evaluation_criteria: Optional[str] = None


class Assessment(BaseModel):
    assessment_id: str
    session_id: str
    lesson_id: str
    questions: list[AssessmentQuestion]
    total_questions: int
    created_at: Optional[str] = None


class StudentAnswerRecord(BaseModel):
    question_id: str
    student_answer: str
    time_taken_seconds: Optional[int] = None


class AssessmentSubmit(BaseModel):
    answers: list[StudentAnswerRecord]


class QuestionResult(BaseModel):
    question_id: str
    question_text: str
    student_answer: str
    correct_answer: Optional[str] = None
    score: float = Field(ge=0.0, le=1.0)
    status: str
    feedback: str
    concept_key: str


class AssessmentResult(BaseModel):
    assessment_id: str
    session_id: str
    total_score: float = Field(ge=0.0, le=1.0)
    total_questions: int
    correct_count: int
    partial_count: int
    incorrect_count: int
    question_results: list[QuestionResult]
    concept_scores: dict[str, float] = Field(default_factory=dict)
    grade: Optional[str] = None
