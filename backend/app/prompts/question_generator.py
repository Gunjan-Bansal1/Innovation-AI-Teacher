"""
Question generator prompt templates.
"""
from typing import Optional


def build_question_prompt(
    concept_key: str,
    topic: str,
    question_type: str,
    level: str,
    language: str,
    source_context: str,
    previous_questions: list[str],
) -> str:
    """Build a prompt to generate a question."""
    prev_q_section = ""
    if previous_questions:
        prev_q_section = f"\nDO NOT repeat these previous questions:\n" + "\n".join(
            f"- {q}" for q in previous_questions[-3:]
        )

    context_section = ""
    if source_context and len(source_context) > 50:
        context_section = f"\nSOURCE CONTEXT:\n{source_context[:1500]}\n"

    type_instructions = {
        "mcq": "Create a multiple choice question with 4 options (A, B, C, D). Exactly one option is correct.",
        "short_answer": "Create a short answer question (1-3 sentence answer expected).",
        "conceptual": "Create a question that tests conceptual understanding, not just recall.",
        "application": "Create a question that requires applying the concept to a new situation.",
        "problem_solving": "Create a problem that requires calculation or step-by-step reasoning.",
        "explain_own_words": "Ask the student to explain the concept in their own words.",
    }.get(question_type, "Create a question that tests understanding of the concept.")

    return f"""Generate a {question_type} question about: {concept_key} (Topic: {topic})

Student level: {level}
Language: {language}
{type_instructions}
{context_section}
{prev_q_section}

RESPOND WITH THIS EXACT JSON:
{{
  "question_text": "The question in {language}",
  "question_type": "{question_type}",
  "difficulty": "easy|medium|hard",
  "concept_key": "{concept_key}",
  "options": ["A. ...", "B. ...", "C. ...", "D. ..."] or null if not MCQ,
  "correct_answer": "The correct answer",
  "evaluation_criteria": "What a correct answer must demonstrate — used for semantic evaluation"
}}"""


def build_easier_question_prompt(
    concept_key: str,
    topic: str,
    level: str,
    language: str,
    original_question: str,
    source_context: str,
) -> str:
    """Build a simpler follow-up question after a wrong answer."""
    return f"""The student struggled with: "{original_question}"

Create an EASIER question about the same concept: {concept_key} ({topic})
Level: {level}, Language: {language}

Make it much simpler — test the most basic aspect of the concept first.

RESPOND WITH THIS EXACT JSON:
{{
  "question_text": "Simpler question in {language}",
  "question_type": "mcq",
  "difficulty": "easy",
  "concept_key": "{concept_key}",
  "options": ["A. ...", "B. ...", "C. ...", "D. ..."],
  "correct_answer": "Correct option letter and text",
  "evaluation_criteria": "What constitutes a correct understanding"
}}"""
