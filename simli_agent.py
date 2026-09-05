import logging
import os

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    WorkerOptions,
    WorkerType,
    cli,
)
from livekit.plugins import openai, simli

# from livekit.plugins import deepgram, elevenlabs, silero

logger = logging.getLogger("simli-avatar-example")
logger.setLevel(logging.INFO)

load_dotenv(override=True)


async def entrypoint(ctx: JobContext):
    openai_key = os.getenv("OPENAI_API_KEY")
    
    # If OPENAI_API_KEY is provided, use OpenAI Realtime. Otherwise, use local Ollama!
    if openai_key and openai_key.strip().startswith("sk-"):
        logger.info("Using OpenAI Realtime model (voice: alloy)")
        llm = openai.realtime.RealtimeModel(voice="alloy")
    else:
        ollama_base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        ollama_model = os.getenv("OLLAMA_MODEL", "gemma4:31b-cloud")
        logger.info(f"Using local Ollama model: {ollama_model} at {ollama_base}/v1")
        llm = openai.LLM.with_ollama(
            model=ollama_model,
            base_url=f"{ollama_base}/v1",
        )

    session = AgentSession(llm=llm)

    simliAPIKey = os.getenv("SIMLI_API_KEY") or os.getenv("API_KEY")
    simliFaceID = os.getenv("SIMLI_FACE_ID", "cace3ef7-a4c4-425d-a8cf-a5358eb0c427")
    if not simliAPIKey:
        raise RuntimeError("SIMLI_API_KEY is required for the LiveKit Simli avatar agent.")

    simli_avatar = simli.AvatarSession(
        simli_config=simli.SimliConfig(
            api_key=simliAPIKey,
            face_id=simliFaceID,
        ),
    )
    await simli_avatar.start(session, room=ctx.room)

    # start the agent, it will join the room and wait for the avatar to join
    await session.start(
        agent=Agent(instructions="Talk to me!"),
        room=ctx.room,
    )


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, worker_type=WorkerType.ROOM))
