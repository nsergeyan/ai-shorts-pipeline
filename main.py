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
from modules.transcriber import transcribe_audio_to_groups

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

SUBJECT = "Alastor From Hazbin Hotel History, Interesting facts!"
BIO_SEARCH_QUERY = "Alastor hazbin hotel moments"

FACT_TOPIC = "ARC Raiders Lore, History & Interesting Facts!"
FACTS_SEARCH_QUERY = "ARC Raiders gameplay 4K no commentary, max 10 min" #YOUTUBE

GAMEPLAY_CHANNEL_URL = "https://www.youtube.com/@RamenStyle/videos"
GAMEPLAY_KEYWORD = "ARC Raiders"

# VOICE CONFIG (ElevenLabs)
VOICE = "hamid"
OUTPUT_FILE = "nifty_short.mp4"

OFFLINE = False
REUSE_VIDEO = None

# Music config
MUSIC_SEARCH_QUERY = "Hazbin hotel OST no lyrics"
MUSIC_VOLUME = 0.04

# Cleanup config
CLEANUP_SOURCE_VIDEOS = True
CLEANUP_SOURCE_MUSIC = True
CLEANUP_NARRATION = True

# Control upload
UPLOAD_TO_YOUTUBE = False

# Subtitles config
SUBTITLES_POSITION = "top"  # "center" is best for shorts, "bottom" can get covered

# ==========================================================

random.seed(time.time())


# --------- Helpers --------- #

def get_video_clips(query=None, channel=None, keyword=None, limit=1):
    if REUSE_VIDEO: return [REUSE_VIDEO]
    if OFFLINE: return pick_existing_gameplay_multi(limit)
    print(f"🎮  Fetching up to {limit} clips...")
    if query:
        return fetch_gameplay_by_search(query, max_videos=limit)
    elif channel and keyword:
        return fetch_gameplay_by_channel(channel, keyword, max_videos=limit)
    return []


def get_music_track():
    if OFFLINE:
        tracks = pick_existing_music_multi(limit=1)
        return random.choice(tracks) if tracks else None
    else:
        return fetch_random_music(search_query=MUSIC_SEARCH_QUERY, offline=False)


def build_tags_and_hashtags(mode, subject_text):
    lower = subject_text.lower()
    tags = ["shorts", "ai"]
    if mode == "facts":
        tags.append("facts")
    elif mode == "bio":
        tags.append("storytime")
    elif mode == "gameplay":
        tags.append("gaming")

    if "hazbin" in lower: tags += ["hazbinhotel", "hazbin"]
    if "helluva" in lower: tags += ["helluvaboss", "helluva"]

    words = re.findall(r"[a-zA-Z0-9]+", lower)
    stop = {"from", "the", "and", "of", "in", "for", "with", "about", "interesting", "facts", "hazbin", "hotel",
            "helluva", "boss", "shorts", "ai", "storytime", "gaming", "mode", "subject"}

    for w in words:
        if len(w) > 2 and w not in stop and w not in tags:
            tags.append(w)

    seen = set()
    unique = [x for x in tags if not (x in seen or seen.add(x))]
    return unique, " ".join("#" + t for t in unique)


def _safe_delete(path, label):
    if not path: return
    try:
        if os.path.exists(path):
            os.remove(path)
            print(f"🧹 Deleted {label}: {path}")
    except Exception as e:
        print(f"⚠️ Could not delete {label}: {e}")


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

    # 2. Generate voice
    print(f"\n🗣️  Generating voice with ElevenLabs ({VOICE})...")
    audio_path = generate_voice(
        script_text=script_text,
        filename="narration.mp3",
        voice=VOICE,
    )

    # 3. Transcribe for Perfect Timing (The new part)
    subtitle_data = transcribe_audio_to_groups(audio_path, words_per_group=2)

    # 4. Background music
    music_path = get_music_track()
    if music_path:
        print(f"🎵  Using background music: {music_path}")
    else:
        print("🎵  No background music will be used.")

    # 5. Merge into final video
    print("\n🎬  Building final montage short...")
    final_path = merge_audio_video(
        video_paths,
        audio_path,
        output_name=OUTPUT_FILE,
        vertical=True,
        shorts_cap=True,
        music_path=music_path,
        music_volume=MUSIC_VOLUME,
        subtitles_text=None,  # We use data now, not text
        subtitles_data=subtitle_data,  # <--- Pass the exact timestamps
        subtitles_position=SUBTITLES_POSITION,
    )
    print(f"\n✨  Done! Final: {final_path}")

    # 6. Build metadata
    if not title:
        if MODE == "bio":
            title = f"{SUBJECT} — Crazy Story"
        elif MODE == "facts":
            title = f"{FACT_TOPIC} (You Won't Believe)"
        else:
            title = "Insane AI Story"

    subject_text = SUBJECT if MODE == "bio" else (FACT_TOPIC if MODE == "facts" else GAMEPLAY_KEYWORD)

    if not description:
        description = f"{title}\n\nUnofficial fan content."
        auto_tags, hashtag_line = build_tags_and_hashtags(MODE, subject_text)
        description += "\n\n" + hashtag_line
        if tags is None: tags = auto_tags
    else:
        if tags is None:
            tags, _ = build_tags_and_hashtags(MODE, subject_text)

    # 7. Upload
    if UPLOAD_TO_YOUTUBE:
        try:
            upload_video(
                file_path=final_path,
                title=title,
                description=description,
                tags=tags,
                category_id="24",
                privacy_status="public",
            )
        except Exception as e:
            print(f"⚠️ Upload failed: {e}")
    else:
        print(f"📥 Upload skipped. Saved to: {final_path}")

    # 8. Cleanup
    if not OFFLINE and not REUSE_VIDEO and CLEANUP_SOURCE_VIDEOS:
        for vp in video_paths: _safe_delete(vp, "source video")
    if not OFFLINE and CLEANUP_SOURCE_MUSIC and music_path:
        _safe_delete(music_path, "music track")
    if CLEANUP_NARRATION and audio_path:
        _safe_delete(audio_path, "narration audio")


# --------- Entry point --------- #

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