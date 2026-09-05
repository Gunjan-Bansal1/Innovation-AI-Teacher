"""
Assessment generation prompt templates.
"""


def build_assessment_prompt(
    taught_concepts: list[str],
    topic: str,
    level: str,
    language: str,
    question_count: int,
    source_context: str,
) -> str:
    context_section = ""
    if source_context and len(source_context) > 50:
        context_section = f"\nSOURCE MATERIAL:\n{source_context[:2000]}\n"

    concepts_str = ", ".join(taught_concepts)

    return f"""Generate a final assessment for students who just finished learning about: {topic}

CONCEPTS ACTUALLY TAUGHT (only test these):
{concepts_str}

Student level: {level}
Language: {language}
Number of questions: {question_count}
{context_section}

Generate ONLY questions about concepts that were actually taught.
Include a mix of question types for a thorough assessment.
Question types: mcq, short_answer, conceptual, application, problem_solving

RESPOND WITH THIS EXACT JSON:
{{
  "questions": [
    {{
      "question_id": "q1",
      "question_text": "question in {language}",
      "question_type": "mcq|short_answer|conceptual|application|problem_solving",
      "difficulty": "easy|medium|hard",
      "concept_key": "snake_case",
      "options": ["A. ...", "B. ...", "C. ...", "D. ..."] or null,
      "correct_answer": "correct answer",
      "evaluation_criteria": "what constitutes a correct answer"
    }}
  ]
}}"""


def build_report_prompt(
    topic: str,
    session_data: dict,
    mastery_data: dict,
    misconceptions: list[str],
) -> str:
    return f"""Generate a learning report summary for a student who just completed learning: {topic}

SESSION DATA:
- Total questions attempted: {session_data.get('total_questions', 0)}
- Correct answers: {session_data.get('correct_answers', 0)}
- Incorrect answers: {session_data.get('incorrect_answers', 0)}
- Learning time: {session_data.get('elapsed_minutes', 0)} minutes

CONCEPT MASTERY:
{chr(10).join(f"- {k}: {round(v*100)}%" for k, v in mastery_data.items())}

MISCONCEPTIONS DETECTED:
{chr(10).join(f"- {m}" for m in misconceptions) if misconceptions else "None detected"}

Generate a constructive, encouraging learning summary.

RESPOND WITH THIS EXACT JSON:
{{
  "overall_summary": "2-3 sentence summary of the student's learning",
  "strong_concepts": ["concepts the student mastered"],
  "weak_concepts": ["concepts needing more practice"],
  "recommended_revision": ["specific topics to revise"],
  "recommended_practice": ["specific practice activities"],
  "next_topic": "recommended next topic to learn",
  "encouragement": "1-2 sentence encouraging message"
}}"""
