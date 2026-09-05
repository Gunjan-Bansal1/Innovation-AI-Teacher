"""
Assessments API — final assessment generation and submission.
"""
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.schemas.assessment import AssessmentSubmit
from app.agents.assessment_agent import assessment_agent
from app.agents.evaluator_agent import evaluator_agent
from app.orchestration.teacher_orchestrator import calculate_mastery, _update_mastery
from app.services.mongodb_service import mongodb_service
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


class AssessmentGenerateRequest(BaseModel):
    session_id: str
    lesson_id: str
    question_count: int = 5


@router.get("/api/assessments/{session_id}")
async def get_assessment(session_id: str):
    """Fetch the assessment for a given session (if already generated)."""
    assessment_doc = await mongodb_service.assessments.find_one({"session_id": session_id})
    if not assessment_doc:
        raise HTTPException(404, "No assessment found for this session")

    return {
        "assessment_id": assessment_doc["_id"],
        "session_id": session_id,
        "total_questions": assessment_doc.get("total_questions", 0),
        "questions": [
            {
                "question_id": q.get("question_id"),
                "question_text": q.get("question_text"),
                "question_type": q.get("question_type"),
                "difficulty": q.get("difficulty"),
                "concept_key": q.get("concept_key"),
                "options": q.get("options"),
                # Don't send correct_answer to frontend
            }
            for q in assessment_doc.get("questions", [])
        ],
    }


@router.post("/api/assessments/generate")
async def generate_assessment(body: AssessmentGenerateRequest):
    """Generate a final assessment from actually-taught concepts."""
    session = await mongodb_service.learning_sessions.find_one({"_id": body.session_id})
    if not session:
        raise HTTPException(404, "Session not found")

    taught_concepts = session.get("taught_concepts", session.get("concept_keys", []))

    assessment = await assessment_agent.generate_assessment(
        session_id=body.session_id,
        lesson_id=body.lesson_id,
        taught_concepts=taught_concepts,
        topic=session.get("topic", ""),
        level=session.get("level", "beginner"),
        language=session.get("language", "english"),
        question_count=body.question_count,
        document_id=session.get("document_id"),
    )

    # Store assessment
    now = datetime.now(timezone.utc).isoformat()
    await mongodb_service.assessments.insert_one({
        "_id": assessment.assessment_id,
        "session_id": body.session_id,
        "lesson_id": body.lesson_id,
        "questions": [q.model_dump() for q in assessment.questions],
        "total_questions": assessment.total_questions,
        "created_at": now,
    })

    return {
        "assessment_id": assessment.assessment_id,
        "session_id": body.session_id,
        "total_questions": assessment.total_questions,
        "questions": [
            {
                "question_id": q.question_id,
                "question_text": q.question_text,
                "question_type": q.question_type.value,
                "difficulty": q.difficulty.value,
                "concept_key": q.concept_key,
                "options": q.options,
                # Don't send correct_answer to frontend
            }
            for q in assessment.questions
        ],
    }


@router.post("/api/assessments/{assessment_id}/submit")
async def submit_assessment(assessment_id: str, body: AssessmentSubmit):
    """Submit assessment answers and get scores."""
    assessment_doc = await mongodb_service.assessments.find_one({"_id": assessment_id})
    if not assessment_doc:
        raise HTTPException(404, "Assessment not found")

    session_id = assessment_doc["session_id"]
    session = await mongodb_service.learning_sessions.find_one({"_id": session_id})
    learner_id = session["learner_id"] if session else "unknown"

    questions_map = {q["question_id"]: q for q in assessment_doc["questions"]}
    answers_map = {a.question_id: a.student_answer for a in body.answers}

    question_results = []
    concept_scores: dict[str, list] = {}
    correct_count = 0
    partial_count = 0
    incorrect_count = 0

    for q_id, question in questions_map.items():
        student_answer = answers_map.get(q_id, "")
        if not student_answer:
            student_answer = "(no answer)"

        # Evaluate each answer
        eval_result = await evaluator_agent.evaluate_assessment_answer(
            question=question,
            student_answer=student_answer,
        )

        score = eval_result.get("score", 0.0)
        status = eval_result.get("status", "incorrect")
        feedback = eval_result.get("feedback", "")
        concept_key = question.get("concept_key", "general")

        if score >= 0.8:
            correct_count += 1
        elif score >= 0.4:
            partial_count += 1
        else:
            incorrect_count += 1

        if concept_key not in concept_scores:
            concept_scores[concept_key] = []
        concept_scores[concept_key].append(score)

        # Update mastery
        await _update_mastery(
            learner_id=learner_id,
            concept_key=concept_key,
            score=score,
            difficulty=question.get("difficulty", "medium"),
        )

        question_results.append({
            "question_id": q_id,
            "question_text": question.get("question_text", ""),
            "student_answer": student_answer,
            "correct_answer": question.get("correct_answer", ""),
            "score": score,
            "status": status,
            "feedback": feedback,
            "concept_key": concept_key,
        })

    total_questions = len(questions_map)
    total_score = (
        sum(r["score"] for r in question_results) / total_questions
        if total_questions > 0 else 0.0
    )

    # Concept-level scores
    concept_avg = {
        k: round(sum(v) / len(v), 3)
        for k, v in concept_scores.items()
    }

    # Grade
    grade = _score_to_grade(total_score)

    result = {
        "assessment_id": assessment_id,
        "session_id": session_id,
        "total_score": round(total_score, 3),
        "total_score_pct": round(total_score * 100, 1),
        "total_questions": total_questions,
        "correct_count": correct_count,
        "partial_count": partial_count,
        "incorrect_count": incorrect_count,
        "concept_scores": concept_avg,
        "grade": grade,
        "question_results": question_results,
    }

    # Store result
    await mongodb_service.assessment_results.insert_one({
        "_id": str(uuid.uuid4()),
        **result,
        "learner_id": learner_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    # Update session status
    await mongodb_service.learning_sessions.update_one(
        {"_id": session_id},
        {
            "$set": {
                "status": "completed",
                "final_score": total_score,
                "grade": grade,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        },
    )

    return result


def _score_to_grade(score: float) -> str:
    if score >= 0.9:
        return "A"
    elif score >= 0.8:
        return "B"
    elif score >= 0.7:
        return "C"
    elif score >= 0.6:
        return "D"
    else:
        return "F"
