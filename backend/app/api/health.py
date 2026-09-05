"""
Health check endpoints — return actual status, never hard-coded.
"""
from fastapi import APIRouter
from app.services.ollama_service import ollama_service, OllamaConnectionError
from app.services.mongodb_service import mongodb_service

router = APIRouter()


@router.get("/api/health")
@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/api/health/dependencies")
@router.get("/health/dependencies")
async def health_dependencies():
    """Return actual dependency status — tests all connections live."""
    result = {
        "mongodb": "unknown",
        "ollama": "unknown",
        "gemma4": "unknown",
        "embedding_model": "unknown",
    }

    # MongoDB
    try:
        mongo_ok = await mongodb_service.health_check()
        result["mongodb"] = "connected" if mongo_ok else "error"
    except Exception as e:
        result["mongodb"] = f"error: {str(e)[:80]}"

    # Ollama + model availability
    try:
        ollama_status = await ollama_service.check_availability()
        result["ollama"] = "connected"
        result["gemma4"] = "available" if ollama_status["gemma4_available"] else "not_found"
        result["embedding_model"] = "available" if ollama_status["embedding_available"] else "not_found"
        result["available_models"] = ollama_status.get("available_models", [])
    except OllamaConnectionError as e:
        result["ollama"] = f"error: {str(e)[:80]}"
        result["gemma4"] = "unknown"
        result["embedding_model"] = "unknown"
    except Exception as e:
        result["ollama"] = f"error: {str(e)[:80]}"

    return result
