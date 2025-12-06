"""
Memory Routes
Handles facts, journal, and memory management.
"""
from fastapi import APIRouter, Depends

from api.models.schemas import FactsResponse, SyncResponse
from api.services.memory import memory_service
from api.routes.deps import get_current_user

router = APIRouter(prefix="/memory", tags=["Memory"])


@router.get("/facts", response_model=FactsResponse)
async def get_facts(user: dict = Depends(get_current_user)):
    """
    Get stored facts about the user.
    Free tier only sees facts from last 48 hours.
    """
    user_id = user["id"]
    memory = await memory_service.load_memory(user_id)
    
    tier = memory.get('tier', 0)
    raw_facts = memory.get('user_facts', [])
    
    valid_facts, expired_count = memory_service.get_valid_facts_with_expiry(raw_facts, tier)
    
    return FactsResponse(
        facts=valid_facts,
        expired_count=expired_count,
        tier=tier
    )


@router.delete("/facts")
async def clear_facts(user: dict = Depends(get_current_user)):
    """
    Clear all stored facts.
    """
    user_id = user["id"]
    memory = await memory_service.load_memory(user_id)
    
    memory['user_facts'] = []
    await memory_service.save_memory(user_id, memory)
    
    return {"message": "Facts cleared successfully"}


@router.post("/sync", response_model=SyncResponse)
async def sync_memory(user: dict = Depends(get_current_user)):
    """
    Force sync memory from cloud.
    Useful after background tasks update the database.
    """
    user_id = user["id"]
    
    try:
        # Just load fresh - this forces a new read from Supabase
        memory = await memory_service.load_memory(user_id)
        
        return SyncResponse(
            success=True,
            message=f"Synced {len(memory.get('user_facts', []))} facts, {len(memory.get('history', []))} messages"
        )
    except Exception as e:
        return SyncResponse(
            success=False,
            message=str(e)
        )


@router.get("/emotional-state")
async def get_emotional_state(user: dict = Depends(get_current_user)):
    """
    Get current emotional state scores.
    """
    user_id = user["id"]
    memory = await memory_service.load_memory(user_id)
    
    return {
        "emotional_state": memory.get('emotional_state', {}),
        "active_context": memory.get('active_context', {})
    }


@router.get("/stats")
async def get_memory_stats(user: dict = Depends(get_current_user)):
    """
    Get memory statistics for the user.
    """
    user_id = user["id"]
    memory = await memory_service.load_memory(user_id)
    
    history = memory.get('history', [])
    user_messages = len([m for m in history if m.get('role') == 'user'])
    assistant_messages = len([m for m in history if m.get('role') == 'assistant'])
    
    tier = memory.get('tier', 0)
    raw_facts = memory.get('user_facts', [])
    valid_facts, expired_count = memory_service.get_valid_facts_with_expiry(raw_facts, tier)
    
    return {
        "total_messages": len(history),
        "user_messages": user_messages,
        "assistant_messages": assistant_messages,
        "facts_count": len(valid_facts),
        "expired_facts_count": expired_count,
        "tier": tier,
        "emotional_state": memory.get('emotional_state', {}),
        "last_active": memory.get('last_active_timestamp', ''),
        "balance": memory.get('balance', 100)
    }

