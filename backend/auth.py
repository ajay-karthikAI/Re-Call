from __future__ import annotations

from hmac import compare_digest
from typing import Optional

from fastapi import Depends, HTTPException, WebSocket, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config import get_settings


bearer_scheme = HTTPBearer(auto_error=False)


def configured_api_token() -> str:
    return get_settings().recall_api_token.strip()


def api_auth_enabled() -> bool:
    return bool(configured_api_token())


def _valid_token(token: Optional[str]) -> bool:
    expected = configured_api_token()
    if not expected:
        return True
    provided = (token or "").strip()
    return bool(provided) and compare_digest(provided, expected)


async def require_api_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> None:
    if not api_auth_enabled():
        return
    if not credentials or credentials.scheme.lower() != "bearer" or not _valid_token(credentials.credentials):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _authorization_header_token(header_value: Optional[str]) -> Optional[str]:
    if not header_value:
        return None
    scheme, _, token = header_value.partition(" ")
    if scheme.lower() != "bearer":
        return None
    return token.strip() or None


async def require_websocket_api_token(websocket: WebSocket) -> bool:
    if not api_auth_enabled():
        return True

    token = websocket.query_params.get("token") or _authorization_header_token(websocket.headers.get("authorization"))
    if _valid_token(token):
        return True

    await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
    return False
