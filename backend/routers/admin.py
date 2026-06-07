from collections.abc import Callable, Mapping

from fastapi import APIRouter


def build_router(handlers: Mapping[str, Callable]) -> APIRouter:
    router = APIRouter()
    routes = [
        ("GET", "/admin", "admin_page"),
        ("GET", "/api/admin/me", "admin_me"),
        ("GET", "/api/admin/sessions", "list_sessions"),
        ("POST", "/api/admin/sessions/clear", "clear_sessions"),
        ("POST", "/api/admin/rag/evaluate", "evaluate_rag"),
        (
            "POST",
            "/api/admin/stt/evaluate-transcripts",
            "evaluate_stt_transcripts",
        ),
    ]
    for method, path, name in routes:
        router.add_api_route(path, handlers[name], methods=[method])
    return router
