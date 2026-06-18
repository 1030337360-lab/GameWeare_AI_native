from fastapi import APIRouter

from app.schemas import SessionState

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=SessionState)
def register() -> SessionState:
    return SessionState(authenticated=False, user=None)


@router.post("/login", response_model=SessionState)
def login() -> SessionState:
    return SessionState(authenticated=False, user=None)


@router.post("/logout", response_model=SessionState)
def logout() -> SessionState:
    return SessionState(authenticated=False, user=None)


@router.get("/session", response_model=SessionState)
def session() -> SessionState:
    return SessionState(authenticated=False, user=None)
