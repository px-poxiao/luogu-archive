"""API v1 路由包。"""
from fastapi import APIRouter

from app.api.v1 import admin_auth, admin_panel, auth, content, save, takedown, user

api_v1 = APIRouter(prefix="/api/v1")
api_v1.include_router(save.router)
api_v1.include_router(content.router)
api_v1.include_router(user.router)
api_v1.include_router(takedown.router)
api_v1.include_router(auth.router)
api_v1.include_router(admin_auth.router)
api_v1.include_router(admin_panel.router)
