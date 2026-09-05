"""
Avatar API — endpoints for Simli AI Avatar sessions and video feeds.
"""
import os
import uuid
from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel
from typing import Optional
from app.services.simli_service import simli_service
from app.services.video_generation_service import video_generation_service, VideoGenerationError
from app.services.lesson_script_service import lesson_script_service
from app.services.mongodb_service import mongodb_service
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/avatar", tags=["avatar"])


class SpeechRequest(BaseModel):
    text: str
    language: Optional[str] = "english"
    voice_name: Optional[str] = None


@router.get("/speech")
@router.post("/speech")
async def generate_speech(
    text: Optional[str] = Query(None),
    language: Optional[str] = Query("english"),
    voice_name: Optional[str] = Query(None),
    body: Optional[SpeechRequest] = None,
):
    """
    Generate MP3 speech audio for spoken text using configured TTS (Edge-TTS / ElevenLabs).
    """
    input_text = (body.text if body else None) or text or ""
    input_text = input_text.strip()
    if not input_text:
        raise HTTPException(status_code=400, detail="Text is required")

    input_lang = (body.language if body else None) or language or "english"
    input_voice = (body.voice_name if body else None) or voice_name

    try:
        tts_provider = (settings.tts_provider or "edge-tts").strip().lower()
        if tts_provider == "elevenlabs" and simli_service.elevenlabs_api_key:
            selected_voice = input_voice or settings.elevenlabs_voice_id or "pMsXgVXv3BLzUgSXRplE"
            audio_bytes = await simli_service._generate_elevenlabs_audio(input_text, selected_voice)
        else:
            selected_voice = input_voice or simli_service._default_edge_voice(input_lang)
            audio_bytes = await simli_service._generate_edge_tts_audio(input_text, selected_voice)

        return Response(content=audio_bytes, media_type="audio/mpeg")
    except Exception as e:
        logger.error(f"Speech generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))




class AvatarSessionRequest(BaseModel):
    face_id: Optional[str] = None


class LessonVideoRequest(BaseModel):
    lesson_id: str
    max_duration_seconds: int = 90


class TopicVideoRequest(BaseModel):
    topic: str
    level: str = "beginner"
    language: str = "english"
    teaching_style: str = "simple"
    duration_seconds: int = 60
    face_id: Optional[str] = None
    voice_name: Optional[str] = None
    document_id: Optional[str] = None
    custom_question: Optional[str] = None


async def _get_document_context(document_id: Optional[str], query: str) -> str:
    """Retrieve grounded text from uploaded document for custom question video generation."""
    if not document_id:
        return ""

    # 1. Try vector RAG retrieval first
    try:
        from app.rag.retriever import retrieve_context
        res = await retrieve_context(query=query, document_id=document_id, top_k=5)
        if res.get("has_sufficient_context") and res.get("context_text"):
            return res["context_text"]
    except Exception as e:
        logger.warning(f"RAG retrieval failed for doc {document_id}: {e}")

    # 2. Fallback to raw document chunks from mongodb
    try:
        cursor = mongodb_service.document_chunks.find(
            {"document_id": document_id},
            {"text": 1},
        ).limit(6)
        chunks = await cursor.to_list(6)
        if chunks:
            return "\n\n".join(c["text"] for c in chunks if c.get("text"))
    except Exception as e:
        logger.warning(f"Direct chunk fetch failed for doc {document_id}: {e}")

    # 3. Fallback to document metadata if available
    try:
        doc = await mongodb_service.documents.find_one({"_id": document_id})
        if doc:
            sections = doc.get("detected_sections", [])
            chapters = doc.get("detected_chapters", [])
            if sections or chapters:
                return f"Document: {doc.get('filename')}\nChapters: {', '.join(chapters)}\nSections: {', '.join(sections)}"
    except Exception as e:
        logger.warning(f"Document lookup failed for doc {document_id}: {e}")

    return ""


def build_visual_storyboard(topic: str, teaching_style: str = "visual") -> list[dict]:
    clean_topic = topic.strip() or "Topic"
    return [
        {
            "type": "flow",
            "title": f"{clean_topic}: big picture",
            "description": f"Start with the main idea, then connect it to parts, examples, and learner checks.",
            "labels": [clean_topic, "Key parts", "Example", "Check"],
        },
        {
            "type": "diagram",
            "title": "Labeled concept diagram",
            "description": f"Show {clean_topic} as labeled blocks so the learner can see how each part connects.",
            "labels": ["Input", "Process", "Result"],
        },
        {
            "type": "chart",
            "title": "Simple comparison chart",
            "description": f"Compare the most important points in {clean_topic} using short visual bars.",
            "labels": ["Definition", "Example", "Common mistake"],
        },
        {
            "type": "recap",
            "title": "Revision map",
            "description": f"End with a small map of what to remember and what to practice next.",
            "labels": ["Remember", "Practice", "Next"],
        },
    ]


async def build_script_matched_visual_storyboard(topic: str, script: str, duration_seconds: int) -> list[dict]:
    try:
        return await lesson_script_service.generate_visual_storyboard_from_script(
            topic=topic,
            script=script,
            duration_seconds=duration_seconds,
        )
    except Exception as visual_error:
        logger.error(f"Script-matched visual storyboard failed: {visual_error}")
        return build_visual_storyboard(topic)


@router.post("/session")
async def create_avatar_session(body: Optional[AvatarSessionRequest] = None):
    """
    Create a new Simli WebRTC session for the live AI Teacher avatar.
    Returns session token for browser WebRTC connection.
    """
    try:
        face_id = body.face_id if body else None
        session_info = await simli_service.create_session(face_id)
        return {
            "status": "success",
            "provider": "simli",
            **session_info,
        }
    except Exception as e:
        logger.error(f"Error starting Simli avatar session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/lesson-video")
async def generate_lesson_video(body: LessonVideoRequest):
    """
    Generate a local MP4 lesson video from a saved lesson plan.

    This creates a demo-ready video by looping the teacher avatar clip and adding
    timed lesson captions. Use `/api/avatar/session` for live Simli avatar sessions.
    """
    lesson = await mongodb_service.lessons.find_one({"_id": body.lesson_id})
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")

    max_duration = max(8, min(body.max_duration_seconds, 180))
    try:
        result = await video_generation_service.generate_lesson_video(
            lesson=lesson,
            max_duration_seconds=max_duration,
        )
        await mongodb_service.db["generated_videos"].insert_one({
            "_id": result["video_id"],
            "lesson_id": body.lesson_id,
            **result,
        })
        return result
    except VideoGenerationError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/topic-video")
async def generate_topic_video(body: TopicVideoRequest):
    """
    Generate a local MP4 teaching video directly from a user topic.

    This path does not require a pre-existing lesson or live LLM call, so a demo
    video can still be created when Ollama/Simli are not running.
    """
    topic = (body.custom_question or body.topic).strip()
    if not topic:
        raise HTTPException(status_code=400, detail="Topic or question is required")

    duration = max(20, min(body.duration_seconds, 180))
    segment_seconds = max(5, min(12, duration // 5))
    concept_key = topic.lower().replace(" ", "_")[:80]
    visual_storyboard = build_visual_storyboard(topic, body.teaching_style)
    lesson = {
        "_id": f"topic-video-{topic[:40]}",
        "topic": topic,
        "title": f"{topic} Teaching Video",
        "duration_seconds": duration,
        "language": body.language,
        "teaching_style": body.teaching_style,
        "level": body.level,
        "document_id": body.document_id,
        "custom_question": body.custom_question,
        "segments": [
            {
                "type": "introduction",
                "title": f"Welcome to {topic}",
                "duration_seconds": segment_seconds,
                "description": f"A {body.level} friendly introduction in {body.language}.",
            },
            {
                "type": "concept",
                "title": f"Core idea of {topic}",
                "concept_key": concept_key,
                "duration_seconds": segment_seconds,
                "description": f"Explain the main concept with a {body.teaching_style} teaching style.",
            },
            {
                "type": "example",
                "title": f"Simple example for {topic}",
                "duration_seconds": segment_seconds,
                "example_description": "Use a relatable example so the learner can connect the idea to real life.",
            },
            {
                "type": "diagram",
                "title": f"Visual explanation of {topic}",
                "duration_seconds": segment_seconds,
                "diagram_description": visual_storyboard[1]["description"],
            },
            {
                "type": "graph",
                "title": f"Chart for {topic}",
                "duration_seconds": segment_seconds,
                "graph_description": visual_storyboard[2]["description"],
            },
            {
                "type": "question",
                "title": f"Check your understanding of {topic}",
                "concept_key": concept_key,
                "duration_seconds": segment_seconds,
                "question_type": "short_answer",
            },
            {
                "type": "summary",
                "title": f"What to revise next after {topic}",
                "duration_seconds": segment_seconds,
                "description": "Summarize key points and recommend the next revision step.",
            },
        ],
    }

    try:
        result = await video_generation_service.generate_lesson_video(
            lesson=lesson,
            max_duration_seconds=duration,
        )
        video_id = result.get("video_id", f"video-{uuid.uuid4().hex[:8]}")
        try:
            if mongodb_service._db is not None:
                await mongodb_service.db["generated_videos"].insert_one({
                    "_id": video_id,
                    "topic": topic,
                    "source": "topic",
                    "document_id": body.document_id,
                    "custom_question": body.custom_question,
                    "visual_storyboard": visual_storyboard,
                    **result,
                })
        except Exception as mongo_err:
            logger.warning(f"Could not persist topic video record to MongoDB: {mongo_err}")

        result["topic"] = topic
        result["visual_storyboard"] = visual_storyboard
        result["document_id"] = body.document_id
        result["custom_question"] = body.custom_question
        return result
    except VideoGenerationError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/simli-topic-video")
async def generate_simli_topic_video(body: TopicVideoRequest):
    """
    Generate a real Simli talking-avatar video stream from a user topic and/or document.

    Flow: user topic/custom question + optional document -> Gemma script -> ElevenLabs/Edge-TTS voice -> Simli avatar video.
    If Simli API hits a rate limit or error, automatically falls back to local video generation.
    """
    topic = (body.custom_question or body.topic).strip()
    if not topic:
        raise HTTPException(status_code=400, detail="Topic or custom question is required")

    duration = max(30, min(body.duration_seconds, 180))
    try:
        doc_context = await _get_document_context(body.document_id, topic)

        script = await lesson_script_service.generate_topic_script(
            topic=topic,
            level=body.level,
            language=body.language,
            teaching_style=body.teaching_style,
            duration_seconds=duration,
            document_context=doc_context,
            custom_question=body.custom_question,
        )
        visual_storyboard = await build_script_matched_visual_storyboard(topic, script, duration)

        simli_failed = False
        simli_error_msg = ""
        result = {}

        try:
            result = await simli_service.create_text_to_video_stream(
                text=script,
                face_id=body.face_id,
                voice_name=body.voice_name,
                language=body.language,
            )
        except Exception as simli_err:
            simli_failed = True
            simli_error_msg = str(simli_err)
            logger.warning(f"Simli cloud generation rate-limited or failed ({simli_err}), activating automatic local generator fallback.")

        if not simli_failed and (result.get("hls_url") or result.get("mp4_url")):
            source_video_url = result.get("hls_url") or result.get("mp4_url")
            composed_result = {
                "video_url": source_video_url,
                "provider": result.get("provider", "simli_talking_avatar"),
            }
            try:
                visual_res = await video_generation_service.generate_visual_avatar_video(
                    source_video_url=source_video_url,
                    topic=topic,
                    visual_storyboard=visual_storyboard,
                    max_duration_seconds=duration,
                )
                composed_result.update(visual_res)
                composed_result["source_avatar_url"] = source_video_url
            except Exception as compose_error:
                logger.warning(f"Visual video overlay skipped (using direct Simli video): {compose_error}")

            response_result = {**result, **composed_result}
        else:
            # Automatic graceful fallback to local generator with real Simli avatar
            segment_seconds = max(5, min(12, duration // 5))
            concept_key = topic.lower().replace(" ", "_")[:80]
            fallback_lesson = {
                "_id": f"simli-fallback-{topic[:40]}",
                "topic": topic,
                "title": f"{topic} Teaching Video",
                "duration_seconds": duration,
                "language": body.language,
                "teaching_style": body.teaching_style,
                "level": body.level,
                "document_id": body.document_id,
                "custom_question": body.custom_question,
                "segments": [
                    {
                        "type": "introduction",
                        "title": f"Welcome to {topic}",
                        "duration_seconds": segment_seconds,
                        "description": script[:200],
                    },
                    {
                        "type": "concept",
                        "title": f"Understanding {topic}",
                        "concept_key": concept_key,
                        "duration_seconds": segment_seconds,
                        "description": script[200:500] if len(script) > 200 else script,
                    },
                    {
                        "type": "diagram",
                        "title": f"Visual breakdown of {topic}",
                        "duration_seconds": segment_seconds,
                        "diagram_description": visual_storyboard[1]["description"] if len(visual_storyboard) > 1 else topic,
                    },
                ],
            }
            local_res = await video_generation_service.generate_lesson_video(
                lesson=fallback_lesson,
                max_duration_seconds=duration,
            )
            response_result = {
                "provider": "simli_local_fallback",
                "notice": "Simli cloud API rate-limited; automatically rendered via high-performance local generator.",
                **local_res,
            }

        video_doc = {
            "topic": topic,
            "source": "gemma_to_simli",
            "script": script,
            "visual_storyboard": visual_storyboard,
            "duration_seconds": duration,
            "document_id": body.document_id,
            "custom_question": body.custom_question,
            **response_result,
        }
        saved_id = f"video-{uuid.uuid4().hex[:8]}"
        try:
            if mongodb_service._db is not None:
                insert_result = await mongodb_service.db["generated_videos"].insert_one(video_doc)
                saved_id = str(insert_result.inserted_id)
        except Exception as mongo_err:
            logger.warning(f"Could not persist Simli video record to MongoDB: {mongo_err}")

        return {
            "video_id": saved_id,
            "topic": topic,
            "script": script,
            "visual_storyboard": visual_storyboard,
            "document_id": body.document_id,
            "custom_question": body.custom_question,
            **response_result,
        }
    except Exception as e:
        logger.error(f"Gemma to Simli video generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
