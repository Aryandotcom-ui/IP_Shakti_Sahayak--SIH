from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import router
from .config import settings

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="Backend API for IP-SAKTI Sahayak.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix=settings.api_v1_prefix)


@app.get("/health", tags=["health"])
def health() -> dict:
    return {"status": "ok", "service": settings.app_name}
