import json
import math
import os
import random
import re
import time
import subprocess
from typing import Optional

import yt_dlp
from config import VIDEO_MATERIAL_DIR

BROWSER = "chrome"  # Try: "chrome", "firefox", "safari", "edge"
PROFILE = "Default"
COOKIEFILE = ""

# YouTube search filter for 4-20 minute videos
YT_FILTER = "EgIYAw%3D%3D"

# Download sanity thresholds. Real 360p runs well above 100 KB/s; SABR stubs
# land near 0.5 KB/s, so 10 KB/s separates them with a wide margin on both sides.
MIN_BYTES_PER_SEC = 10_000
MIN_DOWNLOAD_BYTES = 100_000

# Only this much of each source is kept after download.
MAX_SOURCE_SECONDS = 300

# 1080p because close-ups can be cropped to fill the whole 9:16 screen (main.py
# "full" layout), which scales the picture up about 2.7x. 720p looks soft there.
MAX_HEIGHT = 1080

# How many search results to look at before picking which one to download.
SEARCH_RESULTS = 15

# How many of those ranked results to actually try downloading per query. When
# YouTube is blocking requests every attempt fails, and hammering it with all 15
# (4 methods each) only makes the block last longer.
MAX_DOWNLOAD_TRIES = 3

# Settings every download method shares to look less like a bot:
# - IPv4 only: YouTube judges IPv6 users per /64 block, so neighbours' traffic can flag you
# - pauses between requests and between videos, and a download speed cap, because
#   fast bursts are what trigger "Sign in to confirm you're not a bot"
POLITE_OPTS = {
    "source_address": "0.0.0.0",
    "sleep_interval_requests": 1.5,
    "sleep_interval": 3,
    "max_sleep_interval": 8,
    "ratelimit": 3 * 1024 * 1024,  # 3 MB/s
}

# Player clients for cookie requests. yt-dlp's defaults answer a flagged IP with
# "not a bot" before the token check even runs; these clients accept cookies
# and go through it.
COOKIE_PLAYER_CLIENTS = ["tv", "web_safari", "mweb"]

# Set once YouTube answers a cookie-less request with "confirm you're not a bot";
# from then on this run only uses the methods that send browser cookies.
_no_cookie_blocked = False

# Title words that usually mean a third party's commentary sits on top of the footage.
# Penalised rather than dropped, and ignored when the query itself contains the word.
PENALTY_WORDS = (
    "reaction", "reacts", "react", "reacting", "podcast", "review", "tier list",
    "ranking", "explained", "explaining", "breakdown", "analysis", "theory",
    "theories", "commentary", "first time", "top 10", "top 5", "iceberg", "lore",
)
# Title words that usually mean clean, original footage.
BONUS_WORDS = (
    "official", "4k", "1080p", "hd", "remastered", "creditless", "no commentary",
    "full scene", "highlights", "trailer", "cutscene", "gameplay", "footage", "raw",
)


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
        "outtmpl": os.path.join(VIDEO_MATERIAL_DIR, "%(id)s.%(ext)s"),
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


def _make_opts_hd(skip_download: bool, use_cookies: bool = False):
    """yt-dlp options for separate video + audio streams up to MAX_HEIGHT.

    YouTube only serves 360p (format 18) as a single progressive file, so anything
    sharper needs DASH streams merged by ffmpeg. Without cookies the player
    clients are left to yt-dlp's defaults; with cookies COOKIE_PLAYER_CLIENTS is used.
    The whole video is downloaded and trimmed afterwards: a partial download
    (download_ranges) goes through ffmpeg, which YouTube throttles to ~100 KB/s,
    about 12x slower than downloading the full file.
    Cookies are off by default: with browser cookies YouTube currently serves only
    storyboard images, while the cookie-less default clients get every resolution.
    """
    opts = {
        "outtmpl": os.path.join(VIDEO_MATERIAL_DIR, "%(id)s.%(ext)s"),
        "quiet": False,
        "skip_download": skip_download,
        "playlistend": 1,
        "restrictfilenames": True,
        "ignoreerrors": True,
        "overwrites": True,
        "nopart": True,

        # Prefer H.264 (plays everywhere), then any codec, then a single file.
        "format": (
            f"bestvideo[height<={MAX_HEIGHT}][vcodec^=avc1]+bestaudio[ext=m4a]"
            f"/bestvideo[height<={MAX_HEIGHT}]+bestaudio"
            f"/best[height<={MAX_HEIGHT}]"
        ),
        "merge_output_format": "mp4",
        "js_runtimes": {"node": {}},
        **POLITE_OPTS,
    }

    if use_cookies:
        opts.update(youtube_cookie_opts())

    return opts


def _has_word(text: str, word: str) -> bool:
    return re.search(rf"\b{re.escape(word)}\b", text) is not None


def _score_entry(entry: dict, query: str, position: int) -> float:
    """Score a search result from its title and views, before anything is downloaded.

    Downloading and Gemini-checking a video is slow and costs quota, so obvious
    commentary/reaction uploads are pushed down here instead of being rejected later.
    """
    title = (entry.get("title") or "").lower()
    query = query.lower()

    query_tokens = [t for t in re.findall(r"\w+", query) if len(t) > 2]
    overlap = sum(_has_word(title, t) for t in query_tokens) / max(len(query_tokens), 1)
    score = overlap * 4

    score -= 5 * sum(_has_word(title, w) for w in PENALTY_WORDS if not _has_word(query, w))
    score += min(sum(_has_word(title, w) for w in BONUS_WORDS), 2)

    views = entry.get("view_count") or 0
    score += math.log10(views + 1) * 0.3

    # YouTube's own relevance order still counts as a tiebreaker.
    score -= 0.15 * position
    return score


def _rank_entries(entries: list, query: str) -> list:
    scored = sorted(
        ((_score_entry(e, query, i), e) for i, e in enumerate(entries)),
        key=lambda pair: pair[0], reverse=True,
    )
    print("   📊 Ranked candidates:")
    for score, e in scored[:5]:
        print(f"      {score:5.1f}  {e.get('title', 'Unknown')[:70]}")
    return [e for _, e in scored]


def _write_source_meta(filepath: str, title: str, source_duration) -> None:
    """Save sidecars next to the download: the title, and the full length of the
    original upload so later steps know whether the file was cut short."""
    base = os.path.splitext(filepath)[0]
    with open(base + ".title.txt", "w") as tf:
        tf.write(title)
    with open(base + ".meta.json", "w") as mf:
        json.dump({"source_duration": source_duration}, mf)


def _make_opts_no_cookies(skip_download: bool):
    """yt-dlp options without browser cookies — used as a fallback when cookie-based download fails."""
    return {
        "outtmpl": os.path.join(VIDEO_MATERIAL_DIR, "%(id)s.%(ext)s"),
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
        **POLITE_OPTS,
    }


def _probe_duration(path: str) -> Optional[float]:
    """Return container duration in seconds, or None if ffprobe cannot read it."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=30
        )
        return float(result.stdout.strip())
    except Exception:
        return None


def _download_is_healthy(path: Optional[str]) -> bool:
    """Reject stub downloads and delete them.

    Under YouTube's SABR rollout, yt-dlp can write a container whose header
    claims the full duration while holding almost no video data. ffprobe reads
    that header and reports the real length, so a size-only check passes and a
    few hundred KB of nothing flows down the pipeline. Compare bytes against
    duration instead: a genuine 360p stream is well above 100 KB/s, whereas the
    stubs come in around 0.5 KB/s.
    """
    if not path or not os.path.exists(path):
        return False

    size = os.path.getsize(path)
    if size < MIN_DOWNLOAD_BYTES:
        print(f"   ⚠️ Download too small: {size / 1024:.0f} KB, discarding")
        _discard(path)
        return False

    duration = _probe_duration(path)
    if not duration:
        print(f"   ⚠️ Download unreadable by ffprobe, discarding")
        _discard(path)
        return False

    rate = size / duration
    if rate < MIN_BYTES_PER_SEC:
        print(f"   ⚠️ Stub download: {size / 1e6:.2f} MB for {duration:.0f}s "
              f"({rate / 1024:.1f} KB/s), discarding")
        _discard(path)
        return False

    return True


def _discard(path: str) -> None:
    """Delete a bad download so the next fallback method starts from a clean path."""
    try:
        os.remove(path)
    except Exception:
        pass


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
        candidate = os.path.join(VIDEO_MATERIAL_DIR, f"{vid_id}{ext}")
        if os.path.exists(candidate):
            return candidate

    try:
        for f in os.listdir(VIDEO_MATERIAL_DIR):
            if vid_id in f and f.endswith(('.mp4', '.webm', '.mkv')):
                return os.path.join(VIDEO_MATERIAL_DIR, f)
    except Exception:
        pass

    return os.path.join(VIDEO_MATERIAL_DIR, f"{vid_id}.mp4")


def _safe_title(t: str) -> str:
    """Strip characters that are invalid in filenames and truncate to 200 chars."""
    t = re.sub(r'[\\/*?:"<>|]', " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:200]


def _pick_existing_video_material() -> Optional[str]:
    """Return the largest video file already in VIDEO_MATERIAL_DIR, or None if empty."""
    os.makedirs(VIDEO_MATERIAL_DIR, exist_ok=True)
    candidates = [f for f in os.listdir(VIDEO_MATERIAL_DIR) if f.lower().endswith((".mp4", ".webm", ".mkv"))]
    if candidates:
        # Return the largest file (most likely complete)
        candidates.sort(key=lambda f: os.path.getsize(os.path.join(VIDEO_MATERIAL_DIR, f)), reverse=True)
        return os.path.join(VIDEO_MATERIAL_DIR, candidates[0])
    return None


def _find_latest_video() -> Optional[str]:
    """Find the most recently created video file"""
    try:
        video_files = []
        for f in os.listdir(VIDEO_MATERIAL_DIR):
            if f.endswith(('.mp4', '.webm', '.mkv')):
                full_path = os.path.join(VIDEO_MATERIAL_DIR, f)
                if os.path.getsize(full_path) > 10000:  # At least 10KB
                    video_files.append((full_path, os.path.getctime(full_path)))

        if video_files:
            video_files.sort(key=lambda x: x[1], reverse=True)
            return video_files[0][0]
    except:
        pass
    return None


def youtube_cookie_opts() -> dict:
    """yt-dlp options for sending browser cookies the way that currently gets past
    the bot check. Shared with music_generator so both downloaders stay in sync."""
    opts = {
        "js_runtimes": {"node": {}},
        "extractor_args": {"youtube": {"player_client": COOKIE_PLAYER_CLIENTS}},
    }
    if COOKIEFILE and os.path.exists(COOKIEFILE):
        opts["cookiefile"] = COOKIEFILE
    else:
        opts["cookiesfrombrowser"] = (BROWSER, PROFILE)
    return opts


def no_cookie_blocked() -> bool:
    """True once this run has seen YouTube's bot check on a cookie-less request."""
    return _no_cookie_blocked


class _ErrorCollector:
    """yt-dlp logger that stays silent and keeps the error messages, so a failed
    method can be summarised in one line instead of a wall of warnings."""

    def __init__(self):
        self.errors = []

    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        self.errors.append(msg)


def _short_error(msg: str) -> str:
    """'ERROR: [youtube] abc123: Sign in to confirm you're not a bot. Use ...' -> 'Sign in to confirm you're not a bot'"""
    msg = re.sub(r"^ERROR:\s*(\[[^\]]+\]\s*)?[\w-]+:\s*", "", msg.strip())
    return msg.split(". ")[0][:90]


def _note_bot_check(errors, uses_cookies: bool) -> None:
    """Once YouTube answers a cookie-less request with its bot check, every other
    cookie-less request this run will get the same answer, so stop sending them."""
    global _no_cookie_blocked
    if not uses_cookies and not _no_cookie_blocked and any("not a bot" in e for e in errors):
        _no_cookie_blocked = True
        print("   🚫 YouTube bot check: skipping no-cookie methods for the rest of this run")


def _try_download(label: str, opts: dict, url: str, uses_cookies: bool) -> Optional[str]:
    """Run one yt-dlp download method quietly. Returns the file path, or None after printing why it failed."""
    log = _ErrorCollector()
    opts = {**opts, "logger": log, "quiet": True, "no_warnings": True}
    path = None
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info:
                path = _final_filepath(ydl, info)
    except Exception as e:
        log.errors.append(str(e))

    if path and _download_is_healthy(path):
        print(f"   ✅ {label}")
        return path
    reason = _short_error(log.errors[-1]) if log.errors else "no usable file"
    print(f"   ⚠️ {label} failed: {reason}")
    _note_bot_check(log.errors, uses_cookies)
    return None


def _try_cli_download(vid_id: str, url: str) -> Optional[str]:
    """Last resort: the yt-dlp command-line tool with the Android client (no cookies)."""
    output_path = os.path.join(VIDEO_MATERIAL_DIR, f"{vid_id}.mp4")
    time.sleep(3)
    try:
        result = subprocess.run([
            "yt-dlp", "--no-warnings", "-4",
            "--sleep-requests", "1.5", "--limit-rate", "3M",
            "--format", "18/best[ext=mp4]/best",
            "--output", output_path,
            "--no-playlist",
            "--extractor-args", "youtube:player_client=android",
            url,
        ], capture_output=True, text=True, timeout=300)
    except Exception as e:
        print(f"   ⚠️ Method 3: CLI failed: {str(e)[:90]}")
        return None

    if _download_is_healthy(output_path):
        print("   ✅ Method 3: CLI")
        return output_path
    errors = [line for line in result.stderr.splitlines() if line.startswith("ERROR")]
    reason = _short_error(errors[-1]) if errors else "no usable file"
    print(f"   ⚠️ Method 3: CLI failed: {reason}")
    _note_bot_check(errors, uses_cookies=False)
    return None


def fetch_video_material_by_search(
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

    os.makedirs(VIDEO_MATERIAL_DIR, exist_ok=True)

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
                "playlistend": max(SEARCH_RESULTS, max_videos * 5),
                "ignoreerrors": True,
                "extractor_args": {"youtube": {"search_filter": YT_FILTER}},
                "source_address": "0.0.0.0",
            }

            with yt_dlp.YoutubeDL(search_opts) as ydl:
                info = ydl.extract_info(f"ytsearch{max(SEARCH_RESULTS, max_videos * 5)}:{query}", download=False)
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

        # Keep every valid result in ranked order: if the best one fails to
        # download, the next one is tried instead of giving up on the query.
        filtered_entries = _rank_entries(valid_entries, query) if valid_entries else []

        if filtered_entries:
            print(f"✅ Found {len(filtered_entries)} suitable video(s).")
            break
        else:
            print(f"⚠️ No valid results. Retrying...")
            time.sleep(2)

    if not filtered_entries:
        print("❌ No suitable videos found after all retries.")
        existing = _pick_existing_video_material()
        if existing:
            print(f"📁 Using existing video: {existing}")
            return [existing]
        return []

    paths = []

    tries = 0
    for e in filtered_entries:
        if len(paths) >= max_videos:
            break
        if tries >= MAX_DOWNLOAD_TRIES:
            print(f"   ⏭️ Tried {tries} results for this query, moving on")
            break
        tries += 1
        vid_id = e.get("id")
        title = _safe_title(e.get("title", "untitled"))
        webpage_url = e.get("webpage_url") or f"https://www.youtube.com/watch?v={vid_id}"

        used_video_ids.add(vid_id)
        print(f"\n⬇️  Downloading: {title}")
        print(f"   URL: {webpage_url}")

        filepath = None

        # Cookie-less first; cookies only help with age-restricted videos.
        for use_cookies in (False, True):
            if filepath or (not use_cookies and _no_cookie_blocked):
                continue
            label = "with cookies" if use_cookies else "no cookies"
            filepath = _try_download(f"Method 1: HD up to {MAX_HEIGHT}p ({label})",
                                     _make_opts_hd(skip_download=False, use_cookies=use_cookies),
                                     webpage_url, uses_cookies=use_cookies)

        if not filepath and not _no_cookie_blocked:
            time.sleep(3)
            filepath = _try_download("Method 2: no cookies (720p)",
                                     _make_opts_no_cookies(skip_download=False),
                                     webpage_url, uses_cookies=False)

        if not filepath and not _no_cookie_blocked:
            filepath = _try_cli_download(vid_id, webpage_url)

        download_success = filepath is not None

        # Check result
        if download_success and filepath and os.path.exists(filepath):
            file_size = os.path.getsize(filepath) / (1024 * 1024)
            print(f"   📁 Downloaded: {os.path.basename(filepath)} ({file_size:.2f} MB)")

            filepath = _trim_video_after_download(filepath, max_duration=MAX_SOURCE_SECONDS)
            paths.append(filepath)
            _write_source_meta(filepath, title, e.get("duration"))
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
    print(f"📂 VIDEO_MATERIAL_DIR: {VIDEO_MATERIAL_DIR}")

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
        results = fetch_video_material_by_search(
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
            existing = _pick_existing_video_material()
            if existing:
                print(f"📁 But found existing: {existing}")

    except Exception as e:
        print(f"\n💥 Test failed: {e}")
        import traceback

        traceback.print_exc()

    print("\n" + "=" * 60)