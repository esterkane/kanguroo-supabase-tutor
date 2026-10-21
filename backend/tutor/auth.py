"""Verify Supabase Auth access tokens against the project's JWKS.

Local Supabase signs user access tokens with an asymmetric key (ES256) published at
`<API_URL>/auth/v1/.well-known/jwks.json`. Only asymmetric algorithms are accepted, so a token signed
with the shared HS256 secret (or an API key like ANON_KEY) can never pass as a learner.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any
from uuid import UUID

import jwt
from fastapi import HTTPException, Request, status

ALGORITHMS = ["ES256", "RS256", "EdDSA"]
AUDIENCE = "authenticated"


class JwtVerifier:
    def __init__(self, api_url: str, key_resolver: Callable[[str], Any] | None = None) -> None:
        base = api_url.rstrip("/")
        self.issuer = f"{base}/auth/v1"
        self._jwks = jwt.PyJWKClient(f"{self.issuer}/.well-known/jwks.json", cache_keys=True, lifespan=600)
        # Tests inject a resolver (token -> public key) instead of fetching the JWKS.
        self._resolve = key_resolver or (lambda token: self._jwks.get_signing_key_from_jwt(token).key)

    def verify(self, token: str) -> dict[str, Any]:
        header = jwt.get_unverified_header(token)
        if header.get("alg") not in ALGORITHMS:
            raise jwt.InvalidAlgorithmError(f"algorithm {header.get('alg')!r} is not accepted")
        claims: dict[str, Any] = jwt.decode(
            token, self._resolve(token), algorithms=ALGORITHMS, audience=AUDIENCE, issuer=self.issuer,
            options={"require": ["exp", "sub", "aud", "iss"]},
        )
        return claims

    async def user_id(self, request: Request) -> UUID:
        auth = request.headers.get("authorization", "")
        if not auth.lower().startswith("bearer "):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
        try:
            claims = await asyncio.to_thread(self.verify, auth[7:].strip())  # JWKS fetch is blocking I/O
            if claims.get("role") != "authenticated":
                raise jwt.InvalidTokenError("not a learner token")
            return UUID(claims["sub"])
        except (jwt.PyJWTError, ValueError) as e:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"invalid token: {e}") from e
