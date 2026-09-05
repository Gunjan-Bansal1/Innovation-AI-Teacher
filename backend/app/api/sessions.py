"""
Sessions API — the main teaching session endpoints.

Controls the full adaptive teaching loop:
start → next → answer → ask → repeat → simplify → switch-language
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.schemas.session import SessionCreate, AnswerSubmit, AskRequest, SwitchLanguageRequest
from app.orchestration.teacher_orchestrator import (
    initialize_session,
    get_session_state,
    advance_lesson,
    process_answer,
    handle_ask,
    handle_simplify,
    handle_language_switch,
)
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


def _state_to_dict(state) -> dict:
    """Convert SessionState to JSON-serializable dict."""
    d = state.model_dump()
    if state.teacher_output:
        d["teacher_output"] = state.teacher_output.model_dump()
    if state.current_question:
        d["current_question"] = state.current_question
    return d


@router.post("/api/sessions/start")
async def start_session(body: SessionCreate):
    """Initialize a new learning session."""
    try:
        state = await initialize_session(
            learner_id=body.learner_id,
            lesson_id=body.lesson_id,
        )
        return _state_to_dict(state)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.error(f"Session start error: {e}")
        raise HTTPException(500, f"Failed to start session: {str(e)}")


@router.get("/api/sessions/{session_id}/state")
async def get_state(session_id: str):
    """Get current session state."""
    try:
        state = await get_session_state(session_id)
        return _state_to_dict(state)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/api/sessions/{session_id}/next")
async def next_segment(session_id: str):
    """Advance the lesson to the next segment."""
    try:
        state = await advance_lesson(session_id)
        return _state_to_dict(state)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.error(f"Advance lesson error: {e}")
        raise HTTPException(500, f"Error advancing lesson: {str(e)}")


@router.post("/api/sessions/{session_id}/answer")
async def submit_answer(session_id: str, body: AnswerSubmit):
    """
    Submit a student answer. Triggers the full adaptive evaluation loop:
    evaluate → detect misconception → adapt → reteach or continue.
    """
    try:
        state = await process_answer(
            session_id=session_id,
            student_answer=body.answer,
            time_taken=body.time_taken_seconds or 0,
        )
        return _state_to_dict(state)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error(f"Answer processing error: {e}")
        raise HTTPException(500, f"Error processing answer: {str(e)}")


@router.post("/api/sessions/{session_id}/ask")
async def ask_teacher(session_id: str, body: AskRequest):
    """Student asks a question — preserves session position."""
    try:
        output = await handle_ask(session_id, body.question)
        return output.model_dump()
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.error(f"Ask error: {e}")
        raise HTTPException(500, f"Error handling question: {str(e)}")


@router.post("/api/sessions/{session_id}/repeat")
async def repeat_segment(session_id: str):
    """Repeat the current teaching segment."""
    try:
        from app.services.mongodb_service import mongodb_service
        session = await mongodb_service.learning_sessions.find_one({"_id": session_id})
        if not session:
            raise HTTPException(404, "Session not found")

        # Step back one segment and re-advance
        idx = max(0, session["current_segment_index"] - 1)
        await mongodb_service.learning_sessions.update_one(
            {"_id": session_id},
            {"$set": {"current_segment_index": idx, "status": "teaching"}},
        )
        state = await advance_lesson(session_id)
        return _state_to_dict(state)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Error repeating: {str(e)}")


@router.post("/api/sessions/{session_id}/simplify")
async def simplify_explanation(session_id: str):
    """Request a simpler explanation of the current concept."""
    try:
        output = await handle_simplify(session_id)
        return output.model_dump()
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, f"Error simplifying: {str(e)}")


@router.post("/api/sessions/{session_id}/switch-language")
async def switch_language(session_id: str, body: SwitchLanguageRequest):
    """Switch lesson language while preserving all session state."""
    try:
        result = await handle_language_switch(session_id, body.language)
        return result
    except Exception as e:
        raise HTTPException(500, f"Error switching language: {str(e)}")
