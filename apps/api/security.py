import hmac
from typing import Optional
from fastapi import Header, HTTPException, Query, status
from edge.config import get_settings


def _matches(expected: Optional[str], given: Optional[str]) -> bool:
    return bool(expected) and bool(given) and hmac.compare_digest(expected.encode(), given.encode())


def require_api_key(x_api_key: Optional[str] = Header(None),
                    api_key: Optional[str] = Query(None, include_in_schema=False)):
    """
    Protects every /api route when LIFELINE_API_KEY is set. The query parameter form
    exists only so <img>/<video> tags in the console can load media files.
    """
    expected = get_settings().api_key
    if not expected:
        return
    if not (_matches(expected, x_api_key) or _matches(expected, api_key)):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or invalid API key (X-API-Key).")


def require_admin(x_admin_key: Optional[str] = Header(None)):
    """Trusted clinical memory can only be changed with LIFELINE_ADMIN_KEY."""
    expected = get_settings().admin_key
    if not expected:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Editing trusted protocols is disabled (LIFELINE_ADMIN_KEY is not configured).")
    if not _matches(expected, x_admin_key):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid admin key (X-Admin-Key).")
