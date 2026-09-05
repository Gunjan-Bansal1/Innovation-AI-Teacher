"""
Misconception Agent — identifies WHY a student is wrong.

This is the core of adaptive teaching.
Does not simply say "Wrong." — identifies the root cause belief.
Uses "unclear" when evidence is insufficient.
Never invents misconceptions.
"""
from typing import Optional
from pydantic import BaseModel

from app.services.ollama_service import ollama_service
from app.schemas.evaluation import MisconceptionResult
from app.prompts.misconception import build_misconception_prompt
from app.prompts.system_teacher import SYSTEM_EVALUATOR
from app.rag.retriever import retrieve_context
from app.core.logging import get_logger

logger = get_logger(__name__)


class MisconceptionAgent:
    """Root-cause analysis for wrong student answers."""

    async def analyze(
        self,
        question: dict,
        student_answer: str,
        concept_key: str,
        topic: str,
        document_id: Optional[str],
    ) -> MisconceptionResult:
        """
        Identify the specific misconception in a wrong answer.

        Returns MisconceptionResult with explanation and evidence.
        If evidence is weak, returns type='unclear'.
        Never fabricates student misconceptions.
        """
        # Retrieve context for grounding the analysis
        source_context = ""
        if document_id:
            ctx = await retrieve_context(
                query=f"{concept_key} {topic}",
                document_id=document_id,
                top_k=3,
            )
            source_context = ctx["context_text"]

        prompt = build_misconception_prompt(
            question_text=question.get("question_text", ""),
            correct_answer=question.get("correct_answer", ""),
            student_answer=student_answer,
            concept_key=concept_key,
            topic=topic,
            source_context=source_context,
        )

        try:
            result = await ollama_service.generate_structured(
                prompt=prompt,
                schema=MisconceptionResult,
                system=SYSTEM_EVALUATOR,
                temperature=0.2,
            )
            logger.info(
                "Misconception identified",
                extra={
                    "type": result.misconception_type,
                    "confidence": result.confidence,
                    "concept": concept_key,
                },
            )
            return result

        except Exception as e:
            logger.error(f"Misconception analysis failed: {e}")
            # Safe fallback — unclear rather than invented
            return MisconceptionResult(
                misconception_type="unclear",
                explanation="The specific misconception could not be determined with confidence.",
                evidence=f"Student answered: {student_answer[:100]}",
                confidence=0.0,
                suggested_correction=None,
            )


misconception_agent = MisconceptionAgent()
