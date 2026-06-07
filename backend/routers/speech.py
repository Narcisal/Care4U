from collections.abc import Callable, Mapping

from fastapi import APIRouter


def build_router(handlers: Mapping[str, Callable]) -> APIRouter:
    router = APIRouter()
    routes = [
        ("POST", "/api/stt", "speech_to_text"),
        ("GET", "/api/stt/status", "get_stt_status"),
        ("POST", "/api/tts", "text_to_speech"),
        ("POST", "/api/stt/language", "set_stt_language"),
    ]
    for method, path, name in routes:
        router.add_api_route(path, handlers[name], methods=[method])
    return router
