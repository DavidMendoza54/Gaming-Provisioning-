from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UserRead(BaseModel):
    id: int
    email: str
    role: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UserRead


class TemplateRead(BaseModel):
    id: int
    name: str
    image: str
    exposed_port: int
    default_cpu: int
    default_memory_mb: int
    description: str
    enabled: bool

    model_config = ConfigDict(from_attributes=True)


class ResourceCreate(BaseModel):
    template_id: int
    name: str = Field(min_length=3, max_length=50)


class ResourceRead(BaseModel):
    id: int
    template_id: int
    slug: str
    desired_state: str
    actual_state: str
    external_id: str | None
    url: str | None
    cpu_limit: int
    memory_mb: int
    created_at: datetime
    expires_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class JobRead(BaseModel):
    id: int
    resource_id: int
    kind: str
    status: str
    attempts: int
    last_error: str | None
    started_at: datetime | None
    finished_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class EventRead(BaseModel):
    id: int
    resource_id: int
    actor_user_id: int | None
    event_type: str
    message: str
    event_metadata: dict
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ResourceLogsRead(BaseModel):
    resource_id: int
    external_id: str
    logs: str


class SystemCheckRead(BaseModel):
    name: str
    status: str
    detail: str
