import re


_ELDER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_PERSONA_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _validate_identifier(value: str, field_name: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ValueError(f"{field_name} 格式不合法")
    return value


def validate_elder_id(elder_id: str) -> str:
    return _validate_identifier(elder_id, "elder_id", _ELDER_ID_PATTERN)


def validate_persona_id(persona_id: str) -> str:
    return _validate_identifier(persona_id, "persona_id", _PERSONA_ID_PATTERN)


def validate_session_id(session_id: str) -> str:
    return _validate_identifier(session_id, "session_id", _SESSION_ID_PATTERN)
