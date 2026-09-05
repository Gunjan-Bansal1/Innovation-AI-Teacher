"""
Teacher Orchestrator — central state machine controlling the entire lesson lifecycle.

State machine:
  TEACHING → QUESTION → EVALUATING → ADAPTING → RETEACHING/TEACHING → ...
                                                ↓ (if correct)
                                            ASSESSMENT → COMPLETED

Key rules:
- Gemma NEVER updates session state directly.
- Orchestrator interprets agent output and applies state transitions.
- Mastery is calculated deterministically — Gemma does not set mastery scores.
- Student answers genuinely change lesson state.
- Adaptation never repeats the same strategy twice in a row.
"""
import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel

from app.services.mongodb_service import mongodb_service
from app.schemas.session import (
    SessionState, SessionStatus, TeacherOutput, BoardContent, BoardType
)
from app.schemas.evaluation import EvaluationStatus, AdaptationAction
from app.agents.teacher_agent import teacher_agent
from app.agents.visual_agent import visual_agent
from app.agents.question_agent import question_agent
from app.agents.evaluator_agent import evaluator_agent
from app.agents.misconception_agent import misconception_agent
from app.agents.adaptation_agent import adaptation_agent
from app.agents.assessment_agent import assessment_agent
from app.agents.report_agent import report_agent
from app.core.logging import get_logger

logger = get_logger(__name__)

AVATAR_GENERATION_TIMEOUT_SECONDS = 25.0


# ── Avatar sync (best-effort — never blocks or breaks the lesson) ─────────────

async def _attach_avatar(output: "TeacherOutput", language: str) -> "TeacherOutput":
    """
    Best-effort: render `output.spoken_text` as a real talking-avatar clip
    (TTS -> Simli) and attach its URL to the output.

    This is intentionally fail-soft: if Simli/TTS keys are not configured, the
    call times out, or the provider errors, we log a warning and return the
    output unchanged (avatar_video_url stays None). The frontend already knows
    how to fall back to the idle avatar loop in that case — a broken avatar
    provider must never break the teaching loop itself.
    """
    text = (output.spoken_text or "").strip()
    if not text:
        return output

    try:
        from app.services.simli_service import simli_service
    except Exception as e:  # pragma: no cover - import-time failure only
        logger.warning(f"Simli service unavailable: {e}")
        return output

    if not simli_service.api_key:
        output.avatar_video_url = "/static/video/simli_sample.mp4"
        output.avatar_status = "local_simli_talking_video"
        return output

    try:
        result = await asyncio.wait_for(
            simli_service.create_text_to_video_stream(
                text=text,
                language=language,
            ),
            timeout=AVATAR_GENERATION_TIMEOUT_SECONDS,
        )
        video_url = result.get("mp4_url") or result.get("hls_url")
        if video_url:
            output.avatar_video_url = video_url
            output.avatar_status = "generated"
        else:
            output.avatar_video_url = "/static/video/simli_sample.mp4"
            output.avatar_status = "local_simli_talking_video"
    except asyncio.TimeoutError:
        logger.warning("Avatar clip generation timed out — using local Simli avatar video.")
        output.avatar_video_url = "/static/video/simli_sample.mp4"
        output.avatar_status = "timeout_fallback"
    except Exception as e:
        logger.warning(f"Avatar clip generation failed: {e}")
        output.avatar_video_url = "/static/video/simli_sample.mp4"
        output.avatar_status = "generation_failed_fallback"

    return output


# ── Mastery calculation (deterministic — NOT Gemma) ───────────────────────────

def calculate_mastery(attempts: list[dict]) -> float:
    """
    Deterministic mastery calculation based on recency-weighted scores.
    Gemma NEVER calls or controls this function.

    Formula:
    - Recent attempts weighted higher
    - Difficulty multipliers: easy=0.8, medium=1.0, hard=1.3
    - Result clamped to [0.0, 1.0]
    """
    if not attempts:
        return 0.0

    weighted_scores = []
    total_weight = 0.0

    for i, attempt in enumerate(attempts):
        weight = 1.0 + (i * 0.15)   # Recent attempts weighted more
        difficulty_multiplier = {
            "easy": 0.8,
            "medium": 1.0,
            "hard": 1.3,
        }.get(attempt.get("difficulty", "medium"), 1.0)

        score = attempt.get("score", 0.0)
        weighted_scores.append(score * weight * difficulty_multiplier)
        total_weight += weight

    if total_weight == 0:
        return 0.0

    raw = sum(weighted_scores) / total_weight
    return round(min(1.0, max(0.0, raw)), 4)


# ── Session initialization ─────────────────────────────────────────────────────

async def initialize_session(
    learner_id: str,
    lesson_id: str,
) -> SessionState:
    """Create a new learning session in MongoDB and return initial state."""
    session_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    # Load lesson from MongoDB
    lesson = await mongodb_service.lessons.find_one({"_id": lesson_id})
    if not lesson:
        raise ValueError(f"Lesson {lesson_id} not found")

    # Load learner profile
    profile = await mongodb_service.learner_profiles.find_one({"learner_id": learner_id})
    language = "english"
    if profile:
        language = profile.get("preferences", {}).get("language", "english")

    segments = lesson.get("segments", [])
    concept_keys = lesson.get("concept_keys", [])

    session_doc = {
        "_id": session_id,
        "learner_id": learner_id,
        "lesson_id": lesson_id,
        "document_id": lesson.get("document_id"),
        "topic": lesson.get("topic", "Unknown"),
        "status": SessionStatus.teaching.value,
        "current_segment_index": 0,
        "total_segments": len(segments),
        "segments": segments,
        "concept_keys": concept_keys,
        "current_concept": None,
        "current_question": None,
        "last_strategy_used": None,
        "adaptation_count": 0,
        "session_history": [],  # list of action strings for adaptation context
        "taught_concepts": [],
        "start_time": now,
        "elapsed_seconds": 0,
        "language": language,
        "level": lesson.get("level", "beginner"),
        "teaching_style": lesson.get("teaching_style", "simple"),
        "subject": lesson.get("subject", "general"),
        "created_at": now,
        "updated_at": now,
    }

    await mongodb_service.learning_sessions.insert_one(session_doc)

    return SessionState(
        session_id=session_id,
        learner_id=learner_id,
        lesson_id=lesson_id,
        status=SessionStatus.teaching,
        current_segment_index=0,
        total_segments=len(segments),
        language=language,
    )


# ── Get session state ─────────────────────────────────────────────────────────

async def get_session_state(session_id: str) -> SessionState:
    """Load current session state from MongoDB."""
    session = await mongodb_service.learning_sessions.find_one({"_id": session_id})
    if not session:
        raise ValueError(f"Session {session_id} not found")

    mastery = await _get_mastery_snapshot(
        session["learner_id"],
        session.get("concept_keys", []),
    )
    idx = session["current_segment_index"]
    total = session["total_segments"]
    progress = (idx / total * 100) if total > 0 else 0

    return SessionState(
        session_id=session_id,
        learner_id=session["learner_id"],
        lesson_id=session["lesson_id"],
        status=SessionStatus(session["status"]),
        current_segment_index=idx,
        total_segments=total,
        current_concept=session.get("current_concept"),
        current_question=session.get("current_question"),
        adaptation_message=None,
        mastery_snapshot=mastery,
        elapsed_seconds=session.get("elapsed_seconds", 0),
        progress_pct=round(progress, 1),
        language=session.get("language", "english"),
        last_strategy_used=session.get("last_strategy_used"),
    )


# ── Advance lesson ─────────────────────────────────────────────────────────────

async def advance_lesson(session_id: str) -> SessionState:
    """
    Advance the lesson to the next segment and generate teaching content.
    Controls the main teaching loop.
    """
    session = await mongodb_service.learning_sessions.find_one({"_id": session_id})
    if not session:
        raise ValueError(f"Session {session_id} not found")

    idx = session["current_segment_index"]
    segments = session.get("segments", [])
    total = len(segments)

    if idx >= total:
        # All segments done
        await _update_session(session_id, {"status": SessionStatus.completed.value})
        return await get_session_state(session_id)

    current_segment = segments[idx]
    seg_type = current_segment.get("type", "concept")
    concept_key = current_segment.get("concept_key")

    # Update current concept
    update_data: dict = {
        "current_segment_index": idx,
        "current_concept": concept_key,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    # Track taught concepts
    taught = session.get("taught_concepts", [])
    if concept_key and concept_key not in taught:
        taught.append(concept_key)
        update_data["taught_concepts"] = taught

    # Build prior segments summary for context
    prior_summary = _build_prior_summary(segments[:idx])

    # Handle assessment segment
    if seg_type == "assessment":
        await _update_session(session_id, {
            **update_data,
            "status": SessionStatus.assessment.value,
        })
        return await get_session_state(session_id)

    # Handle question segment
    if seg_type == "question":
        q_type = current_segment.get("question_type", "mcq")
        prev_questions = [
            qa.get("question_text", "")
            for qa in await _get_previous_questions(session_id)
        ]

        generated_q = await question_agent.generate_question(
            concept_key=concept_key or "general",
            topic=session.get("topic", ""),
            question_type=q_type,
            level=session.get("level", "beginner"),
            language=session.get("language", "english"),
            document_id=session.get("document_id"),
            previous_questions=prev_questions,
        )

        question_dict = generated_q.model_dump()
        question_dict["question_id"] = str(uuid.uuid4())

        # Store question
        await mongodb_service.questions.insert_one({
            **question_dict,
            "session_id": session_id,
            "segment_index": idx,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

        await _update_session(session_id, {
            **update_data,
            "status": SessionStatus.waiting_for_answer.value,
            "current_question": question_dict,
        })

        state = await get_session_state(session_id)
        # Attach teacher output for the question
        state.teacher_output = TeacherOutput(
            spoken_text=generated_q.question_text,
            board=BoardContent(
                type=BoardType.text,
                content=generated_q.question_text,
                caption=f"Question about: {concept_key.replace('_', ' ') if concept_key else 'this concept'}",
            ),
            segment_type="question",
            segment_title=current_segment.get("title", "Question"),
        )
        await _attach_avatar(state.teacher_output, session.get("language", "english"))
        return state

    # Teaching segment — generate content
    teacher_output = await teacher_agent.teach_segment(
        segment=current_segment,
        topic=session.get("topic", ""),
        level=session.get("level", "beginner"),
        language=session.get("language", "english"),
        teaching_style=session.get("teaching_style", "simple"),
        document_id=session.get("document_id"),
        prior_segments_summary=prior_summary,
        strategy_hint=session.get("last_strategy_used"),
    )

    # For visual/diagram segments, enhance with visual agent
    if seg_type in ("diagram", "graph") and not teacher_output.board:
        visual_board = await visual_agent.generate_visual(
            concept=concept_key or current_segment.get("title", "visual explanation"),
            topic=session.get("topic", ""),
            subject=session.get("subject", "general"),
            level=session.get("level", "beginner"),
            language=session.get("language", "english"),
            source_context="",
        )
        teacher_output.board = visual_board

    # Store interaction
    await mongodb_service.student_interactions.insert_one({
        "session_id": session_id,
        "learner_id": session["learner_id"],
        "segment_index": idx,
        "segment_type": seg_type,
        "segment_title": current_segment.get("title", ""),
        "spoken_text": teacher_output.spoken_text,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    # Move to next segment
    await _update_session(session_id, {
        **update_data,
        "current_segment_index": idx + 1,
        "status": SessionStatus.teaching.value,
    })

    state = await get_session_state(session_id)
    state.teacher_output = teacher_output
    await _attach_avatar(state.teacher_output, session.get("language", "english"))
    return state


# ── Process student answer ─────────────────────────────────────────────────────

async def process_answer(session_id: str, student_answer: str, time_taken: int) -> SessionState:
    """
    Core adaptive loop:
    Student answers → Evaluate → Detect misconception → Adapt → Reteach or Continue.
    """
    session = await mongodb_service.learning_sessions.find_one({"_id": session_id})
    if not session:
        raise ValueError(f"Session {session_id} not found")

    current_question = session.get("current_question")
    if not current_question:
        raise ValueError("No active question for this session")

    concept_key = current_question.get("concept_key", "general")
    learner_id = session["learner_id"]

    # 1. Evaluate the answer
    await _update_session(session_id, {"status": SessionStatus.evaluating.value})
    evaluation = await evaluator_agent.evaluate(
        question=current_question,
        student_answer=student_answer,
        document_id=session.get("document_id"),
    )

    # 2. Store the answer
    answer_doc = {
        "session_id": session_id,
        "learner_id": learner_id,
        "question_id": current_question.get("question_id", ""),
        "question_text": current_question.get("question_text", ""),
        "student_answer": student_answer,
        "time_taken_seconds": time_taken,
        "concept_key": concept_key,
        "difficulty": current_question.get("difficulty", "medium"),
        "evaluation_status": evaluation.status.value,
        "score": evaluation.score,
        "understanding": evaluation.understanding.value,
        "misconception_detected": evaluation.misconception_detected,
        "feedback": evaluation.feedback,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await mongodb_service.student_answers.insert_one(answer_doc)

    # 3. Update mastery (deterministic — not Gemma)
    await _update_mastery(
        learner_id=learner_id,
        concept_key=concept_key,
        score=evaluation.score,
        difficulty=current_question.get("difficulty", "medium"),
    )

    # 4. Detect misconception if needed
    misconception_text = None
    if evaluation.misconception_detected and evaluation.status != EvaluationStatus.correct:
        misconception_result = await misconception_agent.analyze(
            question=current_question,
            student_answer=student_answer,
            concept_key=concept_key,
            topic=session.get("topic", ""),
            document_id=session.get("document_id"),
        )
        misconception_text = misconception_result.explanation

        # Store misconception
        await mongodb_service.misconceptions.insert_one({
            "session_id": session_id,
            "learner_id": learner_id,
            "concept_key": concept_key,
            "misconception_type": misconception_result.misconception_type,
            "explanation": misconception_result.explanation,
            "evidence": misconception_result.evidence,
            "confidence": misconception_result.confidence,
            "student_answer": student_answer,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

    # 5. Decide adaptation
    session_history = session.get("session_history", [])
    last_action = session.get("last_strategy_used")

    adaptation = await adaptation_agent.decide(
        concept_key=concept_key,
        evaluation_status=evaluation.status.value,
        understanding=evaluation.understanding.value,
        misconception=misconception_text,
        session_history=session_history,
        level=session.get("level", "beginner"),
        teaching_style=session.get("teaching_style", "simple"),
        last_action=last_action,
    )

    action = adaptation.action

    # 6. FastAPI validates action and executes
    state = await _execute_adaptation(
        session_id=session_id,
        session=session,
        action=action,
        evaluation=evaluation,
        concept_key=concept_key,
        misconception_text=misconception_text,
        adaptation_reason=adaptation.reason,
        session_history=session_history,
    )

    return state


async def _execute_adaptation(
    session_id: str,
    session: dict,
    action: AdaptationAction,
    evaluation,
    concept_key: str,
    misconception_text: Optional[str],
    adaptation_reason: str,
    session_history: list,
) -> SessionState:
    """
    Execute the validated adaptation action.
    Gemma recommended it — orchestrator controls the execution.
    """
    history_entry = f"Q: {concept_key} → {evaluation.status.value} → {action.value}"
    updated_history = (session_history + [history_entry])[-10:]  # keep last 10

    idx = session["current_segment_index"]
    segments = session.get("segments", [])

    if action == AdaptationAction.CONTINUE or evaluation.status == EvaluationStatus.correct:
        # Student got it right — move forward
        next_idx = idx + 1 if idx < len(segments) else idx
        await _update_session(session_id, {
            "status": SessionStatus.teaching.value,
            "current_segment_index": next_idx,
            "current_question": None,
            "last_strategy_used": None,
            "session_history": updated_history,
        })
        state = await get_session_state(session_id)
        state.teacher_output = TeacherOutput(
            spoken_text=evaluation.feedback or "Well done! Let's continue.",
            segment_type="feedback",
            segment_title="Feedback",
        )
        state.adaptation_message = None
        await _attach_avatar(state.teacher_output, session.get("language", "english"))
        return state

    elif action == AdaptationAction.USE_ANALOGY:
        strategy_hint = "analogy"
    elif action == AdaptationAction.SIMPLIFY:
        strategy_hint = "simplify"
    elif action == AdaptationAction.SHOW_VISUAL:
        strategy_hint = "visual"
    elif action == AdaptationAction.GIVE_EXAMPLE:
        strategy_hint = "example"
    elif action == AdaptationAction.RETEACH:
        strategy_hint = "reteach"
    elif action == AdaptationAction.ASK_EASIER_QUESTION:
        strategy_hint = "easier_question"
    elif action == AdaptationAction.DECREASE_DIFFICULTY:
        strategy_hint = "easier_question"
    elif action == AdaptationAction.INCREASE_DIFFICULTY:
        strategy_hint = "increase_difficulty"
    else:
        strategy_hint = "reteach"

    await _update_session(session_id, {
        "status": SessionStatus.adapting.value,
        "last_strategy_used": action.value,
        "session_history": updated_history,
        "current_question": None,
    })

    # Generate reteach content
    if strategy_hint == "easier_question":
        # Generate a simpler question
        orig_q_text = session.get("current_question", {}).get("question_text", "")
        easier_q = await question_agent.generate_easier_question(
            concept_key=concept_key,
            topic=session.get("topic", ""),
            level=session.get("level", "beginner"),
            language=session.get("language", "english"),
            original_question=orig_q_text,
            document_id=session.get("document_id"),
        )
        q_dict = easier_q.model_dump()
        q_dict["question_id"] = str(uuid.uuid4())

        await mongodb_service.questions.insert_one({
            **q_dict,
            "session_id": session_id,
            "segment_index": idx,
            "is_adaptive": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

        await _update_session(session_id, {
            "status": SessionStatus.waiting_for_answer.value,
            "current_question": q_dict,
        })
        state = await get_session_state(session_id)
        state.teacher_output = TeacherOutput(
            spoken_text=f"{evaluation.feedback}\n\n{easier_q.question_text}",
            board=BoardContent(
                type=BoardType.text,
                content=easier_q.question_text,
                caption="Let's try a simpler question",
            ),
            segment_type="question",
            segment_title="Adaptive Question",
        )
        state.adaptation_message = "📚 Teacher adapted the lesson based on your response."
        await _attach_avatar(state.teacher_output, session.get("language", "english"))
        return state

    else:
        # Generate reteach content with new strategy
        current_segment = segments[idx - 1] if idx > 0 else {"type": "concept", "title": concept_key}
        reteach_segment = {
            **current_segment,
            "type": "reteach",
            "title": f"Let's look at this another way",
        }
        prior_summary = _build_prior_summary(segments[:max(0, idx - 1)])

        teacher_output = await teacher_agent.teach_segment(
            segment=reteach_segment,
            topic=session.get("topic", ""),
            level=session.get("level", "beginner"),
            language=session.get("language", "english"),
            teaching_style=session.get("teaching_style", "simple"),
            document_id=session.get("document_id"),
            prior_segments_summary=prior_summary,
            strategy_hint=strategy_hint,
        )

        # After reteach, generate a new question
        prev_questions = [
            qa.get("question_text", "")
            for qa in await _get_previous_questions(session_id)
        ]
        new_question = await question_agent.generate_question(
            concept_key=concept_key,
            topic=session.get("topic", ""),
            question_type="mcq",
            level=session.get("level", "beginner"),
            language=session.get("language", "english"),
            document_id=session.get("document_id"),
            previous_questions=prev_questions,
        )
        q_dict = new_question.model_dump()
        q_dict["question_id"] = str(uuid.uuid4())

        await mongodb_service.questions.insert_one({
            **q_dict,
            "session_id": session_id,
            "segment_index": idx,
            "is_adaptive": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

        await _update_session(session_id, {
            "status": SessionStatus.waiting_for_answer.value,
            "current_question": q_dict,
            "last_strategy_used": action.value,
        })

        state = await get_session_state(session_id)
        state.teacher_output = teacher_output
        state.adaptation_message = "📚 Teacher adapted the lesson based on your response."
        await _attach_avatar(state.teacher_output, session.get("language", "english"))
        return state


# ── Interruption handlers ──────────────────────────────────────────────────────

async def handle_ask(session_id: str, user_question: str) -> TeacherOutput:
    """
    Handle student asking a question — preserve session position.

    Unlike the rest of the teaching loop, this does NOT read back a wall of
    text. It asks Gemma for a short spoken narration plus a separately
    structured board (steps/formula/bullets/etc. — see build_ask_prompt), so
    equations and multi-step working render properly on the Smart Board
    (KaTeX per step) instead of appearing as raw, unescaped LaTeX text. A
    talking-avatar clip is attached on a best-effort basis so the answer is
    actually spoken, matching how the rest of the lesson behaves.
    """
    session = await mongodb_service.learning_sessions.find_one({"_id": session_id})
    if not session:
        raise ValueError(f"Session {session_id} not found")

    from app.services.ollama_service import ollama_service
    from app.prompts.system_teacher import SYSTEM_TEACHER
    from app.prompts.teaching import build_ask_prompt

    topic = session.get("topic", "")
    language = session.get("language", "english")
    level = session.get("level", "beginner")

    prompt = build_ask_prompt(
        topic=topic,
        user_question=user_question,
        level=level,
        language=language,
    )

    class AskAnswer(BaseModel):
        spoken_text: str
        board: dict
        segment_title: Optional[str] = None

    output: TeacherOutput
    try:
        result = await ollama_service.generate_structured(
            prompt=prompt,
            schema=AskAnswer,
            system=SYSTEM_TEACHER,
            temperature=0.4,
        )
        board = _build_ask_board(result.board)
        output = TeacherOutput(
            spoken_text=result.spoken_text,
            board=board,
            segment_type="ask",
            segment_title=result.segment_title or "Student Question",
        )
    except Exception as e:
        logger.error(f"Ask Teacher structured generation failed: {e}")
        # Conservative fallback — still avoid dumping raw LaTeX/markdown as text
        spoken = await ollama_service.generate(
            prompt=(
                f"Answer this student question briefly (3-4 sentences), in {language}, "
                f"for a {level} learner. Topic: {topic}. Question: {user_question}"
            ),
            system=SYSTEM_TEACHER,
            temperature=0.5,
        )
        output = TeacherOutput(
            spoken_text=spoken,
            board=BoardContent(type=BoardType.text, content=spoken, caption="Your Question"),
            segment_type="ask",
            segment_title="Student Question",
        )

    await _attach_avatar(output, language)
    return output


def _build_ask_board(board_data: dict) -> Optional[BoardContent]:
    """Validate/normalize the board dict returned for an Ask Teacher answer."""
    if not board_data:
        return None
    try:
        board_type = BoardType(board_data.get("type", "text"))
    except ValueError:
        board_type = BoardType.text

    content = board_data.get("content", "")
    # `steps` (and bullets/timeline elsewhere) are JSON arrays — serialize
    # consistently so the frontend's existing JSON.parse(board.content) works.
    if isinstance(content, (list, dict)):
        content = json.dumps(content)

    return BoardContent(
        type=board_type,
        content=str(content),
        caption=board_data.get("caption"),
        language=board_data.get("language"),
    )


async def handle_simplify(session_id: str) -> TeacherOutput:
    """Simplify the current explanation."""
    session = await mongodb_service.learning_sessions.find_one({"_id": session_id})
    if not session:
        raise ValueError(f"Session {session_id} not found")

    idx = max(0, session["current_segment_index"] - 1)
    segments = session.get("segments", [])
    current_seg = segments[idx] if segments else {"title": session.get("topic", "")}

    from app.prompts.teaching import build_simplify_prompt
    from app.services.ollama_service import ollama_service
    from app.prompts.system_teacher import SYSTEM_TEACHER

    prompt = build_simplify_prompt(
        concept=current_seg.get("concept_key") or current_seg.get("title", ""),
        previous_explanation="(previous segment content)",
        level=session.get("level", "beginner"),
        language=session.get("language", "english"),
    )

    import json
    raw = await ollama_service.generate(prompt=prompt, system=SYSTEM_TEACHER, temperature=0.5)
    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        data = json.loads(raw[start:end])
        spoken = data.get("spoken_text", raw[:300])
        board_data = data.get("board", {})
        board = BoardContent(
            type=BoardType.text,
            content=board_data.get("content", spoken),
            caption="Simpler Explanation",
        ) if board_data else None
    except Exception:
        spoken = raw[:400]
        board = None

    return TeacherOutput(
        spoken_text=spoken,
        board=board,
        segment_type="simplify",
        segment_title="Simpler Explanation",
    )


async def handle_language_switch(session_id: str, language: str) -> dict:
    """Switch lesson language while preserving all session state."""
    await _update_session(session_id, {
        "language": language,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"message": f"Language switched to {language}", "language": language}


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _update_session(session_id: str, update: dict) -> None:
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    await mongodb_service.learning_sessions.update_one(
        {"_id": session_id},
        {"$set": update},
    )


async def _update_mastery(
    learner_id: str,
    concept_key: str,
    score: float,
    difficulty: str,
) -> None:
    """Update concept mastery using deterministic calculation."""
    # Upsert mastery record
    existing = await mongodb_service.concept_mastery.find_one(
        {"learner_id": learner_id, "concept_key": concept_key}
    )

    attempt = {
        "score": score,
        "difficulty": difficulty,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if existing:
        attempts = existing.get("attempts", []) + [attempt]
        mastery_score = calculate_mastery(attempts)
        await mongodb_service.concept_mastery.update_one(
            {"learner_id": learner_id, "concept_key": concept_key},
            {
                "$set": {
                    "mastery_score": mastery_score,
                    "attempt_count": len(attempts),
                    "last_updated": datetime.now(timezone.utc).isoformat(),
                },
                "$push": {"attempts": attempt},
            },
        )
    else:
        mastery_score = calculate_mastery([attempt])
        await mongodb_service.concept_mastery.insert_one({
            "learner_id": learner_id,
            "concept_key": concept_key,
            "mastery_score": mastery_score,
            "attempt_count": 1,
            "attempts": [attempt],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_updated": datetime.now(timezone.utc).isoformat(),
        })


async def _get_mastery_snapshot(
    learner_id: str,
    concept_keys: list[str],
) -> dict[str, float]:
    """Get current mastery scores for concepts."""
    if not concept_keys:
        return {}

    cursor = mongodb_service.concept_mastery.find(
        {"learner_id": learner_id, "concept_key": {"$in": concept_keys}},
        {"concept_key": 1, "mastery_score": 1},
    )
    docs = await cursor.to_list(None)
    return {d["concept_key"]: d.get("mastery_score", 0.0) for d in docs}


async def _get_previous_questions(session_id: str) -> list[dict]:
    """Get previous questions for this session."""
    cursor = mongodb_service.questions.find(
        {"session_id": session_id},
        {"question_text": 1},
    )
    return await cursor.to_list(10)


def _build_prior_summary(segments: list[dict]) -> str:
    """Build a brief summary of prior lesson segments."""
    if not segments:
        return ""
    titles = [s.get("title", s.get("type", "segment")) for s in segments[-3:]]
    return "Previously covered: " + ", ".join(titles)
