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
    # This now imports the Gemini version we built
    from modules.script_generator import generate_dynamic_script, client, GEMINI_MODEL
    from modules.gameplay_fetcher import fetch_gameplay_by_search
    from modules.music_fetcher import fetch_random_music
    from modules.voice_generator import generate_voice
    from modules.video_editor import merge_audio_video
    from modules.transcriber import transcribe_audio_to_groups
    from google.genai import types  # Added for Producer Gemini call
except ImportError as e:
    print(f"Error importing modules: {e}")
    sys.exit(1)

# ==============================================================================
# 1. CONFIGURATION
# ==============================================================================

# 🌍 CHANGE THIS TO "ru", "en", or "es"
LANGUAGE = "ru"
MUSIC_VOLUME = 0.02
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
                 "Attack on Titan", "The Amazing Digital Circus"]
    VOICE_KEY = "Molodoy"
elif LANGUAGE == "es":
    MY_NICHES = ["SCP Foundation", "Fallout Universe", "Attack on Titan"]
    VOICE_KEY = "spanish_guy"
else:  # English
    MY_NICHES = ["SCP Foundation", "Fallout Universe", "S.T.A.L.K.E.R. Universe", "Attack on Titan"]
    VOICE_KEY = "hamid"

# ==============================================================================
# 2. YOUTUBE DUPLICATE CHECKER
# ==============================================================================

# Cache for existing topics to avoid repeated API calls
existing_topics_cache = {}


def get_youtube_videos(channel_id: str = None, username: str = None, max_results: int = 50) -> list:
    """Fetch video titles from YouTube channel"""
    api_key = "AIzaSyBvnHzrnZ-rukkYvyf8kP9LvSABx3iCJwY"
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


# ... [Keep your imports and YouTube checker functions as they are] ...

# ==============================================================================
# 3. THE PRODUCER AGENT (Restored with Weighted Strategy)
# ==============================================================================

def generate_idea_from_niche(broad_niche, language="ru"):
    print(f"\nPRODUCER (Gemini 2.5): Analyzing '{broad_niche}'...")

    # --- RESTORED STRATEGIC CONTENT TIERS ---
    tiers = [
        "FRANCHISE PILLARS (The most iconic subjects)",
        "CORE NARRATIVE STAPLES (Standard lore/characters)",
        "ESOTERIC LORE & DEEP CUTS (Obscure details, hidden lore)"
    ]
    # Weights: 20% Famous, 60% Standard, 30% Obscure
    selected_tier = random.choices(tiers, weights=[0.33, 0.33, 0.33], k=1)[0]
    print(f"🎯 Strategy: {selected_tier}")

    # Dynamic exclusion logic to guide the AI
    if "FRANCHISE PILLARS" in selected_tier:
        guideline = "Pick the most famous icons (e.g., SCP-173, Vault Boy, Artyom, Nemesis)."
    elif "CORE NARRATIVE" in selected_tier:
        guideline = "Pick beloved subjects, but avoid the absolute top mascots."
    else:
        guideline = "Pick unknown or hidden details. Absolutely no popular characters."

    existing_topics = get_existing_topics_by_language(language)
    existing_topics_str = "\n".join(list(existing_topics)[:30])

    prompt = f"""
        Return JSON ONLY. 
        Universe: "{broad_niche}"
        Language: "{language}"
        Strategy Tier: {selected_tier}
        Guideline: {guideline}

        Avoid these already covered topics:
        {existing_topics_str}

       TASK:
    1. SUBJECT: Choose a character or location or theory.
    2. THEME: Focus ONLY on origins, psychological theories, or historical mysteries, interesting facts, lore..
    3. FORBIDDEN WORDS: "Wildest", "Funny", "Best", "Top 10", "Moments", "Get ready".
    
    TITLE EXAMPLES:
    - "The Human Kinger: Who Was He Before the Mask?"
    - "Who are the red line form metro 2033"
    - "What is the monolith from stalker"
        3. TITLE should be  in {language}.


        4. YOUTUBE QUERY: !!! IMPORTANT !!!
           Search for OFFICIAL EPISODE CLIPS. 
           Avoid words like "Lore", "Secrets", or "Theory" in the query.
           GOOD: "The Amazing Digital Circus Episode 1 kinger scene "
           BAD: "kinger digital lake lore"
           Avoid quering youtube shorts, try to find a video that is more then 60 seconds.

        5. MUSIC MOOD: 
           Don't search for "Subject Theme". Search for the game's official OST style.
           BAD: "The Great Worm theme"
           GOOD: "Metro Last Light Official Soundtrack Dark Ambient" or "Metro 2033 guitar OST"

        Return this JSON structure:
        {{
            "topic": "Title in {language}",
            "specific_subject": "Exact English Wiki Name",
            "youtube_query": "ENGLISH_SEARCH_QUERY_HERE",
            "music_mood": "specific music theme",
            "voice_name": "{VOICE_KEY}"
        }}
        """

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.8
            )
        )
        return json.loads(response.text)
    except Exception as e:
        print(f"AI Producer Error: {e}")
        return None


# ==============================================================================
# 4. THE PIPELINE
# ==============================================================================

def run_pipeline_for_idea(idea_data, niche_name):
    # Unpack from JSON
    TOPIC = idea_data['topic']
    SUBJECT = idea_data['specific_subject']
    YT_QUERY = idea_data['youtube_query']

    # Ensure music search has 'instrumental' to avoid vocals in background
    raw_music = idea_data['music_mood']
    MUSIC_QUERY = f"{raw_music} instrumental ost" if "ost" not in raw_music.lower() else raw_music

    VOICE_NAME = idea_data['voice_name']

    print(f"📋 PLAN: {SUBJECT}")
    print(f"   Title: {TOPIC}")


    contextual_topic = f"{TOPIC} inside the universe of {niche_name}"

    # 1. SCRIPT (Using the Gemini generator with search grounding)
    script = generate_dynamic_script(
        topic=contextual_topic,
        language=LANGUAGE
    )

    if not script or len(script) < 50:
        print("❌ Script generation failed.")
        return False

    # 2. VISUALS
    print(f"🎮 Fetching visuals...")
    video_paths = fetch_gameplay_by_search(YT_QUERY, max_videos=1)
    if not video_paths:
        return False

    # 3. MUSIC
    print(f"🎵 Fetching music...")
    music_path = fetch_random_music(search_query=MUSIC_QUERY)

    # 4. VOICE
    print(f"🗣️ Generating voice...")
    audio_filename = f"narration_{random.randint(1000, 9999)}.mp3"
    audio_path = generate_voice(script, audio_filename, VOICE_NAME, LANGUAGE)

    # 5. SUBTITLES
    subtitle_data = transcribe_audio_to_groups(audio_path, 2, LANGUAGE)

    # 6. EDIT
    final_filename = f"Short_{SUBJECT.replace(' ', '_')}_{random.randint(10, 99)}.mp4"
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

    return True


if __name__ == "__main__":
    # FORCE the test niche
    niche = "Attack on Titan"

    print(f"🎬 TESTING NEW NICHE: {niche}")
    plan = generate_idea_from_niche(niche, LANGUAGE)

    if plan:
        run_pipeline_for_idea(plan, niche)