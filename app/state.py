from enum import StrEnum


class DesiredState(StrEnum):
    RUNNING = "running"
    STOPPED = "stopped"
    DELETED = "deleted"


class ActualState(StrEnum):
    PENDING = "pending"
    PROVISIONING = "provisioning"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    STARTING = "starting"
    FAILED = "failed"
    DELETING = "deleting"
    DELETED = "deleted"


ALLOWED_TRANSITIONS: dict[ActualState, set[ActualState]] = {
    ActualState.PENDING: {ActualState.PROVISIONING, ActualState.FAILED, ActualState.DELETING},
    ActualState.PROVISIONING: {ActualState.RUNNING, ActualState.FAILED, ActualState.DELETING},
    ActualState.RUNNING: {ActualState.STOPPING, ActualState.DELETING, ActualState.FAILED},
    ActualState.STOPPING: {ActualState.STOPPED, ActualState.FAILED, ActualState.DELETING},
    ActualState.STOPPED: {ActualState.STARTING, ActualState.DELETING},
    ActualState.STARTING: {ActualState.RUNNING, ActualState.FAILED, ActualState.DELETING},
    ActualState.FAILED: {ActualState.DELETING, ActualState.PROVISIONING},
    ActualState.DELETING: {ActualState.DELETED, ActualState.FAILED},
    ActualState.DELETED: set(),
}


def can_transition(current: str | ActualState, target: str | ActualState) -> bool:
    current_state = ActualState(current)
    target_state = ActualState(target)
    return target_state in ALLOWED_TRANSITIONS[current_state]

