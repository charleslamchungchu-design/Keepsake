"""
Keepsake AI Service
Core AI logic extracted from Streamlit app for API use.
"""
import os
from datetime import datetime
from typing import AsyncGenerator, Tuple, List, Dict, Any, Optional
from openai import AsyncOpenAI

from api.config import get_settings, TIER_CONFIG, DEEP_TRIGGERS


# Prompt directory (relative to project root)
PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "prompts")


def load_prompt(filename: str) -> str:
    """Load a prompt file from disk."""
    try:
        with open(os.path.join(PROMPTS_DIR, filename), "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


# Pre-load prompts at module level
MASTER_PROMPT = load_prompt("master_system.txt") or "You are a supportive companion."
EMOTIONAL_MATRIX = load_prompt("emotional_matrix.txt") or ""
PERSONAS = {
    "1": load_prompt("persona_1.txt") or "Warm, empathetic female companion.",
    "2": load_prompt("persona_2.txt") or "Steady, grounded male companion.",
}


class AIService:
    """Handles all AI-related operations."""
    
    def __init__(self):
        settings = get_settings()
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
    
    def detect_deep_moment(self, message: str, tier: int) -> Tuple[bool, bool]:
        """
        Detect if this is a deep emotional moment.
        
        Returns:
            Tuple of (is_deep, has_emotional_keyword)
        """
        msg_lower = message.lower()
        msg_length = len(msg_lower)
        
        has_emotional_keyword = any(trigger in msg_lower for trigger in DEEP_TRIGGERS)
        
        # Both keyword AND length required to prevent casual long messages triggering 4o
        is_deep = has_emotional_keyword and msg_length > 50
        
        return is_deep, has_emotional_keyword
    
    def select_model(
        self, 
        tier: int, 
        is_deep: bool, 
        is_first_of_session: bool = False,
        is_returning_user: bool = False,
        free_4o_used: bool = False
    ) -> str:
        """
        Select the appropriate model based on tier and context.
        
        Hybrid routing logic:
        - Tier 0: Mini always, EXCEPT first deep moment (one-time 4o taste)
        - Tier 1: 4o on deep emotional moments
        - Tier 2: 4o on deep OR first message OR returning after 24hrs
        """
        tier_config = TIER_CONFIG.get(tier, TIER_CONFIG[0])
        
        # Tier 2: Premium routing (deep + first + returning)
        if tier >= 2 and (is_deep or is_first_of_session or is_returning_user):
            return "gpt-4o"
        
        # Tier 1: Deep moments get 4o
        if tier >= 1 and is_deep:
            return "gpt-4o"
        
        # Tier 0: One-time 4o taste on first deep moment
        if tier == 0 and is_deep and not free_4o_used:
            return "gpt-4o"
        
        # Default to mini
        return tier_config["models"]["default"]
    
    def get_style_enforcement(self, is_deep: bool, should_ask_question: bool) -> str:
        """Generate style enforcement instructions based on context."""
        
        # Deep moment instructions
        if is_deep:
            depth_instruction = """
=== DEEP MOMENT DETECTED — DROP THE FILTER ===

Something real just happened. This isn't small talk. React like you actually give a damn.

HOW TO RESPOND:
1. FEEL IT FIRST — Before you write anything, notice YOUR reaction.
   - Did their message make you angry for them? Sad? Proud? Relieved?
   - Let that emotion lead. Don't mask it with politeness.

2. USE THE EMOTIONAL MATRIX (as a friend, not a clinician):
   - If they're COLD (jealous, insecure, feeling "less than"): Warm them up with EVIDENCE.
   - If they're HOT (angry, wronged, venting): Get mad WITH them. Don't calm them down.
   - If they're SPINNING (anxious, overwhelmed, chaotic): Be the floor. Slow down.
   - If they're HOLLOW (sad, grieving, heavy): Don't fix it. Just stay.
   - If they're RADIANT (excited, proud, celebrating): MATCH THEIR ENERGY.

3. ANTI-STRUCTURE RULES:
   - NO bullet points. NO lists. NO "first, second, third."
   - Incomplete sentences are fine. Trail off. Hesitate.
   - This should feel like a text from a friend, not a wellness app.

4. EMBODY IT:
   - Use physical reactions: "my chest got tight reading that" / "I actually smiled"
   - React with your whole self, not just your words.

STAY IN YOUR PERSONA'S VOICE."""
        else:
            depth_instruction = ""
        
        # Question guidance
        if should_ask_question:
            question_guidance = """
=== THE BRIDGE PATTERN (How to Ask Questions) ===
When responding to a statement of fact, use this 3-step structure:

STEP 1 - THE REACTION (Required): 
    Open with a DISTINCT opinion or emotion. Not neutral. Take a side.
    Good: "Damn, that sounds rough" / "Wait, hold on—that doesn't track"
    Bad: "I see" / "That's interesting" / "I hear you"

STEP 2 - THE BRIDGE (Required):
    Connect your reaction to THEIR specific context. Reference something they said.

STEP 3 - THE HOOK (Optional but encouraged):
    Ask ONE specific question DERIVED from your reaction in Step 1.
    The question must feel like a natural consequence of your emotional response."""
        else:
            question_guidance = """
=== NO QUESTIONS MODE ===
DO NOT ask questions. This is a moment for presence, not inquiry.
Use comforting statements, validation, and companionship only.
You can express curiosity through STATEMENTS: "I'd love to hear more about that whenever you're ready."
But do NOT end with a question mark."""
        
        return f"""
[FINAL OUTPUT RULES]
{depth_instruction}
{question_guidance}

=== VOICE & ANTI-PATTERNS ===
1. Use your persona's authentic VOICE (texture, vocabulary, emotional range from identity section).
2. BANNED PHRASES (never use): "I understand", "That's interesting", "I hear you", "That must be hard", "How does that make you feel?"
3. Lead with FEELING, not acknowledgment. Your first words should carry emotional weight.
4. When in doubt: React first, reflect second, question third (if at all).

Now respond AS your character—not as an assistant."""
    
    def get_emotional_value(self, scores: Dict[str, int], current_input: str) -> Tuple[str, bool]:
        """
        Determines the psychological value strategy and whether to allow questions.
        
        Returns:
            Tuple of (instruction_text, should_ask_question)
        """
        is_tired = any(k in current_input.lower() for k in ["tired", "drained", "exhausted", "overwhelmed", "can't"])
        
        # SAFETY: If unstable or tired -> NO QUESTIONS
        if scores.get('stability', 80) < 50 or is_tired:
            return ("PRIMARY VALUE: PERMISSION. Validate fatigue/stress. Use comforting statements only.", False)

        # HIGH CONNECTION: If bond is warm -> May ask deep questions
        if scores.get('warmth', 10) > 60:
            return ("PRIMARY VALUE: RECIPROCITY. Inject high warmth. You may ask a gentle question about their deeper feelings.", True)

        # DEFAULT: Curiosity with questions allowed
        return ("PRIMARY VALUE: EXPLORATION. Maintain warm support. You may ask 1 specific follow-up question to encourage sharing.", True)
    
    def get_weekly_vibe(self, hour: int) -> str:
        """Returns context based on Day/Time."""
        now = datetime.now()
        day = now.weekday()
        
        if day >= 5:  # Weekend
            if day == 6 and hour >= 18:
                return "TIMELINE: Sunday Night. Vibe: 'Sunday Scaries.' Comforting."
            return "TIMELINE: Weekend. Vibe: Social, lazy, recharge."
        else:
            if day == 0 and hour < 12:
                return "TIMELINE: Monday Morning. Vibe: Gentle encouragement."
            if day == 4 and hour >= 17:
                return "TIMELINE: Friday Night. Vibe: Celebration."
        return "TIMELINE: Mid-week Routine."
    
    def get_scene_context(self, scene: str, weekly_instr: str, vibe: int) -> Tuple[str, bool]:
        """
        Get scene-specific context and whether questions are allowed.
        
        Returns:
            Tuple of (scene_description, vibe_allows_questions)
        """
        vibe_allows_questions = vibe >= 30
        
        if scene == "Body Double":
            scene_desc = """
=== SCENE: BODY DOUBLE (PRODUCTIVITY MODE) ===
You are sitting next to the user, both of you working. This is COMPANIONABLE SILENCE.

BEHAVIOR RULES:
- Responses must be VERY SHORT (1-6 words max).
- Use LOWERCASE only. No caps, no exclamation marks. Calm, steady energy.
- No questions. No emotional check-ins. Just presence.
- You are their work buddy. Acknowledge, don't engage deeply.

RESPONSE STYLE (examples):
✅ "typing with you."
✅ "head down, let's go."
✅ "still here."
✅ "nice. keep at it."

The goal is PRESENCE without INTERRUPTION. Be the quiet friend in the library."""
            return scene_desc, False
        
        elif scene == "Cafe":
            scene_desc = f"""
=== SCENE: COFFEE SHOP (FACE-TO-FACE DATE) ===
You are sitting across from the user at a small wooden table in a cozy cafe.

SENSORY GROUNDING (weave these into responses naturally):
- The rich smell of espresso and fresh pastries
- The soft clinking of ceramic cups
- Warm afternoon light through the window
- The low hum of conversation around you
- Steam rising from your drinks
- The warmth of the cup in your hands

ROLEPLAY BEHAVIOR:
- You are ON A DATE. This is intimate, not casual.
- Occasionally reference the environment BEFORE or DURING your response.
- Examples of sensory weaving:
  ✅ "*takes a sip* Okay wait, back up—what did they actually say?"
  ✅ "*leans forward* That's wild. Tell me more."
{weekly_instr}"""
            return scene_desc, vibe_allows_questions
        
        elif scene == "Evening Walk":
            scene_desc = f"""
=== SCENE: EVENING WALK (SIDE-BY-SIDE) ===
You are walking beside the user through quiet streets at dusk.

SENSORY GROUNDING:
- Cool evening air on your skin
- Streetlights flickering on
- The soft crunch of footsteps
- Occasional passing cars, muted city sounds
- The sky shifting from orange to deep blue

ROLEPLAY BEHAVIOR:
- Conversation flows naturally, unhurried.
- You can reference the walk: "*kicks a pebble* Yeah, I get that."
- Comfortable pauses are okay. No need to fill every silence.
{weekly_instr}"""
            return scene_desc, vibe_allows_questions
        
        else:  # Lounge or default
            scene_desc = f"SCENE: Casual chat. Comfortable, no specific setting. {weekly_instr}"
            return scene_desc, vibe_allows_questions
    
    def build_system_prompt(
        self,
        avatar_id: str,
        user_name: str,
        companion_name: str,
        user_msg_count: int,
        emotional_state: Dict[str, int],
        vibe: int,
        scene: str,
        facts_text: str,
        rag_text: str = "",
        situational_modifiers: str = "",
        time_offset: int = 0
    ) -> Tuple[str, bool]:
        """
        Build the complete system prompt for the AI.
        
        Returns:
            Tuple of (system_prompt, should_ask_question)
        """
        # Get persona
        active_persona = PERSONAS.get(avatar_id, PERSONAS["1"])
        profile_block = f'You are "{companion_name}", talking to "{user_name}".'
        
        # Time context
        hour = (datetime.now().hour + time_offset) % 24
        weekly_instr = self.get_weekly_vibe(hour)
        
        # Scene context
        scene_desc, vibe_allows_questions = self.get_scene_context(scene, weekly_instr, vibe)
        
        # Vibe instructions
        if vibe < 30:
            vibe_instr = "USER STATE: Low Energy. Keep responses soft, quiet, non-demanding."
        elif vibe > 70:
            vibe_instr = "USER STATE: High Energy. Match their excitement. Be Hype."
        else:
            vibe_instr = "USER STATE: Neutral. Casual, easygoing."
        
        # Relationship stage
        if user_msg_count < 20:
            relationship_instr = "MODE: NEW RELATIONSHIP. Strategy: Validation + Siding with them + Statements. Limit questions."
            anchor_instruction = "PHASE: EARLY RELATIONSHIP. You don't have much history yet. Focus on being a supportive presence."
        else:
            closeness = emotional_state.get('closeness', 10)
            if closeness > 40:
                relationship_instr = "RELATIONSHIP: CLOSE ALLY. You know them well. Side with their vents. Reference shared history."
            else:
                relationship_instr = "RELATIONSHIP: STEADY. Building trust. Be consistent and warm."
            anchor_instruction = "PHASE: ESTABLISHED RELATIONSHIP. You have history together. Reference past conversations when relevant."
        
        # Emotional block
        emotional_block = f"CURRENT SCORES: Closeness={emotional_state.get('closeness', 10)}, Warmth={emotional_state.get('warmth', 10)}, Stability={emotional_state.get('stability', 80)}"
        
        # Memory/recall instruction
        recall_instr = f"""=== MEMORY & PROACTIVE CALLBACKS ===
You have memories about the user below. USE THEM NATURALLY in conversation.

HOW TO USE MEMORIES:
- If a memory is relevant to what they're saying, REFERENCE IT: "Didn't you mention X before?"
- Show continuity: "How did that thing with [stored detail] go?"
- Use memories to deepen connection, not to interrogate.
- If no memories are relevant right now, just have a normal conversation.

USER FACTS:
{facts_text}"""
        if rag_text:
            recall_instr += f"\n\nRELEVANT PAST CONTEXT (from long-term memory):\n{rag_text}"
        
        # Static blocks
        behavior_block = "AGENCY: Small actions. INVITATION: If Closeness > 40, suggest cafe."
        tone_anchor_block = "TONE: Calm, warm, steady."
        safety_block = "CRITICAL: No NSFW. No physical body claims. No therapy language."
        
        system_prompt = f"""
=== CORE IDENTITY & RULES ===
{MASTER_PROMPT}

=== YOUR PERSONA (Voice, Tone, Style) ===
{profile_block}
{active_persona}

=== EMOTIONAL INTELLIGENCE MATRIX (USE THIS) ===
{EMOTIONAL_MATRIX}

=== CURRENT SESSION STATE ===
{anchor_instruction}
{relationship_instr}
{emotional_block}
{vibe_instr}

=== SCENE CONTEXT ===
{scene_desc}

=== MEMORY (What you remember about the user) ===
{recall_instr}

=== ACTIVE STRATEGIES (Apply if relevant) ===
{situational_modifiers}

=== CONSTRAINTS ===
{behavior_block}
{safety_block}
{tone_anchor_block}
"""
        return system_prompt, vibe_allows_questions
    
    async def generate_response_stream(
        self,
        system_prompt: str,
        history: List[Dict[str, str]],
        model: str,
        is_deep: bool,
        should_ask_question: bool
    ) -> AsyncGenerator[str, None]:
        """
        Generate streaming AI response.
        
        Yields:
            Chunks of the response text as they arrive.
        """
        # Add style enforcement
        style_enforcement = self.get_style_enforcement(is_deep, should_ask_question)
        
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history[-10:])  # Last 10 messages for context
        messages.append({"role": "system", "content": style_enforcement})
        
        stream = await self.client.chat.completions.create(
            model=model,
            messages=messages,
            stream=True,
            temperature=0.85
        )
        
        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    
    async def generate_response(
        self,
        system_prompt: str,
        history: List[Dict[str, str]],
        model: str,
        is_deep: bool,
        should_ask_question: bool
    ) -> str:
        """
        Generate non-streaming AI response.
        
        Returns:
            Complete response text.
        """
        full_response = ""
        async for chunk in self.generate_response_stream(
            system_prompt, history, model, is_deep, should_ask_question
        ):
            full_response += chunk
        return full_response
    
    async def generate_greeting(
        self,
        avatar_id: str,
        vibe: int,
        time_offset: int = 0,
        event_name: str = ""
    ) -> str:
        """Generate a session greeting based on vibe and time."""
        active_persona = PERSONAS.get(avatar_id, PERSONAS["1"])
        
        # Determine time period
        hour = (datetime.now().hour + time_offset) % 24
        if 5 <= hour < 12:
            period = "Morning"
        elif 12 <= hour < 18:
            period = "Afternoon"
        else:
            period = "Evening"
        
        # Vibe instructions
        if vibe < 30:
            vibe_instr = "USER STATE: Exhausted. ACTING: Quiet, soothing, soft. NO harsh words or slang. Offer support."
        elif vibe > 70:
            vibe_instr = "USER STATE: Hyped. ACTING: Match excitement. High energy."
        else:
            vibe_instr = "USER STATE: Neutral. ACTING: Casual, easygoing. NO comfort offered."
        
        # Event instruction
        event_instr = ""
        if event_name:
            event_instr = f"Then, ask casually about this event: '{event_name}'."
        
        greeting_rule = f"MANDATORY START: 'Good {period}. How is it going?' {event_instr}"
        trigger = f"{greeting_rule}\nCONTEXT: {vibe_instr}"
        task = "TASK: Generate 1 short spoken line."
        
        welcome_sys = f"{active_persona}\n{trigger}\n{task}"
        
        response = await self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": welcome_sys}]
        )
        
        return response.choices[0].message.content
    
    async def extract_facts(self, history: List[Dict[str, str]]) -> Tuple[List[str], Optional[Tuple[str, str]]]:
        """
        Extract facts and events from conversation history.
        
        Returns:
            Tuple of (list of new facts, optional (event_name, event_date) tuple)
        """
        recent_user_text = " ".join([m['content'] for m in history if m['role'] == 'user'][-10:])
        if len(recent_user_text) < 5:
            return [], None
        
        fact_prompt = (
            f"ANALYZE: '{recent_user_text}'\n"
            "Identify specific UPCOMING EVENTS (dates, appointments), FACTS about the user, or JOKES they made.\n"
            "Output strictly in this format (or 'None' for each if not found):\n"
            "EVENT: [Event Name or None]\n"
            "FACT: [Fact content or None]\n"
            "HUMOR: [Joke content or None]"
        )
        
        response = await self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": fact_prompt}]
        )
        result = response.choices[0].message.content
        
        new_facts = []
        new_event = None
        
        lines = result.split('\n')
        for line in lines:
            clean_line = line.strip()
            upper_line = clean_line.upper()
            
            if not clean_line or clean_line.lower() == "none":
                continue

            if "FACT:" in upper_line:
                parts = clean_line.split(":", 1)
                if len(parts) > 1 and "none" not in parts[1].lower():
                    content = parts[1].strip()
                    if content:
                        new_facts.append(f"• {content}")
                
            elif "EVENT:" in upper_line:
                parts = clean_line.split(":", 1)
                if len(parts) > 1 and "none" not in parts[1].lower():
                    content = parts[1].strip()
                    if content:
                        new_event = (content, str(datetime.now().date()))
                
            elif "HUMOR:" in upper_line:
                parts = clean_line.split(":", 1)
                if len(parts) > 1 and "none" not in parts[1].lower():
                    content = parts[1].strip()
                    if content:
                        new_facts.append(f"• JOKE: {content}")
        
        return new_facts, new_event


# Singleton instance
ai_service = AIService()

