from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.api.routes import router

CONTROL_PANEL_PATH = Path(__file__).parent / "ui" / "control_panel.html"


def create_app() -> FastAPI:
    app = FastAPI(
        title="TinyProvisioner",
        summary="Learning-first compute provisioning control plane.",
        version="0.1.0",
    )
    app.include_router(router)

    @app.get("/", include_in_schema=False)
    def control_panel() -> FileResponse:
        return FileResponse(CONTROL_PANEL_PATH)

    return app


app = create_app()
