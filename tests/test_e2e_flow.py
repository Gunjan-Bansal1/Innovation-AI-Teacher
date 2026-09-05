import sys
import time
import httpx

BASE_URL = "http://127.0.0.1:8000"

def run_tests():
    client = httpx.Client(base_url=BASE_URL, timeout=120.0)
    print("Testing health endpoints...")
    r = client.get("/health")
    assert r.status_code == 200, f"Health failed: {r.text}"
    print("[OK] Health endpoint OK")

    r = client.get("/health/dependencies")
    assert r.status_code == 200, f"Dependencies failed: {r.text}"
    deps = r.json()
    print("[OK] Dependencies:", deps)
    assert deps["mongodb"] == "connected"
    assert deps["ollama"] == "connected"

    print("\n1. Testing Learner Profile Creation...")
    learner_data = {
        "name": "Test Student",
        "preferences": {
            "depth_level": "standard",
            "communication_style": "encouraging",
            "pace": "moderate",
            "analogy_domain": "sports",
            "learning_goal": "Learn Python basics",
            "target_duration_minutes": 30
        }
    }
    r = client.post("/api/learners", json=learner_data)
    assert r.status_code == 200, f"Learner creation failed: {r.status_code} {r.text}"
    learner = r.json()
    learner_id = learner["learner_id"]
    print(f"[OK] Learner created: id={learner_id}, name={learner['name']}")

    print("\n2. Testing Document Upload & RAG...")
    doc_content = b"""# Introduction to Python Programming
Python is a high-level, general-purpose programming language. Its design philosophy emphasizes code readability with the use of significant indentation.
Python is dynamically-typed and garbage-collected. It supports multiple programming paradigms, including structured, object-oriented and functional programming.
Key features of Python include easy syntax, rich standard library, and strong community support. Variables in Python do not need explicit declaration to reserve memory space.
Functions in Python are defined using the def keyword.
Loops can be for loops or while loops.
Lists, tuples, dictionaries, and sets are standard collection data types in Python.
"""
    files = {"file": ("python_intro.txt", doc_content, "text/plain")}
    r = client.post("/api/documents/upload", files=files)
    assert r.status_code == 200, f"Document upload failed: {r.status_code} {r.text}"
    doc_res = r.json()
    doc_id = doc_res["document_id"]
    print(f"[OK] Document uploaded: id={doc_id}, initial status={doc_res['embedding_status']}")

    print("Waiting for embedding status to become complete...")
    for i in range(30):
        time.sleep(1)
        r = client.get(f"/api/documents/{doc_id}")
        if r.status_code == 200:
            doc_info = r.json()
            status = doc_info.get("embedding_status")
            print(f"  Attempt {i+1}: status={status}")
            if status == "complete":
                break
            elif status == "error":
                raise RuntimeError(f"Embedding failed: {doc_info.get('embedding_error')}")
    else:
        raise TimeoutError("Document embedding timed out")

    print(f"[OK] Document embedded successfully with {doc_info.get('chunk_count', 0)} chunks!")

    print("\n3. Testing Document RAG Semantic Search...")
    r = client.post(f"/api/documents/{doc_id}/search", json={"query": "How are functions defined in Python?", "top_k": 2})
    assert r.status_code == 200, f"Search failed: {r.text}"
    search_res = r.json()
    print(f"[OK] Search returned {len(search_res.get('chunks', []))} chunks")

    print("\n4. Testing Topic Extraction/Decomposition with LLM...")
    topic_req = {
        "topic": "Python Functions and Syntax",
        "document_id": doc_id,
        "level": "beginner"
    }
    r = client.post("/api/topics/analyze", json=topic_req)
    assert r.status_code == 200, f"Topic analyze failed: {r.text}"
    topics_res = r.json()
    concepts = topics_res.get("concepts", [])
    print(f"[OK] Topic analyzed: subject={topics_res.get('subject')}, concepts={len(concepts)}")
    for c in concepts[:3]:
        print(f"  - Concept: {c.get('name') or c.get('title') or c}")

    print("\n5. Testing Lesson Plan Generation...")
    lesson_req = {
        "learner_id": learner_id,
        "topic": "Python Functions",
        "subject": "Computer Science",
        "document_id": doc_id,
        "level": "beginner",
        "language": "english",
        "teaching_style": "simple",
        "depth": "standard",
        "available_time_minutes": 10
    }
    r = client.post("/api/lessons/plan", json=lesson_req)
    assert r.status_code == 200, f"Lesson plan failed: {r.text}"
    lesson_res = r.json()
    lesson_id = lesson_res.get("lesson_id")
    print(f"[OK] Lesson plan created: id={lesson_id}, segments={len(lesson_res.get('segments', []))}")

    print("\n6. Testing Teaching Session & Interactive Orchestrator...")
    session_req = {
        "learner_id": learner_id,
        "lesson_id": lesson_id
    }
    r = client.post("/api/sessions/start", json=session_req)
    assert r.status_code == 200, f"Session start failed: {r.text}"
    session_res = r.json()
    session_id = session_res["session_id"]
    print(f"[OK] Session started: id={session_id}, status={session_res.get('status')}")

    print("Testing student question asking...")
    ask_req = {
        "question": "What is a function in simple terms?"
    }
    r = client.post(f"/api/sessions/{session_id}/ask", json=ask_req)
    assert r.status_code == 200, f"Ask failed: {r.text}"
    ask_res = r.json()
    spoken_text = ask_res.get("spoken_text", "")
    assert len(spoken_text) > 0, "Teacher spoken text was empty"
    print(f"[OK] Teacher response received! ({len(spoken_text)} characters)")

    print("\n7. Testing Assessment Generation...")
    assess_req = {
        "session_id": session_id,
        "lesson_id": lesson_id,
        "question_count": 2
    }
    r = client.post("/api/assessments/generate", json=assess_req)
    assert r.status_code == 200, f"Assessment generate failed: {r.text}"
    assess_res = r.json()
    assessment_id = assess_res.get("assessment_id")
    questions = assess_res.get("questions", [])
    print(f"[OK] Assessment generated: id={assessment_id}, questions count={len(questions)}")

    print("\n8. Testing All Frontend HTML Pages...")
    pages = ["/", "/setup", "/analyze", "/lesson-plan", "/classroom", "/assessment", "/report", "/dashboard"]
    for page in pages:
        res = client.get(page)
        assert res.status_code == 200, f"Page {page} failed with {res.status_code}"
        print(f"[OK] Page {page} loaded successfully (status 200)")

    print("\n=======================================================")
    print("ALL END-TO-END SYSTEM TESTS PASSED SUCCESSFULLY!")
    print("=======================================================")

def test_full_pipeline():
    """Pytest entry point for complete end-to-end AI Teacher test."""
    run_tests()

if __name__ == "__main__":
    run_tests()
