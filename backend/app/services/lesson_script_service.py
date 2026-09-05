"""
Generates lesson video scripts with Gemma through Ollama.
"""
from typing import Optional
import json
import re

from app.services.ollama_service import ollama_service
from app.prompts.system_teacher import SYSTEM_TEACHER


class LessonScriptService:
    async def generate_topic_script(
        self,
        topic: str,
        level: str,
        language: str,
        teaching_style: str,
        duration_seconds: int,
        document_context: Optional[str] = None,
        custom_question: Optional[str] = None,
    ) -> str:
        """Ask Gemma to create a spoken teaching script for Simli, optionally grounded in uploaded document context and custom question."""
        user_focus = (custom_question or topic).strip()

        if document_context and document_context.strip():
            prompt = f"""
You are an expert AI teacher presenting a video lesson.
The learner has uploaded educational material and asked a specific question/topic to learn: "{user_focus}".

Source Material from Learner's Document:
\"\"\"
{document_context.strip()[:3500]}
\"\"\"

Lesson Parameters:
- Question/Topic to teach: {user_focus}
- Learner level: {level}
- Language: {language}
- Teaching style: {teaching_style}
- Target duration: about {duration_seconds} seconds

Requirements:
- Start warmly and naturally like an engaging human teacher addressing the question directly.
- Teach the concept progressively, using the source material from the learner's document as the foundation.
- Use one concrete example to make the explanation easy to grasp.
- Mention the visual board at least twice (e.g. refer to the diagram, comparison chart, or formula on screen).
- Explain what is shown on the visual board while speaking.
- Ask one quick question to check understanding.
- Conclude with a clear summary or revision tip.
- Write ONLY the exact words the teacher should speak.
- Do NOT include markdown, stage directions, scene labels, JSON, timestamps, or asterisks.
"""
        else:
            prompt = f"""
Create a spoken AI teacher video script.

Topic: {user_focus}
Learner level: {level}
Language: {language}
Teaching style: {teaching_style}
Target duration: about {duration_seconds} seconds

Requirements:
- Start like a human teacher.
- Explain the topic progressively.
- Use one simple example.
- Mention the visual board at least twice, such as a diagram, flow chart, comparison chart, timeline, or labeled parts.
- Explain what appears on the diagram/chart while teaching.
- Ask one quick understanding question.
- End with a short revision recommendation.
- Write only the words the teacher should speak.
- Do not include markdown, scene labels, JSON, timestamps, or bullet numbers.
"""
        script = await ollama_service.generate(
            prompt=prompt.strip(),
            system=SYSTEM_TEACHER,
            temperature=0.55,
        )
        return script.strip()

    async def generate_visual_storyboard_from_script(
        self,
        topic: str,
        script: str,
        duration_seconds: int,
    ) -> list[dict]:
        """Ask Gemma to create timed visuals from the exact spoken script."""
        prompt = f"""
Create a visual storyboard that matches this exact spoken teaching script.

Topic: {topic}
Video duration: about {duration_seconds} seconds

Spoken script:
{script}

Return only valid JSON. Do not include markdown.
JSON shape:
[
  {{
    "start": 0,
    "end": 10,
    "type": "flow",
    "title": "short title matching what is spoken in this time range",
    "description": "what should appear on the board at this moment",
    "labels": ["label 1", "label 2", "label 3"]
  }}
]

Rules:
- Create 4 to 6 visual scenes.
- Each scene must match the script order.
- Use type values from: flow, diagram, chart, recap.
- Labels must be short and visible in a video.
- Do not add concepts that are not spoken in the script.
- Cover the full duration from 0 to {duration_seconds}.
"""
        raw = await ollama_service.generate(
            prompt=prompt.strip(),
            system=SYSTEM_TEACHER,
            temperature=0.25,
        )
        return self._parse_visual_storyboard(raw, duration_seconds)

    def _parse_visual_storyboard(self, raw: str, duration_seconds: int) -> list[dict]:
        text = raw.strip()
        match = re.search(r"\[[\s\S]*\]", text)
        if match:
            text = match.group(0)

        data = json.loads(text)
        if not isinstance(data, list):
            raise ValueError("Visual storyboard JSON must be a list.")

        cleaned = []
        previous_end = 0
        allowed_types = {"flow", "diagram", "chart", "recap"}
        for index, item in enumerate(data[:6]):
            if not isinstance(item, dict):
                continue
            start = int(item.get("start", previous_end))
            end = int(item.get("end", start + max(6, duration_seconds // 5)))
            start = max(0, min(start, duration_seconds - 1))
            end = max(start + 1, min(end, duration_seconds))
            previous_end = end

            labels = item.get("labels") or []
            if not isinstance(labels, list):
                labels = []

            cleaned.append({
                "start": start,
                "end": end,
                "type": item.get("type") if item.get("type") in allowed_types else "diagram",
                "title": str(item.get("title") or f"Visual {index + 1}")[:80],
                "description": str(item.get("description") or "")[:180],
                "labels": [str(label)[:28] for label in labels[:4]],
            })

        if not cleaned:
            raise ValueError("Visual storyboard JSON did not contain any scenes.")

        cleaned[0]["start"] = 0
        cleaned[-1]["end"] = duration_seconds
        return cleaned


lesson_script_service = LessonScriptService()
