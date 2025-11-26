import os
import time
import random
from typing import List

# Ensure we can import from modules
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), 'modules'))

try:
    from modules.script_generator import (
        generate_script,
        generate_bio_script,
        generate_facts_script,
    )
    from modules.gameplay_fetcher import (
        fetch_gameplay_by_search,
        fetch_gameplay_by_channel,
        pick_existing_gameplay_multi,
    )
    from modules.music_fetcher import (
        fetch_random_music,
        pick_existing_music_multi,
    )
    from modules.voice_generator import generate_voice, VOICES
    from modules.video_editor import merge_audio_video
except ImportError as e:
    print(f"Error importing modules: {e}")
    print("Make sure all required modules are implemented")
    exit(1)

# =================== CONFIG FOR THIS RUN ===================

MODE = "facts"  # "gameplay", "bio", or "facts"

SUBJECT = "Volodymyr Zelenskyy president of Ukraine"
BIO_SEARCH_QUERY = "Volodymyr Zelenskyy moments"

FACT_TOPIC = "Sir Pentious from Hazbin Hotel, INTERESTING FACTS!"
FACTS_SEARCH_QUERY = "Hazbin hotel Sir Pentious moments 10 minutes"

GAMEPLAY_CHANNEL_URL = "https://www.youtube.com/@RamenStyle/videos"
GAMEPLAY_KEYWORD = "ARC Raiders"

# VOICE CONFIG (ElevenLabs)
VOICE = "hamid"  # options: brian, adam, josh, sam, rachel, etc.
OUTPUT_FILE = "nifty_short.mp4"

OFFLINE = False
REUSE_VIDEO = None

# Music config
MUSIC_SEARCH_QUERY = "hazbin hotel music without lyrics"
MUSIC_VOLUME = 0.02

# ==========================================================

random.seed(time.time())


def get_video_clips(query: str = None, channel: str = None, keyword: str = None, limit: int = 1) -> List[str]:
    if REUSE_VIDEO:
        return [REUSE_VIDEO]

    if OFFLINE:
        vids = pick_existing_gameplay_multi(limit)
        return vids

    print(f"🎮  Fetching up to {limit} clips...")

    if query:
        return fetch_gameplay_by_search(query, max_videos=limit)
    elif channel and keyword:
        return fetch_gameplay_by_channel(channel, keyword, max_videos=limit)

    return []


def get_music_track() -> str | None:
    if OFFLINE:
        tracks = pick_existing_music_multi(limit=1)
        return random.choice(tracks) if tracks else None
    else:
        return fetch_random_music(search_query=MUSIC_SEARCH_QUERY, offline=False)


def run_pipeline(script_text: str, video_query: str = None, channel: str = None, keyword: str = None):
    print(f"\n📜  SCRIPT:\n{script_text}\n")

    # 1. Get Videos
    video_paths = get_video_clips(query=video_query, channel=channel, keyword=keyword, limit=1)
    if not video_paths:
        print("❌ No videos found.")
        return

    # 2. Voice (ElevenLabs)
    print(f"\n🗣️  Generating voice with ElevenLabs ({VOICE})...")
    audio_path = generate_voice(
        script_text=script_text,
        filename="narration.mp3",
        voice=VOICE
    )

    # 3. Background music
    music_path = get_music_track()
    if music_path:
        print(f"🎵  Using background music: {music_path}")
    else:
        print("🎵  No background music will be used for this run.")

    # 4. Merge
    print("\n🎬  Building final montage short...")
    merge_audio_video(
        video_paths,
        audio_path,
        output_name=OUTPUT_FILE,
        vertical=True,
        shorts_cap=True,
        music_path=music_path,
        music_volume=MUSIC_VOLUME,
    )
    print(f"\n✨  Done! Final: {os.path.abspath('data/final/' + OUTPUT_FILE)}")


if __name__ == "__main__":
    if MODE == "bio":
        print(f"\n=== BIO SHORT: {SUBJECT} ===")
        script = generate_bio_script(SUBJECT)
        run_pipeline(script, video_query=BIO_SEARCH_QUERY)

    elif MODE == "facts":
        print(f"\n=== FACTS SHORT: {FACT_TOPIC} ===")
        script = generate_facts_script(FACT_TOPIC)
        run_pipeline(script, video_query=FACTS_SEARCH_QUERY)

    else:
        print("\n=== GAMEPLAY SHORT ===")
        script = generate_script()
        run_pipeline(script, channel=GAMEPLAY_CHANNEL_URL, keyword=GAMEPLAY_KEYWORD)