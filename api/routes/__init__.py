"""Keepsake API Routes"""
from api.routes.auth import router as auth_router
from api.routes.chat import router as chat_router
from api.routes.user import router as user_router
from api.routes.memory import router as memory_router
from api.routes.scenes import router as scenes_router

__all__ = [
    "auth_router",
    "chat_router", 
    "user_router",
    "memory_router",
    "scenes_router"
]

