from __future__ import annotations

from fastapi import APIRouter, HTTPException

from models.schemas import MapGenerateRequest, MapResponse, TaskCreateResponse
from services.map_service import get_map_service

router = APIRouter(prefix="/api/map", tags=["map"])
map_service = get_map_service()


@router.post("/generate", response_model=TaskCreateResponse)
async def generate_map(request: MapGenerateRequest) -> TaskCreateResponse:
    return await map_service.create_map_task(request)


@router.get("/{map_id}", response_model=MapResponse)
def get_map(map_id: str) -> MapResponse:
    payload = map_service.get_map(map_id)
    if not payload:
        raise HTTPException(status_code=404, detail="map_not_found")
    return payload
