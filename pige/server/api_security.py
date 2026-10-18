"""/api/passkeys, /api/devices, /api/sessions: passkey sign-in and the list of signed-in devices.

Managing security is reserved to the web app signed in with a session: API tokens
(Thunderbird) can neither add a passkey nor end a session.
"""

from __future__ import annotations

import secrets
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from webauthn import (
    base64url_to_bytes,
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import bytes_to_base64url
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from pige.server.auth import LoginThrottle
from pige.server.config import Settings
from pige.server.security import AuthStore, Challenges

CHALLENGE_COOKIE = "pige_webauthn"
_TRANSPORTS = {t.value for t in AuthenticatorTransport}


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterIn(_In):
    credential: dict[str, Any]
    name: str = Field(default="", max_length=80)


class LoginIn(_In):
    credential: dict[str, Any]


class RenameIn(_In):
    name: str = Field(min_length=1, max_length=80)


def build_security_router(
    settings: Settings,
    store: AuthStore,
    throttle: LoginThrottle,
    require_session: Callable[..., str],
    sign_in: Callable[[Request, Response, str, str | None], None],
) -> APIRouter:
    router = APIRouter(prefix="/api")
    pending = Challenges()
    rp_id = settings.passkey_rp_id
    origin = settings.public_origin

    def configured() -> tuple[str, str]:
        if not rp_id or not origin:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Passkeys are not configured on this server")
        return rp_id, origin

    def client(request: Request) -> str:
        return request.client.host if request.client else "unknown"

    # ------------------------------------------------------------ add a passkey (signed in)

    @router.post("/passkeys/register/options")
    def register_options(sid: str = Depends(require_session)) -> Response:
        rp, _ = configured()
        options = generate_registration_options(
            rp_id=rp,
            rp_name="P.IGE",
            user_id=store.user_handle(),
            user_name="pige",
            user_display_name="P.IGE",
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.REQUIRED,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
            exclude_credentials=[
                PublicKeyCredentialDescriptor(id=base64url_to_bytes(p.id)) for p in store.passkeys()
            ],
        )
        pending.put(f"reg:{store.hash_of(sid)}", options.challenge)
        return Response(options_to_json(options), media_type="application/json")

    @router.post("/passkeys/register/verify", status_code=status.HTTP_201_CREATED)
    def register_verify(body: RegisterIn, request: Request, sid: str = Depends(require_session)) -> dict[str, Any]:
        rp, expected_origin = configured()
        challenge = pending.take(f"reg:{store.hash_of(sid)}")
        if challenge is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Challenge expired, start again")
        try:
            verified = verify_registration_response(
                credential=body.credential,
                expected_challenge=challenge,
                expected_rp_id=rp,
                expected_origin=expected_origin,
                require_user_verification=True,
            )
        except (WebAuthnException, ValueError, KeyError, TypeError) as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Passkey refused: {exc}") from exc
        credential_id = bytes_to_base64url(verified.credential_id)
        if store.passkey(credential_id) is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "This passkey is already registered")
        raw = body.credential.get("response", {}).get("transports") or []
        transports = [t for t in raw if isinstance(t, str) and t in _TRANSPORTS]
        name = body.name.strip() or "Clé d'accès"
        store.add_passkey(
            credential_id, verified.credential_public_key, verified.sign_count, name, transports,
            bool(verified.credential_backed_up),
        )
        return {"id": credential_id, "name": name}

    # ------------------------------------------------------------ sign in with a passkey

    @router.get("/passkeys/status")
    def passkey_status() -> dict[str, bool]:
        """For the sign-in screen: offer the passkey button only when it can work."""
        return {"configured": bool(rp_id and origin), "registered": bool(rp_id and origin and store.passkeys())}

    @router.post("/passkeys/login/options")
    def login_options(request: Request, response: Response) -> Response:
        rp, _ = configured()
        options = generate_authentication_options(rp_id=rp, user_verification=UserVerificationRequirement.REQUIRED)
        key = secrets.token_urlsafe(24)
        pending.put(f"auth:{key}", options.challenge)
        out = Response(options_to_json(options), media_type="application/json")
        out.set_cookie(
            CHALLENGE_COOKIE, key, max_age=300, httponly=True, secure=settings.cookie_secure,
            samesite="strict", path="/api/passkeys/",
        )
        return out

    @router.post("/passkeys/login/verify")
    def login_verify(body: LoginIn, request: Request, response: Response) -> dict[str, bool]:
        rp, expected_origin = configured()
        who = client(request)
        if not throttle.acquire(who):
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts, try later")
        key = request.cookies.get(CHALLENGE_COOKIE, "")
        challenge = pending.take(f"auth:{key}") if key else None
        response.delete_cookie(CHALLENGE_COOKIE, path="/api/passkeys/")
        if challenge is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Challenge expired, start again")
        credential_id = body.credential.get("id")
        passkey = store.passkey(credential_id) if isinstance(credential_id, str) else None
        if passkey is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown passkey")
        try:
            verified = verify_authentication_response(
                credential=body.credential,
                expected_challenge=challenge,
                expected_rp_id=rp,
                expected_origin=expected_origin,
                credential_public_key=passkey.public_key,
                credential_current_sign_count=passkey.sign_count,
                require_user_verification=True,
            )
        except (WebAuthnException, ValueError, KeyError, TypeError) as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Passkey refused") from exc
        throttle.succeeded(who)
        store.passkey_used(passkey.id, verified.new_sign_count)
        sign_in(request, response, "passkey", passkey.id)
        return {"authenticated": True}

    # ------------------------------------------------------------ devices

    @router.get("/devices")
    def devices(sid: str = Depends(require_session)) -> dict[str, Any]:
        mine = store.hash_of(sid)
        return {
            "passkeys_configured": bool(rp_id and origin),
            "passkeys": [
                {"id": p.id, "name": p.name, "created_at": p.created_at, "last_used": p.last_used,
                 "synced": p.backed_up}
                for p in store.passkeys()
            ],
            "sessions": [
                {"id": s.id_hash, "label": s.label, "method": s.method, "created_at": s.created_at,
                 "last_seen": s.last_seen, "current": s.id_hash == mine}
                for s in store.sessions()
            ],
        }

    @router.patch("/passkeys/{credential_id}")
    def rename_passkey(credential_id: str, body: RenameIn, _sid: str = Depends(require_session)) -> dict[str, str]:
        if not store.rename_passkey(credential_id, body.name.strip()):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown passkey")
        return {"id": credential_id, "name": body.name.strip()}

    @router.delete("/passkeys/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
    def remove_passkey(credential_id: str, sid: str = Depends(require_session)) -> Response:
        current = store.check_session(sid)
        if current is not None and current.passkey_id == credential_id:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "This device signed in with this passkey: remove it from another device"
            )
        if not store.remove_passkey(credential_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown passkey")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.delete("/sessions/{id_hash}", status_code=status.HTTP_204_NO_CONTENT)
    def end_session(id_hash: str, sid: str = Depends(require_session)) -> Response:
        if id_hash == store.hash_of(sid):
            raise HTTPException(status.HTTP_409_CONFLICT, "Use « Se déconnecter » for this device")
        if not store.end_session(id_hash):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown session")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/sessions/end-others")
    def end_others(sid: str = Depends(require_session)) -> dict[str, int]:
        return {"ended": store.end_other_sessions(sid)}

    return router
