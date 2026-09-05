"""
Question Agent — generates questions for comprehension checks.

Supports: MCQ, Conceptual, Short Answer, Problem Solving, Application, Explain in Own Words.
When question appears: session status must be set to waiting_for_answer by orchestrator.
"""
import json
from typing import Optional
from pydantic import BaseModel

from app.services.ollama_service import ollama_service
from app.schemas.assessment import QuestionType, Difficulty
from app.prompts.question_generator import build_question_prompt, build_easier_question_prompt
from app.prompts.system_teacher import SYSTEM_TEACHER
from app.rag.retriever import retrieve_context
from app.core.logging import get_logger

logger = get_logger(__name__)


class GeneratedQuestion(BaseModel):
    question_text: str
    question_type: str
    difficulty: str = "medium"
    concept_key: str
    options: Optional[list[str]] = None
    correct_answer: str
    evaluation_criteria: str


class QuestionAgent:
    """Generates contextual questions for teaching segments."""

    async def generate_question(
        self,
        concept_key: str,
        topic: str,
        question_type: str,
        level: str,
        language: str,
        document_id: Optional[str],
        previous_questions: list[str],
    ) -> GeneratedQuestion:
        """Generate a comprehension question for a concept."""
        # Retrieve source context for grounding
        source_context = ""
        if document_id:
            ctx = await retrieve_context(
                query=f"{concept_key} {topic}",
                document_id=document_id,
                top_k=3,
            )
            source_context = ctx["context_text"]

        prompt = build_question_prompt(
            concept_key=concept_key,
            topic=topic,
            question_type=question_type,
            level=level,
            language=language,
            source_context=source_context,
            previous_questions=previous_questions,
        )

        try:
            result = await ollama_service.generate_structured(
                prompt=prompt,
                schema=GeneratedQuestion,
                system=SYSTEM_TEACHER,
                temperature=0.5,
            )
            result.concept_key = concept_key  # Ensure correct concept key
            return result

        except Exception as e:
            logger.error(f"Question generation failed: {e}")
            # Fallback: generate a simple MCQ manually
            return GeneratedQuestion(
                question_text=f"Which of the following best describes {concept_key.replace('_', ' ')}?",
                question_type="mcq",
                difficulty="medium",
                concept_key=concept_key,
                options=[
                    "A. A fundamental concept in this topic",
                    "B. An unrelated concept",
                    "C. A measurement unit",
                    "D. None of the above",
                ],
                correct_answer="A. A fundamental concept in this topic",
                evaluation_criteria="Student understands the basic definition",
            )

    async def generate_easier_question(
        self,
        concept_key: str,
        topic: str,
        level: str,
        language: str,
        original_question: str,
        document_id: Optional[str],
    ) -> GeneratedQuestion:
        """Generate a simpler version after a wrong answer."""
        source_context = ""
        if document_id:
            ctx = await retrieve_context(
                query=f"{concept_key} {topic}",
                document_id=document_id,
                top_k=3,
            )
            source_context = ctx["context_text"]

        prompt = build_easier_question_prompt(
            concept_key=concept_key,
            topic=topic,
            level=level,
            language=language,
            original_question=original_question,
            source_context=source_context,
        )

        try:
            result = await ollama_service.generate_structured(
                prompt=prompt,
                schema=GeneratedQuestion,
                system=SYSTEM_TEACHER,
                temperature=0.4,
            )
            result.concept_key = concept_key
            return result
        except Exception as e:
            logger.error(f"Easier question generation failed: {e}")
            return GeneratedQuestion(
                question_text=f"Can you tell me the basic definition of {concept_key.replace('_', ' ')}?",
                question_type="short_answer",
                difficulty="easy",
                concept_key=concept_key,
                options=None,
                correct_answer="Basic definition of the concept",
                evaluation_criteria="Student can state a basic definition",
            )


question_agent = QuestionAgent()
