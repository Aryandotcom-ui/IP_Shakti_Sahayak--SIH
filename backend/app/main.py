import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import router
from .api.updates_routes import router as updates_router
from .config import settings

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = None
    if settings.updates_scheduler_enabled:
        from ai.updates.scheduler import start_scheduler

        scheduler = start_scheduler(
            interval_minutes=settings.updates_interval_minutes,
            sources_path=settings.updates_sources_path,
            watcher_db_path=settings.updates_watcher_db_path,
            queue_db_path=settings.updates_queue_db_path,
            stage_dir=settings.updates_stage_dir,
            manifest_path=settings.corpus_manifest_path,
            chroma_path=settings.chroma_path,
            chroma_collection=settings.chroma_collection,
            embedding_model=settings.embedding_model,
            embedding_device=settings.embedding_device,
            sqlite_registry_path=settings.sqlite_registry_path,
            auto_ingest=settings.updates_auto_ingest,
        )
    yield
    if scheduler is not None:
        scheduler.shutdown(wait=False)


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="Backend API for IP-SAKTI Sahayak.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix=settings.api_v1_prefix)
app.include_router(updates_router, prefix=settings.api_v1_prefix)


@app.get("/health", tags=["health"])
def health() -> dict:
    return {"status": "ok", "service": settings.app_name}
