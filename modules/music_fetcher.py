import os
import random
import re
import subprocess
import time
from typing import Optional, List, Dict, Any

import yt_dlp
from config import MUSIC_DIR

# Browser config
BROWSER = "chrome"
PROFILE = "Default"
COOKIEFILE = ""

AUDIO_EXTS = (".m4a", ".mp3", ".wav", ".aac", ".flac", ".ogg")
PLAYLIST_ITEMS_MAX = 50


def _get_yt_dlp_version():
    try:
        result = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True)
        return result.stdout.strip()
    except:
        return "unknown"


def _make_opts(skip_download: bool, extract_flat=False):
    """Options with cookies for searching only"""
    opts = {
        "outtmpl": os.path.join(MUSIC_DIR, "%(id)s.%(ext)s"),
        "quiet": False,
        "skip_download": skip_download,
        "playlistend": 15,
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "restrictfilenames": True,
        "noplaylist": True,
        "overwrites": True,
        "nopart": True,
        "extract_flat": extract_flat,
        "sleep_interval": 2,
        "max_sleep_interval": 4,
        "sleep_interval_requests": 1,
    }
    if COOKIEFILE and os.path.exists(COOKIEFILE):
        opts["cookiefile"] = COOKIEFILE
    else:
        opts["cookiesfrombrowser"] = (BROWSER, PROFILE)
    return opts


def _make_opts_no_cookies(skip_download: bool):
    """Download without cookies — most stable method"""
    return {
        "outtmpl": os.path.join(MUSIC_DIR, "%(id)s.%(ext)s"),
        "quiet": False,
        "skip_download": skip_download,
        "playlistend": 5,
        "format": "bestaudio/best",
        "restrictfilenames": True,
        "noplaylist": True,
        "overwrites": True,
        "nopart": True,
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
        "sleep_interval": 2,
        "max_sleep_interval": 4,
    }


def _make_opts_android(skip_download: bool):
    """Android fallback"""
    opts = {
        "outtmpl": os.path.join(MUSIC_DIR, "%(id)s.%(ext)s"),
        "quiet": False,
        "skip_download": skip_download,
        "playlistend": 5,
        "format": "bestaudio/best",
        "restrictfilenames": True,
        "noplaylist": True,
        "overwrites": True,
        "nopart": True,
        "extractor_args": {"youtube": {"player_client": ["android"]}},
        "sleep_interval": 2,
        "max_sleep_interval": 4,
    }
    return opts


def _trim_audio_after_download(input_path: str, max_duration: int = 300) -> str:
    """Trim audio to max_duration seconds using ffmpeg"""
    if not os.path.exists(input_path):
        return input_path

    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", input_path],
            capture_output=True, text=True, timeout=30
        )
        duration = float(result.stdout.strip())
        if duration <= max_duration:
            return input_path
    except:
        return input_path

    base, ext = os.path.splitext(input_path)
    trimmed = f"{base}_trimmed{ext}"
    try:
        subprocess.run(["ffmpeg", "-y", "-i", input_path, "-t", str(max_duration), "-c", "copy", trimmed],
                       capture_output=True, timeout=120, check=True)
        if os.path.exists(trimmed) and os.path.getsize(trimmed) > 0:
            os.remove(input_path)
            os.rename(trimmed, input_path)
    except:
        pass
    return input_path


def _final_filepath(ydl: yt_dlp.YoutubeDL, info: dict) -> str:
    vid_id = info.get("id", "unknown")
    try:
        path = ydl.prepare_filename(info)
        if os.path.exists(path):
            return path
    except:
        pass
    for ext in AUDIO_EXTS:
        candidate = os.path.join(MUSIC_DIR, f"{vid_id}{ext}")
        if os.path.exists(candidate):
            return candidate
    for f in os.listdir(MUSIC_DIR):
        if vid_id in f and f.lower().endswith(AUDIO_EXTS):
            return os.path.join(MUSIC_DIR, f)
    return os.path.join(MUSIC_DIR, f"{vid_id}.m4a")


def _safe_title(t: str) -> str:
    t = re.sub(r'[\\/*?:"<>|]', " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:200] or "untitled"


def _pick_existing_music() -> Optional[str]:
    os.makedirs(MUSIC_DIR, exist_ok=True)
    candidates = [os.path.join(MUSIC_DIR, f)
                  for f in os.listdir(MUSIC_DIR)
                  if f.lower().endswith(AUDIO_EXTS) and os.path.getsize(os.path.join(MUSIC_DIR, f)) > 10000]
    return random.choice(candidates) if candidates else None


def _score_entry(e: dict) -> int:
    title = (e.get("title") or "").lower()
    dur = e.get("duration", 0)
    score = 0
    for kw in ("instrumental", "ost", "soundtrack", "ambient"):
        if kw in title: score += 5
    for kw in ("extended", "loop", "long version"):
        if kw in title: score += 3
    for bad_kw in ("lyrics", "vocal", "shorts", "#shorts"):
        if bad_kw in title: score -= 10
    if 90 <= dur <= 1200:
        score += 2
    elif dur < 45 or dur > 3600:
        score -= 2
    return score


def _download_track(url: str, vid_id: str) -> Optional[str]:
    filepath = None
    # Method 1: No cookies
    try:
        opts = _make_opts_no_cookies(skip_download=False)
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filepath = _final_filepath(ydl, info)
            if os.path.exists(filepath) and os.path.getsize(filepath) > 5000:
                return filepath
    except:
        pass

    # Method 2: Android fallback
    try:
        opts = _make_opts_android(skip_download=False)
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filepath = _final_filepath(ydl, info)
            if os.path.exists(filepath) and os.path.getsize(filepath) > 5000:
                return filepath
    except:
        pass

    # Method 3: CLI fallback
    try:
        output_path = os.path.join(MUSIC_DIR, f"{vid_id}.m4a")
        subprocess.run(["yt-dlp", "--no-warnings", "--format", "bestaudio/best",
                        "--output", output_path, "--no-playlist", url],
                       capture_output=True, text=True, timeout=300)
        if os.path.exists(output_path) and os.path.getsize(output_path) > 5000:
            return output_path
    except:
        pass
    return None


def fetch_music_by_search(queries: List[str], max_tracks: int = 1) -> List[str]:
    os.makedirs(MUSIC_DIR, exist_ok=True)
    used_ids = set()
    results = []

    for attempt, query in enumerate(queries, 1):
        print(f"\n🎵 [Attempt {attempt}/{len(queries)}] Searching: \"{query}\"")
        try:
            with yt_dlp.YoutubeDL(_make_opts(skip_download=True, extract_flat=True)) as ydl:
                info = ydl.extract_info(f"ytsearch{max_tracks*5}:{query}", download=False)
        except Exception as e:
            print(f"❌ Search failed: {e}")
            continue

        entries = info.get("entries", []) or []
        # Filter duplicates and bad durations
        valid_entries = [e for e in entries if e.get("id") not in used_ids and e.get("duration", 0) >= 30]
        valid_entries.sort(key=_score_entry, reverse=True)
        for e in valid_entries[:max_tracks]:
            vid_id = e.get("id")
            url = e.get("webpage_url") or e.get("url")
            used_ids.add(vid_id)
            print(f"⬇️  Downloading: {e.get('title', 'untitled')}")
            path = _download_track(url, vid_id)
            if path:
                path = _trim_audio_after_download(path)
                results.append(path)
        if results:
            break

    # Fallback to existing music
    if not results:
        existing = _pick_existing_music()
        if existing:
            print(f"📁 Using existing music: {existing}")
            results.append(existing)

    return results


# =======================
# TEST
# =======================
if __name__ == "__main__":
    test_queries = [
        "Jujutsu Kaisen soundtrack battle theme OST"
    ]
    print("\n" + "="*60)
    print("   MUSIC FETCHER TEST")
    print("="*60)
    print(f"\n📌 yt-dlp version: {_get_yt_dlp_version()}")
    print(f"📂 MUSIC_DIR: {MUSIC_DIR}")

    tracks = fetch_music_by_search(test_queries, max_tracks=1)
    for i, t in enumerate(tracks, 1):
        if os.path.exists(t):
            size_mb = os.path.getsize(t)/(1024*1024)
            print(f"\n✅ Track {i}: {os.path.basename(t)} ({size_mb:.2f} MB)")
    print("\n" + "="*60)
