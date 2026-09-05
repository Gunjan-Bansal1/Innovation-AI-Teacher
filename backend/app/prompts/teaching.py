"""
Teaching segment prompt templates.
"""
from typing import Optional


def build_teaching_prompt(
    segment_type: str,
    segment_title: str,
    topic: str,
    concept_key: Optional[str],
    level: str,
    language: str,
    teaching_style: str,
    source_context: str,
    prior_segments_summary: str,
    strategy_hint: Optional[str] = None,
) -> str:
    """Build a prompt for a teaching segment."""

    context_section = ""
    if source_context and source_context != "The uploaded material does not provide enough information to explain this confidently.":
        context_section = f"""
SOURCE MATERIAL (base your explanation on this — do not invent):
{source_context[:2500]}
"""
    else:
        context_section = "\nNO source material provided — use your general knowledge. Clearly indicate when explaining from general knowledge.\n"

    style_instructions = {
        "simple": "Use plain language. Avoid jargon. Short sentences. One idea at a time.",
        "visual": "Describe things visually. Use spatial metaphors. Suggest what a diagram would show.",
        "practical": "Focus on real-world applications. Give hands-on examples.",
        "technical": "Use precise technical language. Include formulas and exact definitions.",
        "analogy_based": "Use a relatable everyday analogy as the core explanation.",
    }.get(teaching_style, "Use clear, simple language.")

    strategy_section = ""
    if strategy_hint:
        strategy_section = f"\nTEACHING STRATEGY FOR THIS SEGMENT: {strategy_hint}\n"

    prior_section = ""
    if prior_segments_summary:
        prior_section = f"\nWHAT WAS TAUGHT BEFORE:\n{prior_segments_summary}\n"

    return f"""You are a warm, engaging, and clear human-like AI Teacher teaching a {level}-level student.
Language: {language}
Teaching style: {teaching_style}
Style instruction: {style_instructions}

Topic: {topic}
Segment type: {segment_type}
Segment title: {segment_title}
{f"Concept key: {concept_key}" if concept_key else ""}
{context_section}
{prior_section}
{strategy_section}

Generate the teaching content for this segment.

CRITICAL TEACHING & SPEAKING RULES:
1. "spoken_text": What the AI Teacher will speak out loud in voice to the student. This MUST be a comprehensive, natural, human-like verbal explanation (4-6 full sentences) in {language}. Complete every thought — do NOT cut off or leave sentences unfinished.
2. The teacher MUST explicitly walk the student through everything shown on the Smart Board (e.g. if the board shows code, explain each line/step and what it does; if a table, compare the entries; if a diagram, explain the flow; if a formula, define the variables and operations).
3. "board": Contains the visual smart board element (code, table, mermaid, formula, steps, bullets, or text).
4. Both spoken_text and board MUST work together like a real in-person teacher: the board shows the visual reference while the spoken voice delivers the full, clear explanation of that visual.

RESPOND WITH THIS EXACT JSON (ensure valid JSON syntax, escape quotes properly):
{{
  "spoken_text": "Complete, friendly, human-like spoken teaching explanation in {language} walking through all details on the board.",
  "board": {{
    "type": "one of: text, bullets, formula, mermaid, code, key_takeaways, timeline, table",
    "content": "Content to display on the smart board",
    "caption": "optional caption or label",
    "language": "only for code blocks — programming language name"
  }},
  "source_refs": [],
  "segment_type": "{segment_type}",
  "segment_title": "{segment_title}"
}}

Rules for board types:
- formula: LaTeX or plain math notation (e.g., "V = I × R")
- mermaid: Valid Mermaid.js diagram syntax
- code: Actual runnable code snippet
- bullets: JSON array of strings ["point1", "point2"]
- key_takeaways: JSON array of strings
- text: Plain text explanation
- timeline: JSON array of {{"year": "...", "event": "..."}} objects
- table: Markdown table format"""


def build_analogy_prompt(
    concept: str,
    misconception: Optional[str],
    level: str,
    language: str,
    topic: str,
) -> str:
    """Build prompt for analogy-based reteaching."""
    misconception_section = ""
    if misconception:
        misconception_section = f"\nThe student's misconception: {misconception}\nYour analogy must directly address this misconception.\n"

    return f"""You are an AI Teacher who needs to explain "{concept}" using a relatable analogy.
The student is at {level} level. Language: {language}. Topic: {topic}.
{misconception_section}

Choose an analogy from everyday life (water pipes, traffic, pizza slices, etc.)
that maps perfectly to the concept. Make the mapping explicit.

RESPOND WITH THIS EXACT JSON:
{{
  "spoken_text": "The analogy explanation in {language}. 3-6 sentences.",
  "board": {{
    "type": "text",
    "content": "Clear analogy description with explicit concept mapping",
    "caption": "Analogy: [everyday thing] ↔ [concept]"
  }},
  "source_refs": [],
  "segment_type": "analogy",
  "segment_title": "Let's look at this differently"
}}"""


def build_ask_prompt(
    topic: str,
    user_question: str,
    level: str,
    language: str,
) -> str:
    """
    Build a prompt for an in-lesson student question ("Ask Teacher").

    Separates the SHORT spoken narration from the DETAILED board content so the
    frontend can play a short talking-avatar clip while the smart board carries
    the full worked solution. This mirrors how a human teacher explains at the
    board while narrating out loud, rather than reading a wall of text aloud.
    """
    return f"""You are an AI Teacher. A student has paused the lesson to ask a question.

Lesson topic: {topic}
Student level: {level}
Language: {language}
Student's question: {user_question}

Decide whether answering requires step-by-step working (solving equations, a
multi-step derivation, a numeric problem, a proof, code execution trace, etc.)
or a direct conceptual explanation.

RESPOND WITH THIS EXACT JSON:
{{
  "spoken_text": "A SHORT (2-4 sentence) spoken narration in {language}. Summarize the approach and the final answer only — do NOT read out every algebraic step, that belongs on the board. End with a short transition back to the lesson.",
  "board": {{
    "type": "steps" or "formula" or "text" or "code" or "bullets",
    "content": "See rules below",
    "caption": "Short caption, e.g. 'Solving your equations'"
  }},
  "segment_title": "Short title for this question"
}}

Rules for board.content by type:
- steps: a JSON array of objects, each {{"label": "Step 1: Align coefficients", "expression": "10x + 25y = 50"}}. Use valid LaTeX (no $ delimiters) inside "expression". One clear transformation per step. This is REQUIRED whenever solving equations, doing arithmetic derivations, or working through a multi-step problem — never dump the full derivation into spoken_text or into a single text blob.
- formula: a single LaTeX expression (no $ delimiters), for a one-line result.
- text: plain prose, for conceptual/definition questions with no working to show.
- bullets: JSON array of short strings, for a list-style answer.
- code: an actual code snippet answering a programming question.

Never invent facts outside general subject knowledge. If the question is unrelated to the topic, still answer it helpfully, then gently connect back to {topic}."""


def build_simplify_prompt(
    concept: str,
    previous_explanation: str,
    level: str,
    language: str,
) -> str:
    """Build prompt for simplified reteaching."""
    return f"""You are an AI Teacher who needs to explain "{concept}" in an even simpler way.
Level: {level}. Language: {language}.

PREVIOUS EXPLANATION (the student didn't understand this):
{previous_explanation[:500]}

Simplify drastically. Use the smallest possible vocabulary. One concept at a time.

RESPOND WITH THIS EXACT JSON:
{{
  "spoken_text": "Even simpler explanation in {language}. Very short sentences.",
  "board": {{
    "type": "bullets",
    "content": ["Simple point 1", "Simple point 2", "Simple point 3"]
  }},
  "source_refs": [],
  "segment_type": "reteach",
  "segment_title": "Let me simplify this"
}}"""
