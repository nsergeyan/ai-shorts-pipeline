import os
import random
import sys
import requests
import json
import time

from modules.script_checker import validate_script_context, validate_script_complete

# --- ADD MODULES PATH ---
sys.path.append(os.path.join(os.path.dirname(__file__), "modules"))

try:
    from modules.script_generator import generate_dynamic_script
    from modules.gameplay_fetcher import fetch_gameplay_by_search
    from modules.music_fetcher import fetch_random_music
    from modules.voice_generator import generate_voice
    from modules.video_editor import merge_audio_video
    from modules.transcriber import transcribe_audio_to_groups
except ImportError as e:
    print(f"Error importing modules: {e}")
    sys.exit(1)

# ==============================================================================
# 1. CONFIGURATION
# ==============================================================================

# 🌍 CHANGE THIS TO "ru", "en", or "es"
LANGUAGE = "en"

MODEL_NAME = "gemma2:27b"
MUSIC_VOLUME = 0.04
SUBTITLES_POSITION = "top"
CLEANUP_FILES = True

# YouTube Settings
YOUTUBE_CHANNEL_ID = "UCxgDwAsnx5YXO5GYkzdbQSg"
YOUTUBE_CHANNELS = {
    "ru": {
        "channel_id": "UCy_AQ-qaxvnew5Cn52m20kg",
        "username": "zabavnyi69"
    },
    "es": {
        "channel_id": "UCQUwBh-0nwMZUOpTQxOuGew",
        "username": "Seriohombre"
    },
    "en": {
        "channel_id": "UCxgDwAsnx5YXO5GYkzdbQSg",
        "username": "PLAim-g1x"
    }
}
USE_YOUTUBE_DUPLICATE_CHECK = True

# --- NICHE SELECTOR ---
if LANGUAGE == "ru":
    MY_NICHES = ["SCP Foundation", "Metro 2033 Universe", "S.T.A.L.K.E.R. Universe", "Fallout Universe",
                 "Resident Evil Universe"]
    VOICE_KEY = "Molodoy"
elif LANGUAGE == "es":
    MY_NICHES = ["SCP Foundation", "Fallout Universe", "Resident Evil Universe"]
    VOICE_KEY = "spanish_guy"
else:  # English
    MY_NICHES = ["SCP Foundation", "Fallout Universe", "S.T.A.L.K.E.R. Universe"]
    VOICE_KEY = "hamid"

# ==============================================================================
# 2. YOUTUBE DUPLICATE CHECKER
# ==============================================================================

# Cache for existing topics to avoid repeated API calls
existing_topics_cache = {}


def get_youtube_videos(channel_id: str = None, username: str = None, max_results: int = 50) -> list:
    """Fetch video titles from YouTube channel"""
    api_key = "REDACTED_API_KEY"
    if not api_key:
        print("⚠️ YouTube API key not found. Skipping duplicate check.")
        return []

    try:
        if channel_id:
            url = "https://www.googleapis.com/youtube/v3/search"
            params = {
                'key': api_key,
                'channelId': channel_id,
                'part': 'snippet',
                'maxResults': max_results,
                'type': 'video',
                'order': 'date'  # Get newest first
            }
        elif username:
            # First get channel ID from username
            url = "https://www.googleapis.com/youtube/v3/channels"
            params = {
                'key': api_key,
                'forUsername': username,
                'part': 'contentDetails'
            }
            response = requests.get(url, params=params)
            if response.status_code == 200:
                items = response.json().get('items', [])
                if items:
                    channel_id = items[0]['id']
                    url = "https://www.googleapis.com/youtube/v3/search"
                    params = {
                        'key': api_key,
                        'channelId': channel_id,
                        'part': 'snippet',
                        'maxResults': max_results,
                        'type': 'video',
                        'order': 'date'
                    }
                else:
                    return []
            else:
                return []
        else:
            return []

        response = requests.get(url, params=params)
        if response.status_code == 200:
            videos = response.json().get('items', [])
            titles = [video['snippet']['title'].lower() for video in videos]
            return titles
        return []
    except Exception as e:
        print(f"⚠️ YouTube API error: {e}")
        return []


def load_existing_topics(cache_file: str = "youtube_topics_cache.txt") -> set:
    """Load cached topics from file"""
    try:
        if os.path.exists(cache_file):
            with open(cache_file, 'r', encoding='utf-8') as f:
                return set(line.strip().lower() for line in f.readlines() if line.strip())
    except:
        pass
    return set()


def save_existing_topics(topics: list, cache_file: str = "youtube_topics_cache.txt"):
    """Save topics to cache file"""
    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            for topic in topics:
                f.write(f"{topic}\n")
    except Exception as e:
        print(f"⚠️ Failed to save topics cache: {e}")


def get_existing_topics_by_language(language: str, force_refresh=False) -> set:
    """Get existing topics for specific language channel"""
    global existing_topics_cache

    cache_key = f"topics_{language}"
    if not force_refresh and cache_key in existing_topics_cache:
        return existing_topics_cache[cache_key]

    # Try loading from language-specific cache file
    cache_file = f"youtube_topics_cache_{language}.txt"
    cached_topics = load_existing_topics(cache_file)
    if cached_topics and not force_refresh:
        existing_topics_cache[cache_key] = cached_topics
        return cached_topics

    # If no cache, fetch from YouTube
    if USE_YOUTUBE_DUPLICATE_CHECK:
        channel_config = YOUTUBE_CHANNELS.get(language, {})
        channel_id = channel_config.get("channel_id", "")
        username = channel_config.get("username", "")

        if channel_id or username:
            youtube_titles = get_youtube_videos(
                channel_id=channel_id if channel_id else None,
                username=username if username else None,
                max_results=100
            )
            topics_set = {title.lower() for title in youtube_titles}
            existing_topics_cache[cache_key] = topics_set
            save_existing_topics(list(topics_set), cache_file)  # Save to language-specific file
            return topics_set

    return set()


def check_duplicate_topic(topic: str, existing_topics: set) -> bool:
    """Check if topic already exists in YouTube content"""
    if not existing_topics or not topic:
        return False

    topic_lower = topic.lower()
    for existing_topic in existing_topics:
        # Simple substring matching - can be enhanced with fuzzy matching
        if topic_lower in existing_topic or existing_topic in topic_lower:
            return True
    return False


# ==============================================================================
# 3. THE PRODUCER AGENT (Updated with duplicate prevention)
# ==============================================================================

def generate_idea_from_niche(broad_niche, language="ru"):
    print(f"\n🧠 PRODUCER ({MODEL_NAME}): Analyzing '{broad_niche}'...")

    # Get existing topics to avoid duplicates
    existing_topics = get_existing_topics_by_language(language)

    # Format existing topics for the prompt
    existing_topics_list = list(existing_topics)[:30]  # Limit for prompt size
    existing_topics_str = "\n".join([f"- {topic}" for topic in existing_topics_list])

    if existing_topics_str and USE_YOUTUBE_DUPLICATE_CHECK:
        avoidance_section = f"""
    🚫 AVOID THESE ALREADY COVERED TOPICS IN {language.upper()} CHANNEL:
    {existing_topics_str}

    CRITICAL RULE: DO NOT PICK ANYTHING FROM THE ABOVE TOPICS.
    """
    else:
        avoidance_section = ""

    # --- ⚖️ STRATEGIC CONTENT MIX ---
    tiers = [
        "🏛️ FRANCHISE PILLARS (The absolute face of the franchise, viral icons)",
        "⭐ CORE NARRATIVE STAPLES (less popular characters, or topics)",
        "🧊 ESOTERIC LORE & DEEP CUTS (Hidden experiments, disturbing backstories, obscure items, least popular characters)"
    ]
    selected_tier = random.choices(tiers, weights=[0.10, 0.60, 0.30], k=1)[0]
    print(f"🎲 Content Strategy: {selected_tier}")

    # --- 🚫 DYNAMIC EXCLUSION LOGIC ---
    if "FRANCHISE PILLARS" in selected_tier:
        exclusion_instruction = "Pick the ABSOLUTE MOST FAMOUS icons. (e.g., SCP-173, Vault Boy, Artyom, Nemesis, etc...)."
    elif "CORE NARRATIVE" in selected_tier:
        exclusion_instruction = "Pick beloved characters/factions, but **EXCLUDE** the top mascots. (e.g., Pick Dr. Bright, Sin Faction, Brotherhood of Steel... but DO NOT pick SCP-173, etc..)."
    elif "ESOTERIC LORE" in selected_tier:
        exclusion_instruction = "Pick unknown/hidden details. **ABSOLUTELY NO** popular characters. (e.g., Pick SCP-5000, Vault 11, The Dark Ones' Origin, etc...)."

    prompt = f"""
    Role: Wiki Librarian & Content Strategist.
    Universe: "{broad_niche}"
    Language: "{language}"
    Strategy: {selected_tier}

    TASK:
    1. Analyze the universe based on the Strategy.
    2. Apply Selection Rule: 👉 **{exclusion_instruction}**
    3. Pick a **REAL, CANONICAL** subject matching the rule.
    Avoidance : {avoidance_section}
    4. CRITICAL: Ensure this topic is NOT in the avoided list above.

    ❌ HALLUCINATION & NAMING CHECK (CRITICAL):
    - **S.T.A.L.K.E.R.:** Faction names are SINGULAR. 
      - Bad: "The Sinners" -> Good: "Sin".
      - Bad: "The Mercs" -> Good: "Mercenaries".
      - Bad: "The Freedoms" -> Good: "Freedom".
    - **General:** DO NOT invent names ("The Factory" -> "Jupiter Plant").
    - **General:** DO NOT combine words ("Monolith Bunker" -> "Monolith Control Center").

    ✅ VALID SUBJECT TYPES:

    [[ IF S.T.A.L.K.E.R. ]]
    - Factions (Sin, Duty, Freedom, Monolith, Clear Sky).
    - Mutants (Bloodsucker, Controller, Burer).
    - Labs (X-18, X-16).

    [[ IF METRO 2033 ]]
    - Stations (Polis, D6), Monsters (Librarian, Demon), Factions (Hansa, Red Line).

    [[ IF SCP FOUNDATION ]]
    - SCPs (Objects), Sites (Site-19), GOIs (GOC, Serpent's Hand).

    [[ IF FALLOUT ]]
    - Vaults (11, 22, 108), Factions (Enclave), Creatures (Cazador).

    STRICT RULES:
    - **SUBJECT NAME:** Must be the EXACT English header from the Fandom Wiki.
    - **TITLE:** Clickbait in {language}.
    - **YOUTUBE QUERY:** Visual keywords only.
    - **MUSIC QUERY:** Specific OST/Instrumental.

    Return JSON ONLY:
    {{
        "topic": "Title in {language}",
        "specific_subject": "Exact English Wiki Name",
        "youtube_query": "INSERT_VISUAL_QUERY_HERE",
        "music_mood": "INSERT_SPECIFIC_MUSIC_QUERY_HERE",
        "voice_name": "{VOICE_KEY}"
    }}
    """

    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": MODEL_NAME,
                "prompt": prompt,
                "format": "json",
                "stream": False,
                "options": {"temperature": 0.7, "num_ctx": 4096}
            },
            timeout=120
        )
        if response.status_code != 200: return None
        return json.loads(response.json().get("response", ""))
    except Exception as e:
        print(f"❌ AI Error: {e}")
        return None


# ==============================================================================
# 4. THE PIPELINE
# ==============================================================================

def run_pipeline_for_idea(idea_data, niche_name):
    # Unpack
    TOPIC = idea_data['topic']
    SUBJECT = idea_data['specific_subject']

    # --- 🛑 PYTHON FORCED GOOGLE SEARCH ---
    # We do NOT trust the AI to write the google query. We build it ourselves.
    # This ensures we always search: "Fallout Universe Deathclaw wiki lore" (English)
    GOOGLE_QUERY = f"{niche_name} {SUBJECT} wiki lore"

    # --- CLEAN YOUTUBE VIDEO QUERY ---
    raw_yt = idea_data['youtube_query']
    clean_yt = raw_yt.replace("**VISUALS:**", "").strip()

    if len(clean_yt) < 5:
        clean_yt = f"{SUBJECT} cinematic {niche_name} 4k"

    YT_QUERY = clean_yt

    # --- CLEAN MUSIC QUERY ---
    raw_music = idea_data['music_mood']
    if "instrumental" not in raw_music.lower() and "ost" not in raw_music.lower() and "ambience" not in raw_music.lower():
        MUSIC_QUERY = f"{raw_music} Instrumental OST"
    else:
        MUSIC_QUERY = raw_music

    VOICE_NAME = idea_data['voice_name']

    print(f"📋 PLAN: {SUBJECT}")
    print(f"   Title: {TOPIC}")
    print(f"   Search: '{GOOGLE_QUERY}' (Forced English)")
    print(f"   Visual Search: '{YT_QUERY}'")
    print(f"   Music Search: '{MUSIC_QUERY}'")

    # 1. SCRIPT
    script, context_used = generate_dynamic_script(
        topic=SUBJECT,
        research_query=GOOGLE_QUERY,
        language=LANGUAGE
    )

    if not script or len(script) < 100:
        print("❌ Script generation failed (too short). Skipping.")
        return

    # NEW: Run complete validation (format + content)
    is_valid, feedback = validate_script_complete(script, SUBJECT, context_used, LANGUAGE)

    if not is_valid:
        print(f"❌ SCRIPT VALIDATION FAILED")
        print(f"   Reason: {feedback}")
        print(f"   Topic: {SUBJECT}")
        print(f"   Script Preview: {script[:200]}...")
        return  # STOP HERE - don't proceed to expensive operations

    print("✅ Script passed all validations.")

    # 2. GAMEPLAY / CINEMATICS
    print(f"🎮 Fetching visuals...")
    video_paths = fetch_gameplay_by_search(YT_QUERY, max_videos=1)
    if not video_paths:
        print("❌ No video found. Skipping.")
        return

    # 3. MUSIC
    print(f"🎵 Fetching music...")
    music_path = fetch_random_music(search_query=MUSIC_QUERY)

    # 4. VOICE
    print(f"🗣️ Generating voice: {VOICE_NAME}...")
    audio_filename = f"narration_{SUBJECT.replace(' ', '_')}.mp3"
    audio_path = generate_voice(
        script_text=script,
        filename=audio_filename,
        voice=VOICE_NAME,
        lang=LANGUAGE
    )

    # 5. SUBTITLES
    print("👂 Transcribing...")
    subtitle_data = transcribe_audio_to_groups(audio_path, 2, LANGUAGE)

    # 6. EDIT
    final_filename = f"Short_{SUBJECT.replace(' ', '_')}_{random.randint(100, 999)}.mp4"
    print(f"🎬 Editing '{final_filename}'...")

    final_path = merge_audio_video(
        video_paths=video_paths,
        audio_path=audio_path,
        output_name=final_filename,
        vertical=True,
        shorts_cap=True,
        music_path=music_path,
        music_volume=MUSIC_VOLUME,
        subtitles_data=subtitle_data,
        subtitles_position=SUBTITLES_POSITION
    )

    print(f"\n✅ DONE! Saved to: {final_path}")

    # 7. CLEANUP
    if CLEANUP_FILES:
        if os.path.exists(audio_path): os.remove(audio_path)
        if music_path and os.path.exists(music_path): os.remove(music_path)
        for v in video_paths:
            if os.path.exists(v): os.remove(v)

    return True  # INDICATE SUCCESS


# ==============================================================================
# 5. MAIN LOOP
# ==============================================================================
if __name__ == "__main__":
    print(f"🚀 STARTING AI STUDIO")
    print(f"🌍 Language: {LANGUAGE.upper()}")
    print(f"🤖 Model: {MODEL_NAME}")
    print(f"🎯 Active Niches: {MY_NICHES}")

    # Show YouTube settings status for current language
    if USE_YOUTUBE_DUPLICATE_CHECK:
        current_channel = YOUTUBE_CHANNELS.get(LANGUAGE, {})
        channel_id = current_channel.get("channel_id", "")
        username = current_channel.get("username", "")

        if channel_id or username:
            channel_name = username if username else channel_id
            print(f"📺 YouTube Duplicate Check: ENABLED for {LANGUAGE.upper()} channel ({channel_name})")
        else:
            print(f"⚠️ YouTube Duplicate Check: CONFIG NEEDED for {LANGUAGE.upper()} channel")
    else:
        print(f"⏭️ YouTube Duplicate Check: DISABLED")

    # Keep trying until we successfully create one video
    videos_created = 0
    max_attempts = 10  # Prevent infinite loops
    attempts = 0

    while videos_created < 1 and attempts < max_attempts:
        attempts += 1
        print(f"\n=== 🎬 ATTEMPT {attempts}/{max_attempts} ===")

        niche = random.choice(MY_NICHES)
        plan = generate_idea_from_niche(niche, LANGUAGE)

        if plan:
            # Additional duplicate check (belt and suspenders approach)
            if USE_YOUTUBE_DUPLICATE_CHECK:
                existing_topics = get_existing_topics_by_language(LANGUAGE)
                subject = plan.get('specific_subject', '')
                if check_duplicate_topic(subject, existing_topics):
                    print(
                        f"❌ DUPLICATE DETECTED: '{subject}' already exists in your {LANGUAGE.upper()} channel. Skipping.")
                    print("🔄 Trying again with a different topic...")
                    time.sleep(2)  # Brief pause before next attempt
                    continue

            # Try to run the pipeline
            try:
                # Pass the 'niche' string explicitly so we can build the google query safely
                success = run_pipeline_for_idea(plan, niche)  # GET SUCCESS STATUS
                if success:  # ONLY COUNT AS SUCCESS IF TRUE
                    videos_created += 1
                    print(f"🎉 SUCCESSFULLY CREATED VIDEO #{videos_created}!")
                else:
                    print("❌ Video creation failed validation. Trying again...")
                    time.sleep(3)
            except Exception as e:
                print(f"❌ Pipeline failed with error: {e}")
                print("🔄 Trying again with a different topic...")
                time.sleep(3)
        else:
            print("⚠️ AI Plan failed.")
            print("🔄 Trying again with a different topic...")
            time.sleep(2)  # Brief pause before next attempt

        # Cooldown between attempts (but not after success)
        if videos_created == 0 and attempts < max_attempts:
            print("⏳ Cooldown 3s...")
            time.sleep(3)

    if videos_created >= 1:
        print(f"\n🏆 FINISHED! Successfully created {videos_created} video(s).")
    else:
        print(f"\n💥 FAILED! Could not create any videos after {max_attempts} attempts.")
        print("💡 Try checking your configuration, internet connection, or YouTube API limits.")