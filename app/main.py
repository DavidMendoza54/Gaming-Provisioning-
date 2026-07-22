from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.api.routes import router
from app.observability import configure_logging, install_api_observability
from app.settings import get_settings

CONTROL_PANEL_PATH = Path(__file__).parent / "ui" / "control_panel.html"
CONTROL_PANEL_HTML = CONTROL_PANEL_PATH.read_text(encoding="utf-8")


def create_app() -> FastAPI:
    logger = configure_logging(service="api", level=get_settings().log_level)
    app = FastAPI(
        title="TinyProvisioner",
        summary="Learning-first compute provisioning control plane.",
        version="0.1.0",
    )
    app.include_router(router)
    install_api_observability(app, logger=logger)

    @app.get("/", include_in_schema=False, response_class=HTMLResponse)
    def control_panel() -> HTMLResponse:
        return HTMLResponse(CONTROL_PANEL_HTML)

    return app


app = create_app()
