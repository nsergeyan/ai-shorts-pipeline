import os
import random
import re
from typing import Optional

import yt_dlp
from config import GAMEPLAY_DIR

# Browser cookies
BROWSER = "chrome"
PROFILE = "Default"
COOKIEFILE = ""


def _make_opts(skip_download: bool, download_start_end: Optional[str] = None):
    opts = {
        "outtmpl": os.path.join(GAMEPLAY_DIR, "%(id)s - %(title).200B.%(ext)s"),
        "quiet": False,
        "skip_download": skip_download,
        "playlistend": 1,
        # We use 'best' to avoid complex merging that might break the time limit
        "format": "best[ext=mp4]/best",
        "restrictfilenames": True,
    }

    # ✅ THE FIX: Force FFmpeg to control the download time
    # This creates a "hard cut" after 5 minutes so you don't download 700MB
    if download_start_end and not skip_download:
        opts["external_downloader"] = "ffmpeg"
        opts["external_downloader_args"] = {
            # -ss 00:00:00 = Start at 0
            # -t 00:05:00  = Stop exactly after 5 minutes
            "ffmpeg_i": ["-ss", "00:00:00", "-t", "00:05:00"]
        }

    if COOKIEFILE and os.path.exists(COOKIEFILE):
        opts["cookiefile"] = COOKIEFILE
    else:
        opts["cookiesfrombrowser"] = (BROWSER, PROFILE)

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
    candidates = [f for f in os.listdir(GAMEPLAY_DIR) if f.lower().endswith(".mp4")]
    if candidates:
        return os.path.join(GAMEPLAY_DIR, random.choice(candidates))
    return None


def fetch_gameplay_by_search(search_query: str, max_videos: int = 1) -> list[str]:
    """
    Search YouTube and download ONLY the first 5 minutes of the result.
    """
    os.makedirs(GAMEPLAY_DIR, exist_ok=True)
    print(f"\n🔎 Searching YouTube for: \"{search_query}\"")

    # 1. Search metadata
    try:
        with yt_dlp.YoutubeDL(_make_opts(skip_download=True)) as ydl:
            info = ydl.extract_info(f"ytsearch{max_videos}:{search_query}", download=False)
    except Exception as e:
        print(f"❌ Search failed: {e}")
        return []

    entries = info.get("entries", []) or []
    paths = []

    # 2. Download (Hard limited to 5 mins via FFmpeg)
    # We pass "00:00-05:00" to trigger the external_downloader logic above
    try:
        with yt_dlp.YoutubeDL(_make_opts(skip_download=False, download_start_end="00:00-05:00")) as ydl:
            for e in entries:
                title = _safe_title(e.get("title", "untitled"))
                print(f"⬇️  Downloading (Hard limit: 5 mins): {title}")

                info = ydl.extract_info(e["webpage_url"], download=True)
                filepath = _final_filepath(ydl, info)

                if os.path.exists(filepath):
                    paths.append(filepath)
                else:
                    # Sometimes ffmpeg output naming differs, check directory
                    print("⚠️ Filepath check failed, checking directory...")
                    latest = max([os.path.join(GAMEPLAY_DIR, f) for f in os.listdir(GAMEPLAY_DIR)],
                                 key=os.path.getctime)
                    paths.append(latest)

    except Exception as e:
        print(f"❌ Download error: {e}")

    return paths


def fetch_gameplay_by_channel(channel_url: str, keyword: str, max_videos: int = 1) -> list[str]:
    os.makedirs(GAMEPLAY_DIR, exist_ok=True)
    try:
        with yt_dlp.YoutubeDL(_make_opts(skip_download=True)) as ydl:
            print(f"\n🔍 Searching channel: {channel_url}")
            info = ydl.extract_info(f"{channel_url}/videos", download=False)
    except Exception as e:
        print(f"❌ Channel search failed: {e}")
        return []

    entries = info.get("entries", []) or []
    matching = [e for e in entries if e and e.get("title") and keyword.lower() in e["title"].lower()][:max_videos]

    paths = []
    try:
        with yt_dlp.YoutubeDL(_make_opts(skip_download=False, download_start_end="00:00-05:00")) as ydl:
            for v in matching:
                title = _safe_title(v["title"])
                print(f"⬇️  Downloading (5 min limit): {title}")
                info = ydl.extract_info(v["webpage_url"], download=True)
                paths.append(_final_filepath(ydl, info))
    except Exception as e:
        print(f"❌ Download error: {e}")
    return paths


def pick_existing_gameplay_multi(limit=3) -> list[str]:
    os.makedirs(GAMEPLAY_DIR, exist_ok=True)
    candidates = [os.path.join(GAMEPLAY_DIR, f) for f in os.listdir(GAMEPLAY_DIR) if f.lower().endswith(".mp4")]
    if not candidates: return []
    random.shuffle(candidates)
    return candidates[:limit]


def fetch_random_gameplay(**kwargs):
    if kwargs.get("reuse_path") and os.path.exists(kwargs["reuse_path"]):
        return kwargs["reuse_path"]
    if kwargs.get("offline"):
        return _pick_existing_gameplay() or "placeholder.mp4"
    if kwargs.get("search_query"):
        res = fetch_gameplay_by_search(kwargs["search_query"])
        return res[0] if res else "placeholder.mp4"
    return "placeholder.mp4"