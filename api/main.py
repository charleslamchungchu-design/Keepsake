"""
Keepsake API
FastAPI backend for the Keepsake companion app.

Run with: uvicorn api.main:app --reload
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import get_settings
from api.routes import (
    auth_router,
    chat_router,
    user_router,
    memory_router,
    scenes_router
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    settings = get_settings()
    print(f"🚀 Keepsake API starting...")
    print(f"   Debug mode: {settings.debug}")
    yield
    # Shutdown
    print("👋 Keepsake API shutting down...")


# Initialize FastAPI app
settings = get_settings()
app = FastAPI(
    title=settings.api_title,
    version=settings.api_version,
    description="""
## Keepsake Companion API

Backend API for the Keepsake emotional companion mobile app.

### Features
- 🔐 **Authentication** via Supabase Auth
- 💬 **Chat** with streaming AI responses
- 🧠 **Memory** with tiered fact storage
- 👤 **Profiles** with emotional state tracking
- 🎭 **Scenes** with immersive environments

### Tiers
- **Free (0)**: 15 messages/day, 48-hour memory
- **Plus (1)**: Unlimited, permanent memory, RAG
- **Premium (2)**: All features + persona switching
    """,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# Configure CORS
cors_origins = settings.cors_origins.split(",") if settings.cors_origins != "*" else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(user_router)
app.include_router(memory_router)
app.include_router(scenes_router)


@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "app": "Keepsake API",
        "version": settings.api_version
    }


@app.get("/health")
async def health():
    """Detailed health check."""
    return {
        "status": "healthy",
        "services": {
            "api": "up",
            "openai": "configured",
            "supabase": "configured"
        }
    }


# For running directly with `python -m api.main`
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )

