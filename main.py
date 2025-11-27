# main.py
import os
import sys
import time
import random
import re
from typing import List, Tuple

# Allow imports from modules/
sys.path.append(os.path.join(os.path.dirname(__file__), "modules"))

from modules.youtube_uploader import upload_video

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
    sys.exit(1)

# =================== CONFIG FOR THIS RUN ===================

MODE = "facts"  # "gameplay", "bio", or "facts"

SUBJECT = "Volodymyr Zelenskyy president of Ukraine"
BIO_SEARCH_QUERY = "Volodymyr Zelenskyy moments"

FACT_TOPIC = "Moxxie from Helluva Boss, INTERESTING FACTS!"
FACTS_SEARCH_QUERY = "Moxxie Helluva Boss moments"

GAMEPLAY_CHANNEL_URL = "https://www.youtube.com/@RamenStyle/videos"
GAMEPLAY_KEYWORD = "ARC Raiders"

# VOICE CONFIG (ElevenLabs)
VOICE = "hamid"
OUTPUT_FILE = "nifty_short.mp4"

OFFLINE = False
REUSE_VIDEO = None

# Music config
MUSIC_SEARCH_QUERY = "hazbin hotel song with no lyrics"
MUSIC_VOLUME = 0.05

# ==========================================================

random.seed(time.time())


# --------- Helpers for clips & music --------- #

def get_video_clips(
    query: str | None = None,
    channel: str | None = None,
    keyword: str | None = None,
    limit: int = 1,
) -> List[str]:
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


# --------- Tags + hashtags builder --------- #

def build_tags_and_hashtags(mode: str, subject_text: str) -> Tuple[List[str], str]:
    """
    Build:
    - YouTube API 'tags' list (no #)
    - Visible hashtag line for description (with #)

    Automatically adds Hazbin / Helluva tags when relevant.
    """
    lower = subject_text.lower()

    # Base tags
    tags: List[str] = ["shorts", "ai"]
    if mode == "facts":
        tags.append("facts")
    elif mode == "bio":
        tags.append("storytime")
    elif mode == "gameplay":
        tags.append("gaming")

    # Franchise tags
    if "hazbin" in lower:
        tags += ["hazbinhotel", "hazbin"]
    if "helluva" in lower:
        tags += ["helluvaboss", "helluva"]

    # Extract character / keyword names from subject text
    words = re.findall(r"[a-zA-Z0-9]+", lower)
    stop = {
        "from", "the", "and", "of", "in", "for", "with", "about",
        "interesting", "facts", "hazbin", "hotel",
        "helluva", "boss", "shorts", "ai",
        "storytime", "gaming", "mode", "subject",
    }

    for w in words:
        if len(w) < 3:
            continue
        if w in stop:
            continue
        if w not in tags:
            tags.append(w)

    # Deduplicate, preserve order
    seen = set()
    unique_tags: List[str] = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            unique_tags.append(t)

    hashtag_line = " ".join("#" + t for t in unique_tags)
    return unique_tags, hashtag_line


# --------- Main pipeline --------- #

def run_pipeline(
    script_text: str,
    video_query: str | None = None,
    channel: str | None = None,
    keyword: str | None = None,
    title: str = "",
    description: str = "",
    tags: List[str] | None = None,
):
    print(f"\n📜  SCRIPT:\n{script_text}\n")

    # 1. Get background video clips
    video_paths = get_video_clips(query=video_query, channel=channel, keyword=keyword, limit=1)
    if not video_paths:
        print("❌ No videos found.")
        return

    # 2. Generate voice with ElevenLabs
    print(f"\n🗣️  Generating voice with ElevenLabs ({VOICE})...")
    audio_path = generate_voice(
        script_text=script_text,
        filename="narration.mp3",
        voice=VOICE,
    )

    # 3. Background music
    music_path = get_music_track()
    if music_path:
        print(f"🎵  Using background music: {music_path}")
    else:
        print("🎵  No background music will be used for this run.")

    # 4. Merge into final video
    print("\n🎬  Building final montage short...")
    final_path = merge_audio_video(
        video_paths,
        audio_path,
        output_name=OUTPUT_FILE,
        vertical=True,
        shorts_cap=True,
        music_path=music_path,
        music_volume=MUSIC_VOLUME,
    )
    print(f"\n✨  Done! Final: {final_path}")

    # 5. Build title / description / tags / hashtags
    if not title:
        if MODE == "bio":
            title = f"{SUBJECT} — Crazy Story You Didn't Know"
        elif MODE == "facts":
            title = f"{FACT_TOPIC} (You Won't Believe)"
        else:
            title = "Insane AI-Generated Story Short"

    # Determine subject text for metadata
    if MODE == "bio":
        subject_text = SUBJECT
    elif MODE == "facts":
        subject_text = FACT_TOPIC
    else:
        subject_text = GAMEPLAY_KEYWORD or "Gameplay short"

    if not description:
        description = (
            "AI-generated short using custom scripts, voice, and editing.\n"
            f"Mode: {MODE}\n"
            f"Subject: {subject_text}\n\n"
            "Unofficial fan-made content. All rights to original IP owners."
        )

        auto_tags, hashtag_line = build_tags_and_hashtags(MODE, subject_text)
        description += "\n\n" + hashtag_line

        if tags is None:
            tags = auto_tags
    else:
        if tags is None:
            auto_tags, _ = build_tags_and_hashtags(MODE, subject_text)
            tags = auto_tags

    # 6. Upload to YouTube
    try:
        upload_video(
            file_path=final_path,
            title=title,
            description=description,
            tags=tags,
            category_id="24",      # Entertainment
            privacy_status="public",
        )
    except Exception as e:
        print(f"⚠️ Upload failed: {e}")


# --------- Entry point --------- #

if __name__ == "__main__":
    if MODE == "bio":
        print(f"\n=== BIO SHORT: {SUBJECT} ===")
        script = generate_bio_script(SUBJECT)
        run_pipeline(
            script,
            video_query=BIO_SEARCH_QUERY,
            title=f"{SUBJECT} — The Story Nobody Told You",
        )

    elif MODE == "facts":
        print(f"\n=== FACTS SHORT: {FACT_TOPIC} ===")
        script = generate_facts_script(FACT_TOPIC)
        run_pipeline(
            script,
            video_query=FACTS_SEARCH_QUERY,
            title=f"{FACT_TOPIC} (You Won't Believe #3)",
        )

    else:
        print("\n=== GAMEPLAY SHORT ===")
        script = generate_script()
        run_pipeline(
            script,
            channel=GAMEPLAY_CHANNEL_URL,
            keyword=GAMEPLAY_KEYWORD,
            title="This Game Is Actually INSANE (AI Commentary)",
        )