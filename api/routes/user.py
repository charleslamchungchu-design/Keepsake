"""
User Profile Routes
Handles profile retrieval and updates.
"""
from fastapi import APIRouter, HTTPException, Depends

from api.models.schemas import ProfileUpdate, ProfileResponse
from api.services.memory import memory_service
from api.routes.deps import get_current_user

router = APIRouter(prefix="/user", tags=["User"])


@router.get("/profile", response_model=ProfileResponse)
async def get_profile(user: dict = Depends(get_current_user)):
    """
    Get current user's profile and stats.
    """
    user_id = user["id"]
    memory = await memory_service.load_memory(user_id)
    
    profile = memory.get('user_profile', {})
    emotional = memory.get('emotional_state', {})
    
    return ProfileResponse(
        user_profile={
            "name": profile.get('name', ''),
            "age": profile.get('age', ''),
            "gender": profile.get('gender', ''),
            "companion_name": profile.get('companion_name', 'Keepsake')
        },
        emotional_state=emotional,
        balance=memory.get('balance', 100),
        tier=memory.get('tier', 0),
        avatar_id=memory.get('avatar_id', '1'),
        current_outfit=memory.get('current_outfit', 'default')
    )


@router.put("/profile", response_model=ProfileResponse)
async def update_profile(
    updates: ProfileUpdate,
    user: dict = Depends(get_current_user)
):
    """
    Update user profile fields.
    Only provided fields will be updated.
    """
    user_id = user["id"]
    memory = await memory_service.load_memory(user_id)
    
    # Update profile fields
    profile = memory.get('user_profile', {})
    
    if updates.name is not None:
        profile['name'] = updates.name
    if updates.age is not None:
        profile['age'] = updates.age
    if updates.gender is not None:
        profile['gender'] = updates.gender
    if updates.companion_name is not None:
        profile['companion_name'] = updates.companion_name
    
    memory['user_profile'] = profile
    
    # Update other fields
    if updates.avatar_id is not None:
        memory['avatar_id'] = updates.avatar_id
    if updates.current_outfit is not None:
        memory['current_outfit'] = updates.current_outfit
    if updates.time_offset is not None:
        memory['time_offset'] = updates.time_offset
    
    # Save
    await memory_service.save_memory(user_id, memory)
    
    return ProfileResponse(
        user_profile=profile,
        emotional_state=memory.get('emotional_state', {}),
        balance=memory.get('balance', 100),
        tier=memory.get('tier', 0),
        avatar_id=memory.get('avatar_id', '1'),
        current_outfit=memory.get('current_outfit', 'default')
    )


@router.post("/avatar/{avatar_id}")
async def set_avatar(
    avatar_id: str,
    user: dict = Depends(get_current_user)
):
    """
    Set user's avatar/persona.
    Premium users can switch freely, others are locked.
    """
    user_id = user["id"]
    memory = await memory_service.load_memory(user_id)
    
    tier = memory.get('tier', 0)
    
    # Check if persona switching is allowed
    if tier < 2 and memory.get('has_chosen_avatar', False):
        raise HTTPException(
            status_code=403,
            detail="Persona switching requires Premium tier. Upgrade to switch companions."
        )
    
    memory['avatar_id'] = avatar_id
    memory['has_chosen_avatar'] = True
    await memory_service.save_memory(user_id, memory)
    
    return {"message": f"Avatar updated to {avatar_id}", "avatar_id": avatar_id}


@router.get("/balance")
async def get_balance(user: dict = Depends(get_current_user)):
    """
    Get user's coin balance.
    """
    user_id = user["id"]
    memory = await memory_service.load_memory(user_id)
    
    return {
        "balance": memory.get('balance', 100),
        "tier": memory.get('tier', 0)
    }


@router.post("/spend/{amount}")
async def spend_coins(
    amount: int,
    user: dict = Depends(get_current_user)
):
    """
    Spend coins (for purchases, gifts, etc.)
    """
    user_id = user["id"]
    memory = await memory_service.load_memory(user_id)
    
    current_balance = memory.get('balance', 100)
    
    if amount > current_balance:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient balance. You have {current_balance} coins."
        )
    
    memory['balance'] = current_balance - amount
    
    # Spending coins increases warmth
    memory['emotional_state']['warmth'] = min(
        100, 
        memory['emotional_state'].get('warmth', 10) + (amount // 2)
    )
    
    await memory_service.save_memory(user_id, memory)
    
    return {
        "new_balance": memory['balance'],
        "spent": amount,
        "warmth_gained": amount // 2
    }

