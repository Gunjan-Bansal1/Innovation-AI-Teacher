"""
Misconception detection and adaptation prompt templates.
"""
from typing import Optional


def build_misconception_prompt(
    question_text: str,
    correct_answer: str,
    student_answer: str,
    concept_key: str,
    topic: str,
    source_context: str,
) -> str:
    context_section = ""
    if source_context and len(source_context) > 50:
        context_section = f"\nSOURCE CONTEXT:\n{source_context[:1200]}\n"

    return f"""Analyze WHY this student is wrong. Identify the root cause misconception.

TOPIC: {topic}
CONCEPT: {concept_key}
QUESTION: {question_text}
CORRECT ANSWER: {correct_answer}
STUDENT ANSWER: {student_answer}
{context_section}

Your job is not to say "wrong". Your job is to diagnose WHAT the student believes
that is causing them to give this answer. This helps us reteach more effectively.

If evidence is insufficient to determine a specific misconception, use "unclear".

RESPOND WITH THIS EXACT JSON:
{{
  "misconception_type": "brief label for the misconception type",
  "explanation": "Explanation of what the student appears to believe that is incorrect. Be specific.",
  "evidence": "The specific part of their answer that reveals this misconception",
  "confidence": 0.0 to 1.0,
  "suggested_correction": "How to correct this specific misconception"
}}"""


def build_adaptation_prompt(
    concept_key: str,
    evaluation_status: str,
    understanding: str,
    misconception: Optional[str],
    session_history: list[str],
    level: str,
    teaching_style: str,
    last_action: Optional[str],
) -> str:
    history_str = ""
    if session_history:
        history_str = "RECENT TEACHING HISTORY:\n" + "\n".join(
            f"- {h}" for h in session_history[-5:]
        )

    last_action_str = ""
    if last_action:
        last_action_str = f"\nDO NOT select '{last_action}' again — choose a DIFFERENT strategy.\n"

    misconception_str = ""
    if misconception:
        misconception_str = f"\nDETECTED MISCONCEPTION: {misconception}\n"

    return f"""You are an adaptive AI Teacher deciding the next teaching action.

STUDENT STATUS:
- Concept: {concept_key}
- Evaluation: {evaluation_status}
- Understanding level: {understanding}
{misconception_str}
- Student level: {level}
- Preferred style: {teaching_style}
{history_str}
{last_action_str}

ALLOWED ACTIONS:
- CONTINUE: Student understood — move to next concept
- RETEACH: Reteach the same concept with a different approach
- SIMPLIFY: Use simpler language and smaller steps
- USE_ANALOGY: Use a real-world analogy to explain
- SHOW_VISUAL: Show a diagram or visual representation
- GIVE_EXAMPLE: Give a concrete worked example
- ASK_EASIER_QUESTION: Ask a simpler version of the question
- INCREASE_DIFFICULTY: Student is doing well — increase challenge
- DECREASE_DIFFICULTY: Student is struggling — decrease complexity

Choose the best action based on the student's current state.
If the student answered incorrectly: do NOT choose CONTINUE.
If the student answered correctly: do NOT choose RETEACH or SIMPLIFY.

RESPOND WITH THIS EXACT JSON:
{{
  "action": "one of the ALLOWED ACTIONS above",
  "reason": "Why you chose this action (1-2 sentences)",
  "strategy_description": "How you will execute this action specifically"
}}"""


def build_content_analysis_prompt(
    text_sample: str,
    filename: str,
    focus_question: Optional[str] = None,
) -> str:
    """Prompt for analyzing document content to extract topics and concepts, optionally focused on user's custom question."""
    focus_block = ""
    if focus_question and focus_question.strip():
        focus_block = f"""
LEARNER'S CUSTOM QUESTION / FOCUS TOPIC:
"{focus_question.strip()}"
Please extract concepts and topics specifically relevant to explaining and answering this question based on the document text.
"""

    return f"""Analyze this educational document and extract its structure.

FILENAME: {filename}
CONTENT SAMPLE (first ~2000 chars):
{text_sample[:2000]}
{focus_block}
Extract what topics and concepts are covered. Be accurate — only identify what is
actually present in the text. Do not invent topics not in the text.

RESPOND WITH THIS EXACT JSON:
{{
  "subject": "subject area (e.g., Physics, Mathematics, Biology)",
  "main_topics": ["list of main topics actually found in the text"],
  "concepts": [
    {{
      "key": "snake_case_identifier",
      "name": "Human Readable Name",
      "description": "1 sentence description"
    }}
  ],
  "difficulty_level": "beginner|intermediate|advanced",
  "document_type": "textbook|notes|slides|article|other"
}}"""
