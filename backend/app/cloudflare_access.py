"""Cloudflare Access identity: who is the person behind this request?

With Cloudflare Access in front of the website (deploy/vm), every request that reaches the Cloudflare Tunnel on
the server carries a ``Cf-Access-Jwt-Assertion`` header: a token signed by Cloudflare for THIS application
(audience = the application's AUD tag) naming the signed-in person's e-mail. Cloudflare removes any such header
a visitor sent and sets its own, and the tunnel is the only way to reach the server, so verifying this token is
the complete check: signature against Cloudflare's published keys, audience, issuer, expiry.

No shared secret is needed and no password exists anywhere. The keys are fetched from
``https://<team>.cloudflareaccess.com/cdn-cgi/access/certs`` and cached for an hour.
"""
from __future__ import annotations

import logging
import threading

import jwt
from jwt import PyJWKClient

from .config import settings

log = logging.getLogger("mclabor.access")
_clients: dict[str, PyJWKClient] = {}
_lock = threading.Lock()


class AccessTokenInvalid(Exception):
    """The token is missing, forged, for another application, expired or otherwise not acceptable."""


def _issuer() -> str:
    team = (settings.cloudflare_access_team_domain or "").strip().lower().removeprefix("https://").rstrip("/")
    if not team:
        raise AccessTokenInvalid("CLOUDFLARE_ACCESS_TEAM_DOMAIN is not set")
    return f"https://{team}"


def _jwk_client(issuer: str) -> PyJWKClient:
    with _lock:
        client = _clients.get(issuer)
        if client is None:
            client = PyJWKClient(f"{issuer}/cdn-cgi/access/certs", cache_keys=True, lifespan=3600, timeout=10)
            _clients[issuer] = client
        return client


def verify(token: str | None, require_email: bool = True) -> dict:
    """The token's claims (``email`` among them), or AccessTokenInvalid. Never raises anything else.
    ``require_email=False`` accepts a service token (a machine such as the office sync agent: ``common_name`` instead of an e-mail)."""
    if not token or not isinstance(token, str) or len(token) > 8192:
        raise AccessTokenInvalid("no token")
    aud = (settings.cloudflare_access_aud or "").strip()
    if not aud:
        raise AccessTokenInvalid("CLOUDFLARE_ACCESS_AUD is not set")
    try:
        issuer = _issuer()
        key = _jwk_client(issuer).get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["RS256"], audience=aud, issuer=issuer, options={"require": ["exp", "iat"] + (["email"] if require_email else [])}, leeway=30)
    except AccessTokenInvalid:
        raise
    except Exception as exc:  # noqa: BLE001 - every failure means "not signed in"; the reason goes to the log only
        log.warning("Cloudflare Access token refused (%s)", type(exc).__name__)
        raise AccessTokenInvalid(type(exc).__name__) from None
    email = str(claims.get("email", "")).strip().lower()
    if not email and require_email:
        raise AccessTokenInvalid("no e-mail in the token")
    if not email and not str(claims.get("common_name", "")).strip():
        raise AccessTokenInvalid("neither an e-mail nor a service token name in the token")
    claims["email"] = email
    return claims


def reset_for_tests() -> None:
    with _lock:
        _clients.clear()
