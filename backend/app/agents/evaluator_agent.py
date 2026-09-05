"""
Evaluator Agent — evaluates student answers.

Grading policy (important — read before changing):
- MCQ answers have a single objectively-correct option. These are graded
  DETERMINISTICALLY (exact match after normalization) and NEVER sent to the
  LLM for a "semantic" judgment. An LLM grading a multiple-choice question is
  solving an easier problem worse — it can be talked into leniency by an
  answer that merely *sounds* plausible. This is the fix for reports showing
  100% accuracy despite a wrong option being selected.
- Blank/empty answers are graded as 0 deterministically — never sent to the
  LLM (an LLM asked to "evaluate" an empty string will sometimes hedge with a
  non-zero score instead of just saying "no answer given").
- Free-text answers (short_answer, problem_solving, conceptual, application,
  explain_own_words) have no single canonical string to match against, so
  they still go through Gemma for semantic evaluation. See prompts/evaluator.py
  for the anti-leniency calibration added to that prompt.

Output is validated against EvaluationResult / a simple assessment schema.
"""
import re
from typing import Optional

from app.services.ollama_service import ollama_service
from app.schemas.evaluation import EvaluationResult, EvaluationStatus, Understanding, AdaptationAction
from app.prompts.evaluator import build_evaluator_prompt, build_assessment_evaluator_prompt
from app.prompts.system_teacher import SYSTEM_EVALUATOR
from app.rag.retriever import retrieve_context
from app.core.logging import get_logger

logger = get_logger(__name__)

_OPTION_PREFIX_RE = re.compile(r"^\(?([A-Za-z])\)?[\.\):\-]\s*")
_TRAILING_PUNCT_RE = re.compile(r"[\s.]+$")


def _normalize_mcq_answer(text: Optional[str]) -> str:
    """
    Normalize an MCQ answer/option for exact comparison.

    Strips a leading option label ("A.", "B)", "(C)", "d -") so that a student
    answer of just "A" and a stored correct_answer of "A. Ohm's Law" compare
    equal on their substance, not their formatting.
    """
    if not text:
        return ""
    t = text.strip()
    t = _OPTION_PREFIX_RE.sub("", t)
    t = _TRAILING_PUNCT_RE.sub("", t)
    return t.strip().lower()


def _deterministic_mcq_result(
    question_type: str,
    options: Optional[list],
    correct_answer: Optional[str],
    student_answer: str,
) -> Optional[dict]:
    """
    If this is an MCQ with a known correct option, grade it deterministically.
    Returns None (defer to LLM) when the question isn't a gradeable MCQ —
    e.g. correct_answer missing, which happens if question generation failed
    to populate it.
    """
    if question_type != "mcq" or not correct_answer:
        return None

    student_norm = _normalize_mcq_answer(student_answer)
    correct_norm = _normalize_mcq_answer(correct_answer)
    if not student_norm:
        return {"is_correct": False, "reason": "blank"}

    is_correct = student_norm == correct_norm

    # Fallback: student answered with just a bare letter ("A") — match it
    # against the leading letter of whichever option text equals correct_answer.
    if not is_correct and options and len(student_norm) == 1 and student_norm.isalpha():
        for i, opt in enumerate(options):
            if _normalize_mcq_answer(opt) == correct_norm:
                letter = chr(ord("a") + i)
                is_correct = student_norm == letter
                break

    return {"is_correct": is_correct, "reason": "matched"}


class EvaluatorAgent:
    """Evaluates student answers — deterministically for MCQ, semantically (via Gemma) otherwise."""

    async def evaluate(
        self,
        question: dict,
        student_answer: str,
        document_id: Optional[str],
    ) -> EvaluationResult:
        """
        Evaluate a student answer.

        Returns EvaluationResult with score, understanding, misconception detection.
        Backend (not Gemma) controls what happens with the result, and backend
        (not Gemma) decides correctness for MCQs — see module docstring.
        """
        question_text = question.get("question_text", "")
        question_type = question.get("question_type", "short_answer")
        correct_answer = question.get("correct_answer", "")
        evaluation_criteria = question.get("evaluation_criteria", "")
        concept_key = question.get("concept_key", "unknown")
        options = question.get("options")

        # ── Deterministic path for MCQ ──────────────────────────────────────
        mcq_result = _deterministic_mcq_result(question_type, options, correct_answer, student_answer)
        if mcq_result is not None:
            if mcq_result["is_correct"]:
                result = EvaluationResult(
                    status=EvaluationStatus.correct,
                    score=1.0,
                    concept=concept_key,
                    confidence=1.0,
                    understanding=Understanding.strong,
                    misconception_detected=False,
                    misconception=None,
                    recommended_action=AdaptationAction.CONTINUE,
                    feedback="Correct! Well done.",
                )
            else:
                result = EvaluationResult(
                    status=EvaluationStatus.incorrect,
                    score=0.0,
                    concept=concept_key,
                    confidence=1.0,
                    understanding=Understanding.none,
                    misconception_detected=True,
                    misconception=f"Selected an incorrect option instead of: {correct_answer}",
                    recommended_action=AdaptationAction.RETEACH,
                    feedback=f"Not quite. The correct answer was: {correct_answer}",
                )
            logger.info(
                "Deterministic MCQ evaluation",
                extra={"concept": concept_key, "status": result.status, "score": result.score},
            )
            return result

        # ── Semantic (Gemma) path for free-text answers ─────────────────────
        if not student_answer or not student_answer.strip():
            # Blank free-text answer — no need to ask the LLM to "evaluate" nothing.
            return EvaluationResult(
                status=EvaluationStatus.incorrect,
                score=0.0,
                concept=concept_key,
                confidence=1.0,
                understanding=Understanding.none,
                misconception_detected=False,
                misconception=None,
                recommended_action=AdaptationAction.SIMPLIFY,
                feedback="No answer was given. Let's go over this again.",
            )

        # Retrieve source context for grounding evaluation
        source_context = ""
        if document_id and question_text:
            ctx = await retrieve_context(
                query=f"{concept_key} {question_text}",
                document_id=document_id,
                top_k=3,
            )
            source_context = ctx["context_text"]

        prompt = build_evaluator_prompt(
            question_text=question_text,
            question_type=question_type,
            correct_answer=correct_answer,
            evaluation_criteria=evaluation_criteria,
            student_answer=student_answer,
            concept_key=concept_key,
            source_context=source_context,
        )

        try:
            result = await ollama_service.generate_structured(
                prompt=prompt,
                schema=EvaluationResult,
                system=SYSTEM_EVALUATOR,
                temperature=0.2,
            )
            logger.info(
                "Evaluation complete",
                extra={
                    "concept": concept_key,
                    "status": result.status,
                    "score": result.score,
                    "misconception": result.misconception_detected,
                },
            )
            return result

        except Exception as e:
            logger.error(f"Evaluation failed: {e}")
            # Conservative fallback — mark as unclear rather than fake evaluation
            return EvaluationResult(
                status=EvaluationStatus.unclear,
                score=0.0,
                concept=concept_key,
                confidence=0.0,
                understanding=Understanding.none,
                misconception_detected=False,
                misconception=None,
                recommended_action=AdaptationAction.ASK_EASIER_QUESTION,
                feedback="I couldn't evaluate your answer clearly. Let me ask a simpler question.",
            )

    async def evaluate_assessment_answer(
        self,
        question: dict,
        student_answer: str,
    ) -> dict:
        """Evaluate a final assessment answer. Returns score and feedback."""
        question_type = question.get("question_type", "short_answer")
        correct_answer = question.get("correct_answer", "")
        options = question.get("options")

        # ── Deterministic path: MCQ ──────────────────────────────────────────
        mcq_result = _deterministic_mcq_result(question_type, options, correct_answer, student_answer)
        if mcq_result is not None:
            if mcq_result["is_correct"]:
                return {"status": "correct", "score": 1.0, "feedback": "Correct! Well done."}
            return {
                "status": "incorrect",
                "score": 0.0,
                "feedback": f"Not quite. The correct answer was: {correct_answer}",
            }

        # ── Deterministic path: blank answer ─────────────────────────────────
        if not student_answer or not student_answer.strip() or student_answer.strip() == "(no answer)":
            return {"status": "incorrect", "score": 0.0, "feedback": "No answer was given."}

        # ── Semantic (Gemma) path for free-text answers ──────────────────────
        prompt = build_assessment_evaluator_prompt(
            question_text=question.get("question_text", ""),
            correct_answer=correct_answer,
            evaluation_criteria=question.get("evaluation_criteria", ""),
            student_answer=student_answer,
            concept_key=question.get("concept_key", "unknown"),
        )

        from pydantic import BaseModel as _BaseModel

        class SimpleEval(_BaseModel):
            status: str
            score: float
            feedback: str

        try:
            result = await ollama_service.generate_structured(
                prompt=prompt,
                schema=SimpleEval,
                system=SYSTEM_EVALUATOR,
                temperature=0.2,
            )
            return result.model_dump()
        except Exception as e:
            logger.error(f"Assessment evaluation failed: {e}")
            return {
                "status": "unclear",
                "score": 0.0,
                "feedback": "Could not evaluate this answer.",
            }


evaluator_agent = EvaluatorAgent()
