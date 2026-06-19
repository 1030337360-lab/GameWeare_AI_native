from fastapi import APIRouter, Depends, HTTPException

from app.schemas import ProfileActivity, ProfileProjectDetail
from app.services.auth_service import require_user
from app.services.profile_service import get_profile_activity, get_profile_project_detail

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("/activity", response_model=ProfileActivity)
def profile_activity(user=Depends(require_user)) -> ProfileActivity:
    return get_profile_activity(user.id)


@router.get("/projects/{project_id}", response_model=ProfileProjectDetail)
def profile_project(project_id: str, user=Depends(require_user)) -> ProfileProjectDetail:
    detail = get_profile_project_detail(user.id, project_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Project not found")
    return detail
