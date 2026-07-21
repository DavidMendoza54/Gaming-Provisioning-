from unittest.mock import patch

from sqlalchemy.exc import SQLAlchemyError

from app import worker


def test_worker_retries_when_database_is_not_ready() -> None:
    calls = {"count": 0}

    async def fake_run_once(**_kwargs) -> int:
        calls["count"] += 1
        if calls["count"] == 1:
            raise SQLAlchemyError("schema is not ready")
        raise KeyboardInterrupt

    with (
        patch.object(worker, "run_once", side_effect=fake_run_once),
        patch.object(worker, "sleep") as sleep,
        patch.object(worker, "mark_worker_stopped") as mark_worker_stopped,
    ):
        worker.run_forever(idle_sleep_seconds=0)

    assert calls["count"] == 2
    sleep.assert_called_once_with(0)
    mark_worker_stopped.assert_called_once()
