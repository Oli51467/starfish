from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.gaps import router as gaps_router
from api.lineage import router as lineage_router
from api.map import router as map_router
from api.reading_list import router as reading_list_router
from api.tasks import router as tasks_router
from core.settings import get_settings
from models.schemas import HealthResponse

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    description=settings.app_description,
    version=settings.app_version,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(map_router)
app.include_router(tasks_router)
app.include_router(reading_list_router)
app.include_router(gaps_router)
app.include_router(lineage_router)


@app.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
        timestamp=datetime.now(timezone.utc),
    )
