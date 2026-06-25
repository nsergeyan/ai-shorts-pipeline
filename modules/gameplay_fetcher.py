import os
import random
import re
import time
import subprocess
from typing import Optional

import yt_dlp
from config import GAMEPLAY_DIR

BROWSER = "chrome"  # Try: "chrome", "firefox", "safari", "edge"
PROFILE = "Default"
COOKIEFILE = ""

# YouTube search filter for 4-20 minute videos
YT_FILTER = "EgIYAw%3D%3D"


def _get_yt_dlp_version():
    """Check yt-dlp version"""
    try:
        result = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True)
        return result.stdout.strip()
    except:
        return "unknown"


def _make_opts(skip_download: bool, use_range: bool = False):
    """Create yt-dlp options that avoid 403 errors"""
    opts = {
        "outtmpl": os.path.join(GAMEPLAY_DIR, "%(id)s.%(ext)s"),
        "quiet": False,
        "skip_download": skip_download,
        "playlistend": 1,
        "restrictfilenames": True,
        "no_warnings": False,
        "ignoreerrors": True,
        "nocheckcertificate": True,
        "overwrites": True,
        "nopart": True,

        # Progressive formats only — HLS/DASH cause 403s
        "format": "18/best[ext=mp4][protocol=https]/best[ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best",
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "web"],
                "skip": ["hls", "dash"],
            }
        },
        "js_runtimes": {"node": {}},
        "sleep_interval": 3,
        "max_sleep_interval": 6,
        "sleep_interval_requests": 1,

        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }

    if COOKIEFILE and os.path.exists(COOKIEFILE):
        opts["cookiefile"] = COOKIEFILE
    else:
        opts["cookiesfrombrowser"] = (BROWSER, PROFILE)

    return opts


def _make_opts_android(skip_download: bool):
    """yt-dlp options using the Android client — often bypasses YouTube restrictions."""
    opts = {
        "outtmpl": os.path.join(GAMEPLAY_DIR, "%(id)s.%(ext)s"),
        "quiet": False,
        "skip_download": skip_download,
        "playlistend": 1,
        "restrictfilenames": True,
        "ignoreerrors": True,
        "overwrites": True,
        "nopart": True,

        "extractor_args": {
            "youtube": {
                "player_client": ["android"],
            }
        },
        "format": "18/best",
        "js_runtimes": {"node": {}},

        "sleep_interval": 2,
        "max_sleep_interval": 5,
    }

    if COOKIEFILE and os.path.exists(COOKIEFILE):
        opts["cookiefile"] = COOKIEFILE
    else:
        opts["cookiesfrombrowser"] = (BROWSER, PROFILE)

    return opts


def _make_opts_no_cookies(skip_download: bool):
    """yt-dlp options without browser cookies — used as a fallback when cookie-based download fails."""
    return {
        "outtmpl": os.path.join(GAMEPLAY_DIR, "%(id)s.%(ext)s"),
        "quiet": False,
        "skip_download": skip_download,
        "playlistend": 1,
        "restrictfilenames": True,
        "ignoreerrors": True,
        "overwrites": True,
        "nopart": True,
        "format": "best[height<=720]",
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "web"],
                "skip": ["hls", "dash"],
            }
        },
        "sleep_interval": 3,
        "max_sleep_interval": 6,
    }


def _trim_video_after_download(input_path: str, max_duration: int = 300) -> str:
    """Trim video to max_duration seconds AFTER download using ffmpeg"""
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
            print(f"   ✓ Video is already {current_duration:.0f}s (under {max_duration}s limit)")
            return input_path

    except Exception as e:
        print(f"   ⚠️ Could not check duration: {e}")
        return input_path

    # Trim the video
    print(f"   ✂️ Trimming video from {current_duration:.0f}s to {max_duration}s...")

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

    for ext in ['.mp4', '.webm', '.mkv', '.m4a']:
        candidate = os.path.join(GAMEPLAY_DIR, f"{vid_id}{ext}")
        if os.path.exists(candidate):
            return candidate

    try:
        for f in os.listdir(GAMEPLAY_DIR):
            if vid_id in f and f.endswith(('.mp4', '.webm', '.mkv')):
                return os.path.join(GAMEPLAY_DIR, f)
    except Exception:
        pass

    return os.path.join(GAMEPLAY_DIR, f"{vid_id}.mp4")


def _safe_title(t: str) -> str:
    """Strip characters that are invalid in filenames and truncate to 200 chars."""
    t = re.sub(r'[\\/*?:"<>|]', " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:200]


def _pick_existing_gameplay() -> Optional[str]:
    """Return the largest video file already in GAMEPLAY_DIR, or None if empty."""
    os.makedirs(GAMEPLAY_DIR, exist_ok=True)
    candidates = [f for f in os.listdir(GAMEPLAY_DIR) if f.lower().endswith((".mp4", ".webm", ".mkv"))]
    if candidates:
        # Return the largest file (most likely complete)
        candidates.sort(key=lambda f: os.path.getsize(os.path.join(GAMEPLAY_DIR, f)), reverse=True)
        return os.path.join(GAMEPLAY_DIR, candidates[0])
    return None


def _find_latest_video() -> Optional[str]:
    """Find the most recently created video file"""
    try:
        video_files = []
        for f in os.listdir(GAMEPLAY_DIR):
            if f.endswith(('.mp4', '.webm', '.mkv')):
                full_path = os.path.join(GAMEPLAY_DIR, f)
                if os.path.getsize(full_path) > 10000:  # At least 10KB
                    video_files.append((full_path, os.path.getctime(full_path)))

        if video_files:
            video_files.sort(key=lambda x: x[1], reverse=True)
            return video_files[0][0]
    except:
        pass
    return None


def fetch_gameplay_by_search(
        search_queries,
        max_videos: int = 1,
        retry_searches: int = 20,
        used_video_ids: Optional[set] = None
) -> list[str]:
    """
    Search YouTube and download videos, avoiding 403 errors.
    """
    if isinstance(search_queries, str):
        search_queries = [search_queries]

    os.makedirs(GAMEPLAY_DIR, exist_ok=True)

    print(f"📌 yt-dlp version: {_get_yt_dlp_version()}")

    attempts = 0
    query_index = 0
    used_video_ids = used_video_ids or set()
    filtered_entries = []

    while attempts < retry_searches:
        attempts += 1
        query = search_queries[query_index % len(search_queries)]
        query_index += 1

        print(f"\n🔎 [Attempt {attempts}/{retry_searches}] Searching: \"{query}\"")

        try:
            search_opts = {
                "quiet": False,
                "skip_download": True,
                "extract_flat": "in_playlist",
                "playlistend": max_videos * 5,
                "ignoreerrors": True,
                "extractor_args": {"youtube": {"search_filter": YT_FILTER}},
            }

            with yt_dlp.YoutubeDL(search_opts) as ydl:
                info = ydl.extract_info(f"ytsearch{max_videos * 5}:{query}", download=False)
        except Exception as e:
            print(f"❌ Search failed: {e}")
            time.sleep(3)
            continue

        entries = info.get("entries", []) or []

        valid_entries = []
        for entry in entries:
            if not entry:
                continue

            vid_id = entry.get("id", "")
            duration = entry.get("duration", 0)
            is_live = entry.get("is_live", False)
            title = entry.get("title", "").lower()
            webpage_url = entry.get("webpage_url", "")

            if vid_id in used_video_ids:
                continue

            if duration and duration < 61:
                used_video_ids.add(vid_id)
                continue

            if is_live:
                used_video_ids.add(vid_id)
                continue

            if "/shorts/" in webpage_url:
                used_video_ids.add(vid_id)
                continue

            if duration and duration > 7200:
                used_video_ids.add(vid_id)
                continue

            valid_entries.append(entry)
            print(f"✓ Found: {entry.get('title', 'Unknown')[:60]}... ({duration}s)")

        filtered_entries = valid_entries[:max_videos]

        if filtered_entries:
            print(f"✅ Found {len(filtered_entries)} suitable video(s).")
            break
        else:
            print(f"⚠️ No valid results. Retrying...")
            time.sleep(2)

    if not filtered_entries:
        print("❌ No suitable videos found after all retries.")
        existing = _pick_existing_gameplay()
        if existing:
            print(f"📁 Using existing video: {existing}")
            return [existing]
        return []

    paths = []

    for e in filtered_entries:
        vid_id = e.get("id")
        title = _safe_title(e.get("title", "untitled"))
        webpage_url = e.get("webpage_url") or f"https://www.youtube.com/watch?v={vid_id}"

        used_video_ids.add(vid_id)
        print(f"\n⬇️  Downloading: {title}")
        print(f"   URL: {webpage_url}")

        download_success = False
        filepath = None

        if not download_success:
            try:
                print("   📱 Method 1: Android client...")
                opts = _make_opts_android(skip_download=False)

                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(webpage_url, download=True)
                    filepath = _final_filepath(ydl, info)

                    if os.path.exists(filepath) and os.path.getsize(filepath) > 10000:
                        download_success = True
                        print(f"   ✅ Method 1 succeeded!")

            except Exception as e1:
                print(f"   ⚠️ Method 1 failed: {str(e1)[:100]}")

        if not download_success:
            try:
                print("   🔓 Method 2: No cookies...")
                time.sleep(3)
                opts = _make_opts_no_cookies(skip_download=False)

                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(webpage_url, download=True)
                    filepath = _final_filepath(ydl, info)

                    if os.path.exists(filepath) and os.path.getsize(filepath) > 10000:
                        download_success = True
                        print(f"   ✅ Method 2 succeeded!")

            except Exception as e2:
                print(f"   ⚠️ Method 2 failed: {str(e2)[:100]}")

        if not download_success:
            try:
                print("   🖥️ Method 3: CLI fallback...")
                time.sleep(3)
                output_path = os.path.join(GAMEPLAY_DIR, f"{vid_id}.mp4")

                result = subprocess.run([
                    "yt-dlp",
                    "--no-warnings",
                    "--format", "18/best[ext=mp4]/best",
                    "--output", output_path,
                    "--no-playlist",
                    "--extractor-args", "youtube:player_client=android",
                    webpage_url
                ], capture_output=True, text=True, timeout=300)

                if os.path.exists(output_path) and os.path.getsize(output_path) > 10000:
                    filepath = output_path
                    download_success = True
                    print(f"   ✅ Method 3 succeeded!")
                else:
                    print(f"   ⚠️ Method 3: File not created or too small")
                    if result.returncode != 0 and result.stderr:
                        print(f"   yt-dlp error: {result.stderr[:200]}")

            except Exception as e3:
                print(f"   ⚠️ Method 3 failed: {str(e3)[:100]}")

        # Check result
        if download_success and filepath and os.path.exists(filepath):
            file_size = os.path.getsize(filepath) / (1024 * 1024)
            print(f"   📁 Downloaded: {os.path.basename(filepath)} ({file_size:.2f} MB)")

            filepath = _trim_video_after_download(filepath, max_duration=300)
            paths.append(filepath)
            title_file = os.path.splitext(filepath)[0] + ".title.txt"
            with open(title_file, "w") as tf:
                tf.write(title)
        else:
            print(f"   ❌ All methods failed for: {vid_id}")

            latest = _find_latest_video()
            if latest and vid_id in latest:
                print(f"   📁 Found partial download: {latest}")
                paths.append(latest)

    return paths




if __name__ == "__main__":
    import sys

    print("\n" + "=" * 60)
    print("   YOUTUBE UTILS - TEST")
    print("=" * 60)

    print(f"\n📌 yt-dlp version: {_get_yt_dlp_version()}")
    print(f"📂 GAMEPLAY_DIR: {GAMEPLAY_DIR}")

    # Check if yt-dlp needs updating
    print("\n💡 TIP: If downloads fail, update yt-dlp:")
    print("   pip install -U yt-dlp")
    print("   # or")
    print("   yt-dlp -U")

    # Test queries - use generic content less likely to be restricted
    test_queries = [
        "thors cinematic 4k vinland saga"
    ]

    print(f"\n🧪 Testing download with queries: {test_queries[0][:40]}...")

    try:
        results = fetch_gameplay_by_search(
            search_queries=test_queries,
            max_videos=1,
            retry_searches=5,
            used_video_ids=set()
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