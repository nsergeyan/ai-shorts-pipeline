# modules/music_fetcher.py
import os
import random
import re
from typing import Optional

import yt_dlp
from config import MUSIC_DIR

# You can reuse the same browser/cookies strategy as gameplay
BROWSER = "chrome"
PROFILE = "Default"
COOKIEFILE = ""  # leave empty if you are not using a cookies.txt file


def _make_opts(skip_download: bool):
    """
    yt-dlp options tuned for AUDIO (background music).
    """
    opts = {
        "outtmpl": os.path.join(MUSIC_DIR, "%(id)s - %(title).200B.%(ext)s"),
        "quiet": False,
        "skip_download": skip_download,
        "playlistend": 15,
        # AUDIO ONLY: bestaudio, prefer m4a
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "merge_output_format": "m4a",
        "sleep_interval_requests": 1.0,
        "max_sleep_interval_requests": 2.5,
        "extractor_args": {"youtube": {"player_client": ["default"]}},
        "restrictfilenames": True,
    }

    # Cookies: always Chrome / Default (same as gameplay)
    if COOKIEFILE and os.path.exists(COOKIEFILE):
        opts["cookiefile"] = COOKIEFILE
        print(f"Using cookies from file: {COOKIEFILE}")
    else:
        opts["cookiesfrombrowser"] = (BROWSER, PROFILE)
        print(f"Using cookies from browser: {BROWSER} (profile: {PROFILE})")

    return opts


def _final_filepath(ydl: yt_dlp.YoutubeDL, info: dict) -> str:
    """
    Return the final downloaded file path.
    """
    if info.get("requested_downloads"):
        rd = info["requested_downloads"][0]
        path = rd.get("_filename") or ydl.prepare_filename(info)
    else:
        path = info.get("_filename") or ydl.prepare_filename(info)
    return path


def _safe_title(t: str) -> str:
    t = re.sub(r'[\\/*?:"<>|]', " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:200]


def _pick_existing_music() -> Optional[str]:
    """
    Pick one random local music file (for offline or reuse).
    """
    os.makedirs(MUSIC_DIR, exist_ok=True)
    candidates = [
        os.path.join(MUSIC_DIR, f)
        for f in os.listdir(MUSIC_DIR)
        if f.lower().endswith((".m4a", ".mp3", ".wav", ".mp4", ".webm"))
    ]
    if candidates:
        choice = random.choice(candidates)
        print(f"🎵 Using existing music: {choice}")
        return choice
    return None


def pick_existing_music_multi(limit: int = 5) -> list[str]:
    """
    Picks up to `limit` random music files from the local folder.
    """
    os.makedirs(MUSIC_DIR, exist_ok=True)
    candidates = [
        os.path.join(MUSIC_DIR, f)
        for f in os.listdir(MUSIC_DIR)
        if f.lower().endswith((".m4a", ".mp3", ".wav", ".mp4", ".webm"))
    ]
    if not candidates:
        print("⚠️  No local music found.")
        return []
    random.shuffle(candidates)
    selected = candidates[:limit]
    print(f"🎵 Using random offline music:\n   " + "\n   ".join(selected))
    return selected


def fetch_music_by_search(search_query: str, max_tracks: int = 1) -> list[str]:
    """
    Search YouTube for background music using yt-dlp's ytsearch.
    Downloads up to `max_tracks` audio files and returns their paths.
    Will keep tracks that downloaded successfully even if some fail.
    """
    os.makedirs(MUSIC_DIR, exist_ok=True)

    print(f"\n🔎 Searching YouTube for music: \"{search_query}\"")
    try:
        with yt_dlp.YoutubeDL(_make_opts(skip_download=True)) as ydl:
            info = ydl.extract_info(f"ytsearch{max_tracks}:{search_query}", download=False)
    except yt_dlp.utils.DownloadError as e:
        print(f"❌ Failed to search YouTube for music: {e}")
        return []

    entries = info.get("entries", []) or []
    if not entries:
        print("⚠️  No music results found for that search query.")
        return []

    entries = entries[:max_tracks]
    print(f"🧾 Found {len(entries)} music result(s); downloading up to {max_tracks}…")

    paths: list[str] = []

    # Do NOT discard previously downloaded tracks if one fails.
    try:
        with yt_dlp.YoutubeDL(_make_opts(skip_download=False)) as ydl:
            for e in entries:
                title = _safe_title(e.get("title", "untitled"))
                url = e.get("webpage_url")
                if not url:
                    continue

                print(f"⬇️  Downloading music: {title}")
                try:
                    info = ydl.extract_info(url, download=True)
                except yt_dlp.utils.DownloadError as de:
                    print(f"❌ Failed to download '{title}': {de}; skipping this track.")
                    continue

                filepath = _final_filepath(ydl, info)
                paths.append(filepath)
    except yt_dlp.utils.DownloadError as e:
        # This would be a more global/fatal error (e.g. cookies, network, etc.)
        print(f"❌ Download session error while downloading music: {e}")

    if not paths:
        print("⚠️  No music files were downloaded successfully.")
        return []

    print(f"\n✅ Downloaded {len(paths)} music file(s).")
    return paths


def fetch_random_music(
    *,
    search_query: Optional[str] = None,
    offline: bool = False,
    reuse_path: Optional[str] = None,
) -> Optional[str]:
    """
    Choose one music track:
    - reuse_path (if given and exists) → use that
    - offline=True → pick existing local audio file
    - search_query → download from YouTube
    """
    if reuse_path:
        if os.path.exists(reuse_path):
            print(f"🎵 Reusing provided music: {reuse_path}")
            return reuse_path
        print(f"⚠️ Provided reuse path not found: {reuse_path}")

    if offline:
        chosen = _pick_existing_music()
        if chosen:
            return chosen
        print("⚠️  No local music found; offline mode cannot download.")
        return None

    if search_query:
        tracks = fetch_music_by_search(search_query, max_tracks=1)
        if tracks:
            chosen = random.choice(tracks)
            print(f"🎯 Selected music from search: {chosen}")
            return chosen

    print("⚠️  No music could be selected.")
    return None