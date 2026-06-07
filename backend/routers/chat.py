from collections.abc import Callable, Mapping

from fastapi import APIRouter


def build_router(handlers: Mapping[str, Callable]) -> APIRouter:
    router = APIRouter()
    router.add_api_route("/", handlers["read_root"], methods=["GET"])
    router.add_api_route(
        "/api/switch-elder",
        handlers["switch_elder"],
        methods=["POST"],
    )
    router.add_api_route("/api/greet", handlers["greet"], methods=["POST"])
    router.add_api_route("/api/chat", handlers["chat"], methods=["POST"])
    router.add_api_route(
        "/api/chat/background/{task_id}",
        handlers["get_chat_background_result"],
        methods=["GET"],
    )
    return router
