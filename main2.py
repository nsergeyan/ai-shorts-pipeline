import os
import random
import sys
import requests
import json

# --- ADD MODULES PATH ---
sys.path.append(os.path.join(os.path.dirname(__file__), "modules"))

try:
    from modules.script_generator import (
        generate_dynamic_script,
        call_gemini_with_retry,
        GEMINI_MODEL,
        types,
        client
    )
    from modules.gameplay_fetcher import fetch_gameplay_by_search
    from modules.music_fetcher import fetch_random_music
    from modules.voice_generator import generate_voice
    from modules.video_editor import merge_audio_video
    from modules.transcriber import transcribe_audio_to_groups

    from modules.tiktok_checker import (
        get_existing_tiktok_topics_by_language,
        check_duplicate_tiktok_topic
    )
except ImportError as e:
    print(f"Error importing modules: {e}")
    sys.exit(1)
# ==============================================================================
# 1. CONFIGURATION
# ==============================================================================

# 🌍 CHANGE THIS TO "ru", "en", or "es"
LANGUAGE = "en"
MUSIC_VOLUME = 0.025
SUBTITLES_POSITION = "top"
CLEANUP_FILES = True


USE_YOUTUBE_DUPLICATE_CHECK = False
USE_TIKTOK_DUPLICATE_CHECK = True

TIKTOK_CHANNELS = {
    "en": {"username": "plaim62"},
}

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

# --- NICHE SELECTOR ---
if LANGUAGE == "ru":
    MY_NICHES = ["Fallout Universe", "Attack on Titan", "simple popular Ancient History facts", "One-Punch Man",
                 "simple interesting space facts(universe)", "Simple interesting space theories(universe)",
                 "Simple interesting facts about vikings", "Simple interesting football facts",
                 "Simple interesting football facts", "simple interesting ufc facts", "Vinland Saga"]
    VOICE_KEY = "Molodoy"
elif LANGUAGE == "es":
    MY_NICHES = ["Fallout Universe", "Attack on Titan", "simple Ancient History facts", "One-Punch Man",
                 "simple interesting space facts(universe)", "Simple interesting space theories(universe)",
                 "Simple interesting facts about vikings", "Simple interesting football facts",
                 "Simple interesting football facts", "simple interesting ufc facts", "Vinland Saga"]
    VOICE_KEY = "spanish_guy"
else:  # English
    MY_NICHES = ["Fallout Universe", "simple interesting facts about Attack on Titan",
                 "simple popular Ancient History facts", "One-Punch Man", "simple interesting space facts(universe)",
                 "Simple interesting science theories related to universe", "Simple interesting facts about vikings",
                 "Simple interesting football facts", "simple interesting ufc facts", "Vinland Saga", "Jujutsu Kaisen",
                 "the amazing digital circus", "simple mind blowing facts about animals", "Chainsaw Man",
                 "Demon Slayer", "Invincible", "Frieren: Beyond Journey's End", "Murder Drones"]
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

    cache_file = f"youtube_topics_cache_{language}.txt"
    cached_topics = load_existing_topics(cache_file)
    if cached_topics and not force_refresh:
        existing_topics_cache[cache_key] = cached_topics
        return cached_topics

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
            save_existing_topics(list(topics_set), cache_file)
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
# 3. THE PRODUCER AGENT (Restored with Weighted Strategy)
# ==============================================================================

def generate_idea_from_niche(broad_niche, language="ru"):
    print(f"\nPRODUCER (Gemini 2.5): Analyzing '{broad_niche}'...")

    # --- RESTORED STRATEGIC CONTENT TIERS ---
    tiers = [
        "SURFACE CANON (Well-known facts, but with a narrow analytical angle)",
        "SUBTEXT & MECHANICS (Rules, systems, implications fans overlook)",
        "ARCHIVAL / LOST CONTEXT (Scrapped ideas, forgotten lore, external sources)"
    ]

    selected_tier = random.choices(tiers, weights=[0.15, 0.45, 0.4], k=1)[0]
    print(f"🎯 Strategy: {selected_tier}")

    # Dynamic exclusion logic to guide the AI
    if "SURFACE CANON" in selected_tier:
        guideline = (
            "You MAY use a famous subject, "
            "but the focus must be a single overlooked detail, "
            "early-stage concept, or narrow unresolved question. "
            "If the topic can be summarized from a wiki intro, reject it."
        )
    elif "SUBTEXT & MECHANICS" in selected_tier:
        guideline = (
            "Focus on rules, systems, psychological mechanics, "
            "or causal chains that are rarely discussed explicitly. "
            "Avoid character biographies."
        )
    else:
        guideline = (
            "Focus on forgotten, abandoned, or marginal material: "
            "scrapped drafts, minor factions, offhand references, "
            "or inconsistencies with implications."
        )

    existing_topics = set()

    # YouTube
    if USE_YOUTUBE_DUPLICATE_CHECK:
        existing_topics |= get_existing_topics_by_language(language)

    # TikTok
    if USE_TIKTOK_DUPLICATE_CHECK:
        existing_topics |= get_existing_tiktok_topics_by_language(
            language,
            TIKTOK_CHANNELS
        )
    existing_topics_str = "\n".join(list(existing_topics))

    prompt = f"""
    YOU MUST RETURN VALID JSON ONLY.
    NO explanations. NO markdown. NO extra text.

    GLOBAL SETTINGS
    - Universe: "{broad_niche}"
    - Output Language: "{language}"
    - Strategy Tier: {selected_tier}
    - Guideline: {guideline}
    - ALL OUTPUT MUST BE IN ENGLISH (except the TITLE language rule below).

    AVOID DUPLICATION
    Do NOT generate topics similar to or overlapping with the following:
    {existing_topics_str}

    RESEARCH RULE
    If information feels shallow or outdated, you MAY use the google_search tool to fetch deeper or fresher context.
    
    ────────────────────
    TASK DEFINITION
    ────────────────────

    1. SUBJECT SELECTION
    Choose ONE:
    - A character
    - A location
    - A historical event
    - A theory (fictional or real)

    2. THEME RESTRICTIONS (VERY IMPORTANT)
    Focus ONLY on:
    - Origins
    - Psychological analysis
    - Hidden lore
    - Historical mysteries
    - Lesser-known facts or implications

    - Focus on concrete implications, not symbolism or metaphors
    - Avoid abstract themes unless directly tied to a factual detail

    3. FORBIDDEN WORDS (TITLE + SCRIPT IDEAS)
    Never use:
    "Wildest", "Funny", "Best", "Top 10", "Moments", "Get ready"

    ────────────────────
    TITLE GUIDELINES
    ────────────────────
    - Assume the audience is already familiar with the universe
    
    - Title MUST be written in {language}
    - Title must feel documentary-style, mysterious, or analytical
    - No clickbait lists
    - No recap framing

    TONE CONSTRAINT (CRITICAL)
    - Avoid epic, mythic, or heroic language
    - Prefer neutral, restrained, analytical wording
    - If a phrase sounds like an anime trailer, rewrite it plainly

    GOOD EXAMPLES:
    - "The Fallen One: Who Was Sukuna Before He Became a Curse?"
    - "What Is the Culling Game? Kenjaku’s True Endgame"
    - "Who Were the Jomsvikings? The Real Legends Behind Vinland Saga"

    SPECIAL CASE — SPACE / UNIVERSE TOPICS:
    If the topic is about space or cosmic theories:
    - Frame it as a simple but fascinating thought experiment
    - Make it understandable for a TikTok audience
    Example:
    "What Happens to a Human If They Fall Into a Black Hole?"
    
    example of a script that genereted a good tiktoker based on interesting topic/tytle: 
    Most fans assume Mahito’s philosophy about the soul is something he developed himself.
    But in the anime, his most famous idea — that the body is shaped by the soul — isn’t original at all.
    He directly repeats a line from a fictional horror movie, Earthworm Man 3, which he watches while experimenting on humans. The idea comes from a doctor in the film, not from Mahito’s own reasoning.
    That detail subtly changes how he should be read. Mahito isn’t presenting a coherent worldview — he’s borrowing a concept that sounds convincing and using it to justify his behavior.
    Less a philosopher, more an immature curse clinging to borrowed language.
    Seen that way, his obsession with the soul feels less profound — and more unstable.

    ────────────────────
    YOUTUBE SEARCH QUERIES (CRITICAL)
    ────────────────────
     GOAL:
    Find raw cinematic visuals only for background video.
    No narration. No analysis. No commentary. No essays.
    
    STRICTLY AVOID SEARCH TERMS THAT ATTRACT EXPLANATIONS:
    ❌ longevity
    ❌ meaning
    ❌ explained
    ❌ symbolism
    ❌ lore
    ❌ analysis
    ❌ philosophy
    ❌ why
    Avoid UI, HUD, gameplay, or YouTuber edits.
    
    ALWAYS SEARCH FOR: 
    Concrete story moments
    Physical actions
    Episode-specific scenes
    Emotional beats shown on screen
    Prefer official sources to minimize copyright risk.
    SEARCH RULES:
    ❌ NEVER use:
    "Gameplay", "Mission", "Walkthrough", "Playthrough"
    ✅ ALWAYS prefer:
    "Cutscene", "Official Clip", "Scene", "Episode", "Cinematic"

    CHARACTER SEARCH RULE (NPC RULE):
    Use:
    [Character Name] + "scene" OR "moments"

    GOOD EXAMPLES (Frieren):
    "Gojo Satoru scene jjk"
    "Sukuna first apprentice scene jjk"
    
    UNIVERSE-SPECIFIC RULES:
    - Fallout → ONLY visuals from the Fallout TV series
    - Space topics → animations, space footage, cosmic visuals
      ❌ No explanations or educational narration videos

    ────────────────────
    MUSIC MOOD RULES
    ────────────────────

    - Search for OFFICIAL OST styles only
    - Prefer ambient or instrumental
    - No lyrical tracks
    - NEVER use music from Interstellar

    BAD:
    "The Great Worm Theme"

    GOOD:
    - "Metro Last Light Official Soundtrack Ambient"
    - "Hazbin Hotel OST instrumental no lyrics"

    ────────────────────
    OUTPUT FORMAT (STRICT)
    ────────────────────

    Return EXACTLY this JSON structure:

    {{
      "topic": "Title in {language}",
      "specific_subject": "Exact English Wikipedia title",
      "youtube_queries": [
        "PRIMARY_QUERY",
        "BACKUP_QUERY_1",
        "BACKUP_QUERY_2"
      ],
      "music_mood": "specific OST style or vibe",
      "voice_name": "{VOICE_KEY}"
    }}
    """

    if "FRANCHISE PILLARS" in selected_tier:
        temperature = 0.45
    elif "CORE NARRATIVE" in selected_tier:
        temperature = 0.55
    else:  # ESOTERIC LORE & DEEP CUTS
        temperature = 0.6

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        temperature=temperature
    )

    response = call_gemini_with_retry(prompt, config)
    if response and response.text:
        try:
            return json.loads(response.text)
        except Exception as e:
            print(f"AI Producer JSON Error: {e}")
    return None


# ==============================================================================
# 4. THE PIPELINE
# ==============================================================================
def run_pipeline_for_idea(idea_data, niche_name):
    # Unpack from JSON
    TOPIC = idea_data['topic']
    SUBJECT = idea_data['specific_subject']
    YOUTUBE_QUERIES = idea_data.get('youtube_queries', [])

    # Ensure we have a list of queries
    if isinstance(YOUTUBE_QUERIES, str):
        YOUTUBE_QUERIES = [YOUTUBE_QUERIES]

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
    print(script)
    # 2. VISUALS - with query rotation and video tracking
    print(f"🎮 Fetching visuals...")
    used_video_ids = set()  # Track used videos to avoid repeats

    video_paths = fetch_gameplay_by_search(
        search_queries=YOUTUBE_QUERIES,
        max_videos=1,
        retry_searches=10,
        used_video_ids=used_video_ids
    )

    if not video_paths:
        print("⚠️ Skipping due to lack of usable visuals.")
        return False

    # 3. MUSIC
    print(f"🎵 Fetching music...")
    music_path = fetch_random_music(search_query=MUSIC_QUERY)

    # 4. VOICE
    print(f"🗣️ Generating voice...")
    audio_filename = f"narration_{random.randint(1000, 9999)}.mp3"
    audio_path = generate_voice(script, audio_filename, VOICE_NAME, LANGUAGE)

    # 5. SUBTITLES
    print(f"📝 Generating subtitles...")
    subtitle_data = transcribe_audio_to_groups(audio_path, 2, LANGUAGE)
    print(f"✅ Generated {len(subtitle_data) if subtitle_data else 0} subtitle chunks")

    # 6. EDIT
    final_filename = f"Short_{SUBJECT.replace(' ', '_')}_{random.randint(10, 99)}.mp4"
    print(f"🎬 Starting video editing...")

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

        cache_file = f"youtube_topics_cache_{LANGUAGE}.txt"
        if os.path.exists(cache_file):
            os.remove(cache_file)
            print(f"🗑️ Cleaned up YouTube cache: {cache_file}")

        global existing_topics_cache
        existing_topics_cache.clear()

        tiktok_cache = f"tiktok_topics_cache_{LANGUAGE}.txt"
        if os.path.exists(tiktok_cache):
            os.remove(tiktok_cache)
            print(f"🗑️ Cleaned up TikTok cache: {tiktok_cache}")

    return True


if __name__ == "__main__":
    # FORCE the test niche
    niche = "the amazing digital circus"
    print(f"🎬 TESTING NEW NICHE: {niche}")
    plan = generate_idea_from_niche(niche, LANGUAGE)
    if plan:
        run_pipeline_for_idea(plan, niche)
