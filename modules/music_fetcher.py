import os
import random
import re
import yt_dlp
from config import MUSIC_DIR


def _make_opts(skip_download: bool):
    return {
        "outtmpl": os.path.join(MUSIC_DIR, "%(id)s - %(title).200B.%(ext)s"),
        "quiet": False,
        "skip_download": skip_download,
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "merge_output_format": "m4a",
        "restrictfilenames": True,
        "socket_timeout": 30,
        "retries": 10,
        "ignoreerrors": True,
    }


def _final_filepath(ydl, info):
    if info.get("requested_downloads"):
        return info["requested_downloads"][0].get("_filename")
    return info.get("_filename") or ydl.prepare_filename(info)


def fetch_random_music(search_query: str = None, offline: bool = False) -> str:
    os.makedirs(MUSIC_DIR, exist_ok=True)

    if offline:
        candidates = [os.path.join(MUSIC_DIR, f) for f in os.listdir(MUSIC_DIR) if f.endswith((".m4a", ".mp3"))]
        return random.choice(candidates) if candidates else None

    if not search_query: return None

    print(f"\n🔎 Searching Music: \"{search_query}\"")
    try:
        with yt_dlp.YoutubeDL(_make_opts(True)) as ydl:
            info = ydl.extract_info(f"ytsearch10:{search_query}", download=False)
    except:
        return None

    entries = info.get("entries", [])
    # Filter out very long mixes (> 10 mins) to save bandwidth
    valid = [e for e in entries if e and e.get("duration", 0) < 600]

    if not valid: return None
    target = random.choice(valid)

    print(f"⬇️  Downloading Music: {target.get('title')}")
    try:
        with yt_dlp.YoutubeDL(_make_opts(False)) as ydl:
            info = ydl.extract_info(target["webpage_url"], download=True)
            return _final_filepath(ydl, info)
    except Exception as e:
        print(f"❌ Music download failed: {e}")
        return None