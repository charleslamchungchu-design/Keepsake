"""
Chat Routes
Handles messaging, streaming responses, and session greetings.
"""
import asyncio
import random
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.config import get_settings, TIER_CONFIG
from api.models.schemas import (
    ChatRequest, ChatResponse, VibeGreetingRequest, VibeGreetingResponse
)
from api.services.ai import ai_service
from api.services.memory import memory_service
from api.routes.deps import get_current_user

router = APIRouter(prefix="/chat", tags=["Chat"])


class StreamChatRequest(BaseModel):
    """Request for streaming chat."""
    message: str
    vibe: int = 50
    scene: str = "Lounge"
    is_first_of_session: bool = False


@router.post("/message")
async def send_message(
    request: ChatRequest,
    user: dict = Depends(get_current_user)
):
    """
    Send a message and get AI response (non-streaming).
    Use /message/stream for streaming responses.
    """
    user_id = user["id"]
    
    # Load user memory
    memory = await memory_service.load_memory(user_id)
    tier = memory.get('tier', 0)
    tier_config = TIER_CONFIG.get(tier, TIER_CONFIG[0])
    
    # Check message limit for free tier
    user_msg_count = len([m for m in memory['history'] if m['role'] == 'user'])
    if tier_config.get('message_limit') and user_msg_count >= tier_config['message_limit']:
        raise HTTPException(
            status_code=403, 
            detail="Message limit reached. Upgrade for unlimited conversations."
        )
    
    # Add user message to history
    memory['history'].append({"role": "user", "content": request.message})
    
    # Update emotional state
    memory['emotional_state'] = memory_service.update_emotional_state(
        request.message, 
        memory['emotional_state']
    )
    memory['last_active_timestamp'] = datetime.now().isoformat()
    
    # Detect deep moment and select model
    is_deep, _ = ai_service.detect_deep_moment(request.message, tier)
    
    # Check for first-time 4o taste (free users)
    free_4o_used = memory.get('free_4o_taste_used', False)
    if tier == 0 and is_deep and not free_4o_used:
        memory['free_4o_taste_used'] = True
    
    # Detect returning user (24+ hours)
    is_returning_user = False
    last_active = memory.get('last_active_timestamp', '')
    if last_active:
        try:
            last_dt = datetime.fromisoformat(last_active)
            hours_since = (datetime.now() - last_dt).total_seconds() / 3600
            is_returning_user = hours_since >= 24
        except (ValueError, TypeError):
            pass
    
    # Select model
    model = ai_service.select_model(
        tier, is_deep, 
        is_first_of_session=user_msg_count == 0,
        is_returning_user=is_returning_user,
        free_4o_used=free_4o_used
    )
    
    # Get facts for context
    valid_facts, expired_count = memory_service.get_valid_facts_with_expiry(
        memory.get('user_facts', []), tier
    )
    facts_text = "\n".join(valid_facts) if valid_facts else "(No stored facts yet)"
    if tier == 0 and valid_facts:
        facts_text += "\n(Free tier: 48-hour memory window)"
    
    # RAG retrieval for paid users
    rag_text = ""
    if tier >= 1 and tier_config.get('rag_enabled'):
        rag_text = await memory_service.retrieve_context(user_id, request.message)
    
    # Get emotional value strategy
    value_strategy, value_allows_questions = ai_service.get_emotional_value(
        memory['emotional_state'], request.message
    )
    
    # Build system prompt
    profile = memory.get('user_profile', {})
    system_prompt, vibe_allows_questions = ai_service.build_system_prompt(
        avatar_id=memory.get('avatar_id', '1'),
        user_name=profile.get('name', 'Friend'),
        companion_name=profile.get('companion_name', 'Keepsake'),
        user_msg_count=user_msg_count + 1,
        emotional_state=memory['emotional_state'],
        vibe=request.vibe,
        scene=request.scene,
        facts_text=facts_text,
        rag_text=rag_text,
        situational_modifiers=value_strategy,
        time_offset=memory.get('time_offset', 0)
    )
    
    # Determine if questions allowed
    should_ask_question = vibe_allows_questions and value_allows_questions
    if request.scene == "Body Double":
        should_ask_question = False
    
    # Generate response
    response = await ai_service.generate_response(
        system_prompt,
        memory['history'],
        model,
        is_deep,
        should_ask_question
    )
    
    # Add response to history
    memory['history'].append({"role": "assistant", "content": response})
    
    # Update balance
    memory['balance'] = memory.get('balance', 100) + 2
    
    # Random gift from companion
    if memory['emotional_state'].get('agency', 0) > 20 and random.random() < 0.1:
        memory['balance'] += 15
    
    # Save memory
    await memory_service.save_memory(user_id, memory)
    
    # Background: Extract facts (every 3 messages)
    if (user_msg_count + 1) % 3 == 0:
        asyncio.create_task(extract_facts_background(user_id, list(memory['history'])))
    
    # Background: Save to vector store for paid users
    if len(request.message) > 20 and tier >= 1:
        asyncio.create_task(memory_service.save_vector_memory(user_id, request.message))
    
    return ChatResponse(
        response=response,
        emotional_state=memory['emotional_state'],
        balance=memory['balance'],
        model_used=model
    )


@router.post("/message/stream")
async def send_message_stream(
    request: StreamChatRequest,
    user: dict = Depends(get_current_user)
):
    """
    Send a message and get streaming AI response (SSE).
    """
    user_id = user["id"]
    
    # Load user memory
    memory = await memory_service.load_memory(user_id)
    tier = memory.get('tier', 0)
    tier_config = TIER_CONFIG.get(tier, TIER_CONFIG[0])
    
    # Check message limit for free tier
    user_msg_count = len([m for m in memory['history'] if m['role'] == 'user'])
    if tier_config.get('message_limit') and user_msg_count >= tier_config['message_limit']:
        raise HTTPException(
            status_code=403,
            detail="Message limit reached. Upgrade for unlimited conversations."
        )
    
    # Add user message to history
    memory['history'].append({"role": "user", "content": request.message})
    
    # Update emotional state
    memory['emotional_state'] = memory_service.update_emotional_state(
        request.message,
        memory['emotional_state']
    )
    memory['last_active_timestamp'] = datetime.now().isoformat()
    
    # Detect deep moment and select model
    is_deep, _ = ai_service.detect_deep_moment(request.message, tier)
    
    # Check for first-time 4o taste
    free_4o_used = memory.get('free_4o_taste_used', False)
    if tier == 0 and is_deep and not free_4o_used:
        memory['free_4o_taste_used'] = True
    
    # Detect returning user
    is_returning_user = False
    last_active = memory.get('last_active_timestamp', '')
    if last_active:
        try:
            last_dt = datetime.fromisoformat(last_active)
            hours_since = (datetime.now() - last_dt).total_seconds() / 3600
            is_returning_user = hours_since >= 24
        except (ValueError, TypeError):
            pass
    
    model = ai_service.select_model(
        tier, is_deep,
        is_first_of_session=request.is_first_of_session,
        is_returning_user=is_returning_user,
        free_4o_used=free_4o_used
    )
    
    # Get facts
    valid_facts, _ = memory_service.get_valid_facts_with_expiry(
        memory.get('user_facts', []), tier
    )
    facts_text = "\n".join(valid_facts) if valid_facts else "(No stored facts yet)"
    
    # RAG for paid users
    rag_text = ""
    if tier >= 1 and tier_config.get('rag_enabled'):
        rag_text = await memory_service.retrieve_context(user_id, request.message)
    
    # Get value strategy
    value_strategy, value_allows_questions = ai_service.get_emotional_value(
        memory['emotional_state'], request.message
    )
    
    # Build prompt
    profile = memory.get('user_profile', {})
    system_prompt, vibe_allows_questions = ai_service.build_system_prompt(
        avatar_id=memory.get('avatar_id', '1'),
        user_name=profile.get('name', 'Friend'),
        companion_name=profile.get('companion_name', 'Keepsake'),
        user_msg_count=user_msg_count + 1,
        emotional_state=memory['emotional_state'],
        vibe=request.vibe,
        scene=request.scene,
        facts_text=facts_text,
        rag_text=rag_text,
        situational_modifiers=value_strategy,
        time_offset=memory.get('time_offset', 0)
    )
    
    should_ask_question = vibe_allows_questions and value_allows_questions
    if request.scene == "Body Double":
        should_ask_question = False
    
    async def generate():
        """Stream generator for SSE."""
        full_response = ""
        
        async for chunk in ai_service.generate_response_stream(
            system_prompt,
            memory['history'],
            model,
            is_deep,
            should_ask_question
        ):
            full_response += chunk
            yield f"data: {chunk}\n\n"
        
        # Signal end of stream
        yield f"data: [DONE]\n\n"
        
        # Save response to history and memory
        memory['history'].append({"role": "assistant", "content": full_response})
        memory['balance'] = memory.get('balance', 100) + 2
        
        if memory['emotional_state'].get('agency', 0) > 20 and random.random() < 0.1:
            memory['balance'] += 15
        
        await memory_service.save_memory(user_id, memory)
        
        # Background tasks
        if (user_msg_count + 1) % 3 == 0:
            asyncio.create_task(extract_facts_background(user_id, list(memory['history'])))
        
        if len(request.message) > 20 and tier >= 1:
            asyncio.create_task(memory_service.save_vector_memory(user_id, request.message))
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@router.post("/greeting", response_model=VibeGreetingResponse)
async def get_vibe_greeting(
    request: VibeGreetingRequest,
    user: dict = Depends(get_current_user)
):
    """
    Get a personalized session greeting based on vibe and time.
    """
    user_id = user["id"]
    memory = await memory_service.load_memory(user_id)
    
    # Check for event to reference
    active_context = memory.get('active_context', {})
    event_name = ""
    today_str = str(datetime.now().date())
    
    significant_event = active_context.get('significant_event', '')
    event_date = active_context.get('event_date', '')
    last_recalled = active_context.get('last_recalled_date', '')
    
    if significant_event and event_date:
        try:
            rec_date = datetime.strptime(event_date, "%Y-%m-%d").date()
            days_since = (datetime.now().date() - rec_date).days
            if days_since <= 1 and last_recalled != today_str and request.vibe >= 30:
                event_name = significant_event
                # Update last recalled
                memory['active_context']['last_recalled_date'] = today_str
                await memory_service.save_memory(user_id, memory)
        except ValueError:
            pass
    
    # Generate greeting
    time_offset = memory.get('time_offset', 0)
    hour = (datetime.now().hour + time_offset) % 24
    
    if 5 <= hour < 12:
        period = "Morning"
    elif 12 <= hour < 18:
        period = "Afternoon"
    else:
        period = "Evening"
    
    greeting = await ai_service.generate_greeting(
        avatar_id=memory.get('avatar_id', '1'),
        vibe=request.vibe,
        time_offset=time_offset,
        event_name=event_name
    )
    
    # Add greeting to history
    memory['history'].append({"role": "assistant", "content": greeting})
    await memory_service.save_memory(user_id, memory)
    
    return VibeGreetingResponse(
        greeting=greeting,
        time_period=period
    )


@router.get("/history")
async def get_chat_history(
    limit: int = 50,
    user: dict = Depends(get_current_user)
):
    """
    Get chat history for the user.
    """
    user_id = user["id"]
    memory = await memory_service.load_memory(user_id)
    
    history = memory.get('history', [])
    
    # Filter out system messages and limit
    visible_history = [m for m in history if m.get('role') != 'system'][-limit:]
    
    return {
        "history": visible_history,
        "total_messages": len(visible_history)
    }


async def extract_facts_background(user_id: str, history: list):
    """Background task to extract and save facts."""
    try:
        new_facts, new_event = await ai_service.extract_facts(history)
        if new_facts or new_event:
            await memory_service.save_facts(user_id, new_facts, new_event)
    except Exception as e:
        print(f"Fact extraction error: {e}")

