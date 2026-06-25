from unittest.mock import patch

from sqlalchemy.exc import SQLAlchemyError

from app import worker


def test_worker_retries_when_database_is_not_ready() -> None:
    calls = {"count": 0}

    async def fake_run_once() -> int:
        calls["count"] += 1
        if calls["count"] == 1:
            raise SQLAlchemyError("schema is not ready")
        raise KeyboardInterrupt

    with (
        patch.object(worker, "run_once", side_effect=fake_run_once),
        patch.object(worker, "sleep") as sleep,
    ):
        try:
            worker.run_forever(idle_sleep_seconds=0)
        except KeyboardInterrupt:
            pass

    assert calls["count"] == 2
    sleep.assert_called_once_with(0)
