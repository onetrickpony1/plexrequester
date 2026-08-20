"""PIN validation, persisted login sessions, and cookie helpers."""

import secrets
import time


AUTH_COOKIE_NAME = "plex_requester_token"
AUTH_SESSION_TTL = 7 * 24 * 60 * 60
AUTH_REFRESH_AFTER = 24 * 60 * 60


def admin_pin(config):
    return str(config.get("adminPin", "")).strip()


def pin_matches(config, value):
    configured_pin = admin_pin(config)
    return bool(configured_pin) and str(value or "") == configured_pin


def role_from_pin(config, value):
    return "admin" if pin_matches(config, value) else ""


def prune_auth_sessions(sessions, now=None):
    now = int(time.time() if now is None else now)
    changed = False
    for token, session in list(sessions.items()):
        if not isinstance(session, dict) or int(session.get("expiresAt") or 0) <= now:
            sessions.pop(token, None)
            changed = True
    return changed


def create_auth_session(role, load_sessions, save_sessions, now=None):
    sessions = load_sessions()
    now = int(time.time() if now is None else now)
    prune_auth_sessions(sessions, now)
    token = secrets.token_urlsafe(32)
    sessions[token] = {
        "role": role,
        "createdAt": now,
        "expiresAt": now + AUTH_SESSION_TTL,
    }
    save_sessions(sessions)
    return token


def session_cookie_header(token):
    return (
        f"{AUTH_COOKIE_NAME}={token}; Path=/; Max-Age={AUTH_SESSION_TTL}; "
        "HttpOnly; SameSite=Lax"
    )


def expired_session_cookie_header():
    return f"{AUTH_COOKIE_NAME}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"
