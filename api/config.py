"""
Keepsake API Configuration
Loads environment variables and provides typed config access.
"""
import os
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # API Settings
    api_title: str = "Keepsake API"
    api_version: str = "1.0.0"
    debug: bool = False
    
    # OpenAI
    openai_api_key: str
    
    # Supabase
    supabase_url: str
    supabase_key: str  # Service role key for backend operations
    supabase_jwt_secret: str  # For verifying user JWTs
    
    # Security
    cors_origins: str = "*"  # Comma-separated list, or "*" for dev
    
    # Rate Limiting
    rate_limit_per_minute: int = 30
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    """Cached settings instance."""
    return Settings()


# Tier configuration
TIER_CONFIG = {
    0: {  # Free
        "name": "Free",
        "message_limit": 15,
        "memory_hours": 48,
        "models": {"default": "gpt-4o-mini", "deep": "gpt-4o-mini"},
        "first_deep_4o": True,  # One-time taste
        "scenes": ["Lounge", "Body Double"],
        "rag_enabled": False,
    },
    1: {  # Plus
        "name": "Plus", 
        "message_limit": None,  # Unlimited
        "memory_hours": None,  # Permanent
        "models": {"default": "gpt-4o-mini", "deep": "gpt-4o"},
        "first_deep_4o": False,
        "scenes": ["Lounge", "Body Double", "Cafe", "Evening Walk"],
        "rag_enabled": True,
    },
    2: {  # Premium
        "name": "Premium",
        "message_limit": None,
        "memory_hours": None,
        "models": {"default": "gpt-4o-mini", "deep": "gpt-4o"},
        "first_deep_4o": False,
        "scenes": ["Lounge", "Body Double", "Cafe", "Evening Walk", "Firework"],
        "rag_enabled": True,
        "persona_switching": True,
        "priority_routing": True,  # First message & returning user get 4o
    },
}

# Avatar mapping
AVATAR_MAP = {
    "Female - Friend": "1",
    "Male - Friend": "2",
}

# Deep emotional triggers
DEEP_TRIGGERS = [
    # Negative
    "sad", "upset", "anxious", "lonely", "fail", "broken", "worry", "hurt",
    "grief", "depressed", "exhausted", "scared", "angry", "frustrated",
    "hopeless", "overwhelmed", "stressed", "crying", "panic",
    # Positive (celebration moments)
    "amazing", "incredible", "best day", "so happy", "excited", "promotion",
    "got the job", "engaged", "pregnant", "won", "finally"
]

