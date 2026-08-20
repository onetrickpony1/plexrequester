"""PIN validation, persisted login sessions, and cookie helpers."""

import ipaddress
import secrets
import threading
import time


AUTH_COOKIE_NAME = "plex_requester_token"
AUTH_SESSION_TTL = 7 * 24 * 60 * 60
AUTH_REFRESH_AFTER = 24 * 60 * 60
ADMIN_PIN_MIN_LENGTH = 8
ADMIN_PIN_MAX_LENGTH = 128
AUTH_MAX_FAILED_ATTEMPTS = 5
AUTH_FAILURE_WINDOW = 15 * 60
AUTH_LOCKOUT_SECONDS = 15 * 60
INSECURE_ADMIN_PINS = {"change-this-pin"}

_FAILED_LOGIN_LOCK = threading.RLock()
_FAILED_LOGIN_ATTEMPTS = {}


def admin_pin(config):
    return str(config.get("adminPin", "")).strip()


def admin_pin_is_valid(value):
    pin = str(value or "").strip()
    return (
        ADMIN_PIN_MIN_LENGTH <= len(pin) <= ADMIN_PIN_MAX_LENGTH
        and pin.casefold() not in INSECURE_ADMIN_PINS
    )


def pin_matches(config, value):
    configured_pin = admin_pin(config)
    supplied_pin = str(value or "")
    return admin_pin_is_valid(configured_pin) and secrets.compare_digest(supplied_pin, configured_pin)


def role_from_pin(config, value):
    return "admin" if pin_matches(config, value) else ""


def login_rate_limit_key(client_address, access_identity=""):
    """Use a verified Access identity behind a local proxy, otherwise the peer address."""
    address = str(client_address or "unknown").strip() or "unknown"
    identity = str(access_identity or "").strip().casefold()[:320]
    try:
        local_proxy = ipaddress.ip_address(address).is_loopback
    except ValueError:
        local_proxy = False
    if local_proxy and identity:
        return f"access:{identity}"
    return f"address:{address}"


def login_retry_after(key, now=None):
    now = int(time.time() if now is None else now)
    with _FAILED_LOGIN_LOCK:
        entry = _FAILED_LOGIN_ATTEMPTS.get(key)
        if not isinstance(entry, dict):
            return 0
        locked_until = int(entry.get("lockedUntil") or 0)
        if locked_until > now:
            return locked_until - now
        attempts = [
            int(attempt)
            for attempt in entry.get("attempts", [])
            if int(attempt) > now - AUTH_FAILURE_WINDOW
        ]
        if attempts:
            entry["attempts"] = attempts
            entry["lockedUntil"] = 0
        else:
            _FAILED_LOGIN_ATTEMPTS.pop(key, None)
        return 0


def record_failed_login(key, now=None):
    now = int(time.time() if now is None else now)
    with _FAILED_LOGIN_LOCK:
        login_retry_after(key, now)
        entry = _FAILED_LOGIN_ATTEMPTS.setdefault(key, {"attempts": [], "lockedUntil": 0})
        entry["attempts"].append(now)
        if len(entry["attempts"]) >= AUTH_MAX_FAILED_ATTEMPTS:
            entry["lockedUntil"] = now + AUTH_LOCKOUT_SECONDS
            return AUTH_LOCKOUT_SECONDS
        return 0


def clear_failed_logins(key):
    with _FAILED_LOGIN_LOCK:
        _FAILED_LOGIN_ATTEMPTS.pop(key, None)


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
