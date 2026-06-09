from collections.abc import Callable, Mapping

from fastapi import APIRouter


def build_router(handlers: Mapping[str, Callable]) -> APIRouter:
    router = APIRouter()
    routes = [
        ("GET", "/api/system/mode", "get_system_mode"),
        ("GET", "/api/admin/elders", "list_allowed_elders"),
        ("GET", "/api/admin/elders/preview-id", "preview_elder_id"),
        ("POST", "/api/admin/elders", "create_elder"),
        ("POST", "/api/admin/elder-pin", "create_elder_pin"),
        (
            "POST",
            "/api/admin/elder-session/revoke",
            "revoke_elder_session",
        ),
        ("POST", "/api/elder-login", "elder_login"),
        ("GET", "/api/elder/profile", "get_elder_profile"),
        ("GET", "/api/elder/personas", "get_elder_personas"),
        ("POST", "/api/elder/tts", "elder_text_to_speech"),
        (
            "GET",
            "/api/elder/chat/background/{task_id}",
            "get_elder_background_result",
        ),
    ]
    for method, path, name in routes:
        router.add_api_route(path, handlers[name], methods=[method])
    return router
