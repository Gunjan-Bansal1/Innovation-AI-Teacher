"""
Students API and Reports API.
"""
from fastapi import APIRouter, HTTPException
from app.services.mongodb_service import mongodb_service
from app.agents.report_agent import report_agent
from app.core.logging import get_logger

logger = get_logger(__name__)

students_router = APIRouter()
reports_router = APIRouter()


@students_router.get("/api/students/{learner_id}/progress")
async def get_student_progress(learner_id: str):
    """
    Get real student progress from MongoDB.
    Returns actual data — never fake static values.
    """
    # Sessions
    cursor = mongodb_service.learning_sessions.find(
        {"learner_id": learner_id},
        {"topic": 1, "status": 1, "final_score": 1, "created_at": 1, "lesson_id": 1},
    ).sort("created_at", -1)
    sessions = await cursor.to_list(20)

    # Mastery
    cursor = mongodb_service.concept_mastery.find(
        {"learner_id": learner_id},
        {"concept_key": 1, "mastery_score": 1, "attempt_count": 1},
    )
    mastery_docs = await cursor.to_list(None)

    # Misconceptions
    cursor = mongodb_service.misconceptions.find(
        {"learner_id": learner_id},
        {"misconception_type": 1, "concept_key": 1, "created_at": 1},
    ).sort("created_at", -1).limit(10)
    misconceptions = await cursor.to_list(10)

    completed = [s for s in sessions if s.get("status") == "completed"]
    scores = [s.get("final_score", 0) for s in completed if s.get("final_score") is not None]

    mastery_map = {d["concept_key"]: d["mastery_score"] for d in mastery_docs}
    strong = [k for k, v in mastery_map.items() if v >= 0.7]
    needs_revision = [k for k, v in mastery_map.items() if v < 0.5]

    return {
        "learner_id": learner_id,
        "total_sessions": len(sessions),
        "completed_sessions": len(completed),
        "average_score": round(sum(scores) / len(scores), 3) if scores else 0.0,
        "average_score_pct": round(sum(scores) / len(scores) * 100, 1) if scores else 0.0,
        "concept_mastery": mastery_map,
        "strong_concepts": strong,
        "needs_revision": needs_revision,
        "recent_sessions": [
            {
                "_id": str(s["_id"]),
                "topic": s.get("topic"),
                "status": s.get("status"),
                "final_score": s.get("final_score"),
                "created_at": s.get("created_at"),
            }
            for s in sessions[:5]
        ],
        "misconceptions": [
            {
                "concept_key": m.get("concept_key"),
                "misconception_type": m.get("misconception_type"),
                "created_at": m.get("created_at"),
            }
            for m in misconceptions
        ],
    }


@reports_router.get("/api/reports/{session_id}")
async def get_learning_report(session_id: str):
    """
    Generate and return a learning report from real session data.

    Accuracy scoping (read before changing):
    Older versions of this endpoint computed `accuracy_pct` only from the
    in-lesson comprehension-check answers (student_answers), while
    `final_score`/`grade` come only from the separate final-assessment
    submission. Those are two different, differently-sized question pools —
    showing them side by side as "Accuracy: 100%" next to "Grade: F" is
    truthful about each number individually but reads as contradictory to a
    student, because they look like they should describe the same thing.
    `accuracy_pct` below now spans BOTH pools (every graded attempt in the
    session), so it is on the same footing as final_score/grade.
    """
    session = await mongodb_service.learning_sessions.find_one({"_id": session_id})
    if not session:
        raise HTTPException(404, f"Session {session_id} not found")

    learner_id = session["learner_id"]
    concept_keys = session.get("concept_keys", session.get("taught_concepts", []))

    # Get mastery data
    mastery_cursor = mongodb_service.concept_mastery.find(
        {"learner_id": learner_id, "concept_key": {"$in": concept_keys}},
        {"concept_key": 1, "mastery_score": 1, "attempt_count": 1},
    )
    mastery_docs = await mastery_cursor.to_list(None)
    mastery_map = {d["concept_key"]: d.get("mastery_score", 0.0) for d in mastery_docs}

    # Lesson comprehension-check answers
    answers_cursor = mongodb_service.student_answers.find(
        {"session_id": session_id}
    )
    answers = await answers_cursor.to_list(None)
    lesson_total = len(answers)
    lesson_correct = sum(1 for a in answers if a.get("score", 0) >= 0.8)

    # Get misconceptions
    misc_cursor = mongodb_service.misconceptions.find(
        {"session_id": session_id},
        {"explanation": 1, "concept_key": 1},
    )
    misc_docs = await misc_cursor.to_list(None)
    misconceptions = [f"{m['concept_key']}: {m['explanation']}" for m in misc_docs]

    # Get assessment result (final quiz — separate pool of questions)
    assessment_result = await mongodb_service.assessment_results.find_one(
        {"session_id": session_id}
    )
    assessment_taken = assessment_result is not None
    assessment_correct = assessment_result.get("correct_count", 0) if assessment_result else 0
    assessment_total = assessment_result.get("total_questions", 0) if assessment_result else 0

    # Combined accuracy across BOTH pools — same scope as final_score/grade
    combined_total = lesson_total + assessment_total
    combined_correct = lesson_correct + assessment_correct
    accuracy_pct = round(combined_correct / combined_total * 100, 1) if combined_total > 0 else None

    # Build session stats
    elapsed = session.get("elapsed_seconds", 0)
    elapsed_minutes = round(elapsed / 60, 1)

    session_data = {
        "total_questions": combined_total,
        "correct_answers": combined_correct,
        "incorrect_answers": combined_total - combined_correct,
        "elapsed_minutes": elapsed_minutes,
        "final_score": session.get("final_score"),
    }

    # Generate AI summary from real data
    report_summary = await report_agent.generate_report(
        topic=session.get("topic", ""),
        session_data=session_data,
        mastery_data=mastery_map,
        misconceptions=misconceptions,
    )

    return {
        "session_id": session_id,
        "learner_id": learner_id,
        "topic": session.get("topic", ""),
        "language": session.get("language", "english"),
        "elapsed_minutes": elapsed_minutes,
        "total_questions": combined_total,
        "correct_answers": combined_correct,
        "accuracy_pct": accuracy_pct,  # None when nothing has been answered yet
        "lesson_questions_total": lesson_total,
        "lesson_questions_correct": lesson_correct,
        "assessment_taken": assessment_taken,
        "assessment_questions_total": assessment_total,
        "assessment_questions_correct": assessment_correct,
        "final_score": session.get("final_score"),  # None until the final assessment is submitted
        "grade": session.get("grade"),  # None until the final assessment is submitted
        "concept_mastery": mastery_map,
        "misconceptions": misconceptions,
        "overall_summary": report_summary.overall_summary,
        "strong_concepts": report_summary.strong_concepts,
        "weak_concepts": report_summary.weak_concepts,
        "recommended_revision": report_summary.recommended_revision,
        "recommended_practice": report_summary.recommended_practice,
        "next_topic": report_summary.next_topic,
        "encouragement": report_summary.encouragement,
        "assessment": assessment_result,
    }
