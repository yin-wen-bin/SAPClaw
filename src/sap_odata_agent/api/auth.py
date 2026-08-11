from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, Request, status

from sap_odata_agent.infrastructure.config.settings import get_settings


def require_internal_api_key(x_api_key: str | None = Header(default=None)) -> None:
    configured_keys = get_settings().internal_api_key_values
    if not configured_keys:
        return

    if x_api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header.",
        )

    if not any(secrets.compare_digest(x_api_key, configured_key) for configured_key in configured_keys):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
        )


def require_loopback_client(request: Request) -> None:
    host = (request.client.host if request.client else "").lower()
    if host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The local SAPClaw viewer is available only from this computer.",
        )
