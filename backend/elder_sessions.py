import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


MAX_PIN_SESSIONS = 1000
MAX_ELDER_TOKENS = 1000
MAX_LOGIN_FAIL_RECORDS = 2000
LOGIN_MAX_FAILURES = 5
LOGIN_LOCK_SECONDS = 60


@dataclass
class PinSession:
    elder_id: str
    created_at: datetime
    expires_at: datetime
    used: bool = False


@dataclass
class ElderTokenSession:
    elder_id: str
    expires_at: datetime


@dataclass(frozen=True)
class ElderIdentity:
    token: str
    elder_id: str
    expires_at: datetime


@dataclass
class FailRecord:
    failures: int = 0
    locked_until: float = 0.0


class InvalidPinError(Exception):
    pass


class LoginRateLimitedError(Exception):
    pass


pin_sessions: dict[str, PinSession] = {}
elder_tokens: dict[str, ElderTokenSession] = {}
login_fail_counts: dict[str, FailRecord] = {}
session_lock = threading.Lock()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _cleanup_unlocked(now: datetime):
    for pin, session in list(pin_sessions.items()):
        if session.expires_at <= now or session.used:
            pin_sessions.pop(pin, None)
    for token, session in list(elder_tokens.items()):
        if session.expires_at <= now:
            elder_tokens.pop(token, None)


def _trim_unlocked(store: dict, maximum: int):
    while len(store) >= maximum:
        store.pop(next(iter(store)))


def issue_pin(elder_id: str, ttl_minutes: int = 480) -> tuple[str, PinSession]:
    now = _utcnow()
    expires_at = now + timedelta(minutes=ttl_minutes)
    with session_lock:
        _cleanup_unlocked(now)
        _trim_unlocked(pin_sessions, MAX_PIN_SESSIONS)
        for _ in range(100):
            pin = f"{secrets.randbelow(1_000_000):06d}"
            if pin not in pin_sessions:
                session = PinSession(
                    elder_id=elder_id,
                    created_at=now,
                    expires_at=expires_at,
                )
                pin_sessions[pin] = session
                return pin, session
    raise RuntimeError("無法產生唯一 PIN")


def login_with_pin(
    pin: str,
    client_key: str,
) -> tuple[str, ElderTokenSession]:
    now_monotonic = time.monotonic()
    now = _utcnow()
    with session_lock:
        if client_key not in login_fail_counts:
            _trim_unlocked(login_fail_counts, MAX_LOGIN_FAIL_RECORDS)
        record = login_fail_counts.setdefault(client_key, FailRecord())
        if record.locked_until > now_monotonic:
            raise LoginRateLimitedError()
        if record.locked_until:
            record.failures = 0
            record.locked_until = 0.0

        _cleanup_unlocked(now)
        pin_session = pin_sessions.get(pin)
        if (
            pin_session is None
            or pin_session.used
            or pin_session.expires_at <= now
        ):
            record.failures += 1
            if record.failures >= LOGIN_MAX_FAILURES:
                record.locked_until = now_monotonic + LOGIN_LOCK_SECONDS
            raise InvalidPinError()

        pin_session.used = True
        login_fail_counts.pop(client_key, None)
        _trim_unlocked(elder_tokens, MAX_ELDER_TOKENS)
        token = secrets.token_urlsafe(32)
        token_session = ElderTokenSession(
            elder_id=pin_session.elder_id,
            expires_at=pin_session.expires_at,
        )
        elder_tokens[token] = token_session
        return token, token_session


def validate_token(token: str) -> ElderIdentity | None:
    now = _utcnow()
    with session_lock:
        _cleanup_unlocked(now)
        session = elder_tokens.get(token)
        if session is None:
            return None
        return ElderIdentity(
            token=token,
            elder_id=session.elder_id,
            expires_at=session.expires_at,
        )


def revoke_elder(elder_id: str) -> tuple[int, int]:
    with session_lock:
        removed_pins = 0
        removed_tokens = 0
        for pin, session in list(pin_sessions.items()):
            if session.elder_id == elder_id:
                pin_sessions.pop(pin, None)
                removed_pins += 1
        for token, session in list(elder_tokens.items()):
            if session.elder_id == elder_id:
                elder_tokens.pop(token, None)
                removed_tokens += 1
        return removed_pins, removed_tokens


def clear_all_sessions():
    with session_lock:
        pin_sessions.clear()
        elder_tokens.clear()
        login_fail_counts.clear()
