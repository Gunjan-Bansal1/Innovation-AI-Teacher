"""
Lesson planner prompt templates.
"""


def build_lesson_planner_prompt(
    topic: str,
    subject: str,
    level: str,
    language: str,
    teaching_style: str,
    depth: str,
    available_time_minutes: int,
    prior_knowledge: str,
    source_context: str,
    selected_concepts: list[str],
) -> str:
    available_seconds = available_time_minutes * 60
    concepts_str = ", ".join(selected_concepts) if selected_concepts else "all relevant concepts"
    prior_str = f"Prior knowledge: {prior_knowledge}" if prior_knowledge else "No stated prior knowledge."

    context_section = ""
    if source_context:
        context_section = f"""
SOURCE MATERIAL (use this — do not invent):
{source_context[:3000]}
"""

    return f"""Create a lesson plan for teaching: "{topic}"

STUDENT PROFILE:
- Level: {level}
- Language: {language}
- Teaching style: {teaching_style}
- Depth: {depth}
- Available time: {available_time_minutes} minutes ({available_seconds} seconds)
- {prior_str}

CONCEPTS TO COVER: {concepts_str}
SUBJECT: {subject if subject else "general"}
{context_section}

SEGMENT TYPES AVAILABLE:
introduction, concept, example, analogy, formula, diagram, graph, code, question, reteach, summary, assessment

REQUIREMENTS:
1. Total duration_seconds must be approximately {available_seconds} seconds (±20%)
2. Include at least 1-2 "question" segments for comprehension checks
3. Include "reteach" segments as fallback for difficult concepts
4. Include a "summary" near the end
5. Include an "assessment" at the very end
6. concept_key must be simple snake_case (e.g., "ohms_law", "electric_current")
7. Each segment duration must be realistic (minimum 30 seconds)

Respond with this exact JSON structure:
{{
  "title": "string — lesson title",
  "topic": "string",
  "subject": "string or null",
  "duration_seconds": {available_seconds},
  "language": "{language}",
  "teaching_style": "{teaching_style}",
  "concept_keys": ["list", "of", "concept_keys"],
  "learning_objectives": ["list of what student will learn"],
  "segments": [
    {{
      "type": "introduction",
      "title": "string",
      "duration_seconds": 60
    }},
    {{
      "type": "concept",
      "title": "string",
      "concept_key": "snake_case_key",
      "duration_seconds": 120,
      "description": "brief description"
    }},
    ...more segments...
    {{
      "type": "assessment",
      "title": "Final Assessment",
      "duration_seconds": 120,
      "question_count": 5
    }}
  ]
}}"""
