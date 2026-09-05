import sys
from pathlib import Path
import pytest
import httpx

backend_path = str(Path(__file__).parent.parent / "backend")
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from fastapi.testclient import TestClient
from app.main import app

BASE_URL = "http://localhost:8000"
_client = TestClient(app)


def _get(path: str, timeout: int = 10):
    try:
        return httpx.get(f"{BASE_URL}{path}", timeout=timeout)
    except httpx.ConnectError:
        return _client.get(path)


def test_health_endpoint():
    """Test basic health endpoint returns 200."""
    r = _get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"


def test_health_dependencies():
    """Test dependency health returns actual status."""
    r = _get("/health/dependencies", timeout=30)
    assert r.status_code == 200
    data = r.json()

    # Should have all required keys
    assert "mongodb" in data
    assert "ollama" in data
    assert "gemma4" in data
    assert "embedding_model" in data

    # Verify actual connectivity
    assert data["mongodb"] == "connected", f"MongoDB not connected: {data['mongodb']}"
    assert data["ollama"] == "connected", f"Ollama not connected: {data['ollama']}"
    assert data["gemma4"] == "available", f"gemma4:31b-cloud not available: {data['gemma4']}"


def test_homepage_loads():
    """Test homepage returns HTML."""
    r = _get("/")
    assert r.status_code == 200
    assert "AI Teacher" in r.text
    assert "learn today" in r.text.lower()

