"""API v1 路由包。"""
from fastapi import APIRouter

from app.api.v1 import admin_auth, admin_panel, admin_plugin, auth, content, contest, image_card, plugin, save, site, solution_fix, takedown, user
from app.core.config import settings

api_v1 = APIRouter(prefix="/api/v1")
api_v1.include_router(save.router)
api_v1.include_router(content.router)
api_v1.include_router(user.router)
api_v1.include_router(contest.router)
api_v1.include_router(site.router)
api_v1.include_router(image_card.router)
api_v1.include_router(takedown.router)
api_v1.include_router(solution_fix.router)
api_v1.include_router(auth.router)
api_v1.include_router(plugin.router)
api_v1.include_router(admin_auth.router)
api_v1.include_router(admin_panel.router)
api_v1.include_router(admin_plugin.router)


_EXTENDED_ARCHIVE_EXACT_ROUTES = {
    "/api/v1/feed",
    "/api/v1/fake-realtime",
}
_EXTENDED_ARCHIVE_ROUTE_PREFIXES = (
    "/api/v1/problem",
    "/api/v1/contest",
    "/api/v1/admin/problems",
    "/api/v1/admin/contests",
)


def _is_extended_archive_route(path: str) -> bool:
    return path in _EXTENDED_ARCHIVE_EXACT_ROUTES or any(
        path == prefix or path.startswith(f"{prefix}/")
        for prefix in _EXTENDED_ARCHIVE_ROUTE_PREFIXES
    )


if not settings.EXTENDED_ARCHIVE_MODULES_ENABLED:
    # 同时从路由匹配和 OpenAPI 中移除；所有实现仍留在原模块中。
    api_v1.routes[:] = [
        route
        for route in api_v1.routes
        if not _is_extended_archive_route(getattr(route, "path", ""))
    ]


