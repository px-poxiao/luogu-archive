"""API v1 路由包。"""
from fastapi import APIRouter

from app.api.v1 import admin_auth, admin_panel, auth, content, image_card, save, site, solution_fix, takedown, user

api_v1 = APIRouter(prefix="/api/v1")
api_v1.include_router(save.router)
api_v1.include_router(content.router)
api_v1.include_router(user.router)
api_v1.include_router(site.router)
api_v1.include_router(image_card.router)
api_v1.include_router(takedown.router)
api_v1.include_router(solution_fix.router)
api_v1.include_router(auth.router)
api_v1.include_router(admin_auth.router)
api_v1.include_router(admin_panel.router)


