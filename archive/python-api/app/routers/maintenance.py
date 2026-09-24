from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from app.schemas import (
    MaintenanceAsset,
    MaintenanceCreateRun,
    MaintenanceGame,
    MaintenanceGameUpdateRequest,
    MaintenanceJob,
    MaintenanceModerationRequest,
    MaintenanceOverview,
    MaintenanceReview,
    CreateJob,
)
from app.services.maintenance_service import (
    delete_asset,
    list_assets,
    list_failed_create_runs,
    list_games,
    list_jobs,
    list_reviews,
    maintenance_overview,
    mark_job_reviewed,
    moderate_game,
    require_maintainer,
    update_game,
    retry_failed_job,
)
from app.services.create_service import execute_generation_job

router = APIRouter(prefix="/maintenance", tags=["maintenance"])


@router.get("/overview", response_model=MaintenanceOverview)
def overview(_maintainer=Depends(require_maintainer)) -> MaintenanceOverview:
    return maintenance_overview()


@router.get("/jobs", response_model=list[MaintenanceJob])
def jobs(
    status: str | None = None,
    limit: int = 50,
    _maintainer=Depends(require_maintainer),
) -> list[MaintenanceJob]:
    return list_jobs(status_filter=status, limit=limit)


@router.get("/create-runs/failed", response_model=list[MaintenanceCreateRun])
def failed_create_runs(
    limit: int = 20,
    _maintainer=Depends(require_maintainer),
) -> list[MaintenanceCreateRun]:
    return list_failed_create_runs(limit=limit)


@router.post("/jobs/{job_id}/mark-reviewed", response_model=MaintenanceReview)
def review_job(
    job_id: str,
    reason: str = "Reviewed by maintainer",
    maintainer=Depends(require_maintainer),
) -> MaintenanceReview:
    return mark_job_reviewed(job_id, maintainer, reason=reason)


@router.post("/jobs/{job_id}/retry", response_model=CreateJob)
def retry_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
    maintainer=Depends(require_maintainer),
) -> CreateJob:
    job, creator_id = retry_failed_job(job_id, maintainer, getattr(request.state, "jwt_jti", None))
    background_tasks.add_task(execute_generation_job, job.id, creator_id, getattr(request.state, "jwt_jti", None))
    return job


@router.get("/games", response_model=list[MaintenanceGame])
def games(
    status: str | None = None,
    q: str | None = None,
    limit: int = 50,
    _maintainer=Depends(require_maintainer),
) -> list[MaintenanceGame]:
    return list_games(status_filter=status, q=q, limit=limit)


@router.patch("/games/{game_id}", response_model=MaintenanceGame)
def patch_game(
    game_id: str,
    request: MaintenanceGameUpdateRequest,
    maintainer=Depends(require_maintainer),
) -> MaintenanceGame:
    return update_game(game_id, request, maintainer)


@router.post("/games/{game_id}/moderate", response_model=MaintenanceReview)
def game_moderation(
    game_id: str,
    request: MaintenanceModerationRequest,
    maintainer=Depends(require_maintainer),
) -> MaintenanceReview:
    return moderate_game(game_id, request, maintainer)


@router.get("/assets", response_model=list[MaintenanceAsset])
def assets(
    gameId: str | None = None,
    jobId: str | None = None,
    limit: int = 50,
    _maintainer=Depends(require_maintainer),
) -> list[MaintenanceAsset]:
    return list_assets(game_id=gameId, job_id=jobId, limit=limit)


@router.delete("/assets/{asset_id}")
def remove_asset(asset_id: str, maintainer=Depends(require_maintainer)) -> dict[str, str | bool]:
    return delete_asset(asset_id, maintainer)


@router.get("/reviews", response_model=list[MaintenanceReview])
def reviews(
    status: str | None = None,
    limit: int = 50,
    _maintainer=Depends(require_maintainer),
) -> list[MaintenanceReview]:
    return list_reviews(status_filter=status, limit=limit)
