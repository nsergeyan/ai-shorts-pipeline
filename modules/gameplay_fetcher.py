import os
import random
import re
import yt_dlp
from config import GAMEPLAY_DIR, VIDEO_LENGTH_SEC

# Settings to avoid YouTube blocking
BROWSER = "chrome"
PROFILE = "Default"
COOKIEFILE = ""


def _make_opts(skip_download: bool):
    opts = {
        "outtmpl": os.path.join(GAMEPLAY_DIR, "%(id)s - %(title).200B.%(ext)s"),
        "quiet": False,
        "no_warnings": True,
        "skip_download": skip_download,
        "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best",
        "merge_output_format": "mp4",
        "restrictfilenames": True,

        # --- ROBUSTNESS SETTINGS ---
        "socket_timeout": 30,
        "retries": 10,
        "fragment_retries": 10,
        "ignoreerrors": True,
        "extractor_args": {"youtube": {"player_client": ["ios", "web"]}},
    }

    # Only cut video if specific length requested (and not 0)
    if not skip_download and isinstance(VIDEO_LENGTH_SEC, (int, float)) and VIDEO_LENGTH_SEC > 0:
        opts["download_sections"] = {"*": [{"start_time": 0, "end_time": int(VIDEO_LENGTH_SEC)}]}
        opts["force_keyframes_at_cuts"] = True

    if COOKIEFILE and os.path.exists(COOKIEFILE):
        opts["cookiefile"] = COOKIEFILE
    else:
        try:
            opts["cookiesfrombrowser"] = (BROWSER, PROFILE)
        except:
            pass

    return opts


def _final_filepath(ydl: yt_dlp.YoutubeDL, info: dict) -> str:
    if info.get("requested_downloads"):
        rd = info["requested_downloads"][0]
        path = rd.get("_filename") or ydl.prepare_filename(info)
    else:
        path = info.get("_filename") or ydl.prepare_filename(info)

    base, ext = os.path.splitext(path)
    if ext.lower() != ".mp4": return base + ".mp4"
    return path


def _safe_title(t: str) -> str:
    t = re.sub(r'[\\/*?:"<>|]', " ", t)
    return re.sub(r"\s+", " ", t).strip()[:200]


def pick_existing_gameplay_multi(limit=3) -> list[str]:
    os.makedirs(GAMEPLAY_DIR, exist_ok=True)
    candidates = [os.path.join(GAMEPLAY_DIR, f) for f in os.listdir(GAMEPLAY_DIR) if f.endswith(".mp4")]
    if not candidates: return []
    return random.sample(candidates, min(limit, len(candidates)))


def fetch_gameplay_by_search(search_query: str, max_videos: int = 1) -> list[str]:
    os.makedirs(GAMEPLAY_DIR, exist_ok=True)
    print(f"\n🔎 Searching YouTube for: \"{search_query}\"")

    try:
        with yt_dlp.YoutubeDL(_make_opts(skip_download=True)) as ydl:
            info = ydl.extract_info(f"ytsearch15:{search_query}", download=False)
    except Exception as e:
        print(f"❌ Search failed: {e}")
        return []

    entries = info.get("entries", []) or []
    valid_entries = [e for e in entries if e and e.get("duration", 0) > 60]

    if not valid_entries:
        print("⚠️  No valid videos found.")
        return []

    print(f"🧾 Found {len(valid_entries)} candidates. Downloading {max_videos}...")
    random.shuffle(valid_entries)

    downloaded_paths = []
    with yt_dlp.YoutubeDL(_make_opts(skip_download=False)) as ydl:
        for entry in valid_entries:
            if len(downloaded_paths) >= max_videos: break
            title = _safe_title(entry.get("title", "untitled"))
            print(f"⬇️  Attempting download: {title}")
            try:
                info = ydl.extract_info(entry.get("webpage_url"), download=True)
                filepath = _final_filepath(ydl, info)
                if os.path.exists(filepath) and os.path.getsize(filepath) > 1000:
                    downloaded_paths.append(filepath)
            except Exception as e:
                print(f"❌ Failed, skipping: {e}")
                continue

    return downloaded_paths