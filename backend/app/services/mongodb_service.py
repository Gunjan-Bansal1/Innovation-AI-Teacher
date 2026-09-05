"""
MongoDB Service — async motor client with collection accessors.

Creates required collections and indexes on startup.
Handles vector search index creation when a fixed embedding dimension is configured.
"""
from typing import Optional
import motor.motor_asyncio
from pymongo import ASCENDING, DESCENDING, TEXT
from pymongo.errors import OperationFailure, ServerSelectionTimeoutError

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class MongoDBService:
    def __init__(self) -> None:
        self._client: Optional[motor.motor_asyncio.AsyncIOMotorClient] = None
        self._db: Optional[motor.motor_asyncio.AsyncIOMotorDatabase] = None

    async def connect(self) -> None:
        """Establish MongoDB connection and create indexes."""
        try:
            self._client = motor.motor_asyncio.AsyncIOMotorClient(
                settings.mongodb_uri,
                serverSelectionTimeoutMS=5000,
            )
            self._db = self._client[settings.mongodb_database]
            # Verify connection
            await self._client.admin.command("ping")
            logger.info("MongoDB connected", extra={"database": settings.mongodb_database})
            await self._create_indexes()
        except ServerSelectionTimeoutError as e:
            raise ConnectionError(f"Cannot connect to MongoDB at {settings.mongodb_uri}: {e}")

    async def disconnect(self) -> None:
        if self._client:
            self._client.close()
            logger.info("MongoDB disconnected")

    @property
    def db(self) -> motor.motor_asyncio.AsyncIOMotorDatabase:
        if self._db is None:
            raise RuntimeError("MongoDB not connected. Call connect() first.")
        return self._db

    async def health_check(self) -> bool:
        try:
            await self._client.admin.command("ping")
            return True
        except Exception:
            return False

    # ── Collection accessors ──────────────────────────────────────────────────

    @property
    def users(self): return self.db["users"]

    @property
    def learner_profiles(self): return self.db["learner_profiles"]

    @property
    def documents(self): return self.db["documents"]

    @property
    def document_chunks(self): return self.db["document_chunks"]

    @property
    def topics(self): return self.db["topics"]

    @property
    def concepts(self): return self.db["concepts"]

    @property
    def lessons(self): return self.db["lessons"]

    @property
    def lesson_segments(self): return self.db["lesson_segments"]

    @property
    def learning_sessions(self): return self.db["learning_sessions"]

    @property
    def student_interactions(self): return self.db["student_interactions"]

    @property
    def questions(self): return self.db["questions"]

    @property
    def student_answers(self): return self.db["student_answers"]

    @property
    def concept_mastery(self): return self.db["concept_mastery"]

    @property
    def misconceptions(self): return self.db["misconceptions"]

    @property
    def assessments(self): return self.db["assessments"]

    @property
    def assessment_results(self): return self.db["assessment_results"]

    @property
    def learning_reports(self): return self.db["learning_reports"]

    # ── Index creation ────────────────────────────────────────────────────────

    async def _create_indexes(self) -> None:
        """Create all required indexes including vector search."""
        try:
            # document_chunks: text search + lookup indexes
            await self.document_chunks.create_index([("document_id", ASCENDING)])
            await self.document_chunks.create_index([("chunk_index", ASCENDING)])

            # Try to create Atlas Vector Search index for embeddings
            await self._create_vector_index()

            # learning_sessions
            await self.learning_sessions.create_index([("learner_id", ASCENDING)])
            await self.learning_sessions.create_index([("created_at", DESCENDING)])
            await self.learning_sessions.create_index([("status", ASCENDING)])

            # lessons
            await self.lessons.create_index([("learner_id", ASCENDING)])
            await self.lessons.create_index([("document_id", ASCENDING)])

            # concept_mastery
            await self.concept_mastery.create_index(
                [("learner_id", ASCENDING), ("concept_key", ASCENDING)],
                unique=True,
            )

            # student_answers
            await self.student_answers.create_index([("session_id", ASCENDING)])
            await self.student_answers.create_index([("question_id", ASCENDING)])

            # misconceptions
            await self.misconceptions.create_index([("session_id", ASCENDING)])
            await self.misconceptions.create_index([("learner_id", ASCENDING)])

            logger.info("MongoDB indexes created/verified")

        except OperationFailure as e:
            logger.warning(f"Index creation warning (non-fatal): {e}")

    async def _create_vector_index(self) -> None:
        """
        Attempt to create MongoDB Atlas Vector Search index.
        Falls back gracefully if not on Atlas — Python-side cosine similarity
        will be used instead.
        """
        if settings.embedding_dim <= 0:
            logger.info(
                "Skipping Atlas Vector Search index because EMBEDDING_DIM is not fixed. "
                "Python cosine similarity will be used."
            )
            return

        index_name = "chunk_embedding_index"
        try:
            existing = await self.document_chunks.list_search_indexes().to_list(None)
            existing_names = [idx.get("name") for idx in existing]
            if index_name not in existing_names:
                index_def = {
                    "name": index_name,
                    "type": "vectorSearch",
                    "definition": {
                        "fields": [
                            {
                                "type": "vector",
                                "path": "embedding",
                                "numDimensions": settings.embedding_dim,
                                "similarity": "cosine",
                            }
                        ]
                    },
                }
                await self.document_chunks.create_search_index(index_def)
                logger.info("MongoDB Atlas Vector Search index created")
        except Exception as e:
            logger.info(
                f"Atlas Vector Search not available — will use Python cosine similarity. Reason: {e}"
            )


# Singleton
mongodb_service = MongoDBService()
