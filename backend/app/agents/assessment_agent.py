"""
Assessment Agent — generates final assessment from actually-taught concepts.
"""
import uuid
from typing import Optional
from pydantic import BaseModel

from app.services.ollama_service import ollama_service
from app.schemas.assessment import Assessment, AssessmentQuestion, QuestionType, Difficulty
from app.prompts.assessment import build_assessment_prompt
from app.prompts.system_teacher import SYSTEM_PLANNER
from app.rag.retriever import retrieve_context
from app.core.logging import get_logger

logger = get_logger(__name__)


class AssessmentQuestionsOutput(BaseModel):
    questions: list[dict]


class AssessmentAgent:
    """Generates final assessments from actually-taught concepts only."""

    async def generate_assessment(
        self,
        session_id: str,
        lesson_id: str,
        taught_concepts: list[str],
        topic: str,
        level: str,
        language: str,
        question_count: int,
        document_id: Optional[str],
    ) -> Assessment:
        """
        Generate a final assessment. Only tests concepts that were taught.
        Never generates questions about untaught material.
        """
        # Retrieve context for grounding
        source_context = ""
        if document_id and taught_concepts:
            query = " ".join(taught_concepts[:3]) + " " + topic
            ctx = await retrieve_context(
                query=query,
                document_id=document_id,
                top_k=5,
            )
            source_context = ctx["context_text"]

        prompt = build_assessment_prompt(
            taught_concepts=taught_concepts,
            topic=topic,
            level=level,
            language=language,
            question_count=question_count,
            source_context=source_context,
        )

        try:
            raw_output = await ollama_service.generate_structured(
                prompt=prompt,
                schema=AssessmentQuestionsOutput,
                system=SYSTEM_PLANNER,
                temperature=0.3,
            )

            questions = []
            for i, q_dict in enumerate(raw_output.questions[:question_count]):
                qtype = q_dict.get("question_type", "mcq")
                diff = q_dict.get("difficulty", "medium")

                # Validate type
                try:
                    qt = QuestionType(qtype)
                except ValueError:
                    qt = QuestionType.mcq

                # Validate difficulty
                try:
                    d = Difficulty(diff)
                except ValueError:
                    d = Difficulty.medium

                questions.append(AssessmentQuestion(
                    question_id=q_dict.get("question_id", f"q{i+1}"),
                    question_text=q_dict.get("question_text", f"Question {i+1}"),
                    question_type=qt,
                    difficulty=d,
                    concept_key=q_dict.get("concept_key", taught_concepts[0] if taught_concepts else "general"),
                    options=q_dict.get("options"),
                    correct_answer=q_dict.get("correct_answer", ""),
                    evaluation_criteria=q_dict.get("evaluation_criteria", ""),
                ))

        except Exception as e:
            logger.error(f"Assessment generation failed: {e}")
            questions = self._fallback_questions(taught_concepts, topic, language)

        assessment_id = str(uuid.uuid4())
        return Assessment(
            assessment_id=assessment_id,
            session_id=session_id,
            lesson_id=lesson_id,
            questions=questions,
            total_questions=len(questions),
        )

    def _fallback_questions(
        self, taught_concepts: list[str], topic: str, language: str
    ) -> list[AssessmentQuestion]:
        """Minimal questions if generation fails."""
        questions = []
        for i, concept in enumerate(taught_concepts[:3]):
            questions.append(AssessmentQuestion(
                question_id=f"q{i+1}",
                question_text=f"Explain {concept.replace('_', ' ')} in your own words.",
                question_type=QuestionType.explain_own_words,
                difficulty=Difficulty.medium,
                concept_key=concept,
                options=None,
                correct_answer=f"Accurate explanation of {concept.replace('_', ' ')}",
                evaluation_criteria="Student demonstrates basic understanding of the concept",
            ))
        return questions or [
            AssessmentQuestion(
                question_id="q1",
                question_text=f"What did you learn about {topic}?",
                question_type=QuestionType.explain_own_words,
                difficulty=Difficulty.easy,
                concept_key=topic.lower().replace(" ", "_"),
                options=None,
                correct_answer="Accurate summary of main concepts",
                evaluation_criteria="Student demonstrates understanding of the topic",
            )
        ]


assessment_agent = AssessmentAgent()
