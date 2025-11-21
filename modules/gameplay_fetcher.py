# modules/gameplay_fetcher.py
import os
import random
import re
import yt_dlp
from typing import Optional
from config import GAMEPLAY_DIR, VIDEO_LENGTH_SEC

# Cookies (still available via env if you want live mode)
BROWSER = os.getenv("YT_COOKIES_BROWSER", "chrome")
PROFILE = os.getenv("YT_COOKIES_PROFILE", "").strip()
COOKIEFILE = os.getenv("YT_COOKIES_FILE", "").strip()

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
        "extractor_args": {"youtube": {"player_client": ["default"]}},  # cookies supported
        "restrictfilenames": True,
        "download_archive": ARCHIVE_PATH,
        "nooverwrites": True,
        "continuedl": True,
    }
    if isinstance(VIDEO_LENGTH_SEC, (int, float)) and VIDEO_LENGTH_SEC > 0:
        opts["download_sections"] = {"*": [{"start_time": 0, "end_time": int(VIDEO_LENGTH_SEC)}]}
        opts["force_keyframes_at_cuts"] = True

    # Cookies
    if COOKIEFILE and os.path.exists(COOKIEFILE):
        opts["cookiefile"] = COOKIEFILE
        print(f"Using cookies from file: {COOKIEFILE}")
    elif BROWSER and BROWSER.lower() != "none":
        if PROFILE:
            opts["cookiesfrombrowser"] = (BROWSER, PROFILE)
            print(f"Using cookies from browser: {BROWSER} (profile: {PROFILE})")
        else:
            opts["cookiesfrombrowser"] = (BROWSER,)
            print(f"Using cookies from browser: {BROWSER}")

    return opts


def _final_filepath(ydl: yt_dlp.YoutubeDL, info: dict) -> str:
    # Get exact saved path
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


def fetch_gameplay_by_channel(channel_url: str,
                              keyword: str,
                              max_videos: int = 1,
                              *,
                              offline: bool = False,
                              reuse_path: Optional[str] = None):
    """
    - offline=True -> do not download; reuse an existing local .mp4 if available
    - reuse_path points to a specific local .mp4 to use
    Returns list of 0..N file paths.
    """
    # Explicit reuse path wins
    if reuse_path:
        if os.path.exists(reuse_path):
            print(f"📼 Reusing provided video: {reuse_path}")
            return [reuse_path]
        print(f"⚠️ Provided reuse path not found: {reuse_path}")

    if offline:
        chosen = _pick_existing_gameplay()
        if chosen:
            return [chosen]
        print("⚠️ No local .mp4 found; offline mode cannot download.")
        return []

    # Live mode (download)
    os.makedirs(GAMEPLAY_DIR, exist_ok=True)

    # List metadata only
    try:
        with yt_dlp.YoutubeDL(_make_opts(skip_download=True)) as ydl:
            print(f"\n🔍 Searching channel: {channel_url}")
            info = ydl.extract_info(f"{channel_url}/videos", download=False)
    except yt_dlp.utils.DownloadError as e:
        print(f"❌ Failed to list channel videos: {e}")
        print("Tip: set cookies (YT_COOKIES_BROWSER/PROFILE or YT_COOKIES_FILE).")
        return []

    entries = info.get("entries", []) or []
    print(f"🧾 Found {len(entries)} recent uploads, filtering by keyword '{keyword}'...")

    matching = [e for e in entries if e and e.get("title") and keyword.lower() in e["title"].lower()]
    if not matching:
        print("⚠️  No matching gameplay videos found.")
        return []

    matching = matching[:max_videos]
    print(f"🎯 Preparing to download {len(matching)} video(s).")

    # Download and capture exact filepath
    paths = []
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
        print("Tip: If you see a bot check, ensure cookies are passed correctly.")
        return []

    print(f"\n✅ Downloaded {len(paths)} gameplay video(s).")
    return paths


def fetch_random_gameplay(channel_url=None,
                          keyword=None,
                          *,
                          offline: bool = False,
                          reuse_path: Optional[str] = None):
    """
    One clip:
    - reuse_path (if given) → use that
    - offline=True → pick existing local .mp4
    - else download from channel/keyword
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

    if channel_url and keyword:
        videos = fetch_gameplay_by_channel(channel_url, keyword, max_videos=1, offline=False)
        if videos:
            chosen = random.choice(videos)
            print(f"🎲 Selected random clip: {chosen}")
            return chosen

    # Fallback
    placeholder = os.path.join(GAMEPLAY_DIR, "placeholder_gameplay.mp4")
    print(f"⚠️  Using placeholder: {placeholder}")
    return placeholder