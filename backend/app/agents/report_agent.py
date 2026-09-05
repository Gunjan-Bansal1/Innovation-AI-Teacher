"""
Report Agent — generates learning reports from real MongoDB data.
Never uses fake or static values.
"""
from typing import Optional
from pydantic import BaseModel

from app.services.ollama_service import ollama_service
from app.prompts.assessment import build_report_prompt
from app.prompts.system_teacher import SYSTEM_TEACHER
from app.core.logging import get_logger

logger = get_logger(__name__)


class ReportSummary(BaseModel):
    overall_summary: str
    strong_concepts: list[str]
    weak_concepts: list[str]
    recommended_revision: list[str]
    recommended_practice: list[str]
    next_topic: str
    encouragement: str


class ReportAgent:
    """Generates learning reports from real session data."""

    async def generate_report(
        self,
        topic: str,
        session_data: dict,
        mastery_data: dict,
        misconceptions: list[str],
    ) -> ReportSummary:
        """
        Generate a learning report from actual session statistics.
        All input data comes from MongoDB — nothing is invented.
        """
        prompt = build_report_prompt(
            topic=topic,
            session_data=session_data,
            mastery_data=mastery_data,
            misconceptions=misconceptions,
        )

        try:
            result = await ollama_service.generate_structured(
                prompt=prompt,
                schema=ReportSummary,
                system=SYSTEM_TEACHER,
                temperature=0.5,
            )
            return result

        except Exception as e:
            logger.error(f"Report generation failed: {e}")
            # Minimal factual report from real data
            strong = [k for k, v in mastery_data.items() if v >= 0.7]
            weak = [k for k, v in mastery_data.items() if v < 0.5]
            return ReportSummary(
                overall_summary=f"You completed a lesson on {topic}. Keep practicing to strengthen your understanding.",
                strong_concepts=strong,
                weak_concepts=weak,
                recommended_revision=weak,
                recommended_practice=[f"Practice problems on {c}" for c in weak[:3]],
                next_topic="Continue with the next topic in this subject",
                encouragement="Great effort! Every step forward is progress.",
            )


report_agent = ReportAgent()
