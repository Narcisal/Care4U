from collections.abc import Callable, Mapping

from fastapi import APIRouter


def build_router(handlers: Mapping[str, Callable]) -> APIRouter:
    router = APIRouter()
    routes = [
        ("GET", "/api/profile/{elder_id}", "get_profile"),
        ("GET", "/api/history/{elder_id}", "get_history"),
        ("GET", "/api/safety/{elder_id}", "get_safety"),
        (
            "PATCH",
            "/api/isafe/{elder_id}/events/{index}/acknowledge",
            "acknowledge_safety_event",
        ),
        (
            "POST",
            "/api/isafe/{elder_id}/events/acknowledge-tag",
            "acknowledge_safety_events_by_tag",
        ),
        ("GET", "/api/agent-logs", "get_agent_logs"),
        ("POST", "/api/profile/save", "save_profile"),
        ("POST", "/api/profile/save-biography", "save_biography"),
        (
            "POST",
            "/api/profile/background-candidates",
            "background_candidates",
        ),
        ("POST", "/api/profile/biography-draft", "biography_draft"),
        ("POST", "/api/profile/biography-preview-new", "biography_preview_new"),
        ("POST", "/api/profile/family-note/add", "add_family_note"),
        (
            "POST",
            "/api/profile/family-note/delete",
            "delete_family_note",
        ),
    ]
    for method, path, name in routes:
        router.add_api_route(path, handlers[name], methods=[method])
    return router
