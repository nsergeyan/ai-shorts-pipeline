import os
import random
import re
import time
import subprocess
from typing import Optional

import yt_dlp
from config import GAMEPLAY_DIR

# Browser cookies - use only as fallback for downloads if needed
BROWSER = "chrome"   # Try: "chrome", "firefox", "safari", "edge"
PROFILE = "Default"
COOKIEFILE = ""

# YouTube search filter for videos roughly 4-20 min
YT_FILTER = "EgIYAw%3D%3D"


def _get_yt_dlp_version():
    """Check yt-dlp version"""
    try:
        result = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True)
        return result.stdout.strip()
    except Exception:
        return "unknown"


def _make_search_opts():
    """
    Lightweight search options.
    Important:
    - no cookies by default
    - extract_flat avoids full extraction during search
    - no playlistend here
    """
    return {
        "quiet": False,
        "skip_download": True,
        "ignoreerrors": True,
        "no_warnings": False,
        "extract_flat": True,
        "nocheckcertificate": True,
        "socket_timeout": 20,
        "retries": 2,
        "sleep_interval_requests": 1,
        "extractor_args": {
            "youtube": {
                "search_filter": [YT_FILTER],
                "player_client": ["web"],
            }
        },
        "user_agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }


def _make_download_opts(skip_download: bool = False, use_cookies: bool = False):
    """
    Standard download options.
    Avoid HLS/DASH where possible.
    """
    opts = {
        "outtmpl": os.path.join(GAMEPLAY_DIR, "%(id)s.%(ext)s"),
        "quiet": False,
        "skip_download": skip_download,
        "restrictfilenames": True,
        "no_warnings": False,
        "ignoreerrors": False,
        "nocheckcertificate": True,
        "overwrites": True,
        "nopart": True,
        "socket_timeout": 20,
        "retries": 2,
        "fragment_retries": 2,
        "sleep_interval": 2,
        "max_sleep_interval": 5,
        "sleep_interval_requests": 1,
        "format": "best[ext=mp4][protocol=https]/best[ext=mp4]/best",
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "web"],
                "skip": ["hls", "dash"],
            }
        },
        "user_agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }

    if use_cookies:
        if COOKIEFILE and os.path.exists(COOKIEFILE):
            opts["cookiefile"] = COOKIEFILE
        else:
            opts["cookiesfrombrowser"] = (BROWSER, PROFILE)

    return opts


def _make_opts_android(skip_download: bool = False, use_cookies: bool = False):
    """Fallback options forcing Android client."""
    opts = {
        "outtmpl": os.path.join(GAMEPLAY_DIR, "%(id)s.%(ext)s"),
        "quiet": False,
        "skip_download": skip_download,
        "restrictfilenames": True,
        "ignoreerrors": False,
        "overwrites": True,
        "nopart": True,
        "nocheckcertificate": True,
        "socket_timeout": 20,
        "retries": 2,
        "sleep_interval": 2,
        "max_sleep_interval": 5,
        "format": "best",
        "extractor_args": {
            "youtube": {
                "player_client": ["android"],
            }
        },
    }

    if use_cookies:
        if COOKIEFILE and os.path.exists(COOKIEFILE):
            opts["cookiefile"] = COOKIEFILE
        else:
            opts["cookiesfrombrowser"] = (BROWSER, PROFILE)

    return opts


def _make_opts_no_cookies(skip_download: bool = False):
    """Fallback options without cookies."""
    return {
        "outtmpl": os.path.join(GAMEPLAY_DIR, "%(id)s.%(ext)s"),
        "quiet": False,
        "skip_download": skip_download,
        "restrictfilenames": True,
        "ignoreerrors": False,
        "overwrites": True,
        "nopart": True,
        "nocheckcertificate": True,
        "socket_timeout": 20,
        "retries": 2,
        "fragment_retries": 2,
        "sleep_interval": 2,
        "max_sleep_interval": 5,
        "format": "best[ext=mp4][protocol=https]/best[ext=mp4]/best",
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "web"],
                "skip": ["hls", "dash"],
            }
        },
    }


def _trim_video_after_download(input_path: str, max_duration: int = 300) -> str:
    """Trim video to max_duration seconds AFTER download using ffmpeg"""
    if not os.path.exists(input_path):
        return input_path

    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                input_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        current_duration = float(result.stdout.strip())

        if current_duration <= max_duration:
            print(f"   ✓ Video is already {current_duration:.0f}s (under {max_duration}s limit)")
            return input_path

    except Exception as e:
        print(f"   ⚠️ Could not check duration: {e}")
        return input_path

    print(f"   ✂️ Trimming video from {current_duration:.0f}s to {max_duration}s...")

    base, ext = os.path.splitext(input_path)
    trimmed_path = f"{base}_trimmed{ext}"

    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", input_path,
                "-t", str(max_duration),
                "-c", "copy",
                trimmed_path,
            ],
            capture_output=True,
            timeout=120,
            check=True,
        )

        if os.path.exists(trimmed_path) and os.path.getsize(trimmed_path) > 0:
            os.remove(input_path)
            os.rename(trimmed_path, input_path)
            print(f"   ✓ Trimmed successfully to {max_duration}s")

    except Exception as e:
        print(f"   ⚠️ Trim failed: {e}")
        if os.path.exists(trimmed_path):
            os.remove(trimmed_path)

    return input_path


def _final_filepath(ydl: yt_dlp.YoutubeDL, info: dict) -> str:
    """Get the final filepath of downloaded video"""
    vid_id = info.get("id", "unknown")

    if info.get("requested_downloads"):
        rd = info["requested_downloads"][0]
        path = rd.get("filepath") or rd.get("_filename")
        if path and os.path.exists(path):
            return path

    try:
        path = ydl.prepare_filename(info)
        if os.path.exists(path):
            return path
    except Exception:
        pass

    for ext in [".mp4", ".webm", ".mkv", ".m4a"]:
        candidate = os.path.join(GAMEPLAY_DIR, f"{vid_id}{ext}")
        if os.path.exists(candidate):
            return candidate

    try:
        for f in os.listdir(GAMEPLAY_DIR):
            if vid_id in f and f.endswith((".mp4", ".webm", ".mkv", ".m4a")):
                return os.path.join(GAMEPLAY_DIR, f)
    except Exception:
        pass

    return os.path.join(GAMEPLAY_DIR, f"{vid_id}.mp4")


def _safe_title(t: str) -> str:
    t = re.sub(r'[\\/*?:"<>|]', " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:200]


def _pick_existing_gameplay() -> Optional[str]:
    os.makedirs(GAMEPLAY_DIR, exist_ok=True)
    candidates = [
        f for f in os.listdir(GAMEPLAY_DIR)
        if f.lower().endswith((".mp4", ".webm", ".mkv"))
    ]
    if candidates:
        candidates.sort(
            key=lambda f: os.path.getsize(os.path.join(GAMEPLAY_DIR, f)),
            reverse=True
        )
        return os.path.join(GAMEPLAY_DIR, candidates[0])
    return None


def _find_latest_video() -> Optional[str]:
    """Find the most recently created video file"""
    try:
        video_files = []
        for f in os.listdir(GAMEPLAY_DIR):
            if f.endswith((".mp4", ".webm", ".mkv")):
                full_path = os.path.join(GAMEPLAY_DIR, f)
                if os.path.getsize(full_path) > 10000:
                    video_files.append((full_path, os.path.getctime(full_path)))

        if video_files:
            video_files.sort(key=lambda x: x[1], reverse=True)
            return video_files[0][0]
    except Exception:
        pass
    return None


def _normalize_webpage_url(entry: dict) -> str:
    """Handle flat search results safely."""
    webpage_url = entry.get("webpage_url") or entry.get("url", "")
    vid_id = entry.get("id", "")

    if webpage_url and webpage_url.startswith("http"):
        return webpage_url

    if vid_id:
        return f"https://www.youtube.com/watch?v={vid_id}"

    return ""


def fetch_gameplay_by_search(
    search_queries,
    max_videos: int = 1,
    retry_searches: int = 20,
    used_video_ids: Optional[set] = None
) -> list[str]:
    """
    Search YouTube and download videos.
    Uses lightweight search first, then full extraction for downloads.
    """
    if isinstance(search_queries, str):
        search_queries = [search_queries]

    os.makedirs(GAMEPLAY_DIR, exist_ok=True)

    print(f"📌 yt-dlp version: {_get_yt_dlp_version()}")

    attempts = 0
    query_index = 0
    used_video_ids = used_video_ids or set()
    filtered_entries = []

    # PHASE 1: SEARCH
    while attempts < retry_searches:
        attempts += 1
        query = search_queries[query_index % len(search_queries)]
        query_index += 1

        print(f"\n🔎 [Attempt {attempts}/{retry_searches}] Searching: \"{query}\"")

        try:
            with yt_dlp.YoutubeDL(_make_search_opts()) as ydl:
                info = ydl.extract_info(f"ytsearch{max_videos * 5}:{query}", download=False)
        except Exception as e:
            print(f"❌ Search failed: {e}")
            time.sleep(2)
            continue

        entries = info.get("entries", []) or []
        valid_entries = []

        for entry in entries:
            if not entry:
                continue

            vid_id = entry.get("id", "")
            duration = entry.get("duration", 0) or 0
            is_live = entry.get("is_live", False)
            webpage_url = _normalize_webpage_url(entry)
            title = entry.get("title", "Unknown")

            if not vid_id:
                continue

            if vid_id in used_video_ids:
                continue

            if duration and duration < 30:
                used_video_ids.add(vid_id)
                continue

            if duration and duration > 3600:
                used_video_ids.add(vid_id)
                continue

            if is_live:
                used_video_ids.add(vid_id)
                continue

            if "/shorts/" in webpage_url:
                used_video_ids.add(vid_id)
                continue

            entry["webpage_url"] = webpage_url
            valid_entries.append(entry)
            print(f"✓ Found: {title[:60]}... ({duration}s)")

        filtered_entries = valid_entries[:max_videos]

        if filtered_entries:
            print(f"✅ Found {len(filtered_entries)} suitable video(s).")
            break

        print("⚠️ No valid results. Retrying...")
        time.sleep(2)

    if not filtered_entries:
        print("❌ No suitable videos found after all retries.")
        existing = _pick_existing_gameplay()
        if existing:
            print(f"📁 Using existing video: {existing}")
            return [existing]
        return []

    # PHASE 2: DOWNLOAD
    paths = []

    for e in filtered_entries:
        vid_id = e.get("id")
        title = _safe_title(e.get("title", "untitled"))
        webpage_url = e.get("webpage_url")

        if not webpage_url:
            print(f"   ❌ Missing webpage URL for: {vid_id}")
            continue

        used_video_ids.add(vid_id)

        print(f"\n⬇️  Downloading: {title}")
        print(f"   URL: {webpage_url}")

        download_success = False
        filepath = None

        # Method 1: No cookies, standard opts
        if not download_success:
            try:
                print("   🔓 Method 1: Standard download without cookies...")
                opts = _make_download_opts(skip_download=False, use_cookies=False)

                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(webpage_url, download=True)
                    filepath = _final_filepath(ydl, info)

                if filepath and os.path.exists(filepath) and os.path.getsize(filepath) > 10000:
                    download_success = True
                    print("   ✅ Method 1 succeeded!")

            except Exception as e1:
                print(f"   ⚠️ Method 1 failed: {str(e1)[:200]}")

        # Method 2: Android-only fallback
        if not download_success:
            try:
                print("   📱 Method 2: Android client fallback...")
                time.sleep(2)
                opts = _make_opts_android(skip_download=False, use_cookies=False)

                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(webpage_url, download=True)
                    filepath = _final_filepath(ydl, info)

                if filepath and os.path.exists(filepath) and os.path.getsize(filepath) > 10000:
                    download_success = True
                    print("   ✅ Method 2 succeeded!")

            except Exception as e2:
                print(f"   ⚠️ Method 2 failed: {str(e2)[:200]}")

        # Method 3: With browser cookies
        if not download_success:
            try:
                print("   🍪 Method 3: Retry with browser cookies...")
                time.sleep(2)
                opts = _make_download_opts(skip_download=False, use_cookies=True)

                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(webpage_url, download=True)
                    filepath = _final_filepath(ydl, info)

                if filepath and os.path.exists(filepath) and os.path.getsize(filepath) > 10000:
                    download_success = True
                    print("   ✅ Method 3 succeeded!")

            except Exception as e3:
                print(f"   ⚠️ Method 3 failed: {str(e3)[:200]}")

        # Method 4: CLI fallback
        if not download_success:
            try:
                print("   🖥️ Method 4: CLI fallback...")
                time.sleep(2)
                output_path = os.path.join(GAMEPLAY_DIR, f"{vid_id}.%(ext)s")

                cmd = [
                    "yt-dlp",
                    "--format", "best[ext=mp4][protocol=https]/best[ext=mp4]/best",
                    "--output", output_path,
                    "--no-playlist",
                    "--extractor-args", "youtube:player_client=android;skip=hls,dash",
                    "--socket-timeout", "20",
                    "--retries", "2",
                    webpage_url,
                ]

                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=180,
                )

                if result.returncode != 0:
                    print(f"   ⚠️ CLI stderr: {result.stderr[:300]}")

                latest = _find_latest_video()
                if latest and os.path.exists(latest) and os.path.getsize(latest) > 10000:
                    filepath = latest
                    download_success = True
                    print("   ✅ Method 4 succeeded!")

            except Exception as e4:
                print(f"   ⚠️ Method 4 failed: {str(e4)[:200]}")

        if download_success and filepath and os.path.exists(filepath):
            file_size = os.path.getsize(filepath) / (1024 * 1024)
            print(f"   📁 Downloaded: {os.path.basename(filepath)} ({file_size:.2f} MB)")
            filepath = _trim_video_after_download(filepath, max_duration=300)
            paths.append(filepath)
        else:
            print(f"   ❌ All methods failed for: {vid_id}")

            latest = _find_latest_video()
            if latest and vid_id in os.path.basename(latest):
                print(f"   📁 Found possible partial/latest file: {latest}")
                paths.append(latest)

    return paths


def fetch_gameplay_by_channel(channel_url: str, keyword: str, max_videos: int = 1) -> list[str]:
    os.makedirs(GAMEPLAY_DIR, exist_ok=True)

    try:
        with yt_dlp.YoutubeDL(_make_search_opts()) as ydl:
            print(f"\n🔍 Searching channel: {channel_url}")
            info = ydl.extract_info(f"{channel_url}/videos", download=False)
    except Exception as e:
        print(f"❌ Channel search failed: {e}")
        return []

    entries = info.get("entries", []) or []
    matching = [
        e for e in entries
        if e and e.get("title") and keyword.lower() in e["title"].lower()
    ][:max_videos]

    paths = []

    for v in matching:
        try:
            webpage_url = _normalize_webpage_url(v)
            title = _safe_title(v.get("title", "untitled"))

            print(f"⬇️  Downloading: {title}")

            with yt_dlp.YoutubeDL(_make_download_opts(skip_download=False, use_cookies=False)) as ydl:
                info = ydl.extract_info(webpage_url, download=True)
                filepath = _final_filepath(ydl, info)

            if os.path.exists(filepath):
                filepath = _trim_video_after_download(filepath)
                paths.append(filepath)

        except Exception as e:
            print(f"❌ Download error: {e}")

    return paths


def pick_existing_gameplay_multi(limit=3) -> list[str]:
    os.makedirs(GAMEPLAY_DIR, exist_ok=True)
    candidates = [
        os.path.join(GAMEPLAY_DIR, f)
        for f in os.listdir(GAMEPLAY_DIR)
        if f.lower().endswith((".mp4", ".webm", ".mkv"))
    ]
    candidates = [c for c in candidates if os.path.getsize(c) > 100000]
    if not candidates:
        return []
    random.shuffle(candidates)
    return candidates[:limit]


def fetch_random_gameplay(**kwargs):
    if kwargs.get("reuse_path") and os.path.exists(kwargs["reuse_path"]):
        return kwargs["reuse_path"]

    if kwargs.get("offline"):
        return _pick_existing_gameplay() or "placeholder.mp4"

    if kwargs.get("search_query") or kwargs.get("search_queries"):
        search_queries = kwargs.get("search_queries") or [kwargs.get("search_query")]
        used_video_ids = kwargs.get("used_video_ids", set())

        res = fetch_gameplay_by_search(
            search_queries=search_queries,
            max_videos=1,
            retry_searches=20,
            used_video_ids=used_video_ids,
        )
        return res[0] if res else "placeholder.mp4"

    return "placeholder.mp4"


# ============================================================================
# TEST SECTION
# ============================================================================
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("   YOUTUBE UTILS - TEST")
    print("=" * 60)

    print(f"\n📌 yt-dlp version: {_get_yt_dlp_version()}")
    print(f"📂 GAMEPLAY_DIR: {GAMEPLAY_DIR}")

    print("\n💡 TIP: If downloads fail, update yt-dlp:")
    print("   pip install -U yt-dlp")
    print("   # or")
    print("   yt-dlp -U")

    print("\n💡 TIP: Install Node.js if you see 'n challenge solving failed':")
    print("   brew install node")

    # Try a less protected test query first
    test_queries = [
        "tadc episode 8"
        # "tadc episode 8"
    ]

    print(f"\n🧪 Testing download with query: {test_queries[0]}")

    try:
        results = fetch_gameplay_by_search(
            search_queries=test_queries,
            max_videos=1,
            retry_searches=5,
            used_video_ids=set(),
        )

        if results:
            print(f"\n✅ SUCCESS! Downloaded {len(results)} video(s):")
            for i, path in enumerate(results, 1):
                if os.path.exists(path):
                    size_mb = os.path.getsize(path) / (1024 * 1024)
                    print(f"   {i}. {os.path.basename(path)} ({size_mb:.2f} MB)")
        else:
            print("\n❌ No videos downloaded.")
            existing = _pick_existing_gameplay()
            if existing:
                print(f"📁 But found existing: {existing}")

    except Exception as e:
        print(f"\n💥 Test failed: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 60)