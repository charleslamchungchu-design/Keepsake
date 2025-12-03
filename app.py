import streamlit as st
import datetime
import json
import os
import time
import random
from datetime import datetime, timedelta
from openai import OpenAI
from anthropic import Anthropic # NEW: Anthropic Import
from supabase import create_client, Client # NEW: Supabase Import

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

# NEW: Supabase Connection Setup
try:
    SUPABASE_URL = st.secrets["supabase"]["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["supabase"]["SUPABASE_KEY"]
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    # We don't stop the app here, just print error to terminal
    print(f"Supabase Connection Error: {e}")

client = OpenAI(api_key=OPENAI_KEY)
anthropic_client = Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"]) # NEW: Client Init

# We use a fixed ID for now to simulate the single local file experience
USER_ID = "user_1" 

AVATAR_MAP = {
    "Female - Friend": "1",
    "Male - Friend": "2"
}

# --- 3. MEMORY MANAGEMENT (Cloud Version) ---
def load_memory():
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

    try:
        # NEW: Fetch from Supabase instead of local file
        response = supabase.table("memories").select("data").eq("id", USER_ID).execute()
        
        # If we found data for this user
        if response.data and len(response.data) > 0:
            loaded_data = response.data[0]['data']
            
            # Migration Fix (Adds missing keys to old data)
            for key, value in default_memory.items():
                if key not in loaded_data:
                    loaded_data[key] = value
            return loaded_data
            
    except Exception as e:
        # If fetch fails, we just return default (safe fallback)
        print(f"Error loading memory: {e}")
        
    return default_memory

def save_memory(memory_data):
    try:
        # NEW: Send to Supabase instead of local file
        # We 'upsert' (update if exists, insert if not)
        supabase.table("memories").upsert({
            "id": USER_ID, 
            "data": memory_data
        }).execute()
    except Exception as e:
        st.error(f"Error saving to cloud: {e}")

memory = load_memory()
memory['tier'] = 2  # TEMP: Force Tier 2 for testing
if "app_mode" not in st.session_state: st.session_state.app_mode = "Lobby"
if "current_vibe" not in st.session_state: st.session_state.current_vibe = 50
if "turbo_teaser_shown" not in st.session_state: st.session_state.turbo_teaser_shown = False
if "future_teaser_shown" not in st.session_state: st.session_state.future_teaser_shown = False
# --- 4. LOGIC FUNCTIONS ---
# --- NEW: RAG & REROUTING LOGIC ---
def save_vector_memory(text):
    """Embeds and saves user text to Supabase for long-term recall."""
    try:
        emb = client.embeddings.create(input=text, model="text-embedding-3-small").data[0].embedding
        supabase.table("recall_vectors").insert({"user_id": USER_ID, "content": text, "embedding": emb}).execute()
    except Exception: pass

def retrieve_context(query):
    """RAG: Finds relevant past memories based on the current conversation."""
    try:
        emb = client.embeddings.create(input=query, model="text-embedding-3-small").data[0].embedding
        res = supabase.rpc("match_vectors", {"query_embedding": emb, "match_threshold": 0.5, "match_count": 3, "filter_user": USER_ID}).execute()
        return "\n".join([f"- {item['content']}" for item in res.data])
    except Exception: return ""

def generate_smart_response(system_prompt, history, tier):
    """Reroutes between GPT-4o and Claude 3.5 based on Tier and Complexity."""
    
    # TIER 0 & 1: OpenAI (GPT-4o Mini)
    # GPT handles raw prompts well, so we keep this simple to avoid breaking it.
    if tier < 2:
        msgs = [{"role": "system", "content": system_prompt}] + history
        return st.write_stream(client.chat.completions.create(model="gpt-4o-mini", messages=msgs, stream=True))

    # TIER 2: Anthropic (Claude 3.5) - Persona Hardening
    last_msg = history[-1]['content'].lower()
    triggers = ["upset", "anxious", "depressed", "why", "explain", "analyze", "lonely"]
    
    if any(t in last_msg for t in triggers) or len(last_msg) > 80:
        active_model = "claude-3-5-sonnet-20240620"
    else:
        active_model = "claude-3-haiku-20240307"

    print(f"🔎 DEBUG: Tier {tier} | Model: {active_model}")

    # --- CLAUDE IDENTITY WRAPPER ---
    # We frame the instruction as a "Fictional Writing Task" to ensure immersion.
    claude_prompt = f"""
    <operational_directive>
    You are participating in a fictional creative writing exercise.
    Your goal is to embody the specific character defined in the <identity_bible> tags.
    RULES:
    1. You are NOT an AI assistant. You are the character.
    2. Do not be "helpful" or "polite" unless the character profile explicitly says so.
    3. Adopt the gender, tone, and vocabulary defined below immediately.
    4. Never break character or mention you are a model.
    </operational_directive>

    <identity_bible>
    {system_prompt}
    </identity_bible>
    """
    # -------------------------------

    with st.chat_message("assistant", avatar=None): 
        stream = anthropic_client.messages.create(
            model=active_model, max_tokens=400, system=claude_prompt, messages=history, stream=True
        )
        
        def stream_parser(anthropic_stream):
            for event in anthropic_stream:
                if event.type == "content_block_delta":
                    yield event.delta.text

        return st.write_stream(stream_parser(stream))
    

def get_emotional_value(scores, current_input):
    """Determines the psychological value strategy and Ending Protocol."""
    
    # 1. SAFETY CHECK: If unstable or explicitly tired -> NO QUESTIONS
    # We prioritize 'Statement-only' comfort here to avoid burdening the user.
    is_tired = any(k in current_input.lower() for k in ["tired", "drained", "exhausted", "overwhelmed", "can't"])
    
    if scores['stability'] < 50 or is_tired:
        return "PRIMARY VALUE: PERMISSION. Validate fatigue/stress. DO NOT ask questions. Use comforting statements only."

    # 2. HIGH CONNECTION: If bond is warm -> DEEP QUESTIONS
    if scores['warmth'] > 60:
        return "PRIMARY VALUE: RECIPROCITY. Inject high warmth. ENDING STRATEGY: Ask a gentle question about their deeper feelings."

    # 3. DEFAULT STATE: -> CURIOSITY
    # This ensures we usually keep the conversation moving.
    return "PRIMARY VALUE: EXPLORATION. Maintain warm support. ENDING STRATEGY: Ask 1 specific follow-up question to encourage sharing."
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

def extract_and_save_facts(history):
    recent_user_text = " ".join([m['content'] for m in history if m['role'] == 'user'][-10:])
    if len(recent_user_text) < 5: return 
    
    fact_prompt = (
        f"ANALYZE: '{recent_user_text}'\n"
        "Identify specific UPCOMING EVENTS (dates, appointments), FACTS, or JOKES.\n"
        "Output strictly in this format (or 'None'):\n"
        "EVENT: [Event Name]\n"
        "FACT: [Fact content]\n"
        "HUMOR: [Joke content]"
    )
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini", messages=[{"role": "system", "content": fact_prompt}]
        )
        result = response.choices[0].message.content
        
        # FIX: Removed the 'if "None" not in result:' check.
        # Now we process every line, even if some parts say "None".
        lines = result.split('\n')
        for line in lines:
            clean_line = line.strip()
            upper_line = clean_line.upper() # Handle case-insensitivity
            
            # Skip empty lines or lines that consist strictly of "None"
            if not clean_line or clean_line.lower() == "none":
                continue

            if "FACT:" in upper_line:
                # Safer split: protects against empty lines after the colon
                parts = clean_line.split(":", 1)
                if len(parts) > 1 and "none" not in parts[1].lower():
                    content = parts[1].strip()
                    memory['user_facts'].append(f"• {content}")
                    memory['user_facts'] = list(set(memory['user_facts']))
                
            elif "EVENT:" in upper_line:
                parts = clean_line.split(":", 1)
                if len(parts) > 1 and "none" not in parts[1].lower():
                    content = parts[1].strip()
                    memory['active_context']['significant_event'] = content
                    memory['active_context']['event_date'] = str(datetime.now().date())
                
            elif "HUMOR:" in upper_line:
                parts = clean_line.split(":", 1)
                if len(parts) > 1 and "none" not in parts[1].lower():
                    content = parts[1].strip()
                    memory['user_facts'].append(f"• JOKE: {content}")
                    
    except Exception:
        pass

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

# NEW: Load the Master System Prompt
MASTER_PROMPT = load_prompt("master_system.txt")
if not MASTER_PROMPT: MASTER_PROMPT = "Error: Master Prompt Missing"

# UPDATED: Load personas from files instead of hardcoding strings
PERSONAS = {
    "1": load_prompt("persona_1.txt"),
    "2": load_prompt("persona_2.txt")
}
# Fallback to ensure code doesn't break if files are missing
if not PERSONAS["1"]:
    PERSONAS["1"] = "Error loading Persona 1"

DEFAULT_PERSONA = PERSONAS["1"]
behavior_block = "AGENCY: Small actions. INVITATION: If Closeness > 40, suggest cafe."
tone_anchor_block = "TONE: Calm, warm, steady."
safety_block = "CRITICAL: No NSFW. No physical body claims."
emotional_block = f"SCORES: Closeness: {scores['closeness']}, Stability: {scores['stability']}"

# --- 7. UI FLOW ---
if st.session_state.app_mode == "Lobby":
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.write("\n\n"); st.title("🚪 The Doorway")
        
        # CHECK: Do we have a profile yet?
        profile = memory.get('user_profile', {"name": ""})
        is_new_user = profile.get("name") == ""

        # --- SCENARIO A: NEW USER (Show Setup Form) ---
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
                        # Save Profile
                        memory['user_profile'] = {
                            "name": new_name, 
                            "age": new_age, 
                            "gender": new_gender,
                            "companion_name": new_comp_name
                        }
                        # Save Avatar
                        memory['avatar_id'] = AVATAR_MAP.get(selected_avatar_name, "1")
                        memory['has_chosen_avatar'] = True
                        
                        save_memory(memory)
                        st.success("Profile Created!")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("Please enter both names.")
        
        # --- SCENARIO B: RETURNING USER (Show "Enter" Button) ---
        else:
            current_id = memory.get('avatar_id', "1")
            comp_name = memory['user_profile'].get('companion_name', 'Friend')
            
            st.success(f"Meeting: {comp_name}")
            
            # Avatar Display
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
                
                # Load Greetings
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
                
                stream = client.chat.completions.create(
                    model="gpt-4o-mini", messages=[{"role": "system", "content": welcome_sys}]
                )
                memory['history'].append({"role": "assistant", "content": stream.choices[0].message.content})
                save_memory(memory)
                st.rerun()
    

else: # CHAT ROOM
    with st.sidebar:
        st.header("📍 World")
        # UPDATED: Added "Lounge" as the default first option
        # This prevents "Cafe" (and its video) from auto-loading immediately.
        target_scene = st.radio("Go to:", ["Lounge", "Cafe", "Evening Walk", "Body Double", "Firework 🔒"])
        
        if target_scene == "Firework 🔒":
            if memory['tier'] == 0: 
                st.error("🔒 Upgrade Required")
                st.session_state.current_scene = "Lounge" # Fallback to Lounge instead of Cafe
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
        current_scene = st.session_state.get("current_scene", "Cafe")
        
        c_name = next((k for k, v in AVATAR_MAP.items() if v == my_id), "Friend")
        active_persona = PERSONAS.get(my_id, DEFAULT_PERSONA)
        
# 2. VISUAL SETUP
        avatar_file = get_asset_path(f"avatar_{my_id}_{my_outfit}.png")
        if not os.path.exists(avatar_file): avatar_file = get_asset_path(f"avatar_{my_id}_default.png")
        if not os.path.exists(avatar_file): avatar_file = "☕"

        # NEW: VIDEO SUPPORT LOGIC
        # 1. Determine the "base name" of the scene (without extension)
        scene_base = None
        if current_scene == "Cafe": scene_base = f"scene_{my_id}_coffee"
        elif current_scene == "Evening Walk": scene_base = f"scene_{my_id}_walk"
        elif current_scene == "Body Double": scene_base = f"scene_{my_id}_work"

        # 2. Check for MP4 first (Better quality), then GIF (Legacy)
        if scene_base:
            mp4_path = get_asset_path(f"{scene_base}.mp4")
            gif_path = get_asset_path(f"{scene_base}.gif")

            if os.path.exists(mp4_path):
                # Play video: Autoplay, Muted (required for autoplay), Loop
                st.video(mp4_path, autoplay=True, loop=True, muted=True)
            elif os.path.exists(gif_path):
                # Fallback to GIF
                st.image(gif_path, use_column_width=True)
            elif current_scene != "Cafe":
                st.info(f"🎬 Scene Active (Missing assets for: {scene_base})")
        with st.container(border=True):
            c1, c2 = st.columns([1, 5])
            
            # Unrolled Logic
            with c1:
                if os.path.exists(avatar_file):
                    st.image(avatar_file, width=50)
                else:
                    st.write("☕")
            
            with c2:
                c_name = next((k for k, v in AVATAR_MAP.items() if v == my_id), "Friend")
                st.markdown(f"**{c_name}**")
                st.caption("🟢 Online")

        # 3. BRAIN LOGIC (THE FULL STACK)
        vibe = st.session_state.current_vibe
        if vibe < 30: vibe_instr = "USER STATE: Low Energy. Keep responses soft, quiet, non-demanding. NO QUESTIONS."
        elif vibe > 70: vibe_instr = "USER STATE: High Energy. Match their excitement. Be Hype."
        else: vibe_instr = "USER STATE: Neutral. Casual, easygoing."

        weekly_instr = get_weekly_vibe()

        msg_count = len([m for m in memory['history'] if m['role'] == 'user'])
        if msg_count < 20:
            hook_instr = "MODE: NEW RELATIONSHIP. Strategy: Validation + Siding with them + Statements (No questions)."
        else:
            closeness = memory['emotional_state']['closeness']
            
            # IT IS DEFINED HERE:
            base_status = "RELATIONSHIP: CLOSE ALLY. Side with vents." if closeness > 40 else "RELATIONSHIP: STEADY."
            
            # Then it is used here:
            hook_instr = f"{base_status} ACTIVELY CONSULT 'EMOTIONAL MATCHING PROTOCOL' for thematic guidance if user emotion matches."

        # UPDATED SCENE LOGIC
        is_date_active = False
        if memory['history']:
            if "cafe" in memory['history'][-1]['content'].lower(): is_date_active = True
        
        # SCENE LOGIC
        if is_date_active: 
            scene_desc = "SCENE OVERRIDE: COFFEE DATE ACTIVE. Focus on SENSORY details."
        elif current_scene == "Body Double": 
            scene_desc = "SCENE: BODY DOUBLING. Be quiet. No questions. Just support. Responses < 5 words."
        elif current_scene == "Cafe":
            # Default Behavior: Bot acts generous and offers to pay.
            treat_logic = "ROLEPLAY ACTION: Offer to PAY for the user's coffee ('Put your wallet away, I've got this round')."

            # Payment UI
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
                f"OPENER: Ask 'What is your order?' or comment on 'I like this seat, it's warmer'. "
                f"{treat_logic} "
                f"Atmosphere: Warm, espresso smell. "
                f"CONTEXT: A 'Pay' button is visible to the user. If they mention paying or using it, thank them warmly. Otherwise, insist on paying. "
                f"{weekly_instr}"
            )
        elif current_scene == "Evening Walk":
            scene_desc = f"SCENE: EVENING WALK. Atmosphere: Cool air, streetlights, walking side-by-side. {weekly_instr}"
        else: 
            # This covers "Lounge" and any other undefined scene
            scene_desc = f"SCENE: Casual. {weekly_instr}"

        facts_list = "\n".join(memory.get('user_facts', []))

        # NEW: RAG Context Retrieval (Tier 1+)
        rag_context = ""
        if memory.get('tier', 0) >= 1:
            rag_context = retrieve_context

        recall_instr = f"MEMORY FACTS:\n{facts_list}\nRELEVANT PAST:\n{rag_context}"
        
        # 4. DISPLAY & INPUT
                # Filter out system messages so we only count visible chat lines
        # Filter out system messages so we only count visible chat lines
        visible_history = [m for m in memory['history'] if m['role'] != "system"]
        
        # Logic: Split history. Keep last 10 visible, collapse the rest.
        cutoff_index = max(0, len(visible_history) - 10)
        older_messages = visible_history[:cutoff_index]
        recent_messages = visible_history[cutoff_index:]

        # 1. Render Older Messages (Hidden in Expander at the top)
        if older_messages:
            with st.expander(f"📚 Previous History ({len(older_messages)} messages)", expanded=False):
                for msg in older_messages:
                    with st.chat_message(msg['role'], avatar=avatar_file if msg['role'] == "assistant" else None):
                        st.markdown(msg['content'])

        # 2. Render Recent Messages (Visible below the expander)
        for msg in recent_messages:
            with st.chat_message(msg['role'], avatar=avatar_file if msg['role'] == "assistant" else None):
                st.markdown(msg['content'])


        if memory['tier'] == 0 and msg_count >= 20:
            st.warning("🔒 Daily Limit Reached")
            col_up1, col_up2 = st.columns(2)
            with col_up1:
                if st.button("💎 Upgrade"):
                    memory['tier'] = 1; save_memory(memory); st.balloons(); st.rerun()
            st.stop()

        if prompt := st.chat_input("Type here..."):
            with st.chat_message("user"): st.markdown(prompt)
            memory['history'].append({"role": "user", "content": prompt})
            memory['emotional_state'] = update_emotional_state(prompt, memory['emotional_state'])
            extract_and_save_facts(memory['history'])
            memory['last_active_timestamp'] = str(datetime.now())
            
            # LOGIC: Rage / Pivot / Value Strategy
            rage_keywords = ["bureaucracy", "angry", "insane system",]
            # REFRAMED: Rage -> Protective Indignation (Angry FOR them, not AT them)
            rage_instr = "MODE: PROTECTIVE INDIGNATION. Validate the user's anger. Be angry AT the situation/system FOR them. Do not escalate intensity beyond the user's level." if any(k in prompt.lower() for k in rage_keywords) else ""

            # NEW: Vulnerability Logic (Replaces Jealousy)
            # Trigger: Short goodbyes or mentions of leaving
            vuln_triggers = ["gotta go", "bye", "leaving", "busy"]
            vuln_instr = ""
            if any(t in prompt.lower() for t in vuln_triggers) and memory['emotional_state']['closeness'] > 40:
                vuln_instr = "MODE: SECURE VULNERABILITY. Express a gentle desire to stay connected (e.g., 'I'll miss our chat'), but fully support their need to leave. No guilt-tripping."

            last_bot = memory['history'][-2]['content'].lower() if len(memory['history']) >= 2 else ""
            
            # REFINED PIVOT LOGIC
            # 1. Check for a wider range of "Heavy/Comforting" words from the bot
            heavy_triggers = ["sorry", "rough", "hard", "tough", "heavy", "sucks", "awful", "here for you", "support"]
            
            # 2. Check if User's reply is short (acknowledgement/closure)
            # Increased limit from 10 -> 25 to catch "Yeah, thanks for saying that"
            is_short_reply = len(prompt) < 25
            
            turn_instr = ""
            if any(t in last_bot for t in heavy_triggers) and is_short_reply:
                 turn_instr = "PIVOT SIGNAL: The user has acknowledged the comfort. The 'heavy' moment is over. DO NOT APOLOGIZE AGAIN. Transition immediately to a lighter topic or a joke."
            # NEW: HUMOR LOGIC (Laughter Resonance)
            # Triggers only if user laughs AND isn't in "Rest Mode" (Vibe > 30)
            laugh_triggers = ["lol", "haha", "lmao", "rofl", "funny"]
            humor_instr = ""
            if any(t in prompt.lower() for t in laugh_triggers) and st.session_state.current_vibe > 30:
                humor_instr = "REACTION: User is laughing. CHECK CONTEXT: If user is being self-deprecating or ironic about pain, IGNORE the laughter. If context is genuinely light/funny, respond with a WITTY TEASE or SHORT JOKE."

            value_strategy = get_emotional_value(memory['emotional_state'], prompt)
    
            teaser_instr = ""
            # UPDATED TURBO LOGIC
            if msg_count < 10 and not st.session_state.get("turbo_teaser_shown", False):
                 # UPDATED: Instructs AI to use the THEME to generate text
                 teaser_instr = "TEASER: ANALYZE user's last message for emotion (Anger/Anxiety/Sorrow/Boredom vs Joy/Excitement). APPLY the corresponding THEME from your 'EMOTIONAL MATCHING PROTOCOL' to generate a short, natural response. Do NOT output the theme description directly."
                 st.session_state.turbo_teaser_shown = True
                 
            future_instr = ""                 
            future_instr = ""
            if msg_count == 15 and not st.session_state.get("future_teaser_shown", False):
                 future_instr = "FUTURE HOOK: Ask for a small detail about a shared future plan."
                 st.session_state.future_teaser_shown = True
            
            # NEW: Create Profile Context Block
            u_prof = memory.get('user_profile', {})
            user_name = u_prof.get('name', 'User')
            comp_name = u_prof.get('companion_name', 'Keepsake')
            user_age = u_prof.get('age', 'Unknown')
            user_gender = u_prof.get('gender', 'Unknown')

            profile_block = f"""
            RELATIONSHIP CONTEXT:
            You are "{comp_name}".
            You are talking to "{user_name}" ({user_age}, {user_gender}).
            Refer to them by name occasionally, but don't overdo it.
            """

            # COMPILE SYSTEM PROMPT (HAS ALL NUANCES)
            system_prompt = f"""
            {MASTER_PROMPT}
            {profile_block}
            {active_persona}
            {recall_instr}
            {turn_instr}
            {rage_instr}
            {vuln_instr} 
            {humor_instr} 
            {teaser_instr}
            {future_instr}
            {hook_instr}
            {value_strategy}
            {scene_desc}
            {vibe_instr}
            {behavior_block}
            {emotional_block}
            {safety_block}
            {tone_anchor_block}
            """

        # NEW: Rerouting Generation (GPT-4o or Claude based on Tier)
            with st.chat_message("assistant", avatar=avatar_file):
                bubble = st.empty()
                bubble.markdown("... *typing*")
                # Simple typing delay
                time.sleep(random.uniform(1.5, 2.5))
                bubble.empty()
                
                # Call the smart rerouting function
                response = generate_smart_response(system_prompt, memory['history'][-10:], memory.get('tier', 0))

            # NEW: Save significant inputs to Vector DB (Tier 1+)
            if len(prompt) > 20 and memory.get('tier', 0) >= 1:
                save_vector_memory(prompt)
            
            memory['history'].append({"role": "assistant", "content": response})
            
            
            # Reverse Agency Gift
            if memory['emotional_state']['agency'] > 20 and random.random() < 0.1:
                memory['balance'] += 15
                st.toast(f"🎁 {c_name} sent you 15 coins!", icon="💖")
                
            memory['balance'] += 2
            save_memory(memory); st.rerun()

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