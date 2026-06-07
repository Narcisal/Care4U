from collections.abc import Callable, Mapping

from fastapi import APIRouter


def build_router(handlers: Mapping[str, Callable]) -> APIRouter:
    router = APIRouter()
    routes = [
        ("GET", "/api/profile/{elder_id}/personas", "get_personas"),
        ("POST", "/api/profile/persona/add", "add_persona"),
        ("POST", "/api/profile/persona/delete", "delete_persona"),
        ("POST", "/api/profile/persona/switch", "switch_persona"),
        (
            "POST",
            "/api/profile/persona/upload-voice",
            "upload_voice",
        ),
        (
            "POST",
            "/api/profile/persona/upload-avatar",
            "upload_avatar",
        ),
    ]
    for method, path, name in routes:
        router.add_api_route(path, handlers[name], methods=[method])
    return router
