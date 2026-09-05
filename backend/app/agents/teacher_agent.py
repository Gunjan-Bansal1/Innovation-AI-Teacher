"""
Teacher Agent — generates per-segment teaching content.

For document-backed sessions: retrieves source context BEFORE generating.
If retrieval is insufficient: does NOT invent content — returns a clear limitation.
"""
import json
from typing import Optional

from app.services.ollama_service import ollama_service
from app.schemas.session import TeacherOutput, BoardContent, BoardType
from app.prompts.teaching import (
    build_teaching_prompt,
    build_analogy_prompt,
    build_simplify_prompt,
)
from app.prompts.system_teacher import SYSTEM_TEACHER
from app.rag.retriever import retrieve_context, retrieve_topic_context, INSUFFICIENT_EVIDENCE_MSG
from app.core.logging import get_logger

logger = get_logger(__name__)


import re


class TeacherAgent:
    """Generates segment-by-segment teaching content."""

    async def teach_segment(
        self,
        segment: dict,
        topic: str,
        level: str,
        language: str,
        teaching_style: str,
        document_id: Optional[str],
        prior_segments_summary: str,
        strategy_hint: Optional[str] = None,
    ) -> TeacherOutput:
        """
        Generate teaching content for a lesson segment.
        Always retrieves source context first for document-backed sessions.
        """
        segment_type = segment.get("type", "concept")
        segment_title = segment.get("title", topic)
        concept_key = segment.get("concept_key")

        # Retrieve source context
        retrieval_query = f"{topic} {segment_title} {concept_key or ''}"
        if document_id:
            context_result = await retrieve_context(
                query=retrieval_query,
                document_id=document_id,
                top_k=4,
            )
        else:
            context_result = await retrieve_topic_context(
                query=retrieval_query,
                document_id=None,
            )

        source_context = context_result["context_text"]
        source_refs = context_result["source_refs"]

        # Choose prompt based on strategy
        if strategy_hint == "analogy":
            prompt = build_analogy_prompt(
                concept=concept_key or segment_title,
                misconception=None,
                level=level,
                language=language,
                topic=topic,
            )
        elif strategy_hint == "simplify":
            prompt = build_simplify_prompt(
                concept=concept_key or segment_title,
                previous_explanation=prior_segments_summary,
                level=level,
                language=language,
            )
        else:
            prompt = build_teaching_prompt(
                segment_type=segment_type,
                segment_title=segment_title,
                topic=topic,
                concept_key=concept_key,
                level=level,
                language=language,
                teaching_style=teaching_style,
                source_context=source_context,
                prior_segments_summary=prior_segments_summary,
                strategy_hint=strategy_hint,
            )

        try:
            raw = await ollama_service.generate(
                prompt=prompt,
                system=SYSTEM_TEACHER,
                temperature=0.6,
            )

            # Parse JSON output
            output_data = self._parse_teacher_output(raw)
            output_data["source_refs"] = source_refs

            board_data = output_data.get("board")
            board = None
            if board_data and isinstance(board_data, dict):
                try:
                    board_type = BoardType(board_data.get("type", "text"))
                    content = board_data.get("content", "")
                    # If content is a list (for bullets/key_takeaways), serialize it
                    if isinstance(content, list):
                        content = json.dumps(content)
                    board = BoardContent(
                        type=board_type,
                        content=str(content),
                        caption=board_data.get("caption"),
                        language=board_data.get("language"),
                    )
                except Exception as e:
                    logger.warning(f"Board parsing failed: {e}")

            return TeacherOutput(
                spoken_text=output_data.get("spoken_text", segment_title),
                board=board,
                source_refs=source_refs,
                segment_type=segment_type,
                segment_title=segment_title,
            )

        except Exception as e:
            logger.error(f"Teacher agent error: {e}")
            return TeacherOutput(
                spoken_text=f"Let me explain {segment_title}. {INSUFFICIENT_EVIDENCE_MSG if document_id else 'I will teach this from general knowledge.'}",
                board=None,
                source_refs=[],
                segment_type=segment_type,
                segment_title=segment_title,
            )

    def _parse_teacher_output(self, raw: str) -> dict:
        """Parse Gemma JSON output with cleanup and resilient fallback extraction."""
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            if len(lines) > 2:
                cleaned = "\n".join(lines[1:-1]).strip()

        # Find outer JSON object boundaries
        start = cleaned.find("{")
        end = cleaned.rfind("}") + 1
        if start >= 0 and end > start:
            json_candidate = cleaned[start:end]
            try:
                return json.loads(json_candidate)
            except Exception:
                # Try fixing literal unescaped control chars / newlines inside strings
                try:
                    fixed_candidate = json_candidate.replace('\r\n', '\\n').replace('\n', '\\n').replace('\t', '\\t')
                    return json.loads(fixed_candidate)
                except Exception:
                    pass

        # Resilient Regex fallback extraction
        data = {}
        spoken_match = re.search(r'"spoken_text"\s*:\s*"((?:[^"\\]|\\.)*)"', cleaned, re.DOTALL)
        if spoken_match:
            try:
                data["spoken_text"] = spoken_match.group(1).encode('utf-8').decode('unicode_escape')
            except Exception:
                data["spoken_text"] = spoken_match.group(1)
        else:
            spoken_match_unclosed = re.search(r'"spoken_text"\s*:\s*"(.*?)(?=",\s*"|"\s*\})', cleaned, re.DOTALL)
            if spoken_match_unclosed:
                data["spoken_text"] = spoken_match_unclosed.group(1)

        board_type_match = re.search(r'"type"\s*:\s*"([^"]+)"', cleaned)
        board_content_match = re.search(r'"content"\s*:\s*("(?:[^"\\]|\\.)*"|\[.*?\]|\{.*?\})', cleaned, re.DOTALL)
        board_caption_match = re.search(r'"caption"\s*:\s*"([^"]*)"', cleaned)
        board_lang_match = re.search(r'"language"\s*:\s*"([^"]*)"', cleaned)

        if board_type_match or board_content_match:
            b_type = board_type_match.group(1) if board_type_match else "text"
            b_content = ""
            if board_content_match:
                raw_c = board_content_match.group(1)
                try:
                    b_content = json.loads(raw_c)
                except Exception:
                    b_content = raw_c.strip('"')
            data["board"] = {
                "type": b_type,
                "content": b_content,
                "caption": board_caption_match.group(1) if board_caption_match else "",
                "language": board_lang_match.group(1) if board_lang_match else None,
            }

        if not data.get("spoken_text") and not data.get("board"):
            cleaned_prose = re.sub(r'[\{\}"\[\]]', '', cleaned).strip()
            data["spoken_text"] = cleaned_prose or "Here is the explanation for this segment."

        return data


teacher_agent = TeacherAgent()
