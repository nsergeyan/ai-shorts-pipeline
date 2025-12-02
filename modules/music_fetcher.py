# modules/music_fetcher.py
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
    - download_start_end: e.g., "0:00-5:00" to download only that segment (requires yt-dlp >= 2023.07.06)
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
        "extractor_args": {"youtube": {"player_client": ["default"]}},
        "restrictfilenames": True,
        "noplaylist": noplaylist,
    }

    # Download only a section (e.g., first 5 minutes)
    if download_start_end and not skip_download:
        opts["download_sections"] = download_start_end  # e.g., "0:00-5:00"

    if extract_flat:
        opts["extract_flat"] = True

    # Cookies
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
    except yt_dlp.utils.DownloadError as e:
        print(f"⚠️ Failed to expand playlist: {e}")
        return []
    entries = (info or {}).get("entries") or []
    videos = []
    for e in entries:
        if isinstance(e, dict) and (e.get("_type") in (None, "url") or e.get("id")):
            # normalize minimal fields
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
    """Prefer instrumental/no-lyrics, reasonable length. Strongly penalize bad content types."""
    title = (e.get("title") or "").lower()
    dur = e.get("duration")
    s = 0

    # BIG BONUS for good music keywords
    good_keywords = ("instrumental", "ost", "soundtrack", "background", "ambient", "atmospheric")
    for keyword in good_keywords:
        if keyword in title:
            s += 5

    # Medium bonus for extended/playable versions
    medium_keywords = ("extended", "loop", "10 min", "10min", "long version")
    for keyword in medium_keywords:
        if keyword in title:
            s += 3

    # Small bonus for potentially usable stuff
    if "no lyrics" in title or "without lyrics" in title:
        s += 2

    # STRONG PENALTIES for bad types (karaoke, covers, etc.)
    bad_keywords = (
        "sing along", "nightcore", "8d audio", "slowed",
        "reverb", "cover", "lyrics", "vocal", "singing", "acoustic",
        "shorts", "#shorts", "tutorial", "how to"
    )
    for bad_keyword in bad_keywords:
        if bad_keyword in title:
            s -= 10  # Strong penalty

    # Duration scoring
    if isinstance(dur, (int, float)):
        if 90 <= dur <= 1200:  # 1.5min to 20min - ideal
            s += 3
        elif dur < 45 or dur > 3600:  # Too short or too long
            s -= 2

    return s


def fetch_music_by_search(search_query: str, max_tracks: int = 1) -> List[str]:
    """
    Search YouTube for background music. If a result is a PLAYLIST,
    expand it and pick a random item from within (instead of downloading the whole playlist).
    """
    os.makedirs(MUSIC_DIR, exist_ok=True)

    print(f"\n🔎 Searching YouTube for music: \"{search_query}\"")
    search_count = max(10, max_tracks * 10)
    try:
        with yt_dlp.YoutubeDL(_make_opts(skip_download=True, extract_flat=True)) as ydl:
            info = ydl.extract_info(f"ytsearch{search_count}:{search_query}", download=False)
    except yt_dlp.utils.DownloadError as e:
        print(f"❌ Failed to search YouTube for music: {e}")
        return []

    entries = (info or {}).get("entries") or []
    if not entries:
        print("⚠️  No music results found for that search query.")
        return []

    # Flatten: videos as-is; playlists expanded to their video entries
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

    # Filter invalid
    video_candidates = [v for v in video_candidates if v.get("webpage_url") and v.get("id")]
    if not video_candidates:
        print("⚠️  No playable items found (after expanding playlists).")
        return []

    # Rank and pick randomly from top pool for variety
    ranked = sorted(video_candidates, key=_score_entry, reverse=True)

    # Filter out heavily penalized items (score < 0)
    filtered_ranked = [item for item in ranked if _score_entry(item) >= 0]
    if not filtered_ranked:
        print("⚠️  All music candidates were filtered out due to low quality scores.")
        return []

    pool = filtered_ranked[: min(12, len(filtered_ranked))]
    random.shuffle(pool)
    chosen_items = pool[: max_tracks]

    print(f"🧾 Picked {len(chosen_items)} item(s) to download from search/playlist.")

    # Download each chosen as a SINGLE item (noplaylist=True)
    paths: List[str] = []
    try:
        ydl_opts = _make_opts(skip_download=False, noplaylist=True, extract_flat=False, download_start_end="0:00-5:00")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            for v in chosen_items:
                url = v["webpage_url"]
                title = _safe_title(v.get("title") or "untitled")
                print(f"⬇️  Downloading music: {title}")
                try:
                    info = ydl.extract_info(url, download=True)
                except yt_dlp.utils.DownloadError as de:
                    print(f"❌ Failed to download '{title}': {de}; skipping.")
                    continue
                filepath = _final_filepath(ydl, info)
                paths.append(filepath)
    except yt_dlp.utils.DownloadError as e:
        print(f"❌ Download session error: {e}")

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
    - reuse_path (if exists) → use that
    - offline=True → pick existing local audio file
    - search_query → search and download (expands playlists, picks a random item)
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