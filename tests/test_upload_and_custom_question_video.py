"""
Tests for the streamlined Upload & Custom Question Video pipeline.
Verifies that:
1. Setup page renders only the upload section and custom question input (no preference buttons).
2. /api/topics/analyze handles custom questions.
3. /api/avatar/topic-video handles document_id and custom_question without errors.
"""
import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

backend_path = str(Path(__file__).parent.parent / "backend")
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from app.main import app

client = TestClient(app)


def test_setup_page_ui_elements():
    """Verify setup page supports both document mode (streamlined) and topic mode (restored)."""
    # 1. Document Mode
    r_doc = client.get("/setup?mode=document")
    assert r_doc.status_code == 200
    html_doc = r_doc.text
    assert "Upload Your Learning Material" in html_doc
    assert "Drop your file here" in html_doc
    assert "file-input" in html_doc
    assert "Your Custom Question or Topic" in html_doc
    assert "custom-question" in html_doc
    assert "explain population vs sample with examples" in html_doc
    assert "Analyze &amp; Generate Video" in html_doc or "Analyze & Generate Video" in html_doc
    assert "Open Interactive Lesson Plan &amp; Classroom" in html_doc or "Open Interactive Lesson Plan & Classroom" in html_doc

    # 2. Topic Mode (Restored)
    r_topic = client.get("/setup?mode=topic")
    assert r_topic.status_code == 200
    html_topic = r_topic.text
    assert "What do you want to learn?" in html_topic
    assert "topic-video-btn" in html_topic
    assert "Create video from this topic" in html_topic
    assert 'name="level"' in html_topic
    assert 'name="available_time"' in html_topic
    assert 'name="teaching_style"' in html_topic
    assert 'name="depth"' in html_topic
    assert 'id="objective-select"' in html_topic
    assert "Analyze Topic" in html_topic


def test_topic_analyze_with_custom_question():
    """Verify /api/topics/analyze accepts custom_question."""
    body = {
        "topic": "Statistics",
        "custom_question": "explain population vs sample with examples",
        "level": "beginner"
    }
    r = client.post("/api/topics/analyze", json=body)
    assert r.status_code in [200, 500]  # 200 if Ollama is running, or 500 Ollama error (not 422 validation error)
    if r.status_code == 200:
        data = r.json()
        assert "concepts" in data


def test_topic_video_with_custom_question_and_doc():
    """Verify /api/avatar/topic-video accepts custom_question and document_id."""
    body = {
        "topic": "Statistics",
        "custom_question": "explain population vs sample with examples",
        "level": "beginner",
        "language": "english",
        "teaching_style": "visual",
        "duration_seconds": 25,
        "document_id": "test-doc-id-123"
    }
    r = client.post("/api/avatar/topic-video", json=body)
    assert r.status_code == 200
    data = r.json()
    assert "video_id" in data
    assert data["topic"] == "explain population vs sample with examples"
    assert data["document_id"] == "test-doc-id-123"
    assert data["custom_question"] == "explain population vs sample with examples"
