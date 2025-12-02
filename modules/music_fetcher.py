import os
import random
import re
from typing import Optional, List, Dict, Any

import yt_dlp
from config import MUSIC_DIR

# Browser cookies (same approach as gameplay)
BROWSER = "chrome"
PROFILE = "Default"
COOKIEFILE = ""  # path to cookies.txt if you prefer; leave empty to use browser cookies

os.makedirs(MUSIC_DIR, exist_ok=True)

AUDIO_EXTS = (".m4a", ".mp3", ".wav", ".aac", ".flac", ".ogg")

# Limit how many items to read from a playlist when expanding
PLAYLIST_ITEMS_MAX = 50


def _make_opts(skip_download: bool, *, noplaylist: bool = False, extract_flat: bool = False,
               download_start_end: Optional[str] = None):
    """
    Build yt-dlp options tuned for audio.
    """
    opts = {
        "outtmpl": os.path.join(MUSIC_DIR, "%(id)s - %(title).200B.%(ext)s"),
        "quiet": False,
        "skip_download": skip_download,
        "playlistend": 15,
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "merge_output_format": "m4a",
        "sleep_interval_requests": 1.0,
        "max_sleep_interval_requests": 2.5,
        "restrictfilenames": True,
        "noplaylist": noplaylist,
    }

    # ✅ THE FIX: Force FFmpeg to control the download time (Same as Gameplay)
    if download_start_end and not skip_download:
        opts["external_downloader"] = "ffmpeg"
        opts["external_downloader_args"] = {
            # Start at 0, Stop exactly after 5 minutes (300 seconds)
            "ffmpeg_i": ["-ss", "00:00:00", "-t", "00:05:00"]
        }

    if extract_flat:
        opts["extract_flat"] = True

    # Cookies
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
    return path


def _safe_title(t: str) -> str:
    t = re.sub(r'[\\/*?:"<>|]', " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:200] or "untitled"


def _pick_existing_music() -> Optional[str]:
    candidates = [
        os.path.join(MUSIC_DIR, f)
        for f in os.listdir(MUSIC_DIR)
        if f.lower().endswith(AUDIO_EXTS)
    ]
    if candidates:
        choice = random.choice(candidates)
        print(f"🎵 Using existing music: {choice}")
        return choice
    return None


def pick_existing_music_multi(limit: int = 5) -> List[str]:
    candidates = [
        os.path.join(MUSIC_DIR, f)
        for f in os.listdir(MUSIC_DIR)
        if f.lower().endswith(AUDIO_EXTS)
    ]
    if not candidates:
        print("⚠️  No local music found.")
        return []
    random.shuffle(candidates)
    selected = candidates[:limit]
    print(f"🎵 Using random offline music:\n   " + "\n   ".join(selected))
    return selected


def _is_playlist_entry(e: Dict[str, Any]) -> bool:
    if not isinstance(e, dict):
        return False
    if e.get("_type") == "playlist":
        return True
    ie = (e.get("ie_key") or "").lower()
    if "playlist" in ie or "tab" in ie:
        return True
    url = (e.get("webpage_url") or e.get("url") or "").lower()
    return "playlist?list=" in url or "/playlist" in url


def _expand_playlist(playlist_url: str, max_items: int = PLAYLIST_ITEMS_MAX) -> List[Dict[str, Any]]:
    """
    Return a list of flat video entries from a playlist URL (no downloads).
    """
    print(f"📜 Expanding playlist: {playlist_url}")
    opts = _make_opts(skip_download=True, noplaylist=False, extract_flat=True)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(playlist_url, download=False)
    except Exception as e:
        print(f"⚠️ Failed to expand playlist: {e}")
        return []
    entries = (info or {}).get("entries") or []
    videos = []
    for e in entries:
        if isinstance(e, dict) and (e.get("_type") in (None, "url") or e.get("id")):
            videos.append({
                "id": e.get("id"),
                "title": e.get("title"),
                "webpage_url": e.get("webpage_url") or e.get("url"),
                "duration": e.get("duration"),
            })
        if len(videos) >= max_items:
            break
    return videos


def _score_entry(e: Dict[str, Any]) -> int:
    """Prefer instrumental/no-lyrics, reasonable length."""
    title = (e.get("title") or "").lower()
    dur = e.get("duration")
    s = 0

    good_keywords = ("instrumental", "ost", "soundtrack", "background", "ambient", "atmospheric")
    for keyword in good_keywords:
        if keyword in title:
            s += 5

    medium_keywords = ("extended", "loop", "10 min", "10min", "long version")
    for keyword in medium_keywords:
        if keyword in title:
            s += 3

    if "no lyrics" in title or "without lyrics" in title:
        s += 2

    bad_keywords = (
        "sing along", "nightcore", "8d audio", "slowed",
        "reverb", "cover", "lyrics", "vocal", "singing", "acoustic",
        "shorts", "#shorts", "tutorial", "how to"
    )
    for bad_keyword in bad_keywords:
        if bad_keyword in title:
            s -= 10

    if isinstance(dur, (int, float)):
        if 90 <= dur <= 1200:
            s += 3
        elif dur < 45 or dur > 3600:
            s -= 2

    return s


def fetch_music_by_search(search_query: str, max_tracks: int = 1) -> List[str]:
    """
    Search YouTube for music, download ONLY FIRST 5 MINS.
    """
    os.makedirs(MUSIC_DIR, exist_ok=True)

    print(f"\n🔎 Searching YouTube for music: \"{search_query}\"")
    search_count = max(10, max_tracks * 10)
    try:
        with yt_dlp.YoutubeDL(_make_opts(skip_download=True, extract_flat=True)) as ydl:
            info = ydl.extract_info(f"ytsearch{search_count}:{search_query}", download=False)
    except Exception as e:
        print(f"❌ Failed to search YouTube for music: {e}")
        return []

    entries = (info or {}).get("entries") or []
    if not entries:
        print("⚠️  No music results found.")
        return []

    video_candidates: List[Dict[str, Any]] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        if _is_playlist_entry(e):
            purl = e.get("webpage_url") or e.get("url")
            if purl:
                pl_items = _expand_playlist(purl, max_items=PLAYLIST_ITEMS_MAX)
                video_candidates.extend(pl_items)
        else:
            video_candidates.append({
                "id": e.get("id"),
                "title": e.get("title"),
                "webpage_url": e.get("webpage_url") or e.get("url"),
                "duration": e.get("duration"),
            })

    video_candidates = [v for v in video_candidates if v.get("webpage_url") and v.get("id")]
    ranked = sorted(video_candidates, key=_score_entry, reverse=True)
    filtered_ranked = [item for item in ranked if _score_entry(item) >= 0]

    if not filtered_ranked:
        # If strict filtering fails, fallback to top results
        filtered_ranked = ranked[:5]

    pool = filtered_ranked[: min(12, len(filtered_ranked))]
    random.shuffle(pool)
    chosen_items = pool[: max_tracks]

    print(f"🧾 Picked {len(chosen_items)} item(s) to download.")

    paths: List[str] = []
    try:
        # ✅ TRIGGER THE 5-MINUTE LIMIT: Pass download_start_end="0:00-5:00"
        ydl_opts = _make_opts(skip_download=False, noplaylist=True, extract_flat=False, download_start_end="0:00-5:00")

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            for v in chosen_items:
                url = v["webpage_url"]
                title = _safe_title(v.get("title") or "untitled")
                print(f"⬇️  Downloading music (Hard limit: 5 mins): {title}")
                try:
                    info = ydl.extract_info(url, download=True)
                    filepath = _final_filepath(ydl, info)

                    # Ensure file exists (ffmpeg sometimes messes with naming slightly)
                    if not os.path.exists(filepath):
                        # check if a .m4a exists with similar name
                        base = os.path.splitext(filepath)[0]
                        if os.path.exists(base + ".m4a"):
                            filepath = base + ".m4a"

                    paths.append(filepath)
                except Exception as de:
                    print(f"❌ Failed to download '{title}': {de}; skipping.")
                    continue
    except Exception as e:
        print(f"❌ Download session error: {e}")

    return paths


def fetch_random_music(
        *,
        search_query: Optional[str] = None,
        offline: bool = False,
        reuse_path: Optional[str] = None,
) -> Optional[str]:
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