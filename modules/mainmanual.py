import os
import random
import sys
import requests
import json
import time

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
    MY_NICHES = ["Fallout Universe", "Attack on Titan", "simple Ancient History facts", "One-Punch Man", "simple interesting space facts(universe)","Simple interesting space theories(universe)", "Simple interesting facts about vikings", "Simple interesting football facts", "Simple interesting football facts", "simple interesting ufc facts", "Vinland Saga"]
    VOICE_KEY = "Molodoy"
elif LANGUAGE == "es":
    MY_NICHES = ["Fallout Universe", "Attack on Titan", "simple Ancient History facts", "One-Punch Man", "simple interesting space facts(universe)","Simple interesting space theories(universe)", "Simple interesting facts about vikings", "Simple interesting football facts", "Simple interesting football facts", "simple interesting ufc facts", "Vinland Saga"]
    VOICE_KEY = "spanish_guy"
else:  # English
    MY_NICHES = ["Fallout Universe", "simple interesting facts about Attack on Titan", "simple Ancient History facts", "One-Punch Man", "simple interesting space facts(universe)","Simple interesting science theories related to universe", "Simple interesting facts about vikings", "Simple interesting football facts", "simple interesting ufc facts", "Vinland Saga", "Jujutsu Kaisen", "the amazing digital circus", "simple mind blowing facts about animals", "Chainsaw Man"]
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

    selected_tier = random.choices(tiers, weights=[0.3, 0.3, 0.3], k=1)[0]
    print(f"🎯 Strategy: {selected_tier}")

    # Dynamic exclusion logic to guide the AI
    if "FRANCHISE PILLARS" in selected_tier:
        guideline = "Pick the most famous icons (e.g., Gojo, Thorfin, Sukuna)."
    elif "CORE NARRATIVE" in selected_tier:
        guideline = "Pick beloved subjects, but avoid the absolute top mascots."
    else:
        guideline = "Pick unknown or hidden details. Absolutely no popular characters."

    existing_topics = get_existing_topics_by_language(language)
    existing_topics_str = "\n".join(list(existing_topics))

    prompt = f"""
        Return JSON ONLY. 
        Universe: "{broad_niche}"
        Language: "{language}"
        Strategy Tier: {selected_tier}
        Guideline: {guideline}

        Avoid these already covered topics:
        {existing_topics_str}
        Everything has to be in ENGLISH!
        If you think you need more information about the topic you can use the 'google_search' tool to find fresh and deep information.

       TASK:
    1. SUBJECT: Choose a character or location or theory.
    2. THEME: Focus ONLY on origins, psychological theories, or historical mysteries, interesting facts, lore..
    3. FORBIDDEN WORDS: "Wildest", "Funny", "Best", "Top 10", "Moments", "Get ready".
    
    TITLE EXAMPLES:
    
    STRICT RULE: Do not summarize the basic plot or provide common-knowledge character motivations (e.g., 'Thorfinn changed because Askeladd died'(vinland saga)).
    - "The Fallen One: Who Was Sukuna Before He Became a Curse?"
    - "What is the Culling Game? Kenjaku’s Master Plan Explained"
    - "Who Were the Jomsvikings? The Real-Life Legends Behind the Anime Vinland Saga"
    - If the topic is "Simple interesting space theories(universe)" -> Make a videos like what will happen if a person goes to black hole, etc. Make it simple for a typical tiktok watcher.
       Perfect script for perfect topic:
       How powerful is Gojo Satoru? Well, powerful enough that Jujutsu Kaisen’s creator actually hates Gojo for it. First, there’s Gojo’s Infinity. Essentially, the closer you get to Gojo, the slower your movements are. You’ll slowly approach Gojo, but you’ll never be able to touch him. Next, you have Limitless, which allows Gojo to distort and manipulate the space around him at will. For example, Reversed Limitless Red gives Gojo the ability to repel, while Lapse Blue is the opposite; it’s essentially a black hole. Combining the two gives you Hollow Purple, which will erase its target from existence. All of this, combined with Gojo’s Six Eyes, allows him to keep his brain refreshed at all times, preventing burnout.
       
       Another perfect script for perfect topic:
       Have you ever wondered why Geto betrayed Gojo and turned evil in Jujutsu Kaisen? Let me explain. Well, Geto didn't wake up one day and decide to destroy the world; the world destroyed him first. He used to be the perfect sorcerer: protect the weak, save the helpless, and carry the burden without complaint. That was his whole identity. But everything snapped when Riko died in front of him. What hurt wasn't just Toji killing her; it was the crowd of non-sorcerers celebrating her death like it was entertainment—the same people he swore his life to protect. After that, every mission felt heavier. He kept swallowing curses, absorbing the vomit-tasting negativity humans created, and slowly he began to hate the people he was protecting. Then Yuki told him the truth that broke whatever sanity he had left: non-sorcerers are the source of curses. Sorcerers keep dying because of people who don't even care, and that's when Geto's belief flipped. He didn't want to save non-sorcerers anymore; he wanted a world where sorcerers didn't have to suffer for them. Haibara's death pushed him off the edge completely. On his next mission, he wiped out an entire village of 112 non-sorcerers just to rescue two sorcerer girls, and from that moment, Geto wasn't a protector anymore.
       
        3. TITLE should be  in {language}.
        

        4. YOUTUBE QUERY: !!! IMPORTANT !!!
           GOAL: Find high-quality, scenes that focuses on characters and atmosphere. Avoid UI, HUD, and player-controlled movement. Try to get from official sources. SO WE DONT HAVE ANY COPYRIGHT PROBLEMS FROM OTHER YOUTUBERS.
            1. SEARCH STRATEGY:
            
            NEVER use words like: "Mission", "Gameplay", "Playthrough", "Walkthrough".
            
            ALWAYS use words like: "Cutscene", "Official Clip", episode, "scene", etc...
            
            2. CHARACTER FOCUS (The "NPC" Rule):
            
            To find specific character (like gojo satoru or fallout characters), search for the character's name + "Scenes" or "Moments".
            
            Example: "satoru gojo speach jjk scene"
            
            Example: "fallout brotherhood of steel NPC idle cinematic 4K"
            
            If it is about fallout universe use only visuals from the movie fallout.
            
            If it is about space(universe) search for images,animations,footages of universe, no explanations or ifnormative videos just universe.

        5. MUSIC MOOD: 
           Don't search for "Subject Theme". Search for the game's official OST style.
           BAD: "The Great Worm theme"
           GOOD: "Metro Last Light Official Soundtrack  Ambient" or "Hazbin hotel soundtrack instrumental no lyrics" etc...
           Don't use a music from Interstellar.

        Return this JSON structure:
        {{
            "topic": "Title in {language}",
            "specific_subject": "Exact English Wiki Name",
            "youtube_queries": [
        "PRIMARY_QUERY_Youtube",
        "BACKUP_QUERY1_Youtube",
        "BACKUP_QUERY2_Youtube"
    ],
            "music_mood": "specific music theme",
            "voice_name": "{VOICE_KEY}"
        }}
        """
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        temperature=0.8
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

    return True


if __name__ == "__main__":
    # FORCE the test niche
    niche =  "Jujutsu Kaisen"
    print(f"🎬 TESTING NEW NICHE: {niche}")
    plan = generate_idea_from_niche(niche, LANGUAGE)
    if plan:
        run_pipeline_for_idea(plan, niche)
