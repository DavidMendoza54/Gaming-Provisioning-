from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import Event, Resource, Template, User
from app.schemas import (
    EventRead,
    LoginRequest,
    RegisterRequest,
    ResourceCreate,
    ResourceLogsRead,
    ResourceRead,
    SystemCheckRead,
    TemplateRead,
    TokenResponse,
    UserRead,
)
from app.services.auth import authenticate_user, get_user_by_token, issue_token, register_user
from app.provisioners.factory import make_provisioner
from app.services.resources import (
    ResourceActionError,
    create_resource,
    get_owned_resource,
    queue_delete_resource,
    queue_restart_resource,
    queue_start_resource,
    queue_stop_resource,
)
from app.services.system_status import collect_system_status

router = APIRouter()
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: Session = Depends(get_session),
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = get_user_by_token(session, credentials.credentials)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/system/status", response_model=list[SystemCheckRead])
def system_status(
    session: Session = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> list[dict[str, str]]:
    return collect_system_status(session)


@router.post("/auth/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest,
    session: Session = Depends(get_session),
) -> TokenResponse:
    try:
        user = register_user(session, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    issued = issue_token(session, user, name="register")
    return TokenResponse(access_token=issued.raw_token, expires_at=issued.api_token.expires_at, user=user)


@router.post("/auth/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    session: Session = Depends(get_session),
) -> TokenResponse:
    user = authenticate_user(session, payload)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    issued = issue_token(session, user, name="login")
    return TokenResponse(access_token=issued.raw_token, expires_at=issued.api_token.expires_at, user=user)


@router.get("/me", response_model=UserRead)
def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.get("/templates", response_model=list[TemplateRead])
def list_templates(session: Session = Depends(get_session)) -> list[Template]:
    return list(session.scalars(select(Template).where(Template.enabled.is_(True))).all())


@router.post("/resources", response_model=ResourceRead, status_code=status.HTTP_202_ACCEPTED)
def request_resource(
    payload: ResourceCreate,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Resource:
    try:
        return create_resource(session, user, payload)
    except ResourceActionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/resources", response_model=list[ResourceRead])
def list_resources(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[Resource]:
    statement = select(Resource).where(Resource.user_id == user.id).order_by(Resource.created_at.desc())
    return list(session.scalars(statement).all())


@router.get("/resources/{resource_id}", response_model=ResourceRead)
def get_resource(
    resource_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Resource:
    resource = session.get(Resource, resource_id)
    if resource is None or resource.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")
    return resource


@router.post("/resources/{resource_id}/start", response_model=ResourceRead, status_code=status.HTTP_202_ACCEPTED)
def start_resource(
    resource_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Resource:
    resource = get_owned_resource(session, user, resource_id)
    if resource is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")

    try:
        return queue_start_resource(session, resource, user)
    except ResourceActionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/resources/{resource_id}/stop", response_model=ResourceRead, status_code=status.HTTP_202_ACCEPTED)
def stop_resource(
    resource_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Resource:
    resource = get_owned_resource(session, user, resource_id)
    if resource is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")

    try:
        return queue_stop_resource(session, resource, user)
    except ResourceActionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/resources/{resource_id}/restart", response_model=ResourceRead, status_code=status.HTTP_202_ACCEPTED)
def restart_resource(
    resource_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Resource:
    resource = get_owned_resource(session, user, resource_id)
    if resource is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")

    try:
        return queue_restart_resource(session, resource, user)
    except ResourceActionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete("/resources/{resource_id}", response_model=ResourceRead, status_code=status.HTTP_202_ACCEPTED)
def delete_resource(
    resource_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Resource:
    resource = get_owned_resource(session, user, resource_id)
    if resource is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")

    return queue_delete_resource(session, resource, user)


@router.get("/resources/{resource_id}/events", response_model=list[EventRead])
def list_resource_events(
    resource_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[Event]:
    resource = session.get(Resource, resource_id)
    if resource is None or resource.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")

    statement = select(Event).where(Event.resource_id == resource.id).order_by(Event.created_at.asc())
    return list(session.scalars(statement).all())


@router.get("/resources/{resource_id}/logs", response_model=ResourceLogsRead)
async def get_resource_logs(
    resource_id: int,
    tail: int = 100,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ResourceLogsRead:
    resource = get_owned_resource(session, user, resource_id)
    if resource is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")
    if resource.external_id is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Resource has not been provisioned")

    safe_tail = max(1, min(tail, 500))
    logs = await make_provisioner().logs(external_id=resource.external_id, tail=safe_tail)
    return ResourceLogsRead(resource_id=resource.id, external_id=resource.external_id, logs=logs)
