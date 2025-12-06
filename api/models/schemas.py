"""
Pydantic models for API request/response schemas.
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


# ============ AUTH ============

class UserRegister(BaseModel):
    """User registration request."""
    email: str
    password: str
    name: str
    age: Optional[str] = None
    gender: Optional[str] = None
    companion_name: str = "Keepsake"
    avatar_id: str = "1"


class UserLogin(BaseModel):
    """User login request."""
    email: str
    password: str


class AuthResponse(BaseModel):
    """Authentication response with tokens."""
    access_token: str
    refresh_token: str
    user_id: str
    expires_at: int


# ============ USER PROFILE ============

class UserProfile(BaseModel):
    """User profile data."""
    name: str
    age: Optional[str] = None
    gender: Optional[str] = None
    companion_name: str = "Keepsake"


class EmotionalState(BaseModel):
    """Emotional state scores."""
    closeness: int = Field(default=10, ge=0, le=100)
    warmth: int = Field(default=10, ge=0, le=100)
    pace: int = Field(default=10, ge=0, le=100)
    stability: int = Field(default=80, ge=0, le=100)
    scene_score: int = Field(default=0, ge=0, le=100)
    agency: int = Field(default=10, ge=0, le=100)


class ActiveContext(BaseModel):
    """Active conversation context."""
    last_topic: str = ""
    significant_event: str = ""
    event_date: str = ""
    last_recalled_date: str = ""


class UserFact(BaseModel):
    """A stored fact about the user."""
    content: str
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class UserMemory(BaseModel):
    """Complete user memory state."""
    history: List[Dict[str, str]] = Field(default_factory=list)
    emotional_state: EmotionalState = Field(default_factory=EmotionalState)
    user_profile: UserProfile = Field(default_factory=lambda: UserProfile(name=""))
    active_context: ActiveContext = Field(default_factory=ActiveContext)
    user_facts: List[UserFact] = Field(default_factory=list)
    balance: int = 100
    inventory: List[str] = Field(default_factory=lambda: ["default"])
    current_outfit: str = "default"
    tier: int = 0
    avatar_id: str = "1"
    has_chosen_avatar: bool = False
    time_offset: int = 0
    last_active_timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class ProfileUpdate(BaseModel):
    """Profile update request."""
    name: Optional[str] = None
    age: Optional[str] = None
    gender: Optional[str] = None
    companion_name: Optional[str] = None
    avatar_id: Optional[str] = None
    current_outfit: Optional[str] = None
    time_offset: Optional[int] = None


class ProfileResponse(BaseModel):
    """Profile response."""
    user_profile: UserProfile
    emotional_state: EmotionalState
    balance: int
    tier: int
    avatar_id: str
    current_outfit: str


# ============ CHAT ============

class ChatMessage(BaseModel):
    """A single chat message."""
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    """Chat message request."""
    message: str
    vibe: int = Field(default=50, ge=0, le=100)
    scene: str = "Lounge"


class ChatResponse(BaseModel):
    """Non-streaming chat response."""
    response: str
    emotional_state: EmotionalState
    balance: int
    model_used: str


class VibeGreetingRequest(BaseModel):
    """Request for session greeting."""
    vibe: int = Field(default=50, ge=0, le=100)


class VibeGreetingResponse(BaseModel):
    """Session greeting response."""
    greeting: str
    time_period: str


# ============ MEMORY ============

class FactsResponse(BaseModel):
    """User facts response."""
    facts: List[str]
    expired_count: int = 0
    tier: int


class SyncResponse(BaseModel):
    """Memory sync response."""
    success: bool
    message: str


# ============ SCENES ============

class SceneInfo(BaseModel):
    """Scene information."""
    name: str
    available: bool
    tier_required: int
    description: str


class ScenesResponse(BaseModel):
    """Available scenes response."""
    scenes: List[SceneInfo]
    current_tier: int

