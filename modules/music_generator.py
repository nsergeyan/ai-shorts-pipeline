import os
import random
import yt_dlp
from elevenlabs.client import ElevenLabs
from config import MUSIC_DIR, ELEVENLABS_API_KEY
from modules.video_material_fetcher import (
    POLITE_OPTS, _ErrorCollector, _short_error, no_cookie_blocked, youtube_cookie_opts,
)

MUSIC_LENGTH_MS = 90_000
MAX_MUSIC_SOURCE_SECONDS = 600
MUSIC_SEARCH_RESULTS = 5
MIX_SECTION = (60, 240)   # seconds kept from a long mix: past its intro, enough for any Short


def generate_music(prompt: str) -> str | None:
    """Generate instrumental music via ElevenLabs and save to MUSIC_DIR."""
    os.makedirs(MUSIC_DIR, exist_ok=True)

    client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

    filename = f"music_{random.randint(10000, 99999)}.mp3"
    output_path = os.path.join(MUSIC_DIR, filename)

    print("Generating music with ElevenLabs...")
    print(f"   Prompt: {prompt}")

    try:
        audio_stream = client.music.compose(
            prompt=prompt,
            music_length_ms=MUSIC_LENGTH_MS,
            force_instrumental=True,
            output_format="mp3_44100_128",
        )

        with open(output_path, "wb") as f:
            for chunk in audio_stream:
                f.write(chunk)

        if os.path.exists(output_path) and os.path.getsize(output_path) > 5000:
            size_mb = os.path.getsize(output_path) / (1024 * 1024)
            print(f"Music generated: {filename} ({size_mb:.2f} MB)")
            return output_path

    except Exception as e:
        print(f"ElevenLabs music generation failed: {e}")
        if os.path.exists(output_path):
            os.remove(output_path)

    # Returns None so the pipeline can continue without music
    return None


def fetch_music_from_youtube(query: str, skip_ids: set | None = None) -> str | None:
    """Search YouTube for the query and download the first result as an MP3 audio file.

    Results whose id is in `skip_ids` are passed over, and the downloaded id is added
    to it, so calling again with the same set gets the next result.

    Uses the same anti-bot setup as the video downloader: cookie-less first, then
    browser cookies, and straight to cookies once the run has hit YouTube's bot check.
    """
    os.makedirs(MUSIC_DIR, exist_ok=True)
    output_template = os.path.join(MUSIC_DIR, f"yt_music_{random.randint(10000, 99999)}")
    skip_ids = set() if skip_ids is None else skip_ids
    downloaded = []

    def _usable(info, *, incomplete=False):
        return "already tried" if info.get("id") in skip_ids else None

    def _section(info, _ydl):
        # Generic mood searches ("dark cyberpunk ambient") return only hour-long mixes.
        # Downloading all of one took minutes and was too long for Gemini, and skipping
        # them left nothing, so only a 3-minute stretch of a long mix is fetched.
        duration = info.get("duration") or 0
        if duration > MAX_MUSIC_SOURCE_SECONDS:
            yield {"start_time": MIX_SECTION[0], "end_time": MIX_SECTION[1]}
        else:
            yield {"start_time": 0, "end_time": duration or MAX_MUSIC_SOURCE_SECONDS}

    def _remember(d):
        if d.get("status") == "finished":
            downloaded.append(d.get("info_dict", {}).get("id"))

    base_opts = {
        "format": "bestaudio/best",
        "outtmpl": output_template + ".%(ext)s",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
        "noplaylist": True,
        "match_filter": _usable,
        "download_ranges": _section,
        "progress_hooks": [_remember],
        "max_downloads": 1,
        "quiet": True,
        "no_warnings": True,
        **POLITE_OPTS,
    }

    print(f"Fetching music from YouTube: '{query}'...")
    output_path = output_template + ".mp3"
    attempts = [True] if no_cookie_blocked() else [False, True]
    for use_cookies in attempts:
        log = _ErrorCollector()
        ydl_opts = {**base_opts, "logger": log, **(youtube_cookie_opts() if use_cookies else {})}
        label = "with cookies" if use_cookies else "no cookies"
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([f"ytsearch{MUSIC_SEARCH_RESULTS}:{query}"])
        except yt_dlp.utils.MaxDownloadsReached:
            pass   # raised after the first file is saved, it is the normal stop
        except Exception as e:
            log.errors.append(str(e))

        skip_ids.update(i for i in downloaded if i)
        if os.path.exists(output_path) and os.path.getsize(output_path) > 5000:
            size_mb = os.path.getsize(output_path) / (1024 * 1024)
            print(f"YouTube music downloaded ({label}): {os.path.basename(output_path)} ({size_mb:.2f} MB)")
            return output_path

        reason = _short_error(log.errors[-1]) if log.errors else "no usable file"
        print(f"   Music download ({label}) failed: {reason}")
        if os.path.exists(output_path):
            os.remove(output_path)

    return None


if __name__ == "__main__":
    test_prompt = "Epic orchestral cinematic music, dark and dramatic tension, slow build-up with strings and brass, anime battle lore atmosphere"
    path = generate_music(test_prompt)
    if path:
        print(f"Saved to: {path}")
    else:
        print("Music generation failed")
