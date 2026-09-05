"""
Lesson Planner Agent — generates structured lesson plans using gemma4:31b-cloud.

Output is validated against LessonPlan Pydantic schema.
Gemma proposes — FastAPI validates and controls.
"""
from typing import Optional

from app.services.ollama_service import ollama_service, OllamaStructuredOutputError
from app.schemas.lesson import LessonPlan
from app.schemas.learner import LearnerProfile
from app.prompts.lesson_planner import build_lesson_planner_prompt
from app.prompts.system_teacher import SYSTEM_PLANNER
from app.core.logging import get_logger

logger = get_logger(__name__)


class LessonPlannerAgent:
    """Creates structured lesson plans validated by Pydantic."""

    async def plan_lesson(
        self,
        topic: str,
        subject: str,
        profile: LearnerProfile,
        source_context: str,
        selected_concepts: list[str],
    ) -> LessonPlan:
        """
        Generate a lesson plan for the given topic and learner profile.

        Uses Gemma to propose segments — validates with Pydantic.
        Retries are handled inside ollama_service.generate_structured.
        """
        prefs = profile.preferences

        prompt = build_lesson_planner_prompt(
            topic=topic,
            subject=subject,
            level=prefs.level.value,
            language=prefs.language.value,
            teaching_style=prefs.teaching_style.value,
            depth=prefs.depth.value,
            available_time_minutes=prefs.available_time_minutes,
            prior_knowledge=prefs.prior_knowledge or "",
            source_context=source_context,
            selected_concepts=selected_concepts,
        )

        try:
            lesson_plan = await ollama_service.generate_structured(
                prompt=prompt,
                schema=LessonPlan,
                system=SYSTEM_PLANNER,
                temperature=0.3,
            )
            logger.info(
                "Lesson plan created",
                extra={
                    "topic": topic,
                    "segments": len(lesson_plan.segments),
                    "duration_seconds": lesson_plan.duration_seconds,
                },
            )
            return lesson_plan

        except OllamaStructuredOutputError as e:
            logger.error(f"Lesson planning failed: {e}")
            # Return minimal fallback lesson plan
            return self._fallback_plan(
                topic=topic,
                language=prefs.language.value,
                teaching_style=prefs.teaching_style.value,
                available_time_minutes=prefs.available_time_minutes,
                selected_concepts=selected_concepts,
            )

    def _fallback_plan(
        self,
        topic: str,
        language: str,
        teaching_style: str,
        available_time_minutes: int,
        selected_concepts: list[str],
    ) -> LessonPlan:
        """Minimal valid lesson plan if Gemma fails."""
        available_seconds = available_time_minutes * 60
        concept_keys = [c.lower().replace(" ", "_") for c in selected_concepts] or [
            topic.lower().replace(" ", "_")
        ]

        segments = [
            {"type": "introduction", "title": f"Introduction to {topic}", "duration_seconds": 60},
        ]
        per_concept = max(60, (available_seconds - 180) // max(len(concept_keys), 1))
        for ck in concept_keys:
            segments.append({
                "type": "concept",
                "title": ck.replace("_", " ").title(),
                "concept_key": ck,
                "duration_seconds": per_concept,
            })
            segments.append({
                "type": "question",
                "title": f"Check: {ck.replace('_', ' ').title()}",
                "concept_key": ck,
                "duration_seconds": 60,
                "question_type": "mcq",
            })

        segments.append({"type": "summary", "title": "Summary", "duration_seconds": 60})
        segments.append({
            "type": "assessment",
            "title": "Final Assessment",
            "duration_seconds": 120,
            "question_count": 3,
        })

        return LessonPlan(
            title=f"Learning {topic}",
            topic=topic,
            duration_seconds=available_seconds,
            language=language,
            teaching_style=teaching_style,
            concept_keys=concept_keys,
            learning_objectives=[f"Understand {topic}"],
            segments=segments,
        )


lesson_planner_agent = LessonPlannerAgent()
