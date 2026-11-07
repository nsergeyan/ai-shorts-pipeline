import json
import math
import os
import re
import time
import subprocess
from typing import Optional

import yt_dlp
from config import VIDEO_MATERIAL_DIR

BROWSER = "chrome"  # Try: "chrome", "firefox", "safari", "edge"
PROFILE = "Default"
COOKIEFILE = ""

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

# Only MAX_SOURCE_SECONDS of a source is kept and the whole file is downloaded first,
# so a long upload is a huge download for a few seconds of footage. Longer results are skipped.
MAX_RESULT_SECONDS = 600

# Shorter results are skipped. Fans post scene clips of a new season at 30-60s, which
# is plenty for 4-6s shots; YouTube Shorts are skipped by their URL, not by length.
MIN_RESULT_SECONDS = 30

# A video that several different queries found is usually the central footage
# ("Talia Catches Roman" came up for three of six queries). Bonus per extra query, capped.
MULTI_QUERY_BONUS = 0.5
MAX_MULTI_QUERY_BONUS = 1.0

# Trailers, teasers and promos are montages of the same footage, and they show up in
# almost every query, so five of them topped the pool. Only the best one keeps its place.
TRAILER_WORDS = ("trailer", "teaser", "promo", "pv", "予告編")

# A query's best result is checked first only if it is a decent match. A query that
# found nothing good ("Irish fans chant Messi", 0.3) shouldn't push ahead of real clips.
MIN_FIRST_PICK_SCORE = 2.0

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
    # burned-in lyrics or translated subtitles, fan edits and re-pitched re-uploads
    "lyrics", "lyric", "letra", "subtitulado", "sub español", "legendado", "traducida",
    "amv", "nightcore", "slowed", "sped up",
    # side-by-side comparisons: two labelled pictures, not clean footage
    "comparison", "compared", "english vs japanese", "japanese vs english", "sub vs dub", "dub vs sub",
    # song uploads: one still image over the track ("Corbin - Worth It (Original Series Soundtrack)").
    # Only the footage search uses this list; music is searched separately.
    "soundtrack", "ost", "full album", "official audio",
)
# Title words that usually mean a news roundup: several stories in one video, with
# the subject in only one of them (and often cut out by the most-replayed trim).
ROUNDUP_WORDS = (
    "breaking", "morning report", "news roundup", "roundup", "recap", "weekly",
    "this week", "daily", "news update", "headlines",
)
# Title words that usually mean clean, original footage.
BONUS_WORDS = (
    "official", "4k", "1080p", "hd", "remastered", "creditless", "no commentary",
    "full scene", "highlights", "trailer", "cutscene", "gameplay", "footage", "raw",
)
# Query words that say little about WHICH video is wanted. They count a quarter as much
# in the title match: a result missing "music" or "video" can still be the right one,
# a result missing "Watson" is not ("High Forever (Official Music Video)" outranked the
# Watson music video because it matched "music" and "video").
GENERIC_QUERY_WORDS = {
    "music", "video", "official", "edit", "edits", "episode", "clip", "clips", "scene", "scenes",
    "full", "season", "part", "english", "dub", "dubbed", "sub", "subbed", "trailer", "anime",
    "movie", "film", "series", "goes", "hard", "best", "moment", "moments", "the", "and", "with",
}
# Title words that only say where an upload came from. Two titles that are the same once
# these are dropped are the same footage ("Official Trailer" vs "Official Trailer | Netflix Anime").
UPLOAD_FILLER_WORDS = {
    "official", "netflix", "anime", "crunchyroll", "youtube", "hd", "4k", "1080p", "new", "the", "and",
}

# Search results per query for this run: trying a query's second candidate reuses
# the first search instead of searching YouTube again (which also reshuffled the ranking).
_search_cache: dict = {}


def _get_yt_dlp_version():
    try:
        result = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True)
        return result.stdout.strip()
    except Exception:
        return "unknown"


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


def _is_roundup(title: str, query_tokens: list) -> bool:
    """
    True when a title packs a second, unrelated story: split on "+", "|" and
    "!", a part of 3+ words that shares no word with the query is another
    story ("Tsarukyan SUSPENDED + FINED! Robert Whittaker had EMERGENCY SURGERY!").
    """
    parts = [p.strip() for p in re.split(r"[+|!]", title) if p.strip()]
    if len(parts) < 2:
        return False
    return any(len(p.split()) >= 3 and not any(_has_word(p, t) for t in query_tokens) for p in parts[1:])


def _score_entry(entry: dict, query: str, position: int) -> float:
    """Score a search result from its title and views, before anything is downloaded.

    Downloading and Gemini-checking a video is slow and costs quota, so obvious
    commentary/reaction uploads are pushed down here instead of being rejected later.
    """
    title = (entry.get("title") or "").lower()
    query = query.lower()

    # numbers count too: "2" in "Edgerunners 2" is what separates season 2 from season 1
    query_tokens = [t for t in re.findall(r"\w+", query) if len(t) > 2 or t.isdigit()]
    weights = {t: 0.25 if t in GENERIC_QUERY_WORDS else 1.0 for t in query_tokens}
    overlap = sum(w for t, w in weights.items() if _has_word(title, t)) / max(sum(weights.values()), 1)
    score = overlap * 4
    # a missing specific word (a song, a character) usually means a different video
    score -= sum(1 for t, w in weights.items() if w == 1.0 and not _has_word(title, t))

    score -= 5 * sum(_has_word(title, w) for w in PENALTY_WORDS if not _has_word(query, w))
    score += min(sum(_has_word(title, w) for w in BONUS_WORDS), 2)
    score -= 4 * sum(_has_word(title, w) for w in ROUNDUP_WORDS if not _has_word(query, w))
    if _is_roundup(title, query_tokens):
        score -= 4

    views = entry.get("view_count") or 0
    score += math.log10(views + 1) * 0.3

    # YouTube's own relevance order still counts as a tiebreaker.
    score -= 0.15 * position
    return score


def _third_party(entry: dict, query: str) -> bool:
    """True when the title says someone else's video sits on top of the footage
    (a reaction, recap, comparison, lyrics...). Gemini rejects every one of these
    after a full download and upload, so they are not downloaded at all, unless
    the query itself asked for that word."""
    title = (entry.get("title") or "").lower()
    query = query.lower()
    return any(_has_word(title, w) and not _has_word(query, w) for w in PENALTY_WORDS + ROUNDUP_WORDS)


ROMAN = {"2": "ii", "3": "iii", "4": "iv", "5": "v", "6": "vi", "7": "vii", "8": "viii", "9": "ix"}


def _wrong_installment(title: str, query: str) -> bool:
    """
    True when the query names a season or sequel number ("Edgerunners 2") and the title
    doesn't have it. "Rebecca's Death - Cyberpunk: Edgerunners (2022)" won a season 2 query
    and put season 1 footage in the video. "S2", "Season 2" and "II" all count; a year
    like 2026 does not contain a 2 on its own.
    """
    m = re.search(r"(?<![\w])([2-9])(?![\w])", query)
    if not m:
        return False
    n, title = m.group(1), title.lower()
    return not (re.search(rf"(?<!\d){n}(?!\d)", title) or re.search(rf"\b{ROMAN[n]}\b", title))


def _title_key(title: str) -> frozenset:
    """A title's words minus upload filler, for spotting re-uploads of the same video."""
    return frozenset(w for w in re.findall(r"\w+", title.lower()) if w not in UPLOAD_FILLER_WORDS)


def _write_source_meta(filepath: str, title: str, source_duration, trim_start: float = 0.0) -> None:
    """Save sidecars next to the download: the title, the full length of the
    original upload and where the kept part starts, so later steps know whether
    the file was cut short."""
    base = os.path.splitext(filepath)[0]
    with open(base + ".title.txt", "w") as tf:
        tf.write(title)
    with open(base + ".meta.json", "w") as mf:
        json.dump({"source_duration": source_duration, "trim_start": trim_start}, mf)


def _best_window_start(heatmap, source_duration, window) -> float:
    """Start of the `window`-second stretch viewers rewatch most, from YouTube's
    "Most replayed" graph. yt-dlp gives it as ~100 {"start_time", "end_time", "value"}
    segments with value 0-1. Returns 0 (the opening, as before) when there is no heatmap.
    """
    if not heatmap or not source_duration or source_duration <= window:
        return 0.0

    def score(start):
        end = start + window
        return sum(seg["value"] * max(0.0, min(end, seg["end_time"]) - max(start, seg["start_time"]))
                   for seg in heatmap)

    candidates = [min(seg["start_time"], source_duration - window) for seg in heatmap]
    return max(candidates, key=score)


def _make_opts_no_cookies(skip_download: bool):
    """yt-dlp options without browser cookies, used as a fallback when cookie-based download fails."""
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
        print(f"   Download too small: {size / 1024:.0f} KB, discarding")
        _discard(path)
        return False

    duration = _probe_duration(path)
    if not duration:
        print("   Download unreadable by ffprobe, discarding")
        _discard(path)
        return False

    rate = size / duration
    if rate < MIN_BYTES_PER_SEC:
        print(f"   Stub download: {size / 1e6:.2f} MB for {duration:.0f}s "
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


def _trim_video_after_download(input_path: str, max_duration: int = 300, start: float = 0.0) -> str:
    """Cut a downloaded video down to max_duration seconds from `start` (stream copy, no re-encode).

    -ss goes before -i so ffmpeg seeks straight there; with stream copy the cut
    lands on the nearest keyframe, at most a couple of seconds early.
    """
    if not os.path.exists(input_path):
        return input_path

    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", input_path],
            capture_output=True, text=True, timeout=30
        )
        current_duration = float(result.stdout.strip())

        if current_duration <= max_duration:
            print(f"   Video is already {current_duration:.0f}s (under {max_duration}s limit)")
            return input_path

    except Exception as e:
        print(f"   Could not check duration: {e}")
        return input_path

    print(f"   Trimming video from {current_duration:.0f}s to {max_duration}s (from {start:.0f}s)...")

    base, ext = os.path.splitext(input_path)
    trimmed_path = f"{base}_trimmed{ext}"

    try:
        subprocess.run([
            "ffmpeg", "-y", "-ss", f"{start:.1f}", "-i", input_path,
            "-t", str(max_duration),
            "-c", "copy",
            trimmed_path
        ], capture_output=True, timeout=120, check=True)

        if os.path.exists(trimmed_path) and os.path.getsize(trimmed_path) > 0:
            os.remove(input_path)
            os.rename(trimmed_path, input_path)
            print(f"   Trimmed successfully to {max_duration}s")

    except Exception as e:
        print(f"   Trim failed: {e}")
        if os.path.exists(trimmed_path):
            os.remove(trimmed_path)

    return input_path


def _final_filepath(ydl: yt_dlp.YoutubeDL, info: dict) -> str:
    """Find where yt-dlp actually wrote the file (the extension depends on the format it picked)."""
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


def _find_latest_video() -> Optional[str]:
    """Most recently created video in VIDEO_MATERIAL_DIR that is over 10 KB, or None."""
    try:
        video_files = []
        for f in os.listdir(VIDEO_MATERIAL_DIR):
            if f.endswith(('.mp4', '.webm', '.mkv')):
                full_path = os.path.join(VIDEO_MATERIAL_DIR, f)
                if os.path.getsize(full_path) > 10000:
                    video_files.append((full_path, os.path.getctime(full_path)))

        if video_files:
            video_files.sort(key=lambda x: x[1], reverse=True)
            return video_files[0][0]
    except Exception:
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
        print("   YouTube bot check: skipping no-cookie methods for the rest of this run")


def _try_download(label: str, opts: dict, url: str, uses_cookies: bool) -> tuple:
    """Run one yt-dlp download method quietly. Returns (file path, "Most replayed" heatmap),
    or (None, None) after printing why it failed."""
    log = _ErrorCollector()
    opts = {**opts, "logger": log, "quiet": True, "no_warnings": True}
    path = None
    heatmap = None
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info:
                path = _final_filepath(ydl, info)
                heatmap = info.get("heatmap")
    except Exception as e:
        log.errors.append(str(e))

    if path and _download_is_healthy(path):
        print(f"   {label}: ok")
        return path, heatmap
    reason = _short_error(log.errors[-1]) if log.errors else "no usable file"
    print(f"   {label} failed: {reason}")
    _note_bot_check(log.errors, uses_cookies)
    return None, None


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
        print(f"   Method 3: CLI failed: {str(e)[:90]}")
        return None

    if _download_is_healthy(output_path):
        print("   Method 3: CLI")
        return output_path
    errors = [line for line in result.stderr.splitlines() if line.startswith("ERROR")]
    reason = _short_error(errors[-1]) if errors else "no usable file"
    print(f"   Method 3: CLI failed: {reason}")
    _note_bot_check(errors, uses_cookies=False)
    return None


def _search(query: str) -> list:
    """Raw YouTube results for a query (titles, durations, no download), cached for the run."""
    if query in _search_cache:
        return _search_cache[query]
    for attempt in range(1, 4):
        print(f"\nSearching: \"{query}\"" + (f" (attempt {attempt}/3)" if attempt > 1 else ""))
        try:
            search_opts = {
                "quiet": True,
                "skip_download": True,
                "extract_flat": "in_playlist",
                "playlistend": SEARCH_RESULTS,
                "ignoreerrors": True,
                "source_address": "0.0.0.0",
            }
            with yt_dlp.YoutubeDL(search_opts) as ydl:
                info = ydl.extract_info(f"ytsearch{SEARCH_RESULTS}:{query}", download=False)
            _search_cache[query] = [e for e in (info.get("entries", []) or []) if e]
            print(f"   {len(_search_cache[query])} results")
            return _search_cache[query]
        except Exception as e:
            print(f"Search failed: {e}")
            time.sleep(3)
    return []


def _installment_number(queries: list) -> Optional[str]:
    """The season/sequel number most queries name ("2" for "Edgerunners 2"), if at least half
    of them name it. Applied to every result, so a query that left the number out can't
    bring season 1 back in."""
    found = [m.group(1) for q in queries for m in [re.search(r"(?<![\w])([2-9])(?![\w])", q)] if m]
    if not found:
        return None
    n = max(set(found), key=found.count)
    return n if found.count(n) * 2 >= len(queries) else None


def _skip_reason(entry: dict, query: str, installment: Optional[str]) -> Optional[str]:
    """Why a search result can't be used, or None when it can."""
    duration = entry.get("duration") or 0
    if entry.get("is_live"):
        return "live"
    if "/shorts/" in (entry.get("url") or entry.get("webpage_url") or ""):
        return "Short"
    if duration and duration < MIN_RESULT_SECONDS:
        return "too short"
    if duration and duration > MAX_RESULT_SECONDS:
        return "too long"
    if installment and _wrong_installment(entry.get("title", ""), installment):
        return f"not part {installment}"
    if _third_party(entry, query):
        return "reaction/recap/comparison"
    return None


def search_pool(queries: list, used_video_ids: Optional[set] = None) -> list:
    """
    Search every query first, then rank all results together.

    Trying queries one by one gave each query two download slots, so a bad query
    ("King and Avida edit goes hard") burned two slow downloads while a good query's
    third result was never tried. Searching costs seconds, a download and Gemini check
    costs minutes, so the downloads now go to the best results across all queries.
    Re-uploads of the same video (same title once upload filler is dropped) count once.
    Returns entries, best first, each with "_score" and "_queries" added.
    """
    used_video_ids = used_video_ids if used_video_ids is not None else set()
    installment = _installment_number(queries)
    if installment:
        print(f"Queries ask for part {installment}: results without it are skipped")
    pool, skipped = {}, {}
    for query in queries:
        for pos, e in enumerate(_search(query)):
            vid = e.get("id")
            if not vid or vid in used_video_ids:
                continue
            reason = _skip_reason(e, query, installment)
            if reason:
                skipped[reason] = skipped.get(reason, 0) + 1
                continue
            score = _score_entry(e, query, pos)
            slot = pool.setdefault(vid, {"entry": e, "score": score, "queries": set(), "query": query})
            if score > slot["score"]:
                slot["score"], slot["query"] = score, query
            slot["queries"].add(query)
    if skipped:
        print(f"Skipped results: {', '.join(f'{n} {r}' for r, n in skipped.items())}")

    def total(slot):
        return slot["score"] + min(MULTI_QUERY_BONUS * (len(slot["queries"]) - 1), MAX_MULTI_QUERY_BONUS)

    ranked, keys = [], set()
    for slot in sorted(pool.values(), key=total, reverse=True):
        key = _title_key(slot["entry"].get("title", ""))
        if key in keys:
            continue   # a re-upload of a video already ranked higher
        keys.add(key)
        ranked.append({**slot["entry"], "_score": round(total(slot), 2), "_queries": len(slot["queries"]),
                       "_query": slot["query"]})

    trailers = [e for e in ranked if any(w in e.get("title", "").lower() for w in TRAILER_WORDS)]
    if len(trailers) > 1:
        extra = trailers[1:]
        ranked = [e for e in ranked if e not in extra] + extra

    # Each query names one moment of the script, so its best result goes first, in query
    # order: ranked by score alone, two red card clips filled the slots and the gesture
    # clip (tenth) was never checked. The rest follow by score.
    first = []
    for q in queries:
        pick = next((e for e in ranked if e["_query"] == q and e["_score"] >= MIN_FIRST_PICK_SCORE
                     and not any(e is f for f in first)), None)
        if pick:
            pick["_first_pick"] = True
            first.append(pick)
    ranked = first + [e for e in ranked if not any(e is f for f in first)]

    print(f"\n{len(ranked)} usable videos across {len(queries)} queries (* = best result of its query, checked first):")
    for e in ranked[:10]:
        print(f"   {'*' if e.get('_first_pick') else ' '}{e['_score']:5.1f}  ({e['_queries']} quer{'y' if e['_queries'] == 1 else 'ies'})  "
              f"{e.get('title', '')[:65]} ({e.get('duration') or '?'}s)")
    return ranked


def download_entry(e: dict, used_video_ids: Optional[set] = None) -> Optional[str]:
    """Download one search result (trimmed to MAX_SOURCE_SECONDS). Returns the path or None."""
    os.makedirs(VIDEO_MATERIAL_DIR, exist_ok=True)
    vid_id = e.get("id")
    title = _safe_title(e.get("title", "untitled"))
    webpage_url = e.get("webpage_url") or f"https://www.youtube.com/watch?v={vid_id}"
    if used_video_ids is not None:
        used_video_ids.add(vid_id)
    print(f"\nDownloading: {title}")
    print(f"   URL: {webpage_url}")

    filepath, heatmap = None, None
    # Cookie-less first; cookies only help with age-restricted videos.
    for use_cookies in (False, True):
        if filepath or (not use_cookies and _no_cookie_blocked):
            continue
        label = "with cookies" if use_cookies else "no cookies"
        filepath, heatmap = _try_download(f"Method 1: HD up to {MAX_HEIGHT}p ({label})",
                                          _make_opts_hd(skip_download=False, use_cookies=use_cookies),
                                          webpage_url, uses_cookies=use_cookies)
    if not filepath and not _no_cookie_blocked:
        time.sleep(3)
        filepath, heatmap = _try_download("Method 2: no cookies (720p)",
                                          _make_opts_no_cookies(skip_download=False),
                                          webpage_url, uses_cookies=False)
    if not filepath and not _no_cookie_blocked:
        filepath = _try_cli_download(vid_id, webpage_url)

    if filepath and os.path.exists(filepath):
        print(f"   Downloaded: {os.path.basename(filepath)} ({os.path.getsize(filepath) / (1024 * 1024):.2f} MB)")
        start = _best_window_start(heatmap, e.get("duration"), MAX_SOURCE_SECONDS)
        print(f"   Most replayed window starts at {start:.0f}s" if start else
              "   No most-replayed peak to use, keeping the opening")
        filepath = _trim_video_after_download(filepath, MAX_SOURCE_SECONDS, start)
        _write_source_meta(filepath, title, e.get("duration"), start)
        return filepath

    print(f"   All methods failed for: {vid_id}")
    latest = _find_latest_video()
    if latest and vid_id in latest:
        print(f"   Found partial download: {latest}")
        return latest
    return None


if __name__ == "__main__":
    import traceback

    print(f"yt-dlp version: {_get_yt_dlp_version()} (if downloads fail, run: pip install -U yt-dlp)")
    print(f"VIDEO_MATERIAL_DIR: {VIDEO_MATERIAL_DIR}")

    test_query = "thors cinematic 4k vinland saga"
    print(f"\nTesting download with query: {test_query}")

    try:
        pool = search_pool([test_query])
        path = download_entry(pool[0]) if pool else None
        results = [path] if path else []
        if results:
            print(f"\nDownloaded {len(results)} video(s):")
            for i, path in enumerate(results, 1):
                if os.path.exists(path):
                    size_mb = os.path.getsize(path) / (1024 * 1024)
                    print(f"   {i}. {os.path.basename(path)} ({size_mb:.2f} MB)")
        else:
            print("\nNo videos downloaded.")
    except Exception as e:
        print(f"\nTest failed: {e}")
        traceback.print_exc()
