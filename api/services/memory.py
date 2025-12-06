"""
Keepsake Memory Service
Handles all Supabase memory operations.
"""
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from supabase import create_client, Client

from api.config import get_settings, TIER_CONFIG
from api.models.schemas import UserMemory, UserFact, EmotionalState, UserProfile, ActiveContext


class MemoryService:
    """Handles all memory-related operations with Supabase."""
    
    def __init__(self):
        settings = get_settings()
        self.client: Client = create_client(settings.supabase_url, settings.supabase_key)
    
    def get_default_memory(self) -> Dict[str, Any]:
        """Returns default memory structure for new users."""
        return {
            "history": [],
            "emotional_state": {
                "closeness": 10, "warmth": 10, "pace": 10, 
                "stability": 80, "scene_score": 0, "agency": 10
            },
            "user_profile": {
                "name": "", "age": "", "gender": "", "companion_name": "Keepsake"
            },
            "active_context": {"last_topic": "", "significant_event": "", "event_date": "", "last_recalled_date": ""},
            "user_facts": [],
            "balance": 100,
            "inventory": ["default"],
            "current_outfit": "default",
            "tier": 0,
            "avatar_id": "1",
            "has_chosen_avatar": False,
            "time_offset": 0,
            "last_active_timestamp": datetime.now().isoformat()
        }
    
    async def load_memory(self, user_id: str) -> Dict[str, Any]:
        """
        Load user memory from Supabase.
        Returns default memory if not found.
        """
        try:
            response = self.client.table("memories").select("data").eq("id", user_id).execute()
            
            if response.data and len(response.data) > 0:
                loaded_data = response.data[0]['data']
                
                # Migration: Add missing keys from default
                default = self.get_default_memory()
                for key, value in default.items():
                    if key not in loaded_data:
                        loaded_data[key] = value
                
                return loaded_data
        except Exception as e:
            print(f"Error loading memory: {e}")
        
        return self.get_default_memory()
    
    async def save_memory(self, user_id: str, memory_data: Dict[str, Any]) -> bool:
        """
        Save memory to Supabase.
        Automatically truncates history to prevent payload bloat.
        """
        try:
            # Truncate history before saving
            if 'history' in memory_data and len(memory_data['history']) > 50:
                memory_data['history'] = memory_data['history'][-50:]
            
            self.client.table("memories").upsert({
                "id": user_id,
                "data": memory_data
            }).execute()
            return True
        except Exception as e:
            print(f"Error saving memory: {e}")
            return False
    
    async def create_user_memory(self, user_id: str, profile: Dict[str, Any]) -> Dict[str, Any]:
        """Create initial memory for a new user."""
        memory = self.get_default_memory()
        memory['user_profile'] = profile
        memory['has_chosen_avatar'] = True
        
        await self.save_memory(user_id, memory)
        return memory
    
    def migrate_legacy_facts(self, facts_list: List[Any]) -> List[Dict[str, str]]:
        """
        Migrate old string-format facts to timestamped format.
        Old: ["• User likes coffee"]
        New: [{"content": "• User likes coffee", "created_at": "2024-01-15T10:30:00"}]
        """
        migrated = []
        for fact in facts_list:
            if isinstance(fact, str):
                migrated.append({
                    "content": fact,
                    "created_at": datetime.now().isoformat()
                })
            elif isinstance(fact, dict) and "content" in fact:
                migrated.append(fact)
        return migrated
    
    def get_valid_facts_with_expiry(
        self, 
        facts_list: List[Any], 
        tier: int
    ) -> Tuple[List[str], int]:
        """
        Get facts valid for user's tier and count expired facts.
        
        Tier 0: Only facts from last 48 hours
        Tier 1+: All facts (permanent)
        
        Returns:
            Tuple of (list of valid fact strings, count of expired facts)
        """
        if not facts_list:
            return [], 0
        
        facts_list = self.migrate_legacy_facts(facts_list)
        
        # Tier 1+ gets all facts
        if tier >= 1:
            return [f["content"] for f in facts_list if isinstance(f, dict) and "content" in f], 0
        
        # Tier 0: Filter to last 48 hours
        tier_config = TIER_CONFIG.get(tier, TIER_CONFIG[0])
        cutoff_hours = tier_config.get("memory_hours", 48)
        cutoff = datetime.now() - timedelta(hours=cutoff_hours)
        
        valid_facts = []
        expired_count = 0
        
        for fact in facts_list:
            if not isinstance(fact, dict) or "content" not in fact:
                continue
            
            created_str = fact.get("created_at", "")
            if created_str:
                try:
                    created = datetime.fromisoformat(created_str)
                    if created >= cutoff:
                        valid_facts.append(fact["content"])
                    else:
                        expired_count += 1
                except (ValueError, TypeError):
                    valid_facts.append(fact["content"])
            else:
                valid_facts.append(fact["content"])
        
        return valid_facts, expired_count
    
    async def save_facts(
        self, 
        user_id: str, 
        new_facts: List[str], 
        new_event: Optional[Tuple[str, str]] = None
    ) -> bool:
        """
        Save new facts to user memory.
        Thread-safe: Loads fresh DB state, merges, saves.
        """
        if not new_facts and not new_event:
            return True
        
        try:
            # Load fresh state
            response = self.client.table("memories").select("data").eq("id", user_id).execute()
            
            if not response.data or len(response.data) == 0:
                return False
            
            current_data = response.data[0]['data']
            
            # Migrate and merge facts
            existing_facts = self.migrate_legacy_facts(current_data.get('user_facts', []))
            existing_contents = [f.get("content", "") for f in existing_facts if isinstance(f, dict)]
            
            # Add new timestamped facts
            for fact_content in new_facts:
                if fact_content not in existing_contents:
                    existing_facts.append({
                        "content": fact_content,
                        "created_at": datetime.now().isoformat()
                    })
            
            # Keep last 20 facts
            current_data['user_facts'] = existing_facts[-20:]
            
            # Update event if provided
            if new_event:
                event_name, event_date = new_event
                current_data['active_context']['significant_event'] = event_name
                current_data['active_context']['event_date'] = event_date
            
            # Save
            self.client.table("memories").upsert({
                "id": user_id,
                "data": current_data
            }).execute()
            
            return True
        except Exception as e:
            print(f"Error saving facts: {e}")
            return False
    
    def update_emotional_state(
        self, 
        user_text: str, 
        current_scores: Dict[str, int]
    ) -> Dict[str, int]:
        """Update emotional scores based on user message content."""
        text = user_text.lower()
        
        if any(w in text for w in ["thanks", "better", "lighter", "helped"]):
            current_scores['stability'] = min(100, current_scores['stability'] + 15)
            current_scores['warmth'] = min(100, current_scores['warmth'] + 5)
        elif any(w in text for w in ["sad", "tired", "mad"]):
            current_scores['stability'] = max(0, current_scores['stability'] - 5)
        
        if len(text) > 60:
            current_scores['closeness'] = min(100, current_scores['closeness'] + 2)
        
        if current_scores['closeness'] > 30:
            current_scores['agency'] = min(100, current_scores['agency'] + 1)
        
        return current_scores
    
    async def get_embedding(self, text: str) -> List[float]:
        """Create embedding for text using OpenAI."""
        from openai import AsyncOpenAI
        settings = get_settings()
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        
        response = await client.embeddings.create(
            input=text,
            model="text-embedding-3-small"
        )
        return response.data[0].embedding
    
    async def save_vector_memory(self, user_id: str, text: str) -> bool:
        """Save text with embedding to vector store for RAG."""
        try:
            embedding = await self.get_embedding(text)
            
            self.client.table("recall_vectors").insert({
                "user_id": user_id,
                "content": text,
                "embedding": embedding
            }).execute()
            return True
        except Exception as e:
            print(f"Error saving vector: {e}")
            return False
    
    async def retrieve_context(self, user_id: str, query: str, threshold: float = 0.5, count: int = 3) -> str:
        """
        RAG: Retrieve relevant past memories based on query.
        Returns formatted context string.
        """
        try:
            embedding = await self.get_embedding(query)
            
            response = self.client.rpc("match_vectors", {
                "query_embedding": embedding,
                "match_threshold": threshold,
                "match_count": count,
                "filter_user": user_id
            }).execute()
            
            if response.data:
                return "\n".join([f"- {item['content']}" for item in response.data])
            return ""
        except Exception as e:
            print(f"RAG retrieval error: {e}")
            return ""


# Singleton instance
memory_service = MemoryService()

