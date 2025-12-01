import os
import random
import re
from typing import Optional

import yt_dlp
from config import GAMEPLAY_DIR, VIDEO_LENGTH_SEC

# HARD-CODED cookies source: Chrome, "Default" profile
BROWSER = "chrome"
PROFILE = "Default"
COOKIEFILE = ""  # leave empty if you are not using a cookies.txt file

ARCHIVE_PATH = os.path.join(GAMEPLAY_DIR, ".yt-archive.txt")


def _make_opts(skip_download: bool):
    opts = {
        "outtmpl": os.path.join(GAMEPLAY_DIR, "%(id)s - %(title).200B.%(ext)s"),
        "quiet": False,
        "skip_download": skip_download,
        "playlistend": 15,
        "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best",
        "merge_output_format": "mp4",
        "sleep_interval_requests": 1.0,
        "max_sleep_interval_requests": 2.5,
        "extractor_args": {"youtube": {"player_client": ["default"]}},
        "restrictfilenames": True,
    }
    if isinstance(VIDEO_LENGTH_SEC, (int, float)) and VIDEO_LENGTH_SEC > 0:
        opts["download_sections"] = {"*": [{"start_time": 0, "end_time": int(VIDEO_LENGTH_SEC)}]}
        opts["force_keyframes_at_cuts"] = True

    # Cookies: always Chrome / Default
    if COOKIEFILE and os.path.exists(COOKIEFILE):
        opts["cookiefile"] = COOKIEFILE
        print(f"Using cookies from file: {COOKIEFILE}")
    else:
        opts["cookiesfrombrowser"] = (BROWSER, PROFILE)
        print(f"Using cookies from browser: {BROWSER} (profile: {PROFILE})")

    return opts


def _final_filepath(ydl: yt_dlp.YoutubeDL, info: dict) -> str:
    if info.get("requested_downloads"):
        rd = info["requested_downloads"][0]
        path = rd.get("_filename") or ydl.prepare_filename(info)
    else:
        path = info.get("_filename") or ydl.prepare_filename(info)
    base, ext = os.path.splitext(path)
    if ext.lower() != ".mp4":
        path = base + ".mp4"
    return path


def _safe_title(t: str) -> str:
    t = re.sub(r'[\\/*?:"<>|]', " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:200]


def _pick_existing_gameplay() -> Optional[str]:
    os.makedirs(GAMEPLAY_DIR, exist_ok=True)
    candidates = [
        os.path.join(GAMEPLAY_DIR, f)
        for f in os.listdir(GAMEPLAY_DIR)
        if f.lower().endswith(".mp4")
    ]
    if candidates:
        choice = random.choice(candidates)
        print(f"📼 Using existing gameplay: {choice}")
        return choice
    return None


def fetch_gameplay_by_search(search_query: str, max_videos: int = 1) -> list[str]:
    """
    Search all of YouTube for `search_query` using yt-dlp's ytsearch.
    Returns list of downloaded file paths.
    """
    os.makedirs(GAMEPLAY_DIR, exist_ok=True)

    print(f"\n🔎 Searching YouTube for: \"{search_query}\"")
    try:
        with yt_dlp.YoutubeDL(_make_opts(skip_download=True)) as ydl:
            info = ydl.extract_info(f"ytsearch{max_videos}:{search_query}", download=False)
    except yt_dlp.utils.DownloadError as e:
        print(f"❌ Failed to search YouTube: {e}")
        return []

    entries = info.get("entries", []) or []
    if not entries:
        print("⚠️  No results found for that search query.")
        return []

    entries = entries[:max_videos]
    print(f"🧾 Found {len(entries)} result(s); downloading up to {max_videos}…")

    paths: list[str] = []
    try:
        with yt_dlp.YoutubeDL(_make_opts(skip_download=False)) as ydl:
            for e in entries:
                title = _safe_title(e.get("title", "untitled"))
                url = e.get("webpage_url")
                if not url:
                    continue
                print(f"⬇️  Downloading from search result: {title}")
                info = ydl.extract_info(url, download=True)
                filepath = _final_filepath(ydl, info)
                paths.append(filepath)
    except yt_dlp.utils.DownloadError as e:
        print(f"❌ Download error while downloading search result(s): {e}")
        return []

    print(f"\n✅ Downloaded {len(paths)} video(s) from search.")
    return paths


def fetch_gameplay_by_channel(
    channel_url: str,
    keyword: str,
    max_videos: int = 1,
) -> list[str]:
    """
    Search a specific channel's uploads by keyword in the title.
    """
    os.makedirs(GAMEPLAY_DIR, exist_ok=True)

    try:
        with yt_dlp.YoutubeDL(_make_opts(skip_download=True)) as ydl:
            print(f"\n🔍 Searching channel: {channel_url}")
            info = ydl.extract_info(f"{channel_url}/videos", download=False)
    except yt_dlp.utils.DownloadError as e:
        print(f"❌ Failed to list channel videos: {e}")
        return []

    entries = info.get("entries", []) or []
    print(f"🧾 Found {len(entries)} recent uploads, filtering by keyword '{keyword}'...")

    matching = [
        e for e in entries
        if e and e.get("title") and keyword.lower() in e["title"].lower()
    ]
    if not matching:
        print("⚠️  No matching videos found on that channel.")
        return []

    matching = matching[:max_videos]
    print(f"🎯 Preparing to download {len(matching)} video(s).")

    paths: list[str] = []
    try:
        with yt_dlp.YoutubeDL(_make_opts(skip_download=False)) as ydl:
            for v in matching:
                title = _safe_title(v["title"])
                print(f"⬇️  Downloading: {title}")
                info = ydl.extract_info(v["webpage_url"], download=True)
                filepath = _final_filepath(ydl, info)
                paths.append(filepath)
    except yt_dlp.utils.DownloadError as e:
        print(f"❌ Download error: {e}")
        return []

    print(f"\n✅ Downloaded {len(paths)} video(s).")
    return paths


def pick_existing_gameplay_multi(limit=3) -> list[str]:
    """
    Picks up to `limit` random gameplay videos from the local folder.
    Ensures more variety between runs.
    """
    os.makedirs(GAMEPLAY_DIR, exist_ok=True)
    candidates = [
        os.path.join(GAMEPLAY_DIR, f)
        for f in os.listdir(GAMEPLAY_DIR)
        if f.lower().endswith(".mp4")
    ]
    if not candidates:
        print("⚠️  No local gameplay found.")
        return []
    random.shuffle(candidates)
    selected = candidates[:limit]
    print(f"📼 Using random offline videos:\n   " + "\n   ".join(selected))
    return selected

def fetch_random_gameplay(
    channel_url: str = None,
    keyword: str = None,
    *,
    search_query: Optional[str] = None,
    offline: bool = False,
    reuse_path: Optional[str] = None,
) -> str:
    """
    Choose one video clip:
    - reuse_path (if given) → use that
    - offline=True → pick existing local .mp4
    - search_query → global YouTube search
    - else channel_url + keyword → channel search
    """
    if reuse_path:
        if os.path.exists(reuse_path):
            print(f"📼 Reusing provided video: {reuse_path}")
            return reuse_path
        print(f"⚠️ Provided reuse path not found: {reuse_path}")

    if offline:
        chosen = _pick_existing_gameplay()
        if chosen:
            return chosen
        print("⚠️  No local .mp4 found; offline mode cannot download.")
        return os.path.join(GAMEPLAY_DIR, "placeholder_gameplay.mp4")

    if search_query:
        videos = fetch_gameplay_by_search(search_query, max_videos=1)
        if videos:
            chosen = videos[0]
            print(f"🎯 Selected from search: {chosen}")
            return chosen

    if channel_url and keyword:
        videos = fetch_gameplay_by_channel(channel_url, keyword, max_videos=1)
        if videos:
            chosen = random.choice(videos)
            print(f"🎲 Selected from channel: {chosen}")
            return chosen

    placeholder = os.path.join(GAMEPLAY_DIR, "placeholder_gameplay.mp4")
    print(f"⚠️  Using placeholder: {placeholder}")
    return placeholder