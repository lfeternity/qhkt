from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt
from fastapi import Header, HTTPException, Request

from app.config import Settings, get_settings


@dataclass(frozen=True)
class Identity:
    user_id: int
    role_id: int | None
    request_id: str


class JwtVerifier:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._jwks: dict[str, Any] | None = None
        self._loaded_at = 0.0

    async def verify(self, token: str) -> tuple[int, int | None]:
        if not self.settings.jwt_jwks_url:
            raise HTTPException(status_code=503, detail="JWT 校验配置缺失")
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as error:
            raise HTTPException(status_code=401, detail="无效的登录凭证") from error
        kid = header.get("kid")
        if header.get("alg") != "RS256" or not kid:
            raise HTTPException(status_code=401, detail="无效的登录凭证")
        keys = await self._get_keys()
        jwk = next((item for item in keys.get("keys", []) if item.get("kid") == kid), None)
        if not jwk:
            self._jwks = None
            keys = await self._get_keys(force=True)
            jwk = next((item for item in keys.get("keys", []) if item.get("kid") == kid), None)
        if not jwk:
            raise HTTPException(status_code=401, detail="无效的登录凭证")
        try:
            public_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk))
            options = {"verify_aud": bool(self.settings.jwt_audience)}
            payload = jwt.decode(
                token,
                public_key,
                algorithms=["RS256"],
                issuer=self.settings.jwt_issuer or None,
                audience=self.settings.jwt_audience or None,
                options=options,
            )
        except (jwt.PyJWTError, ValueError) as error:
            raise HTTPException(status_code=401, detail="无效的登录凭证") from error
        user = payload.get("user") or {}
        try:
            user_id = int(user["userId"])
        except (KeyError, TypeError, ValueError) as error:
            raise HTTPException(status_code=401, detail="登录凭证缺少用户信息") from error
        role = user.get("roleId")
        return user_id, int(role) if role is not None else None

    async def _get_keys(self, force: bool = False) -> dict[str, Any]:
        if not force and self._jwks and time.monotonic() - self._loaded_at < 300:
            return self._jwks
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(self.settings.jwt_jwks_url)
                response.raise_for_status()
                value = response.json()
                if not isinstance(value, dict) or not isinstance(value.get("keys"), list):
                    raise TypeError("invalid jwks")
                self._jwks = value
                self._loaded_at = time.monotonic()
                return value
        except (httpx.HTTPError, ValueError) as error:
            raise HTTPException(status_code=503, detail="认证服务暂时不可用") from error


def _decode_header_value(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


async def get_identity(
    request: Request,
    user_info: str | None = Header(default=None, alias="user-info"),
    role_info: str | None = Header(default=None, alias="role-info"),
    authorization: str | None = Header(default=None),
    request_id: str | None = Header(default=None, alias="requestId"),
) -> Identity:
    settings = get_settings()
    user_id: int | None = None
    role_id: int | None = None
    if settings.jwt_enabled:
        token = authorization or ""
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        if not token:
            raise HTTPException(status_code=401, detail="请先登录")
        verifier = getattr(request.app.state, "jwt_verifier", None)
        if verifier is None:
            verifier = JwtVerifier(settings)
            request.app.state.jwt_verifier = verifier
        user_id, role_id = await verifier.verify(token)
        supplied = _decode_header_value(user_info)
        if supplied and supplied != str(user_id):
            raise HTTPException(status_code=401, detail="身份信息不一致")
    else:
        if not settings.trust_gateway_headers:
            raise HTTPException(status_code=401, detail="未启用身份校验")
        try:
            user_id = int(_decode_header_value(user_info) or "")
            if user_id <= 0:
                raise ValueError
        except ValueError as error:
            raise HTTPException(status_code=401, detail="请先登录") from error
        try:
            role_id = int(role_info) if role_info else None
        except ValueError:
            role_id = None
    return Identity(user_id, role_id, _decode_header_value(request_id) or request.state.request_id)


def require_admin(identity: Identity, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    if identity.user_id not in settings.admin_users and (identity.role_id is None or identity.role_id not in settings.admin_roles):
        raise HTTPException(status_code=403, detail="需要管理员权限")


def require_knowledge_uploader(identity: Identity, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    if identity.user_id not in settings.admin_users and (
        identity.role_id is None
        or (identity.role_id not in settings.admin_roles and identity.role_id not in settings.teacher_roles)
    ):
        raise HTTPException(status_code=403, detail="需要教师或知识管理员权限")
