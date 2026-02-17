import os
import random
import re
import subprocess
import time
from typing import Optional, List, Dict, Any

import yt_dlp
from config import MUSIC_DIR

BROWSER = "chrome"
PROFILE = "Default"
COOKIEFILE = ""

os.makedirs(MUSIC_DIR, exist_ok=True)

AUDIO_EXTS = (".m4a", ".mp3", ".wav", ".aac", ".flac", ".ogg")

PLAYLIST_ITEMS_MAX = 50


def _make_opts(skip_download: bool, *, noplaylist: bool = False, extract_flat: bool = False):
    """
    Build yt-dlp options tuned for audio.
    NO external_downloader - we trim AFTER download to avoid 403/183 errors.
    """
    opts = {
        "outtmpl": os.path.join(MUSIC_DIR, "%(id)s.%(ext)s"),  # Simplified filename
        "quiet": False,
        "skip_download": skip_download,
        "playlistend": 15,
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "restrictfilenames": True,
        "noplaylist": noplaylist,
        "overwrites": True,
        "nopart": True,

        # Avoid HLS/DASH that cause 403 errors
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "web"],
            }
        },

        # Rate limiting
        "sleep_interval": 2,
        "max_sleep_interval": 4,
        "sleep_interval_requests": 1,
    }

    if extract_flat:
        opts["extract_flat"] = True

    # Cookies
    if COOKIEFILE and os.path.exists(COOKIEFILE):
        opts["cookiefile"] = COOKIEFILE
    else:
        opts["cookiesfrombrowser"] = (BROWSER, PROFILE)

    return opts


def _make_opts_android(skip_download: bool):
    """Fallback options using Android client"""
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

        "extractor_args": {
            "youtube": {
                "player_client": ["android"],
            }
        },

        "sleep_interval": 2,
        "max_sleep_interval": 4,
    }

    if COOKIEFILE and os.path.exists(COOKIEFILE):
        opts["cookiefile"] = COOKIEFILE
    else:
        opts["cookiesfrombrowser"] = (BROWSER, PROFILE)

    return opts


def _make_opts_no_cookies(skip_download: bool):
    """Options without cookies - sometimes works better"""
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
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "web"],
            }
        },
        "sleep_interval": 2,
        "max_sleep_interval": 4,
    }


def _trim_audio_after_download(input_path: str, max_duration: int = 300) -> str:
    """Trim audio to max_duration seconds AFTER download using ffmpeg"""
    if not os.path.exists(input_path):
        return input_path

    # Check current duration
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", input_path],
            capture_output=True, text=True, timeout=30
        )
        current_duration = float(result.stdout.strip())

        if current_duration <= max_duration:
            print(f"   ✓ Audio is already {current_duration:.0f}s (under {max_duration}s limit)")
            return input_path

    except Exception as e:
        print(f"   ⚠️ Could not check duration: {e}")
        return input_path

    # Trim the audio
    print(f"   ✂️ Trimming audio from {current_duration:.0f}s to {max_duration}s...")

    base, ext = os.path.splitext(input_path)
    trimmed_path = f"{base}_trimmed{ext}"

    try:
        subprocess.run([
            "ffmpeg", "-y", "-i", input_path,
            "-t", str(max_duration),
            "-c", "copy",  # Fast copy without re-encoding
            trimmed_path
        ], capture_output=True, timeout=120, check=True)

        # Replace original with trimmed
        if os.path.exists(trimmed_path) and os.path.getsize(trimmed_path) > 0:
            os.remove(input_path)
            os.rename(trimmed_path, input_path)
            print(f"   ✓ Trimmed successfully to {max_duration}s")

    except Exception as e:
        print(f"   ⚠️ Trim failed: {e}")
        if os.path.exists(trimmed_path):
            try:
                os.remove(trimmed_path)
            except:
                pass

    return input_path


def _final_filepath(ydl: yt_dlp.YoutubeDL, info: dict) -> str:
    """Get the final filepath of downloaded audio"""
    vid_id = info.get("id", "unknown")

    # Check requested_downloads first
    if info.get("requested_downloads"):
        rd = info["requested_downloads"][0]
        path = rd.get("filepath") or rd.get("_filename")
        if path and os.path.exists(path):
            return path

    # Try prepared filename
    try:
        path = ydl.prepare_filename(info)
        if os.path.exists(path):
            return path
    except:
        pass

    # Search for file by ID
    for ext in AUDIO_EXTS:
        candidate = os.path.join(MUSIC_DIR, f"{vid_id}{ext}")
        if os.path.exists(candidate):
            return candidate

    # Search for any file containing the ID
    try:
        for f in os.listdir(MUSIC_DIR):
            if vid_id in f and f.lower().endswith(AUDIO_EXTS):
                return os.path.join(MUSIC_DIR, f)
    except:
        pass

    return os.path.join(MUSIC_DIR, f"{vid_id}.m4a")


def _safe_title(t: str) -> str:
    t = re.sub(r'[\\/*?:"<>|]', " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:200] or "untitled"


def _pick_existing_music() -> Optional[str]:
    candidates = [
        os.path.join(MUSIC_DIR, f)
        for f in os.listdir(MUSIC_DIR)
        if f.lower().endswith(AUDIO_EXTS) and os.path.getsize(os.path.join(MUSIC_DIR, f)) > 10000
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
        if f.lower().endswith(AUDIO_EXTS) and os.path.getsize(os.path.join(MUSIC_DIR, f)) > 10000
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
    """Return a list of flat video entries from a playlist URL."""
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


def _download_single_track(url: str, title: str, vid_id: str) -> Optional[str]:
    """
    Download a single track with multiple fallback methods.
    Returns filepath on success, None on failure.
    """
    filepath = None

    # Method 1: Standard download with Android client
    try:
        print(f"   📱 Method 1: Android client...")
        opts = _make_opts_android(skip_download=False)

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filepath = _final_filepath(ydl, info)

            if os.path.exists(filepath) and os.path.getsize(filepath) > 5000:
                print(f"   ✅ Method 1 succeeded!")
                return filepath

    except Exception as e1:
        print(f"   ⚠️ Method 1 failed: {str(e1)[:80]}")

    # Method 2: Without cookies
    try:
        print(f"   🔓 Method 2: No cookies...")
        time.sleep(2)
        opts = _make_opts_no_cookies(skip_download=False)

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filepath = _final_filepath(ydl, info)

            if os.path.exists(filepath) and os.path.getsize(filepath) > 5000:
                print(f"   ✅ Method 2 succeeded!")
                return filepath

    except Exception as e2:
        print(f"   ⚠️ Method 2 failed: {str(e2)[:80]}")

    # Method 3: CLI fallback
    try:
        print(f"   🖥️ Method 3: CLI fallback...")
        time.sleep(2)
        output_path = os.path.join(MUSIC_DIR, f"{vid_id}.m4a")

        result = subprocess.run([
            "yt-dlp",
            "--no-warnings",
            "--format", "bestaudio/best",
            "--output", output_path,
            "--no-playlist",
            "--extractor-args", "youtube:player_client=android",
            url
        ], capture_output=True, text=True, timeout=300)

        if os.path.exists(output_path) and os.path.getsize(output_path) > 5000:
            print(f"   ✅ Method 3 succeeded!")
            return output_path
        else:
            # Check for any file with this ID
            for f in os.listdir(MUSIC_DIR):
                if vid_id in f and f.lower().endswith(AUDIO_EXTS):
                    found_path = os.path.join(MUSIC_DIR, f)
                    if os.path.getsize(found_path) > 5000:
                        print(f"   ✅ Found downloaded file: {f}")
                        return found_path

    except Exception as e3:
        print(f"   ⚠️ Method 3 failed: {str(e3)[:80]}")

    return None


def fetch_music_by_search(search_query: str, max_tracks: int = 1) -> List[str]:
    """
    Search YouTube for music, download and trim to 5 mins if needed.
    """
    os.makedirs(MUSIC_DIR, exist_ok=True)

    print(f"\n🔎 Searching YouTube for music: \"{search_query}\"")
    search_count = max(10, max_tracks * 10)

    try:
        with yt_dlp.YoutubeDL(_make_opts(skip_download=True, extract_flat=True)) as ydl:
            info = ydl.extract_info(f"ytsearch{search_count}:{search_query}", download=False)
    except Exception as e:
        print(f"❌ Failed to search YouTube for music: {e}")
        # Try to return existing music
        existing = _pick_existing_music()
        return [existing] if existing else []

    entries = (info or {}).get("entries") or []
    if not entries:
        print("⚠️  No music results found.")
        existing = _pick_existing_music()
        return [existing] if existing else []

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
    strong_terms = [w for w in search_query.lower().split() if len(w) > 4]

    def matches_query(item):
        title = (item.get("title") or "").lower()
        return any(term in title for term in strong_terms)

    video_candidates = [v for v in video_candidates if matches_query(v)]

    ranked = sorted(video_candidates, key=_score_entry, reverse=True)
    filtered_ranked = [item for item in ranked if _score_entry(item) >= 0]

    if not filtered_ranked:
        filtered_ranked = ranked[:5]

    pool = filtered_ranked[: min(12, len(filtered_ranked))]
    random.shuffle(pool)
    chosen_items = pool[: max_tracks]

    print(f"🧾 Picked {len(chosen_items)} item(s) to download.")

    paths: List[str] = []

    for v in chosen_items:
        url = v["webpage_url"]
        vid_id = v.get("id", "unknown")
        title = _safe_title(v.get("title") or "untitled")

        print(f"\n⬇️  Downloading music: {title}")
        print(f"   URL: {url}")

        filepath = _download_single_track(url, title, vid_id)

        if filepath and os.path.exists(filepath):
            file_size = os.path.getsize(filepath) / (1024 * 1024)
            print(f"   📁 Downloaded: {os.path.basename(filepath)} ({file_size:.2f} MB)")

            # Trim to 5 minutes if needed
            filepath = _trim_audio_after_download(filepath, max_duration=300)
            paths.append(filepath)
        else:
            print(f"   ❌ All download methods failed for: {title}")

    # If we couldn't download anything, try existing music
    if not paths:
        existing = _pick_existing_music()
        if existing:
            print(f"📁 Falling back to existing music: {existing}")
            paths.append(existing)

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

    # Last resort: try existing music
    existing = _pick_existing_music()
    if existing:
        return existing

    print("⚠️  No music could be selected.")
    return None


# ============================================================================
# TEST SECTION
# ============================================================================
if __name__ == "__main__":
    import sys

    print("\n" + "=" * 60)
    print("   MUSIC UTILS - TEST")
    print("=" * 60)

    print(f"\n📂 MUSIC_DIR: {MUSIC_DIR}")

    # Check yt-dlp version
    try:
        result = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True)
        print(f"📌 yt-dlp version: {result.stdout.strip()}")
    except:
        print("⚠️ Could not get yt-dlp version")

    print("\n💡 TIP: If downloads fail, update yt-dlp:")
    print("   pip install -U yt-dlp")

    # Check existing music
    existing = pick_existing_music_multi(limit=3)
    if existing:
        print(f"\n📁 Found {len(existing)} existing music file(s)")

    # Test search and download
    test_query = "relaxing instrumental music no copyright"
    print(f"\n🧪 Testing music download: \"{test_query}\"")

    try:
        results = fetch_music_by_search(test_query, max_tracks=1)

        if results:
            print(f"\n✅ SUCCESS! Downloaded {len(results)} track(s):")
            for i, path in enumerate(results, 1):
                if os.path.exists(path):
                    size_mb = os.path.getsize(path) / (1024 * 1024)
                    print(f"   {i}. {os.path.basename(path)} ({size_mb:.2f} MB)")

                    # Check duration
                    try:
                        result = subprocess.run(
                            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                             "-of", "default=noprint_wrappers=1:nokey=1", path],
                            capture_output=True, text=True, timeout=30
                        )
                        duration = float(result.stdout.strip())
                        print(f"      Duration: {duration:.1f}s ({duration / 60:.1f} min)")
                    except:
                        pass
        else:
            print("\n❌ No music downloaded.")

    except Exception as e:
        print(f"\n💥 Test failed: {e}")
        import traceback

        traceback.print_exc()

    print("\n" + "=" * 60)