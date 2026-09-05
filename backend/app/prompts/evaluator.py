"""
Evaluator prompt templates.
"""


def build_evaluator_prompt(
    question_text: str,
    question_type: str,
    correct_answer: str,
    evaluation_criteria: str,
    student_answer: str,
    concept_key: str,
    source_context: str,
) -> str:
    context_section = ""
    if source_context and len(source_context) > 50:
        context_section = f"\nSOURCE CONTEXT (use for evaluation):\n{source_context[:1500]}\n"

    return f"""Evaluate this student answer for an AI teaching system.
This question type ({question_type}) has already been confirmed to require
semantic judgment rather than exact matching — grade it carefully and
skeptically, the same way a strict human tutor would.

QUESTION: {question_text}
QUESTION TYPE: {question_type}
CONCEPT BEING TESTED: {concept_key}
CORRECT ANSWER: {correct_answer}
EVALUATION CRITERIA: {evaluation_criteria}
{context_section}
STUDENT ANSWER: {student_answer}

GRADING RULES — apply strictly, do not be lenient:
1. If the question has a specific final numeric/factual result (e.g. solving
   an equation, a calculation, a named quantity), first extract the specific
   final value the student gave, then compare it directly to CORRECT ANSWER.
   A different final value is INCORRECT even if the student's method,
   reasoning, or terminology sounds confident or mostly right — effort and
   fluent language are not evidence of a correct result.
2. Confident tone, use of correct-sounding vocabulary, or partial restating
   of the question are NOT evidence of understanding by themselves.
3. If the student's answer only addresses part of what was asked, or omits
   the final result entirely, this is at most partially_correct — never correct.
4. When genuinely uncertain between two adjacent statuses, choose the LOWER
   (stricter) one and lower the confidence score accordingly.

Determine if the student demonstrates genuine understanding of the core concept.

RESPOND WITH THIS EXACT JSON:
{{
  "status": "correct|partially_correct|incorrect|unclear",
  "score": 0.0 to 1.0,
  "concept": "{concept_key}",
  "confidence": 0.0 to 1.0,
  "understanding": "strong|moderate|weak|none",
  "misconception_detected": true or false,
  "misconception": "Brief description of the misconception if detected, else null",
  "recommended_action": "CONTINUE|RETEACH|SIMPLIFY|USE_ANALOGY|SHOW_VISUAL|GIVE_EXAMPLE|ASK_EASIER_QUESTION|INCREASE_DIFFICULTY|DECREASE_DIFFICULTY",
  "feedback": "1-2 sentence feedback to give the student"
}}

Scoring guide:
- correct: 0.8-1.0 — student's final answer/result matches, AND demonstrates real understanding
- partially_correct: 0.4-0.79 — right approach or partial result, but the final answer is wrong, incomplete, or missing
- incorrect: 0.0-0.39 — final answer is wrong or shows fundamental misunderstanding
- unclear: 0.0-0.3 — student answer is too vague to evaluate properly"""


def build_assessment_evaluator_prompt(
    question_text: str,
    correct_answer: str,
    evaluation_criteria: str,
    student_answer: str,
    concept_key: str,
) -> str:
    return f"""Evaluate this final assessment answer. Grade strictly: compare the
student's actual final result/claim to CORRECT ANSWER. Confident tone or
partial reasoning is not evidence of correctness — if the final result is
wrong, the answer is not "correct" even if the approach was reasonable.

QUESTION: {question_text}
CONCEPT: {concept_key}
CORRECT ANSWER: {correct_answer}
EVALUATION CRITERIA: {evaluation_criteria}
STUDENT ANSWER: {student_answer}

RESPOND WITH THIS EXACT JSON:
{{
  "status": "correct|partially_correct|incorrect|unclear",
  "score": 0.0 to 1.0,
  "feedback": "1-2 sentence feedback"
}}"""
