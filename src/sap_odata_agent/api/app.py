from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from sap_odata_agent.api.app_dependencies import get_runtime_service
from sap_odata_agent.api.routes.runtime import router as runtime_router, viewer_router
from sap_odata_agent.application.runtime import SapClawRuntimeService
from sap_odata_agent.infrastructure.config.settings import get_settings


logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(title="SAPClaw Runtime", version="2.0.0")
    frontend_dist = Path("frontend/dist")
    settings = get_settings()

    if not settings.internal_api_key_values:
        logger.warning("Internal API authentication is disabled.")

    @app.get("/health")
    def health(
        runtime: SapClawRuntimeService = Depends(get_runtime_service),
    ) -> dict[str, Any]:
        return runtime.health()

    app.include_router(runtime_router)
    app.include_router(viewer_router)

    if frontend_dist.exists():
        assets_dir = frontend_dist / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

        @app.get("/", include_in_schema=False)
        def frontend_index() -> FileResponse:
            return FileResponse(frontend_dist / "index.html")

    return app
