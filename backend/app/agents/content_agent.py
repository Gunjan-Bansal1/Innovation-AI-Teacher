"""
Content Agent — analyzes document/topic to extract real structure.
Never fabricates topics, chapters, or concepts.
"""
from typing import Optional
from pydantic import BaseModel

from app.services.ollama_service import ollama_service
from app.prompts.misconception import build_content_analysis_prompt
from app.prompts.system_teacher import SYSTEM_PLANNER
from app.core.logging import get_logger

logger = get_logger(__name__)


class ConceptInfo(BaseModel):
    key: str
    name: str
    description: str


class ContentAnalysis(BaseModel):
    subject: str
    main_topics: list[str]
    concepts: list[ConceptInfo]
    difficulty_level: str
    document_type: str


class ContentAgent:
    """Analyzes document content to extract genuine educational structure."""

    async def analyze_document(
        self,
        text_sample: str,
        filename: str,
        chapters: list[str],
        sections: list[str],
        focus_question: Optional[str] = None,
    ) -> ContentAnalysis:
        """
        Extract real topics and concepts from document text.
        Returns only what is genuinely present — never fabricates.
        """
        prompt = build_content_analysis_prompt(text_sample, filename, focus_question=focus_question)

        try:
            result = await ollama_service.generate_structured(
                prompt=prompt,
                schema=ContentAnalysis,
                system=SYSTEM_PLANNER,
                temperature=0.2,
            )
            logger.info(
                "Content analysis complete",
                extra={
                    "doc_filename": filename,
                    "topics": len(result.main_topics),
                    "concepts": len(result.concepts),
                },
            )
            return result

        except Exception as e:
            logger.error(f"Content analysis failed: {e}")
            # Return minimal structure from what we can detect
            return ContentAnalysis(
                subject="general",
                main_topics=chapters[:10] if chapters else ["General Content"],
                concepts=[],
                difficulty_level="intermediate",
                document_type="other",
            )

    async def analyze_topic(self, topic: str, level: str) -> ContentAnalysis:
        """
        For topic-based learning (no document), infer subject and concepts.
        Gemma uses its own knowledge — clearly not document-backed.
        """
        prompt = f"""For the topic "{topic}" at {level} level, identify:
1. Subject area
2. Main sub-topics
3. Key concepts (with simple identifiers)

{build_content_analysis_prompt(f"Topic: {topic}", "user-entered-topic")}"""

        try:
            return await ollama_service.generate_structured(
                prompt=prompt,
                schema=ContentAnalysis,
                system=SYSTEM_PLANNER,
                temperature=0.2,
            )
        except Exception as e:
            logger.error(f"Topic analysis failed: {e}")
            return ContentAnalysis(
                subject="general",
                main_topics=[topic],
                concepts=[
                    ConceptInfo(
                        key=topic.lower().replace(" ", "_"),
                        name=topic,
                        description=f"Core concept: {topic}",
                    )
                ],
                difficulty_level=level,
                document_type="other",
            )


content_agent = ContentAgent()
