"""
Scenes Routes
Handles scene availability and information.
"""
from fastapi import APIRouter, Depends

from api.config import TIER_CONFIG
from api.models.schemas import ScenesResponse, SceneInfo
from api.services.memory import memory_service
from api.routes.deps import get_current_user

router = APIRouter(prefix="/scenes", tags=["Scenes"])

# Scene definitions
SCENE_DEFINITIONS = {
    "Lounge": {
        "tier_required": 0,
        "description": "Casual chat. Comfortable, no specific setting."
    },
    "Body Double": {
        "tier_required": 0,
        "description": "Work together in companionable silence. Productivity mode."
    },
    "Cafe": {
        "tier_required": 1,
        "description": "Face-to-face at a cozy coffee shop. Intimate conversation."
    },
    "Evening Walk": {
        "tier_required": 1,
        "description": "Side-by-side stroll through quiet streets at dusk."
    },
    "Firework": {
        "tier_required": 2,
        "description": "Special celebration scene for milestone moments."
    }
}


@router.get("", response_model=ScenesResponse)
async def get_scenes(user: dict = Depends(get_current_user)):
    """
    Get all scenes with availability based on user's tier.
    """
    user_id = user["id"]
    memory = await memory_service.load_memory(user_id)
    
    tier = memory.get('tier', 0)
    tier_config = TIER_CONFIG.get(tier, TIER_CONFIG[0])
    available_scenes = tier_config.get('scenes', ["Lounge", "Body Double"])
    
    scenes = []
    for name, info in SCENE_DEFINITIONS.items():
        scenes.append(SceneInfo(
            name=name,
            available=name in available_scenes,
            tier_required=info["tier_required"],
            description=info["description"]
        ))
    
    return ScenesResponse(
        scenes=scenes,
        current_tier=tier
    )


@router.get("/{scene_name}")
async def get_scene_info(
    scene_name: str,
    user: dict = Depends(get_current_user)
):
    """
    Get detailed info about a specific scene.
    """
    if scene_name not in SCENE_DEFINITIONS:
        return {"error": "Scene not found", "available_scenes": list(SCENE_DEFINITIONS.keys())}
    
    user_id = user["id"]
    memory = await memory_service.load_memory(user_id)
    
    tier = memory.get('tier', 0)
    tier_config = TIER_CONFIG.get(tier, TIER_CONFIG[0])
    available_scenes = tier_config.get('scenes', ["Lounge", "Body Double"])
    
    scene_info = SCENE_DEFINITIONS[scene_name]
    
    return {
        "name": scene_name,
        "available": scene_name in available_scenes,
        "tier_required": scene_info["tier_required"],
        "description": scene_info["description"],
        "current_tier": tier,
        "unlock_message": None if scene_name in available_scenes else f"Upgrade to Tier {scene_info['tier_required']} to unlock this scene."
    }

