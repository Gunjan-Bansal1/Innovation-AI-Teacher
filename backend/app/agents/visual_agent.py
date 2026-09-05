"""
Visual Agent — generates subject-aware visuals for the Smart Board.

Supported renderers:
- mermaid: Mermaid.js diagram syntax
- formula: Math notation (LaTeX/plain)
- code: Runnable code snippet
- timeline: Year/event timeline
- table: Markdown table
- text: Plain description
"""
import json
from typing import Optional
from pydantic import BaseModel

from app.services.ollama_service import ollama_service
from app.schemas.session import BoardContent, BoardType
from app.prompts.system_teacher import SYSTEM_TEACHER
from app.core.logging import get_logger

logger = get_logger(__name__)

ALLOWED_RENDERERS = {"mermaid", "formula", "code", "text", "bullets", "timeline", "table", "key_takeaways"}


class VisualOutput(BaseModel):
    visual_type: str
    renderer: str
    content: str
    reason: str
    caption: Optional[str] = None


class VisualAgent:
    """Generates subject-appropriate visuals for the Smart Board."""

    SUBJECT_VISUAL_HINTS = {
        "physics": ["formula", "mermaid", "table"],
        "mathematics": ["formula", "code", "table"],
        "biology": ["mermaid", "bullets", "text"],
        "chemistry": ["formula", "mermaid", "table"],
        "history": ["timeline", "table", "text"],
        "programming": ["code", "mermaid", "text"],
        "geography": ["table", "text", "mermaid"],
        "general": ["bullets", "text", "mermaid"],
    }

    async def generate_visual(
        self,
        concept: str,
        topic: str,
        subject: str,
        level: str,
        language: str,
        source_context: str,
    ) -> Optional[BoardContent]:
        """Generate the most appropriate visual for a concept."""
        subject_lower = subject.lower() if subject else "general"
        preferred_renderers = self.SUBJECT_VISUAL_HINTS.get(
            subject_lower,
            self.SUBJECT_VISUAL_HINTS["general"],
        )

        context_section = ""
        if source_context and len(source_context) > 50:
            context_section = f"\nSOURCE CONTEXT:\n{source_context[:1200]}\n"

        prompt = f"""Generate an appropriate visual/diagram for teaching: {concept}
Topic: {topic}, Subject: {subject}, Level: {level}, Language: {language}

Preferred renderers for {subject}: {preferred_renderers}

RENDERER OPTIONS:
- mermaid: Use for process flows, relationships, hierarchies
- formula: Use for mathematical/physics equations
- code: Use for programming concepts  
- timeline: Use for historical sequences (JSON array of {{year, event}})
- table: Use for comparisons (markdown table format)
- bullets: Use for key points (JSON array of strings)
- text: Use for descriptive visuals
{context_section}

RESPOND WITH THIS EXACT JSON:
{{
  "visual_type": "diagram|formula|code|timeline|table|list|description",
  "renderer": "one of: mermaid|formula|code|timeline|table|bullets|text",
  "content": "the actual content to render",
  "reason": "why this visual type was chosen",
  "caption": "descriptive label for the visual"
}}"""

        try:
            result = await ollama_service.generate_structured(
                prompt=prompt,
                schema=VisualOutput,
                system=SYSTEM_TEACHER,
                temperature=0.4,
            )

            # Validate renderer is allowed
            if result.renderer not in ALLOWED_RENDERERS:
                result.renderer = "text"

            content = result.content
            if isinstance(content, list):
                content = json.dumps(content)

            return BoardContent(
                type=BoardType(result.renderer) if result.renderer in BoardType._value2member_map_ else BoardType.text,
                content=str(content),
                caption=result.caption,
            )

        except Exception as e:
            logger.error(f"Visual agent error: {e}")
            return None


visual_agent = VisualAgent()
