from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from sap_odata_agent.api.routes.agent import router as agent_router
from sap_odata_agent.api.routes.queries import router as queries_router
from sap_odata_agent.infrastructure.config.settings import get_settings


logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(title="SAP OData Agent")
    frontend_dist = Path("frontend/dist")
    settings = get_settings()

    if not settings.internal_api_key_values:
        logger.warning("Internal API authentication is disabled.")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(agent_router)
    app.include_router(queries_router)

    if frontend_dist.exists():
        assets_dir = frontend_dist / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

        @app.get("/", include_in_schema=False)
        def frontend_index() -> FileResponse:
            return FileResponse(frontend_dist / "index.html")

    return app
