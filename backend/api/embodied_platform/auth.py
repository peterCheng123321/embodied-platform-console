"""Write-role authorization and signed principal helpers."""
from __future__ import annotations

from collections.abc import Callable
import hmac
import os

from fastapi import Header, HTTPException


WRITE_ROLES = {
    "admin",
    "data_manager",
    "annotator",
    "reviewer",
    "ml_engineer",
    "deployment_operator",
    # Compatibility with the initial scaffold; production UI uses the specific roles above.
    "operator",
}


def require_write_actor(
    x_embodied_role: str = Header(default="viewer"),
    x_embodied_actor: str = Header(default="anonymous"),
    x_embodied_signature: str = Header(default="", alias="X-Embodied-Signature"),
) -> dict[str, str]:
    # Authenticate before authorize: verify the signature (authn) FIRST so an
    # unauthenticated caller cannot learn the allowed-role set from the authz
    # error message.
    _verify_principal_signature(x_embodied_actor, x_embodied_role, x_embodied_signature)
    if x_embodied_role not in WRITE_ROLES:
        raise HTTPException(status_code=403, detail="write access requires an embodied platform write role")
    return {"role": x_embodied_role, "actor": x_embodied_actor}


def require_roles(*allowed_roles: str) -> Callable[[str, str], dict[str, str]]:
    allowed = set(allowed_roles)

    def _dependency(
        x_embodied_role: str = Header(default="viewer"),
        x_embodied_actor: str = Header(default="anonymous"),
        x_embodied_signature: str = Header(default="", alias="X-Embodied-Signature"),
    ) -> dict[str, str]:
        # Authenticate before authorize: verify the signature (authn) FIRST so an
        # unauthenticated caller cannot enumerate the allowed-role set from the
        # authz error message.
        _verify_principal_signature(x_embodied_actor, x_embodied_role, x_embodied_signature)
        if x_embodied_role not in allowed:
            raise HTTPException(status_code=403, detail=f"requires one of: {', '.join(sorted(allowed))}")
        return {"role": x_embodied_role, "actor": x_embodied_actor}

    return _dependency


data_actor = require_roles("admin", "data_manager", "operator")
annotation_actor = require_roles("admin", "annotator", "reviewer", "operator")
ml_actor = require_roles("admin", "ml_engineer", "operator")
deployment_actor = require_roles("admin", "deployment_operator", "operator")
system_actor = require_roles("admin")


def _auth_secret() -> str:
    secret = os.environ.get("XINGJU_EMBODIED_PLATFORM_AUTH_SECRET")
    if not secret:
        raise RuntimeError("XINGJU_EMBODIED_PLATFORM_AUTH_SECRET is required for embodied write auth")
    return secret


def _canonical_principal_message(actor: str, role: str) -> bytes:
    """Injective encoding of (actor, role) for signing.

    A bare ``f"{actor}:{role}"`` join collides (sign('a','b:c') == sign('a:b','c'))
    because a ':' in either field is indistinguishable from the separator.
    Length-prefixing each field makes the (actor, role) -> message mapping
    unambiguous so distinct principals never share a signed message.
    """
    actor_bytes = actor.encode()
    role_bytes = role.encode()
    return b"%d:%b:%d:%b" % (len(actor_bytes), actor_bytes, len(role_bytes), role_bytes)


def sign_principal(actor: str, role: str) -> str:
    return hmac.digest(_auth_secret().encode(), _canonical_principal_message(actor, role), "sha256").hex()


def _verify_principal_signature(actor: str, role: str, signature: str) -> None:
    try:
        expected = sign_principal(actor, role)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    # Compare on bytes: hmac.compare_digest rejects non-ASCII str operands with a
    # TypeError, which a non-ASCII signature header would otherwise turn into a
    # 500. Encoding both operands makes such a header a clean 403 (it is simply an
    # invalid signature).
    if not signature or not hmac.compare_digest(signature.encode(), expected.encode()):
        raise HTTPException(status_code=403, detail="invalid embodied platform principal signature")
