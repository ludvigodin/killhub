"""Bearer auth for Internal Worker API (D52)."""

from typing import Optional

from fastapi import Header, HTTPException, status

from config import get_settings


def require_internal_token(
    authorization: Optional[str] = Header(default=None),
) -> None:
    settings = get_settings()
    expected = settings.internal_api_token
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "INTERNAL_API_TOKEN is not configured",
                "code": "misconfigured",
            },
        )
    if authorization != f"Bearer {expected}":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "unauthorized", "code": "unauthorized"},
            headers={"WWW-Authenticate": "Bearer"},
        )
