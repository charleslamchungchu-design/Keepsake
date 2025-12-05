import streamlit as st
import datetime
import json
import os
import time
import random
import threading  # For background tasks (latency fix)
from datetime import datetime, timedelta
from openai import OpenAI
from supabase import create_client, Client

# --- 1. SETUP & PATHS ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROMPTS_DIR = os.path.join(BASE_DIR, "prompts")

def get_asset_path(filename):
    return os.path.join(BASE_DIR, "assets", filename)

def load_prompt(filename):
    try:
        with open(os.path.join(PROMPTS_DIR, filename), "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        st.error(f"Error: Could not find prompt file: {filename}")
        return ""

def load_json(filename):
    try:
        with open(os.path.join(PROMPTS_DIR, filename), "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

# --- 2. CONFIGURATION (OpenAI & Supabase) ---
try:
    OPENAI_KEY = st.secrets.get("OPENAI_API_KEY")
except:
    OPENAI_KEY = "LOCAL-DEV-KEY"

# Supabase Connection Setup
# Using a flag to track if Supabase is available (prevents crashes if not configured)
SUPABASE_AVAILABLE = False
supabase = None
try:
    SUPABASE_URL = st.secrets["supabase"]["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["supabase"]["SUPABASE_KEY"]
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    SUPABASE_AVAILABLE = True
except Exception as e:
    print(f"Supabase Connection Error (non-fatal): {e}")

client = OpenAI(api_key=OPENAI_KEY)

# NOTE: Anthropic client removed - not currently used in this codebase
# If you plan to use Claude, uncomment and configure:
# from anthropic import Anthropic
# anthropic_client = Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])

# We use a fixed ID for now to simulate the single local file experience
USER_ID = "user_1" 

AVATAR_MAP = {
    "Female - Friend": "1",
    "Male - Friend": "2"
}

# --- 3. MEMORY MANAGEMENT (Cloud Version) ---
def load_memory():
    """
    Loads user memory from Supabase, with safe fallback to defaults.
    Always returns a valid memory dict, even if DB is unavailable.
    """
    default_memory = {
        "history": [],
        "emotional_state": {
            "closeness": 10, "warmth": 10, "pace": 10, "stability": 80, "scene_score": 0, "agency": 10
        },
        "user_profile": {
            "name": "", "age": "", "gender": "", "companion_name": ""
        },
        "active_context": {"last_topic": "", "significant_event": "", "event_date": ""},
        "user_facts": [],
        "balance": 100,
        "inventory": ["default"],
        "current_outfit": "default",
        "tier": 0, 
        "avatar_id": "1", 
        "has_chosen_avatar": False,
        "is_guest": True, 
        "time_offset": 0,
        "last_active_timestamp": str(datetime.now())
    }

    if not SUPABASE_AVAILABLE:
        return default_memory

    try:
        response = supabase.table("memories").select("data").eq("id", USER_ID).execute()
        
        if response.data and len(response.data) > 0:
            loaded_data = response.data[0]['data']
            
            # Migration Fix: Add missing keys from default (for schema updates)
            for key, value in default_memory.items():
                if key not in loaded_data:
                    loaded_data[key] = value
            return loaded_data
            
    except Exception as e:
        print(f"Error loading memory (using defaults): {e}")
        
    return default_memory

def save_memory(memory_data):
    """
    Saves memory to Supabase with automatic truncation.
    Fails silently to prevent app crashes.
    """
    if not SUPABASE_AVAILABLE:
        return
        
    try:
        # Truncate history before saving to prevent payload bloat
        if 'history' in memory_data and len(memory_data['history']) > 50:
            memory_data['history'] = memory_data['history'][-50:]
        
        supabase.table("memories").upsert({
            "id": USER_ID, 
            "data": memory_data
        }).execute()
    except Exception as e:
        print(f"Supabase save error (non-fatal): {e}")

memory = load_memory()
memory['tier'] = 2  # TEMP: Force Tier 2 for testing

if "app_mode" not in st.session_state: st.session_state.app_mode = "Lobby"
if "current_vibe" not in st.session_state: st.session_state.current_vibe = 50
if "turbo_teaser_shown" not in st.session_state: st.session_state.turbo_teaser_shown = False
if "future_teaser_shown" not in st.session_state: st.session_state.future_teaser_shown = False

# --- 4. LOGIC FUNCTIONS ---

def save_vector_memory(text):
    """Embeds and saves user text to Supabase for long-term recall (RAG)."""
    if not SUPABASE_AVAILABLE:
        return
        
    try:
        emb = client.embeddings.create(input=text, model="text-embedding-3-small").data[0].embedding
        supabase.table("recall_vectors").insert({
            "user_id": USER_ID, 
            "content": text, 
            "embedding": emb
        }).execute()
    except Exception as e:
        print(f"Vector save error (non-fatal): {e}")

def retrieve_context(query):
    """RAG: Finds relevant past memories based on the current conversation."""
    if not SUPABASE_AVAILABLE:
        return ""
        
    try:
        emb = client.embeddings.create(input=query, model="text-embedding-3-small").data[0].embedding
        res = supabase.rpc("match_vectors", {
            "query_embedding": emb, 
            "match_threshold": 0.5, 
            "match_count": 3, 
            "filter_user": USER_ID
        }).execute()
        
        if res.data:
            return "\n".join([f"- {item['content']}" for item in res.data])
        return ""
    except Exception as e:
        print(f"RAG retrieval error (non-fatal): {e}")
        return ""

def generate_smart_response(system_prompt, history, tier, should_ask_question=True):
    """
    REROUTING LOGIC: Returns a stream. Does NOT write to UI.
    
    Args:
        system_prompt: The full system context
        history: Recent conversation history
        tier: User's subscription tier (affects model selection)
        should_ask_question: Whether the style enforcement should encourage questions
    """
    # 1. ANALYZE CONTEXT FOR MODEL ROUTING
    last_msg = history[-1]['content'].lower() if history else ""
    deep_triggers = ["sad", "upset", "anxious", "lonely", "fail", "broken", "worry", "hurt", 
                     "grief", "depressed", "tired", "exhausted", "scared", "angry", "frustrated",
                     "hopeless", "overwhelmed", "stressed", "crying", "panic"]
    is_deep = (any(t in last_msg for t in deep_triggers) or len(last_msg) > 80)
    
    # 2. SELECT MODEL (GPT-4o for deep emotional content at Tier 2+)
    if tier >= 2 and is_deep:
        active_model = "gpt-4o" 
    else:
        active_model = "gpt-4o-mini" 

    # 3. STYLE ENFORCEMENT (Contextual - respects question permissions)
    # FIX: This now respects the should_ask_question flag instead of always asking
    if should_ask_question:
        question_guidance = "If the conversation has momentum, you may ask ONE specific follow-up question about their feelings (not logistics)."
    else:
        question_guidance = "DO NOT ask questions. Use comforting statements and validation only."
    
    style_enforcement = f"""
[FINAL CHECK BEFORE RESPONDING]
1. Match the user's EMOTIONAL STATE using the Emotional Matrix above.
2. Follow the 3:1 rule: 3 statements for every 1 question.
3. Use your persona's VOICE (check tone, texture, vocabulary from your identity section).
4. Avoid banned phrases: "I understand", "That's interesting", therapy-speak.
5. {question_guidance}

Now respond naturally as your character would.
"""
    
    msgs = [{"role": "system", "content": system_prompt}] + history
    msgs.append({"role": "system", "content": style_enforcement})
    
    return client.chat.completions.create(
        model=active_model, 
        messages=msgs, 
        stream=True,
        temperature=0.85
    )

def get_emotional_value(scores, current_input):
    """
    Determines the psychological value strategy and Ending Protocol.
    Returns tuple: (instruction_text, should_ask_question)
    """
    is_tired = any(k in current_input.lower() for k in ["tired", "drained", "exhausted", "overwhelmed", "can't"])
    
    # SAFETY: If unstable or tired -> NO QUESTIONS
    if scores['stability'] < 50 or is_tired:
        return ("PRIMARY VALUE: PERMISSION. Validate fatigue/stress. Use comforting statements only.", False)

    # HIGH CONNECTION: If bond is warm -> May ask deep questions
    if scores['warmth'] > 60:
        return ("PRIMARY VALUE: RECIPROCITY. Inject high warmth. You may ask a gentle question about their deeper feelings.", True)

    # DEFAULT: Curiosity with questions allowed
    return ("PRIMARY VALUE: EXPLORATION. Maintain warm support. You may ask 1 specific follow-up question to encourage sharing.", True)

def get_weekly_vibe():
    """Returns context based on Day/Time."""
    now = datetime.now()
    day = now.weekday()
    hour = now.hour
    if day >= 5: 
        if day == 6 and hour >= 18: return "TIMELINE: Sunday Night. Vibe: 'Sunday Scaries.' Comforting."
        return "TIMELINE: Weekend. Vibe: Social, lazy, recharge."
    else:
        if day == 0 and hour < 12: return "TIMELINE: Monday Morning. Vibe: Gentle encouragement."
        if day == 4 and hour >= 17: return "TIMELINE: Friday Night. Vibe: Celebration."
    return "TIMELINE: Mid-week Routine."

def update_emotional_state(user_text, current_scores):
    """Updates emotional scores based on user message content."""
    text = user_text.lower()
    if any(w in text for w in ["thanks", "better", "lighter", "helped"]):
        current_scores['stability'] = min(100, current_scores['stability'] + 15)
        current_scores['warmth'] += 5
    elif any(w in text for w in ["sad", "tired", "mad"]): 
        current_scores['stability'] -= 5
    if len(text) > 60: current_scores['closeness'] += 2
    if current_scores['closeness'] > 30: current_scores['agency'] += 1
    for k in current_scores: current_scores[k] = max(0, min(100, current_scores[k]))
    return current_scores

def save_facts_only(new_facts, new_event=None):
    """
    Thread-safe: Saves ONLY new facts to Supabase without overwriting other memory.
    Loads current state, merges facts, saves back.
    
    Args:
        new_facts: List of new fact strings to add
        new_event: Optional tuple of (event_name, event_date) to save
    """
    if not SUPABASE_AVAILABLE or (not new_facts and not new_event):
        return
        
    try:
        # Load fresh memory state from DB (not the stale in-memory reference)
        response = supabase.table("memories").select("data").eq("id", USER_ID).execute()
        
        if not response.data or len(response.data) == 0:
            return  # No memory to update
            
        current_data = response.data[0]['data']
        
        # Merge new facts (avoiding duplicates, preserving order)
        existing_facts = current_data.get('user_facts', [])
        for fact in new_facts:
            if fact not in existing_facts:
                existing_facts.append(fact)
        
        # Keep only last 20 facts (no set() - preserves insertion order)
        current_data['user_facts'] = existing_facts[-20:]
        
        # Update event if provided
        if new_event:
            event_name, event_date = new_event
            current_data['active_context']['significant_event'] = event_name
            current_data['active_context']['event_date'] = event_date
        
        # Save merged state back
        supabase.table("memories").upsert({
            "id": USER_ID,
            "data": current_data
        }).execute()
        
    except Exception as e:
        print(f"Facts save error (non-fatal): {e}")


def extract_and_save_facts(history):
    """
    Extracts facts from conversation and saves to Supabase.
    Thread-safe: Does NOT use the global memory reference.
    
    Args:
        history: Conversation history snapshot (list copy, not reference)
    """
    recent_user_text = " ".join([m['content'] for m in history if m['role'] == 'user'][-10:])
    if len(recent_user_text) < 5: 
        return 
    
    fact_prompt = (
        f"ANALYZE: '{recent_user_text}'\n"
        "Identify specific UPCOMING EVENTS (dates, appointments), FACTS about the user, or JOKES they made.\n"
        "Output strictly in this format (or 'None' for each if not found):\n"
        "EVENT: [Event Name or None]\n"
        "FACT: [Fact content or None]\n"
        "HUMOR: [Joke content or None]"
    )
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini", 
            messages=[{"role": "system", "content": fact_prompt}]
        )
        result = response.choices[0].message.content
        
        # Collect extracted data (don't modify any shared state)
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
        
        # Thread-safe save: loads fresh DB state, merges facts, saves
        if new_facts or new_event:
            save_facts_only(new_facts, new_event)
                    
    except Exception as e:
        print(f"Fact extraction error (non-fatal): {e}")

# --- 5. VISUAL STYLING ---
user_offset = memory.get('time_offset', 0)
server_hour = datetime.now().hour
current_hour = (server_hour + user_offset) % 24

if 5 <= current_hour < 12: time_of_day = "Morning"; bg_color = "#e3f2fd"; main_text = "#000000"; card_bg = "#ffffff"
elif 12 <= current_hour < 18: time_of_day = "Afternoon"; bg_color = "#f1f8e9"; main_text = "#000000"; card_bg = "#ffffff"
elif 18 <= current_hour < 23: time_of_day = "Evening"; bg_color = "#0f0f1a"; main_text = "#ffffff"; card_bg = "#1a1a2e"
else: time_of_day = "Late Night"; bg_color = "#000000"; main_text = "#d1d1d1"; card_bg = "#111111"

st.set_page_config(page_title="Companion", page_icon="💬", layout="wide")
st.markdown(f"""
<style>
    .stApp {{ background-color: {bg_color}; }}
    h1, h2, h3, p, span, label, .stMarkdown {{ color: {main_text} !important; }}
    section[data-testid="stSidebar"] {{ background-color: {card_bg} !important; }}
    section[data-testid="stSidebar"] * {{ color: {main_text} !important; }}
    .stChatMessage {{ background-color: {card_bg} !important; border-radius: 15px; }}
    .stChatMessage p {{ color: {main_text} !important; }}
    button {{ background-color: {card_bg} !important; color: {main_text} !important; border: 1px solid grey !important; }}
    button[kind="primary"] {{ background-color: #ff4b4b !important; color: white !important; border: none !important; }}
    .stChatInputInput {{ background-color: {card_bg} !important; color: {main_text} !important; }}
</style>
""", unsafe_allow_html=True)


# --- 6. BRAIN DEFINITIONS (FULL PSYCHOLOGY) ---
scores = memory['emotional_state']

# Load prompt files
MASTER_PROMPT = load_prompt("master_system.txt")
if not MASTER_PROMPT: MASTER_PROMPT = "Error: Master Prompt Missing"
EMOTIONAL_MATRIX = load_prompt("emotional_matrix.txt")

PERSONAS = {
    "1": load_prompt("persona_1.txt"),
    "2": load_prompt("persona_2.txt")
}
if not PERSONAS["1"]:
    PERSONAS["1"] = "Error loading Persona 1"

DEFAULT_PERSONA = PERSONAS["1"]

# Static instruction blocks
behavior_block = "AGENCY: Small actions. INVITATION: If Closeness > 40, suggest cafe."
tone_anchor_block = "TONE: Calm, warm, steady."
safety_block = "CRITICAL: No NSFW. No physical body claims. No therapy language."

# --- 7. UI FLOW ---
if st.session_state.app_mode == "Lobby":
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.write("\n\n"); st.title("🚪 The Doorway")
        
        profile = memory.get('user_profile', {"name": ""})
        is_new_user = profile.get("name") == ""

        # --- SCENARIO A: NEW USER ---
        if is_new_user:
            st.subheader("👋 Welcome! Let's get set up.")
            with st.form("onboarding_form"):
                new_name = st.text_input("What should I call you?")
                new_age = st.text_input("How old are you?")
                new_gender = st.selectbox("I identify as...", ["Male", "Female", "Non-binary", "Prefer not to say"])
                
                st.divider()
                st.caption("Customize Your Companion")
                selected_avatar_name = st.selectbox("Choose Appearance:", list(AVATAR_MAP.keys()))
                new_comp_name = st.text_input("Name your companion:", value="Keepsake")
                
                if st.form_submit_button("Start Journey"):
                    if new_name and new_comp_name:
                        memory['user_profile'] = {
                            "name": new_name, 
                            "age": new_age, 
                            "gender": new_gender,
                            "companion_name": new_comp_name
                        }
                        memory['avatar_id'] = AVATAR_MAP.get(selected_avatar_name, "1")
                        memory['has_chosen_avatar'] = True
                        
                        save_memory(memory)
                        st.success("Profile Created!")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("Please enter both names.")
        
        # --- SCENARIO B: RETURNING USER ---
        else:
            current_id = memory.get('avatar_id', "1")
            comp_name = memory['user_profile'].get('companion_name', 'Friend')
            
            st.success(f"Meeting: {comp_name}")
            
            outfit = memory.get('current_outfit', 'default')
            p_path = get_asset_path(f"avatar_{current_id}_{outfit}.png")
            if not os.path.exists(p_path): p_path = get_asset_path(f"avatar_{current_id}_default.png")
            if os.path.exists(p_path): st.image(p_path, width=150)

            st.write("")
            user_name = memory['user_profile'].get('name', 'Friend')
            st.write(f"Welcome back, **{user_name}**.")
            
            vibe_input = st.slider("Vibe Check", 0, 100, 50, format="", label_visibility="collapsed")
            if vibe_input < 30: st.caption("☁️ Low Energy")
            elif vibe_input > 70: st.caption("✨ High Energy")
            else: st.caption("🙂 Neutral")
            
            st.write("")
            if st.button("Enter Room", type="primary", use_container_width=True):
                st.session_state.current_vibe = vibe_input
                st.session_state.app_mode = "Chat"
                
                VIBE_CONFIG = load_json("vibe_greetings.json")
                if 5 <= current_hour < 12: period = "Morning"
                elif 12 <= current_hour < 18: period = "Afternoon"
                else: period = "Evening"

                # Recall Logic
                event_instr = ""
                active_context = memory.get('active_context', {})
                active_event = active_context.get('significant_event', "")
                rec_date_str = active_context.get('event_date', "")
                last_recalled = active_context.get('last_recalled_date', "")
                today_str = str(datetime.now().date())
                
                should_recall = False
                if active_event and rec_date_str:
                    try:
                        rec_date = datetime.strptime(rec_date_str, "%Y-%m-%d").date()
                        days_since = (datetime.now().date() - rec_date).days
                        if days_since <= 1 and last_recalled != today_str: should_recall = True
                    except ValueError: should_recall = False

                if should_recall and vibe_input >= 30:
                    raw_event_instr = VIBE_CONFIG.get("event_instruction", "")
                    event_instr = raw_event_instr.format(event_name=active_event)
                    memory['active_context']['last_recalled_date'] = today_str
                
                greeting_rule = VIBE_CONFIG.get("greeting_format", "").format(time_period=period, event_instruction=event_instr)
                if vibe_input < 30: vibe_instr = VIBE_CONFIG.get("low", "")
                elif vibe_input > 70: vibe_instr = VIBE_CONFIG.get("high", "")
                else: vibe_instr = VIBE_CONFIG.get("neutral", "")
                
                trigger = f"{greeting_rule}\nCONTEXT: {vibe_instr}"
                task = VIBE_CONFIG.get("task_instruction", "TASK: Generate 1 short spoken line.")
                
                chosen_id = memory.get('avatar_id', "1")
                active_persona = PERSONAS.get(chosen_id, DEFAULT_PERSONA)
                
                welcome_sys = f"{active_persona}\n{trigger}\n{task}"
                
                try:
                    stream = client.chat.completions.create(
                        model="gpt-4o-mini", 
                        messages=[{"role": "system", "content": welcome_sys}]
                    )
                    memory['history'].append({"role": "assistant", "content": stream.choices[0].message.content})
                except Exception as e:
                    memory['history'].append({"role": "assistant", "content": f"Hey! Good to see you."})
                    print(f"Greeting generation error: {e}")
                    
                save_memory(memory)
                st.rerun()
    

else: # CHAT ROOM
    with st.sidebar:
        st.header("📍 World")
        target_scene = st.radio("Go to:", ["Lounge", "Cafe", "Evening Walk", "Body Double", "Firework 🔒"])
        
        if target_scene == "Firework 🔒":
            if memory['tier'] == 0: 
                st.error("🔒 Upgrade Required")
                st.session_state.current_scene = "Lounge"
            else: 
                st.session_state.current_scene = "Firework"
        else: 
            st.session_state.current_scene = target_scene
        
        st.divider()
        st.slider("Energy", 0, 100, st.session_state.current_vibe, disabled=True)
        st.metric("Coins", memory['balance'])
        if st.button("Leave Room"): st.session_state.app_mode = "Lobby"; st.rerun()
        
        st.divider()
        st.caption("🔧 Dev Tools")
        if st.button("❤️ Max Love"): 
            memory['emotional_state']['closeness'] = 50; save_memory(memory); st.rerun()
        if st.button("⚡ Max Out"): 
            for i in range(25): memory['history'].append({"role": "user", "content": "test"})
            save_memory(memory); st.rerun()
        if st.button("👶 New User"): 
            memory['history'] = memory['history'][-5:]; save_memory(memory); st.rerun()
        if st.button("💎 Force Upgrade"):
            memory['tier'] = 1
            save_memory(memory)
            st.success("Upgraded to Tier 1")
            time.sleep(1)
            st.rerun()
        if st.checkbox("🧠 Show Brain"):
            st.write("**Events:**"); st.json(memory.get('active_context', {}))
            st.write("**Facts:**"); st.json(memory.get('user_facts', []))

    tab_chat, tab_shop, tab_profile = st.tabs(["💬 Chat", "🛍️ Shop", "👤 Profile"])

    # --- TAB 1: CHAT ---
    with tab_chat:
        # 1. DATA GATHERING
        my_id = memory.get('avatar_id', "1")
        my_outfit = memory.get('current_outfit', "default")
        current_scene = st.session_state.get("current_scene", "Lounge")
        
        c_name = next((k for k, v in AVATAR_MAP.items() if v == my_id), "Friend")
        active_persona = PERSONAS.get(my_id, DEFAULT_PERSONA)
        
        # 2. VISUAL SETUP
        avatar_file = get_asset_path(f"avatar_{my_id}_{my_outfit}.png")
        if not os.path.exists(avatar_file): avatar_file = get_asset_path(f"avatar_{my_id}_default.png")
        if not os.path.exists(avatar_file): avatar_file = "☕"

        # VIDEO SUPPORT LOGIC
        scene_base = None
        if current_scene == "Cafe": scene_base = f"scene_{my_id}_coffee"
        elif current_scene == "Evening Walk": scene_base = f"scene_{my_id}_walk"
        elif current_scene == "Body Double": scene_base = f"scene_{my_id}_work"

        if scene_base:
            mp4_path = get_asset_path(f"{scene_base}.mp4")
            gif_path = get_asset_path(f"{scene_base}.gif")

            if os.path.exists(mp4_path):
                st.video(mp4_path, autoplay=True, loop=True, muted=True)
            elif os.path.exists(gif_path):
                st.image(gif_path, use_column_width=True)
            elif current_scene != "Cafe":
                st.info(f"🎬 Scene Active (Missing assets for: {scene_base})")
                
        with st.container(border=True):
            c1, c2 = st.columns([1, 5])
            
            with c1:
                if os.path.exists(avatar_file):
                    st.image(avatar_file, width=50)
                else:
                    st.write("☕")
            
            with c2:
                c_name = next((k for k, v in AVATAR_MAP.items() if v == my_id), "Friend")
                st.markdown(f"**{c_name}**")
                st.caption("🟢 Online")

        # 3. BRAIN LOGIC - CONTEXT BUILDING (runs on every page load for display)
        vibe = st.session_state.current_vibe
        if vibe < 30: 
            vibe_instr = "USER STATE: Low Energy. Keep responses soft, quiet, non-demanding."
            vibe_allows_questions = False
        elif vibe > 70: 
            vibe_instr = "USER STATE: High Energy. Match their excitement. Be Hype."
            vibe_allows_questions = True
        else: 
            vibe_instr = "USER STATE: Neutral. Casual, easygoing."
            vibe_allows_questions = True

        weekly_instr = get_weekly_vibe()

        # Count only USER messages for relationship stage (consistent throughout)
        user_msg_count = len([m for m in memory['history'] if m['role'] == 'user'])
        
        # RELATIONSHIP STATUS (This is now the ONLY place hook_instr is defined)
        if user_msg_count < 20:
            relationship_instr = "MODE: NEW RELATIONSHIP. Strategy: Validation + Siding with them + Statements. Limit questions."
        else:
            closeness = memory['emotional_state']['closeness']
            if closeness > 40:
                relationship_instr = "RELATIONSHIP: CLOSE ALLY. You know them well. Side with their vents. Reference shared history."
            else:
                relationship_instr = "RELATIONSHIP: STEADY. Building trust. Be consistent and warm."

        # SCENE LOGIC
        is_date_active = False
        if memory['history']:
            if "cafe" in memory['history'][-1]['content'].lower(): is_date_active = True
        
        if is_date_active: 
            scene_desc = "SCENE OVERRIDE: COFFEE DATE ACTIVE. Focus on SENSORY details."
        elif current_scene == "Body Double": 
            scene_desc = "SCENE: BODY DOUBLING. Be quiet. No questions. Just support. Responses < 5 words."
            vibe_allows_questions = False  # Override for this scene
        elif current_scene == "Cafe":
            treat_logic = "ROLEPLAY ACTION: Offer to PAY for the user's coffee ('Put your wallet away, I've got this round')."

            col_info, col_btn = st.columns([3, 1])
            with col_info:
                st.caption("☕ **Cafe Counter**")
            with col_btn:
                if st.button("Pay (10c)", key="cafe_pay"):
                    if memory['balance'] >= 10:
                        memory['balance'] -= 10
                        memory['emotional_state']['warmth'] += 5
                        save_memory(memory)
                        st.toast("☕ Paid! Warmth +5")
                        st.rerun()
                    else:
                        st.toast("❌ Not enough coins")

            scene_desc = (
                f"SCENE: COFFEE SHOP (FACE-TO-FACE). "
                f"Proximity: Sitting across a small table. "
                f"{treat_logic} "
                f"Atmosphere: Warm, espresso smell. "
                f"CONTEXT: A 'Pay' button is visible to the user. If they mention paying, thank them warmly. "
                f"{weekly_instr}"
            )
        elif current_scene == "Evening Walk":
            scene_desc = f"SCENE: EVENING WALK. Atmosphere: Cool air, streetlights, walking side-by-side. {weekly_instr}"
        else: 
            scene_desc = f"SCENE: Casual. {weekly_instr}"

        # 4. DISPLAY CHAT HISTORY
        visible_history = [m for m in memory['history'] if m['role'] != "system"]
        
        cutoff_index = max(0, len(visible_history) - 10)
        older_messages = visible_history[:cutoff_index]
        recent_messages = visible_history[cutoff_index:]

        if older_messages:
            with st.expander(f"📚 Previous History ({len(older_messages)} messages)", expanded=False):
                for msg in older_messages:
                    with st.chat_message(msg['role'], avatar=avatar_file if msg['role'] == "assistant" else None):
                        st.markdown(msg['content'])

        for msg in recent_messages:
            with st.chat_message(msg['role'], avatar=avatar_file if msg['role'] == "assistant" else None):
                st.markdown(msg['content'])

        # PAYWALL CHECK
        if memory['tier'] == 0 and user_msg_count >= 20:
            st.warning("🔒 Daily Limit Reached")
            col_up1, col_up2 = st.columns(2)
            with col_up1:
                if st.button("💎 Upgrade"):
                    memory['tier'] = 1; save_memory(memory); st.balloons(); st.rerun()
            st.stop()

        # === MAIN CHAT INTERACTION ===
        if prompt := st.chat_input("Type here..."):
            
            # 1. IMMEDIATE UI FEEDBACK
            with st.chat_message("user"): 
                st.markdown(prompt)
            
            memory['history'].append({"role": "user", "content": prompt})
            
            # 2. FAST STATE UPDATES (CPU only, no API calls)
            memory['emotional_state'] = update_emotional_state(prompt, memory['emotional_state'])
            memory['last_active_timestamp'] = str(datetime.now())
            
            # Recalculate after adding new message
            total_msg_count = len(memory['history'])
            user_msg_count = len([m for m in memory['history'] if m['role'] == 'user'])

            # === 3. STRATEGY LAYER ===
            
            # Rage Logic
            rage_keywords = ["bureaucracy", "angry", "insane system", "furious", "pissed"]
            rage_instr = ""
            if any(k in prompt.lower() for k in rage_keywords):
                rage_instr = "MODE: PROTECTIVE INDIGNATION. Validate the user's anger. Be angry AT the situation/system FOR them."

            # Vulnerability Logic (when user is leaving)
            vuln_triggers = ["gotta go", "bye", "leaving", "busy", "gtg"]
            vuln_instr = ""
            if any(t in prompt.lower() for t in vuln_triggers) and memory['emotional_state']['closeness'] > 40:
                vuln_instr = "MODE: SECURE VULNERABILITY. Express a gentle desire to stay connected, but fully support their need to leave."

            # Pivot Logic (when heavy moment is over)
            last_bot = memory['history'][-2]['content'].lower() if len(memory['history']) >= 2 else ""
            heavy_triggers = ["sorry", "rough", "hard", "tough", "heavy", "sucks", "awful", "here for you", "support"]
            is_short_reply = len(prompt) < 25 
            turn_instr = ""
            if any(t in last_bot for t in heavy_triggers) and is_short_reply:
                turn_instr = "PIVOT SIGNAL: The user has acknowledged the comfort. The 'heavy' moment is over. DO NOT APOLOGIZE AGAIN. Transition to a lighter topic."

            # Humor Logic
            laugh_triggers = ["lol", "haha", "lmao", "rofl", "funny", "😂", "🤣"]
            humor_instr = ""
            if any(t in prompt.lower() for t in laugh_triggers) and vibe > 30:
                humor_instr = "REACTION: User is laughing. Respond with a WITTY TEASE or SHORT JOKE."

            # Value Strategy (returns tuple now)
            value_strategy, value_allows_questions = get_emotional_value(memory['emotional_state'], prompt)

            # Teasers
            teaser_instr = ""
            if user_msg_count < 10 and not st.session_state.get("turbo_teaser_shown", False):
                teaser_instr = "TEASER: Apply the EMOTIONAL MATRIX theme that matches the user's current emotion."
                st.session_state.turbo_teaser_shown = True
            
            future_instr = ""
            if user_msg_count == 15 and not st.session_state.get("future_teaser_shown", False):
                future_instr = "FUTURE HOOK: Mention a small detail about a shared future plan or something to look forward to."
                st.session_state.future_teaser_shown = True

            # === 4. MEMORY RECALL (FIXED: Combines facts + RAG) ===
            # Build the complete memory context
            facts_list = memory.get('user_facts', [])
            facts_text = "\n".join(facts_list) if facts_list else "(No stored facts yet)"
            
            # RAG retrieval for Tier 1+
            rag_text = ""
            if memory.get('tier', 0) >= 1:
                try:
                    rag_text = retrieve_context(prompt)  # FIX: Actually CALL the function
                except Exception:
                    rag_text = ""
            
            # Combine into single recall instruction (FIX: No more overwriting)
            recall_instr = f"USER FACTS (things you know about them):\n{facts_text}"
            if rag_text:
                recall_instr += f"\n\nRELEVANT PAST CONTEXT (from long-term memory):\n{rag_text}"

            # Retention hook for Tier 0 new users (ADDITIVE, not replacing)
            retention_instr = ""
            if memory.get('tier', 0) == 0 and user_msg_count < 10:
                retention_instr = "RETENTION: New free user. End with a specific, low-stakes question to encourage them to respond."

            # === 5. CONTEXT COMPILATION ===
            u_prof = memory.get('user_profile', {})
            user_name = u_prof.get('name', 'User')
            comp_name = u_prof.get('companion_name', 'Keepsake')

            profile_block = f"You are \"{comp_name}\", talking to \"{user_name}\"."
            
            if user_msg_count < 15:
                anchor_instruction = "PHASE: EARLY RELATIONSHIP. You don't have much history yet. Focus on being a supportive presence."
            else:
                anchor_instruction = "PHASE: ESTABLISHED RELATIONSHIP. You have history together. Reference past conversations when relevant."

            # Current emotional scores for context
            emotional_block = f"CURRENT SCORES: Closeness={scores['closeness']}, Warmth={scores['warmth']}, Stability={scores['stability']}"

            # Build situational modifiers (only non-empty ones)
            situational_modifiers = "\n".join(filter(None, [
                turn_instr,
                rage_instr,
                vuln_instr,
                humor_instr,
                teaser_instr,
                future_instr,
                retention_instr,
            ]))

            # FINAL PROMPT ASSEMBLY (Organized by priority)
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
{value_strategy}
{situational_modifiers}

=== CONSTRAINTS ===
{behavior_block}
{safety_block}
{tone_anchor_block}
"""

            # === 6. DETERMINE IF QUESTIONS ARE ALLOWED ===
            # Questions are allowed only if ALL conditions permit
            should_ask_question = vibe_allows_questions and value_allows_questions
            
            # Body Double scene always disables questions
            if current_scene == "Body Double":
                should_ask_question = False

            # === 7. GENERATION & DISPLAY ===
            with st.chat_message("assistant", avatar=avatar_file):
                bubble = st.empty()
                bubble.markdown("... *typing*")
                time.sleep(random.uniform(0.4, 0.8))
                bubble.empty()
                
                # Get the stream
                stream = generate_smart_response(
                    system_prompt, 
                    memory['history'][-10:], 
                    memory.get('tier', 0),
                    should_ask_question=should_ask_question
                )
                
                # Render the stream
                response = st.write_stream(stream)
                
            memory['history'].append({"role": "assistant", "content": response})

            # === 8. IMMEDIATE SAVE & RERUN (Latency Fix) ===
            # Truncate FIRST to keep payload small
            if len(memory['history']) > 50:
                memory['history'] = memory['history'][-50:]
            
            # Save immediately so user can continue chatting
            save_memory(memory)
            
            # Reverse Agency Gift Logic
            if memory['emotional_state']['agency'] > 20 and random.random() < 0.1:
                memory['balance'] += 15
                st.toast(f"🎁 {c_name} sent you 15 coins!", icon="💖")
                
            memory['balance'] += 2

            # === 9. BACKGROUND TASKS (Run in threads AFTER rerun starts) ===
            # These don't block the user - they run while user can continue chatting
            # IMPORTANT: Only pass COPIES of data, never references to global memory
            history_snapshot = list(memory['history'])  # Copy of history
            prompt_snapshot = prompt  # String is immutable, safe to pass
            user_tier = memory.get('tier', 0)  # Primitive value copy
            should_extract = (user_msg_count % 3 == 0)  # Decide now, not in thread
            
            def run_background_tasks():
                """
                Runs fact extraction and vector save in background.
                Thread-safe: Does NOT modify or save the global memory object.
                """
                try:
                    # Fact extraction (every 3 messages to reduce API calls)
                    # Uses thread-safe save_facts_only() which loads fresh DB state
                    if should_extract:
                        extract_and_save_facts(history_snapshot)
                    
                    # Vector save for Tier 1+ (longer messages only)
                    if len(prompt_snapshot) > 20 and user_tier >= 1:
                        save_vector_memory(prompt_snapshot)
                except Exception as e:
                    print(f"Background task error (non-fatal): {e}")
            
            # Start background thread
            bg_thread = threading.Thread(target=run_background_tasks, daemon=True)
            bg_thread.start()
            
            # Rerun immediately - user can chat while background tasks complete
            st.rerun()

    with tab_shop:
        st.header("🎁 Gift Shop")
        st.write(f"Balance: **{memory['balance']}c**")
        if st.button("Buy Coffee (10c)"):
            if memory['balance'] >= 10:
                memory['balance'] -= 10
                memory['emotional_state']['warmth'] += 5
                save_memory(memory); st.toast("☕ Warmth +5"); st.rerun()
        if st.button("Buy Sweater ($4.99)"):
            st.balloons(); st.toast("Beta Gift: Free!"); memory['current_outfit'] = "sweater"; save_memory(memory)

    with tab_profile:
        st.header("👤 Profile"); st.write(f"Name: {c_name}"); st.divider()
        st.subheader("❤️ Vitals"); st.progress(memory['emotional_state']['closeness']/100, text="Bond")
        st.divider(); st.subheader("🧠 Journal")
        for f in memory.get('user_facts', []): st.info(f)
        if st.button("Clear Memories", key="btn_clear"): memory['user_facts'] = []; save_memory(memory); st.rerun()
        st.divider(); st.subheader("⚙️ Settings")
        off = memory.get('time_offset', 0)
        new_off = st.slider("Timezone", -12, 14, off)
        if new_off != off: memory['time_offset'] = new_off; save_memory(memory); st.rerun()
