"""
Authentication Routes
Handles user registration, login, and token management via Supabase Auth.
"""
from fastapi import APIRouter, HTTPException, Depends
from supabase import create_client

from api.config import get_settings
from api.models.schemas import UserRegister, UserLogin, AuthResponse
from api.services.memory import memory_service

router = APIRouter(prefix="/auth", tags=["Authentication"])


def get_supabase_client():
    """Get Supabase client for auth operations."""
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_key)


@router.post("/register", response_model=AuthResponse)
async def register(user_data: UserRegister):
    """
    Register a new user with Supabase Auth and create initial memory.
    """
    client = get_supabase_client()
    
    try:
        # Create user in Supabase Auth
        auth_response = client.auth.sign_up({
            "email": user_data.email,
            "password": user_data.password,
            "options": {
                "data": {
                    "name": user_data.name,
                    "companion_name": user_data.companion_name
                }
            }
        })
        
        if not auth_response.user:
            raise HTTPException(status_code=400, detail="Failed to create user")
        
        user_id = auth_response.user.id
        
        # Create initial memory for user
        profile = {
            "name": user_data.name,
            "age": user_data.age or "",
            "gender": user_data.gender or "",
            "companion_name": user_data.companion_name
        }
        await memory_service.create_user_memory(user_id, profile)
        
        # Update memory with avatar choice
        memory = await memory_service.load_memory(user_id)
        memory['avatar_id'] = user_data.avatar_id
        await memory_service.save_memory(user_id, memory)
        
        return AuthResponse(
            access_token=auth_response.session.access_token,
            refresh_token=auth_response.session.refresh_token,
            user_id=user_id,
            expires_at=auth_response.session.expires_at
        )
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/login", response_model=AuthResponse)
async def login(credentials: UserLogin):
    """
    Login user and return JWT tokens.
    """
    client = get_supabase_client()
    
    try:
        auth_response = client.auth.sign_in_with_password({
            "email": credentials.email,
            "password": credentials.password
        })
        
        if not auth_response.user:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        
        return AuthResponse(
            access_token=auth_response.session.access_token,
            refresh_token=auth_response.session.refresh_token,
            user_id=auth_response.user.id,
            expires_at=auth_response.session.expires_at
        )
        
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid credentials")


@router.post("/refresh", response_model=AuthResponse)
async def refresh_token(refresh_token: str):
    """
    Refresh access token using refresh token.
    """
    client = get_supabase_client()
    
    try:
        auth_response = client.auth.refresh_session(refresh_token)
        
        if not auth_response.session:
            raise HTTPException(status_code=401, detail="Invalid refresh token")
        
        return AuthResponse(
            access_token=auth_response.session.access_token,
            refresh_token=auth_response.session.refresh_token,
            user_id=auth_response.user.id,
            expires_at=auth_response.session.expires_at
        )
        
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid refresh token")


@router.post("/logout")
async def logout():
    """
    Logout is handled client-side by discarding tokens.
    This endpoint exists for API completeness.
    """
    return {"message": "Logged out successfully"}

