"""
AI Teacher — FastAPI Application Entry Point

Architecture:
    Browser → FastAPI (Jinja2 + REST API) → Teacher Orchestrator → Agents → Ollama/MongoDB
"""
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.services.mongodb_service import mongodb_service
from app.services.ollama_service import ollama_service

# Setup logging first
setup_logging(debug=settings.debug)
logger = get_logger(__name__)

# Import all routers
from app.api.health import router as health_router
from app.api.documents import router as documents_router
from app.api.topics import router as topics_router
from app.api.lessons import router as lessons_router
from app.api.sessions import router as sessions_router
from app.api.assessments import router as assessments_router
from app.api.learners import router as learners_router
from app.api.students_reports import students_router, reports_router
from app.api.avatar import router as avatar_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle — connect on startup, disconnect on shutdown."""
    logger.info("AI Teacher starting up...")

    # Connect to MongoDB
    try:
        await mongodb_service.connect()
        logger.info("MongoDB connected")
    except Exception as e:
        logger.error(f"MongoDB connection failed: {e}")

    # Ensure upload directory exists
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)

    yield  # App is running

    # Cleanup
    await mongodb_service.disconnect()
    await ollama_service.close()
    logger.info("AI Teacher shut down cleanly")


# Create FastAPI app
app = FastAPI(
    title="AI Teacher — Human-Like Adaptive AI Educator",
    description="An adaptive AI tutoring system powered by gemma4:31b-cloud",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files and templates
_static_dir = Path(__file__).parent / "static"
_static_dir.mkdir(parents=True, exist_ok=True)
(Path(__file__).parent / "static" / "css").mkdir(exist_ok=True)
(Path(__file__).parent / "static" / "js").mkdir(exist_ok=True)
(Path(__file__).parent / "static" / "uploads").mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

_templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))

# Register API routers
app.include_router(health_router)
app.include_router(documents_router)
app.include_router(topics_router)
app.include_router(lessons_router)
app.include_router(sessions_router)
app.include_router(assessments_router)
app.include_router(learners_router)
app.include_router(students_router)
app.include_router(reports_router)
app.include_router(avatar_router)


# ── Page routes ─────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/setup", response_class=HTMLResponse)
async def learner_setup(request: Request):
    return templates.TemplateResponse("learner_setup.html", {"request": request})


@app.get("/analyze", response_class=HTMLResponse)
async def document_analysis(request: Request):
    return templates.TemplateResponse("document_analysis.html", {"request": request})


@app.get("/lesson-plan", response_class=HTMLResponse)
async def lesson_plan_page(request: Request):
    return templates.TemplateResponse("lesson_plan.html", {"request": request})


@app.get("/video", response_class=HTMLResponse)
async def video_generator_page(request: Request):
    return templates.TemplateResponse("video_generator.html", {"request": request})


@app.get("/classroom", response_class=HTMLResponse)
async def classroom(request: Request):
    return templates.TemplateResponse("classroom.html", {"request": request})


@app.get("/assessment", response_class=HTMLResponse)
async def assessment_page(request: Request):
    return templates.TemplateResponse("assessment.html", {"request": request})


@app.get("/report", response_class=HTMLResponse)
async def report_page(request: Request):
    return templates.TemplateResponse("report.html", {"request": request})


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})
