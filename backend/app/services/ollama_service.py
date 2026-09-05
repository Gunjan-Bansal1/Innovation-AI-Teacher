"""
Ollama Service — ALL LLM and embedding calls go through here.

Architecture:
    Browser → FastAPI → ollama_service.py → Ollama API → gemma4:31b-cloud

Rules:
- Routes must NOT call Ollama directly.
- Frontend must NEVER call Ollama directly.
- Structured output is validated against Pydantic models.
- Failed JSON is retried once, then raises OllamaStructuredOutputError.
- Never silently falls back to another model.
"""
import json
import asyncio
from typing import Any, Optional, Type, TypeVar
import httpx
from pydantic import BaseModel

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


class OllamaConnectionError(Exception):
    """Raised when Ollama is unreachable."""


class OllamaModelUnavailableError(Exception):
    """Raised when the required model is not available."""


class OllamaTimeoutError(Exception):
    """Raised when Ollama takes too long to respond."""


class OllamaStructuredOutputError(Exception):
    """Raised when structured JSON output fails to parse after retry."""


class OllamaService:
    def __init__(self) -> None:
        self.base_url = settings.ollama_base_url
        self.model = settings.ollama_model
        self.timeout = settings.ollama_timeout
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout, connect=10.0),
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def check_availability(self) -> dict[str, Any]:
        """
        Verify Ollama is running and gemma4:31b-cloud is available.
        Returns actual status — never hard-coded.
        """
        try:
            client = self._get_client()
            resp = await client.get("/api/tags")
            resp.raise_for_status()
            data = resp.json()
            models = [m["name"] for m in data.get("models", [])]
            gemma_available = self.model in models
            # Match embedding model by prefix (e.g. model matches model:latest)
            embed_available = any(
                m == settings.embedding_model or m.startswith(settings.embedding_model + ":")
                for m in models
            )
            return {
                "ollama": "connected",
                "model": self.model,
                "gemma4_available": gemma_available,
                "embedding_model": settings.embedding_model,
                "embedding_available": embed_available,
                "available_models": models,
            }
        except httpx.ConnectError as e:
            raise OllamaConnectionError(
                f"Cannot connect to Ollama at {self.base_url}: {e}"
            )
        except httpx.TimeoutException as e:
            raise OllamaTimeoutError(f"Ollama health check timed out: {e}")

    async def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.7,
        stream: bool = False,
    ) -> str:
        """
        Generate raw text from gemma4:31b-cloud.
        Raises typed errors — never swallows failures.
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": stream,
            "options": {"temperature": temperature},
        }
        if system:
            payload["system"] = system

        try:
            client = self._get_client()
            logger.debug(
                "Ollama generate request",
                extra={"model": self.model, "prompt_length": len(prompt)},
            )
            resp = await client.post("/api/generate", json=payload)
            resp.raise_for_status()
            data = resp.json()
            text = data.get("response", "")
            if not text:
                raise OllamaStructuredOutputError("Empty response from Ollama")
            return text.strip()

        except httpx.ConnectError as e:
            raise OllamaConnectionError(
                f"Cannot connect to Ollama at {self.base_url}: {e}"
            )
        except httpx.TimeoutException as e:
            raise OllamaTimeoutError(
                f"Ollama request timed out after {self.timeout}s: {e}"
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise OllamaModelUnavailableError(
                    f"Model {self.model} not found. "
                    f"Run: ollama pull {self.model}"
                )
            raise OllamaConnectionError(
                f"Ollama returned HTTP {e.response.status_code}: {e.response.text}"
            )

    async def generate_structured(
        self,
        prompt: str,
        schema: Type[T],
        system: Optional[str] = None,
        temperature: float = 0.3,
    ) -> T:
        """
        Generate structured JSON output validated against a Pydantic schema.
        Retries once on JSON parse failure.
        Raises OllamaStructuredOutputError if both attempts fail.
        Never silently invents missing fields.
        """
        json_instruction = (
            f"\n\nYou MUST respond with ONLY valid JSON matching this schema:\n"
            f"{json.dumps(schema.model_json_schema(), indent=2)}\n"
            f"Do NOT include any text before or after the JSON. "
            f"Do NOT add markdown code fences. Output raw JSON only."
        )

        full_prompt = prompt + json_instruction

        for attempt in range(2):
            try:
                raw = await self.generate(
                    prompt=full_prompt,
                    system=system,
                    temperature=temperature,
                )
                # Strip markdown code fences if present
                cleaned = raw.strip()
                if cleaned.startswith("```"):
                    lines = cleaned.split("\n")
                    cleaned = "\n".join(lines[1:-1]) if len(lines) > 2 else cleaned

                parsed = schema.model_validate_json(cleaned)
                return parsed

            except Exception as e:
                if attempt == 0:
                    logger.warning(
                        f"Structured output attempt 1 failed: {e}. Retrying...",
                        extra={"schema": schema.__name__},
                    )
                    await asyncio.sleep(1)
                    continue
                raise OllamaStructuredOutputError(
                    f"Failed to get valid {schema.__name__} JSON after 2 attempts. "
                    f"Last error: {e}"
                )

        raise OllamaStructuredOutputError("Unexpected end of retry loop")

    async def embed(self, text: str) -> list[float]:
        """
        Generate embeddings for a text using the configured Ollama embedding model.
        """
        try:
            client = self._get_client()
            resp = await client.post(
                "/api/embeddings",
                json={"model": settings.embedding_model, "prompt": text},
            )
            resp.raise_for_status()
            data = resp.json()
            embedding = data.get("embedding", [])
            if not embedding:
                raise OllamaConnectionError(
                    f"Empty embedding returned for model {settings.embedding_model}. "
                    f"Ensure it is pulled: ollama pull {settings.embedding_model}"
                )
            return embedding

        except httpx.ConnectError as e:
            raise OllamaConnectionError(
                f"Cannot connect to Ollama for embeddings: {e}"
            )
        except httpx.TimeoutException as e:
            raise OllamaTimeoutError(f"Embedding request timed out: {e}")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise OllamaModelUnavailableError(
                    f"Embedding model {settings.embedding_model} not found. "
                    f"Run: ollama pull {settings.embedding_model}"
                )
            raise OllamaConnectionError(
                f"Ollama embedding error HTTP {e.response.status_code}: {e.response.text}"
            )

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts sequentially (Ollama doesn't support true batch)."""
        results = []
        for text in texts:
            emb = await self.embed(text)
            results.append(emb)
        return results


# Singleton instance
ollama_service = OllamaService()
