import json
import os
import random
import re
import sys
import time
import traceback
import uuid
import subprocess
import itertools
from concurrent.futures import ThreadPoolExecutor
from google import genai
import ffmpeg

subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])

import config
from config import GEMINI_API_KEYS, DATA_DIR, CHANNELS_DIR
from modules.overlay_cropper import crop_overlays

if not GEMINI_API_KEYS:
    raise RuntimeError("GEMINI_API_KEYS is not set. Add it to your .env file.")

_key_pool = itertools.cycle(enumerate(GEMINI_API_KEYS, 1))
_exhausted_keys = set()   # key numbers whose daily limit is used up this run
_client_key = {}          # id(client) -> key number, to know which key hit a limit


class GeminiDailyQuota(Exception):
    """Every key's requests-per-day limit is used up. It resets after hours, not
    seconds, so retrying (and re-uploading the video for each retry) only wastes time."""


def _gemini_client():
    """Return a Gemini client using the next API key in the rotation pool that still has
    daily quota left. Raises GeminiDailyQuota when none does."""
    for _ in range(len(GEMINI_API_KEYS)):
        n, key = next(_key_pool)
        if n not in _exhausted_keys:
            break
    else:
        raise GeminiDailyQuota(
            f"all {len(GEMINI_API_KEYS)} Gemini keys have used up their free daily limit. "
            "Run again after the reset, or turn on billing for a project (much higher limits).")
    # numbered, because every key starts with the same "AQ.Ab8RN" and the log looked like one key
    print(f"Gemini key {n}/{len(GEMINI_API_KEYS)}")
    client = genai.Client(api_key=key)
    _client_key[id(client)] = n
    return client

def _on_quota_hit(client, what, attempt, error=None):
    """
    Handle a Gemini 429 (rate limit). With several keys, switch to the next one; its
    files must then be uploaded again, so the caller re-uploads when this returns True.
    With one key, "switching" gave back the same key and re-uploaded every video for
    nothing (minutes per hit), so just wait for the per-minute limit to reset instead.
    A daily limit is different: that key is done for hours, so it is set aside for the
    rest of the run and the next key that still has quota takes over. Before, all four
    used-up keys were retried in turn, re-uploading a 150 MB video each time.
    GeminiDailyQuota is raised once every key is used up.
    Returns (client, switched).
    """
    if error is not None and re.search(r"PerDay|per day", str(error)):
        n = _client_key.get(id(client))
        if n is not None:
            _exhausted_keys.add(n)
        wait = re.search(r"retry in (\d+h)?(\d+m)?", str(error))
        reset = f", resets in {''.join(g for g in wait.groups() if g)}" if wait and any(wait.groups()) else ""
        left = len(GEMINI_API_KEYS) - len(_exhausted_keys)
        print(f"Gemini key {n}/{len(GEMINI_API_KEYS)} used up its daily limit ({what}{reset}), "
              f"{left} key(s) left")
        return _gemini_client(), True   # raises GeminiDailyQuota when no key is left
    if len(GEMINI_API_KEYS) > 1:
        print(f"Gemini 429 ({what}), switching key... (attempt {attempt})")
        time.sleep(5)
        return _gemini_client(), True
    wait = 20 * attempt
    print(f"Gemini 429 ({what}), rate limited, waiting {wait}s... (attempt {attempt})")
    time.sleep(wait)
    return client, False


def _state_name(file_info):
    """Gemini returns a FileState enum; normalize it to a plain string like 'ACTIVE'."""
    state = getattr(file_info, "state", None)
    return getattr(state, "name", str(state)).upper()


def _wait_for_active(client, file_name, label="File", timeout=300):
    """Poll a Gemini file until it is ACTIVE.

    FAILED is terminal: a corrupt or truncated upload never becomes ACTIVE, so
    raise instead of looping forever. The timeout is a backstop for a file that
    never leaves PROCESSING.
    """
    file_info = client.files.get(name=file_name)
    deadline = time.time() + timeout
    poll_errors = 0
    while _state_name(file_info) != "ACTIVE":
        state = _state_name(file_info)
        if state == "FAILED":
            raise RuntimeError(f"{label} failed to process on Gemini (corrupt or truncated upload)")
        if time.time() > deadline:
            raise RuntimeError(f"{label} still {state} after {timeout}s on Gemini")
        print(f"{label} state: {state}, waiting...")
        time.sleep(2)
        try:
            file_info = client.files.get(name=file_name)
            poll_errors = 0
        except Exception as e:
            if any(code in str(e) for code in ("500", "INTERNAL", "503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED")):
                poll_errors += 1
                print(f"Gemini transient error polling {label} ({poll_errors}/10), retrying...")
                if poll_errors >= 10:
                    raise RuntimeError(f"{label} stuck in PROCESSING with repeated transient errors") from e
            else:
                raise
    print(f"{label} ACTIVE")
    return file_info


def _upload_and_wait(client, path, label=None):
    """Upload a file to Gemini and block until ACTIVE, retrying transient 500s.

    Files are scoped to the API key/project that uploaded them, so any file
    handle must be re-created after rotating to a different key.
    """
    uf = client.files.upload(file=path)
    print(f"Uploaded {label or os.path.basename(path)}: {uf.name}")
    _wait_for_active(client, uf.name, label=label or os.path.basename(path))
    return uf


class _EmptyReply(Exception):
    """Gemini answered without any text: a safety block, or thinking used up the output budget."""


def _require_text(response):
    """Return the response, or raise _EmptyReply when it has no text, so the retry
    loops ask again instead of parsing None (an empty reply once rejected a good video)."""
    if getattr(response, "text", None):
        return response
    try:
        reason = response.candidates[0].finish_reason
    except Exception:
        reason = getattr(getattr(response, "prompt_feedback", None), "block_reason", None)
    raise _EmptyReply(f"Gemini returned no text (finish reason: {getattr(reason, 'name', reason)})")


def _who_is_who(look):
    """
    Prompt lines that stop Gemini from guessing who unfamiliar names are.

    Gemini 2.5 Flash had never heard of Edgerunners 2's King and Avida, so it decided
    they were David and Lucy and approved a teaser without them. Telling it "whoever
    doesn't match the description is not them" went too far the other way: it couldn't
    name anyone in season 2 footage and rejected eleven of twelve videos. So the title
    and the description guide it, and only clear evidence of another show rejects.
    The description is often just one scene (the sports prompt writes the opening shot,
    "Messi stepping off a private jet"), so it only helps tell who is who; a clip of a
    different scene must never fail for not matching it.
    """
    if not look:
        return ""
    return ("WHO IS WHO: the script may name characters or people newer than your training data, so you "
            "may not recognise them. Never call them by the names of characters you already know (an older "
            "season's cast is not the new cast). Use the video's title and this description to recognise "
            f'them: "{look}". The description shows only SOME of the footage, often one scene: use it to '
            "tell who is who, and never reject a shot because it shows a different scene, place or outfit. "
            "Not being able to put a name to a face is NOT a reason to reject: footage from the right show "
            "and season whose title names the subject counts as the subject. The video's title, not the "
            "faces you think you recognise, decides the season: new characters look like the old cast you "
            "know, so never reject footage as 'the old cast'. Reject only footage that clearly comes from "
            "another show, sport or story.")


try:
    from modules.video_material_fetcher import search_pool, download_entry
    from modules.music_generator import generate_music, fetch_music_from_youtube
    from modules.newvoice import generate_voice
    from modules.video_editor import (merge_audio_video, render_thumbnail, append_thumbnail_frame,
                                      sfx_library, pick_sfx, sfx_play_seconds, splice_silence, find_silences,
                                      _probe_duration, SHORTS_CAP_SECONDS)
    from modules.transcriber import transcribe_audio_to_words
except ImportError as e:
    print(f"Error importing modules: {e}")
    sys.exit(1)

LANGUAGE = "en"
MUSIC_LUFS = -34.0                 # music loudness target; voice sits near -17.5, lower = quieter music
CLEANUP_FILES = True
MIN_CLIP_DURATION = 3.0
MIN_SEGMENT_DURATION = 4.0        # shorter segments = a new shot every ~4s instead of every ~10s
MAX_CLIPS = 8
MAX_CANDIDATES = 10                # most videos downloaded and checked per run (best across all queries first)
MAX_SOURCE_VIDEOS_CAP = 5          # first picks may push approvals past 3, never past this
MAX_DOWNLOAD_FAILURES = 4          # stop after this many failed downloads in a row (YouTube is blocking)
MAX_MUSIC_QUERIES = 3              # how many free YouTube tracks to try before paying ElevenLabs
# Each model has its own free daily limit, so the jobs are spread over three of them.
# In a side-by-side test 3.6 spotted a Guardian news edit that 2.5 approved.
GEMINI_MODEL = "gemini-3.6-flash"              # watches video: evaluation, edit plan, thumbnail
GEMINI_CHECK_MODEL = "gemini-3.5-flash-lite"   # still-frame checks, the most frequent call
GEMINI_MUSIC_MODEL = "gemini-2.5-flash"        # music check
EMBED_THUMBNAIL_FRAME = True       # burn the thumbnail as a still frame so YouTube can use it as the cover
THUMBNAIL_FRAME_POSITION = "end"   # "start" = auto cover (0.25s freeze first); "end" = clean hook, pick cover manually
THUMBNAIL_FRAME_DURATION = 0.25    # seconds the thumbnail frame stays on screen
GRAPHIC_TYPES = ("stat", "versus", "list", "quote")

# Used when MANUAL_DATA has no "channel", and as the base each channels/<name>.json overrides.
DEFAULT_CHANNEL = {
    "voice_name": "animatoryoung",
    "theme": {"accent": "#FFE000", "panel": "rgba(10, 10, 14, 0.82)", "text": "#FFFFFF"},
    "frame_background": "blur",        # "blur" = blurred copy of the clip, "dark" = plain dark backdrop
    "allow_full_layout": True,         # let Gemini crop close-ups to fill the whole screen
    "graphic_types": list(GRAPHIC_TYPES),
}

MANUAL_DATA = {
"channel": "anime",
"topic": "Cyberpunk Edgerunners 2",
"specific_subject": "Capri is built on Soulkiller, a program whose inventor Alt Cunningham was kidnapped by Arasaka in 2013 and became its first victim",
"title": "Who really made Capri in Cyberpunk Edgerunners 2?",
"hook": "Who really made Capri?",
"youtube_queries": ["Cyberpunk Edgerunners 2 D Capri scene", "Cyberpunk Edgerunners 2 Talia Capri goes hard", "Cyberpunk Edgerunners 2 Capri 4k", "Cyberpunk Edgerunners 2 episode 3 D datashard", "Cyberpunk Edgerunners 2 Capri english dub", "Cyberpunk Edgerunners 2 official trailer"],
"scene_query": "A black-haired young man with a green cybernetic eye clutches his head as glowing red code and a ghostly digital girl swirl around him, city lights flicker and explode, then a teenage girl with heavy chrome implants floats over a burning neon city wrapped in a shell of twisted metal",
"footage_source": "official_or_press",
"music_mood": "mysterious",
"music_queries": ["Cyberpunk 2077 Never Fade Away instrumental", "Cyberpunk Edgerunners 2 OST", "dark cyberpunk ambient instrumental no copyright"],
"music_prompt": "Dark atmospheric synthwave with a cold industrial edge, 88 BPM. Deep pulsing analog synth bass for a sci-fi cyberpunk feel, glitchy digital textures like corrupted data, and a lonely detuned electric piano melody. Quiet uneasy tension at the start, a sudden low drop and swelling pad at the big reveal around second twenty five, a brief dry lighter beat for a sarcastic joke, then a sad fading synth line for the reflective ending. short-form video background, no lyrics, exclude: upbeat pop drums, bright cheerful brass",
"voice_name": "animatoryoung",
"spoken_word_count": 98,
"script": "[curious] Who really made Capri? We all remember the ghost girl in D's datashard. The show says Kyoko built her for Arasaka. [thoughtful] But Capri is made of engrams, copies of real human minds, and Arasaka makes those with one program... Soulkiller. Game lore says a netrunner named Alt Cunningham invented it. In twenty thirteen, Arasaka *kidnapped:wrong* her and forced her to rebuild it. Its own creator became its first *victim:boom*. [deadpan] Arasaka saw a program that ate its inventor and said, great, let's build *soldiers:meme* with it. [softly] So who really made Capri? A woman Arasaka stole sixty five years ago."
}


def load_channel(name):
    """Return DEFAULT_CHANNEL with channels/<name>.json layered on top (theme merged key by key)."""
    channel = {**DEFAULT_CHANNEL, "theme": dict(DEFAULT_CHANNEL["theme"])}
    if not name:
        return channel
    path = os.path.join(CHANNELS_DIR, f"{name}.json")
    try:
        with open(path) as f:
            overrides = json.load(f)
    except FileNotFoundError:
        print(f"No channel config at {path}, using defaults")
        return channel
    channel["theme"].update(overrides.pop("theme", {}))
    channel.update(overrides)
    print(f"Channel: {name}")
    return channel


def _norm_word(word: str) -> str:
    return word.strip(".,!?;:\"'—…*()").lower()


def _punch_key(word: str):
    """Comparable form of a punch word. Numbers compare by value, because the script
    spells them out for TTS ("fifteen") while Whisper writes digits ("$15")."""
    nums = _numbers_in_text(word)
    return nums.pop() if len(nums) == 1 else _norm_word(word)


_MARKER = re.compile(r'\*([^*]+)\*')


def _split_marker(inner: str):
    """'sprayed:sad' -> ('sprayed', 'sad'); 'stairs' -> ('stairs', None).
    The tag must be letters only, so a time like *10:30* stays a plain word."""
    m = re.fullmatch(r'(.+?):([A-Za-z_]+)', inner.strip())
    return (m.group(1), m.group(2).lower()) if m else (inner, None)


def _strip_punch_markers(script: str):
    """Strip *word* and *word:tag* markers from script.
    Returns (clean_script, [(word, n, tag), ...]); tag is None for a plain *word*,
    which makes no sound (only tagged words get one).
    n is which copy of the word was marked (0 = first time it appears in the script),
    so a marked second "dead" doesn't get matched to the first one.
    The word content (e.g. BUT!) stays in the script for TTS emphasis; the asterisks
    and the :tag are removed, so a tag never reaches ElevenLabs."""
    punch_words = []
    def _unmark(text):
        return _MARKER.sub(lambda m: _split_marker(m.group(1))[0], text)
    def _replace(m):
        spoken, tag = _split_marker(m.group(1))
        word = _punch_key(spoken)
        n = sum(1 for w in _unmark(script[:m.start()]).split() if _punch_key(w) == word)
        punch_words.append((word, n, tag))
        return spoken
    clean_script = _MARKER.sub(_replace, script)
    return clean_script, punch_words


def _check_sfx_tags(punch_words: list):
    """Stop before any download or API call if a tag is wrong or over a limit,
    so a typo costs one second instead of ten minutes and API quota."""
    plain = [str(w) for w, _n, t in punch_words if not t]
    if plain:
        print(f"Plain *word* markers make no sound, only *word:tag* does: {plain}")
    tags = [t for _w, _n, t in punch_words if t]
    if not config.SFX_ENABLED:
        return
    if len(tags) < config.SFX_MIN_TAGGED:
        print(f"WARNING: only {len(tags)} tagged sound(s), the prompt asks for at least {config.SFX_MIN_TAGGED}")
    if not tags:
        return
    library = sfx_library()
    allowed = [t for t in config.SFX_PICTURE_TAGS + config.SFX_AFTER_TAGS if library.get(t)]
    errors = []
    for t in tags:
        if t not in config.SFX_PICTURE_TAGS + config.SFX_AFTER_TAGS:
            errors.append(f"unknown tag '{t}'")
        elif not library.get(t):
            errors.append(f"tag '{t}' has no files in {config.SFX_LIBRARY_DIR}/{t}")
    if len(tags) > config.SFX_MAX_TAGGED:
        errors.append(f"{len(tags)} tagged sounds, max {config.SFX_MAX_TAGGED}")
    after = [t for t in tags if t in config.SFX_AFTER_TAGS]
    if len(after) > config.SFX_MAX_AFTER:
        errors.append(f"{len(after)} after reactions {after}, max {config.SFX_MAX_AFTER}")
    rare = [t for t in tags if t in config.SFX_RARE_TAGS]
    if len(rare) > config.SFX_MAX_RARE:
        errors.append(f"{len(rare)} rare tags {rare}, max {config.SFX_MAX_RARE}")
    repeated = sorted({t for t in tags if tags.count(t) > 1})
    if repeated:
        errors.append(f"tag(s) {repeated} used more than once, each tag once per script")
    big = [t for t in tags if t in config.SFX_BIG_TAGS]
    if len(big) > config.SFX_MAX_BIG:
        errors.append(f"{len(big)} big tags {big}, max {config.SFX_MAX_BIG} of {list(config.SFX_BIG_TAGS)}")
    if errors:
        print("Sound effect tags in the script are wrong:")
        for e in errors:
            print(f"  - {e}")
        print(f"Allowed tags: picture {[t for t in config.SFX_PICTURE_TAGS if t in allowed]}, "
              f"after {[t for t in config.SFX_AFTER_TAGS if t in allowed]}")
        sys.exit(1)
    print(f"Sound effect tags OK: {tags}")


_CURRENCY = {"pound": "£", "pounds": "£", "dollar": "$", "dollars": "$", "euro": "€", "euros": "€"}


def _marker_index(target, n: int, words_data: list):
    """Index in words_data of the nth copy of a marked word, or None."""
    hits = [i for i, (word, _s, _e) in enumerate(words_data) if _punch_key(word) == target]
    if not hits and target in _CURRENCY:
        # Whisper writes "fifty thousand pounds" as "£50,000": the word becomes a symbol
        hits = [i for i, (word, _s, _e) in enumerate(words_data) if _CURRENCY[target] in word]
    if not hits:
        return None
    # Whisper can drop a word, so fall back to the last copy it heard
    return hits[min(n, len(hits) - 1)]


def _sentence_pause(silences: list, word_start: float, word_end: float, reach: float = 1.2) -> float:
    """
    Where to splice a reaction's pause after a sentence's last word: inside the
    longest real pause between that word's Whisper start and `reach` seconds past
    its Whisper end (the sentence-end pause is the longest one around there).
    Falls back to the Whisper end time when the audio has no pause in that range.
    """
    near = [(a, b) for a, b in silences if b > word_start and a < word_end + reach]
    if not near:
        print(f"No pause found after {word_end:.2f}s, splicing at the Whisper end time")
        return word_end
    a, b = max(near, key=lambda g: g[1] - g[0])
    # a little into the pause, so the word's tail is never cut off
    return round(max(a, word_start) + min(0.05, (b - a) / 2), 3)


def _place_tagged_sfx(punch_words: list, words_data: list, audio_path: str, seed: str):
    """
    Pick a file for every *word:tag* and decide when it plays.

    picture: on the tagged word's start, under the voice.
    after:   SFX_AFTER_GAP after the end of the sentence holding the word, in a
             pause of SFX_AFTER_GAP + the effect's length spliced into the
             narration. Files in SFX_VOICE_FILES always count as after.
    The splice shifts every later word, so this returns the shifted
    words_data: run it before segment_by_sentences and everything downstream
    (clips, cards, subtitles) uses the new timeline.
    Returns (words_data, [{time, path, kind, tag, duration}]).
    """
    library = sfx_library()
    placed, counts = [], {}
    for target, n, tag in punch_words:
        if not tag:
            continue
        i = _marker_index(target, n, words_data)
        if i is None:
            print(f"Sound effect word '{target}' ({tag}) not found in transcript, skipping")
            continue
        path = pick_sfx(library[tag], seed, tag, counts.get(tag, 0))
        counts[tag] = counts.get(tag, 0) + 1
        voice = os.path.basename(path) in config.SFX_VOICE_FILES
        kind = "after" if tag in config.SFX_AFTER_TAGS or voice else "picture"
        placed.append({"index": i, "path": path, "kind": kind, "tag": tag,
                       "duration": sfx_play_seconds(path)})

    # Each after sound waits for the end of its sentence (same rule as segment_by_sentences).
    # Whisper's word ends can run half a second early, so the splice goes into the
    # real pause the audio has there, not at Whisper's end time: cutting at the
    # Whisper time once split "real de- [awww] -feat" in half.
    silences = find_silences(audio_path) if any(s["kind"] == "after" for s in placed) else []
    for s in placed:
        if s["kind"] != "after":
            continue
        j = s["index"]
        while j < len(words_data) - 1 and not words_data[j][0].rstrip().endswith(('.', '?', '!')):
            j += 1
        s["end_index"] = j
        s["at"] = _sentence_pause(silences, words_data[j][1], words_data[j][2])
        s["pause"] = config.SFX_AFTER_GAP + s["duration"]

    after = sorted((s for s in placed if s["kind"] == "after"), key=lambda s: s["at"])
    if after:
        splice_silence(audio_path, [(s["at"], s["pause"]) for s in after])
        # Shift by position, not by time: every word after a sentence that got a
        # pause moves by that pause, whatever Whisper said its time was.
        words_data = [
            (w, round(a + shift, 3), round(b + shift, 3))
            for k, (w, a, b) in enumerate(words_data)
            for shift in [sum(s["pause"] for s in after if s["end_index"] < k)]
        ]
        added = sum(s["pause"] for s in after)
        new_dur = _probe_duration(audio_path)
        print(f"Spliced {len(after)} pause(s) into the narration at "
              f"{[round(s['at'], 2) for s in after]}s, +{added:.2f}s, now {new_dur:.1f}s")
        if new_dur > SHORTS_CAP_SECONDS:
            print(f"WARNING: narration is now past the {SHORTS_CAP_SECONDS}s Shorts cap, the end will be cut")

    tagged = []
    for s in placed:
        if s["kind"] == "picture":
            when = words_data[s["index"]][1]
        else:
            # the effect starts in its own pause: after every pause spliced in before it
            when = s["at"] + sum(o["pause"] for o in after[:after.index(s)]) + config.SFX_AFTER_GAP
        tagged.append({"time": round(when, 3), "path": s["path"], "kind": s["kind"],
                       "tag": s["tag"], "duration": s["duration"]})
    tagged.sort(key=lambda s: s["time"])

    after_times = [s["time"] for s in tagged if s["kind"] == "after"]
    for a, b in zip(after_times, after_times[1:]):
        if b - a < config.SFX_MIN_AFTER_GAP_SECONDS:
            print(f"WARNING: reactions at {a:.1f}s and {b:.1f}s are under "
                  f"{config.SFX_MIN_AFTER_GAP_SECONDS:.0f}s apart")
    return words_data, tagged


def _ffprobe_fails(path):
    try:
        ffmpeg.probe(path)
        return False
    except Exception:
        return True


def trim_video_to_end(
    input_file,
    output_file,
    ai_start,
    prepad=0.02,
    max_duration=61.0,
    crop=None,
):
    """Trim from just before the AI-picked timestamp, up to max_duration but never past the end.

    `crop` is an ffmpeg crop string from _detect_crop() that removes baked-in black bars.
    """
    info = ffmpeg.probe(input_file)

    video_stream = next(
        s for s in info["streams"]
        if s["codec_type"] == "video"
    )

    video_duration = float(video_stream["duration"])

    clip_start = max(float(ai_start) - prepad, 0.0)
    clip_start = min(clip_start, video_duration - 0.001)

    # If not enough footage remains after ai_start, back up the start
    # so we still get the full requested duration (avoids tiny tail clips
    # that force video_editor to loop-repeat one clip at the end).
    if video_duration >= max_duration and clip_start + max_duration > video_duration:
        clip_start = video_duration - max_duration

    clip_end = min(clip_start + max_duration, video_duration)
    clip_duration = clip_end - clip_start

    if clip_duration <= 0:
        print("Invalid clip duration. Skipping.")
        return False

    subprocess.run([
        "ffmpeg",
        "-ss", str(clip_start),
        "-i", input_file,
        "-t", str(clip_duration),
        *(["-vf", f"crop={crop}"] if crop else []),
        "-c:v", "libx264",
        "-preset", "veryfast",
        # Remotion re-encodes this clip again, so keep this pass close to lossless.
        "-crf", "18",
        "-c:a", "aac",
        "-movflags", "+faststart",
        output_file
    ], check=True)

    print(f"Trimmed clip saved: {output_file} ({clip_duration:.2f}s from {clip_start:.2f}s to {clip_end:.2f}s)")


def _read_source_meta(video_path):
    """Load the .meta.json sidecar the fetcher writes next to each download ({} if missing)."""
    try:
        with open(os.path.splitext(video_path)[0] + ".meta.json") as f:
            return json.load(f)
    except Exception:
        return {}


def _remove_sidecars(video_path):
    base = os.path.splitext(video_path)[0]
    for ext in (".title.txt", ".meta.json"):
        if os.path.exists(base + ext):
            try:
                os.remove(base + ext)
            except Exception:
                pass


SCENE_CUT_THRESHOLD = 0.3   # ffmpeg scene-change score (0-1) that counts as a hard cut
FLASH_SHOT = 1.0            # a shot shorter than this is a flash frame, not a place to start a clip


def _find_shot_cuts(video_path, start, end):
    """Return timestamps of hard cuts between start and end using ffmpeg's scene-change score."""
    start = max(start, 0.0)
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-ss", f"{start:.3f}", "-i", video_path, "-t", f"{end - start:.3f}",
         "-an", "-vf", f"scale=320:-2,select='gt(scene,{SCENE_CUT_THRESHOLD})',showinfo",
         "-f", "null", "-"],
        capture_output=True, text=True, timeout=60,
    )
    # With -ss before -i, showinfo times are relative to the seek point.
    return [start + float(t) for t in re.findall(r"pts_time:([\d.]+)", result.stderr)]


def _snap_to_shot_cut(video_path, start, max_back=1.5, max_forward=0.7):
    """Move a clip start onto a nearby hard cut so the clip opens on a clean shot.

    Gemini sees video at about 1 frame per second, so its timestamps can land a few
    frames before a cut, which shows up as a flash of the previous shot.
    - A cut just AFTER start means we are in the tail of the previous shot: jump forward to it.
    - Otherwise a cut just BEFORE start is where this shot begins: back up to it.
    """
    try:
        cuts = _find_shot_cuts(video_path, start - max_back, start + max_forward + 2 * FLASH_SHOT)
    except Exception as e:
        print(f"Shot-cut detection failed, keeping {start:.2f}s: {e}")
        return start

    after = [c for c in cuts if start < c <= start + max_forward]
    before = [c for c in cuts if c <= start]
    if after:
        snapped = after[0]
    elif before:
        snapped = before[-1]
    else:
        return start
    # Trailers flash several shots in a row. Starting on one that lasts 0.1s showed a
    # one-frame blip and cancelled the planned full-screen layout, so skip past it.
    while flashes := [c for c in cuts if snapped < c < snapped + FLASH_SHOT]:
        snapped = flashes[-1]

    snapped = round(snapped + 0.02, 2)   # just past the cut so frame one is the new shot
    print(f"Snapped clip start {start:.2f}s → {snapped:.2f}s (shot cut)")
    return snapped


def _detect_crop(video_path):
    """Find baked-in black bars (letterbox / pillarbox) and return an ffmpeg crop string, or None.

    Samples several points and keeps the union of what cropdetect reports, so one
    dark scene can't trick it into cutting into the real picture. A side is only
    cropped when the bars are roughly symmetric, which real bars always are.
    """
    try:
        info = ffmpeg.probe(video_path)
        vs = next(s for s in info["streams"] if s["codec_type"] == "video")
        width, height = int(vs["width"]), int(vs["height"])
        duration = float(info["format"]["duration"])
    except Exception:
        return None

    boxes = []
    for frac in (0.2, 0.4, 0.6, 0.8):
        try:
            result = subprocess.run(
                ["ffmpeg", "-hide_banner", "-ss", f"{duration * frac:.2f}", "-i", video_path, "-t", "2",
                 "-an", "-vf", "cropdetect=limit=24:round=2:reset=0", "-f", "null", "-"],
                capture_output=True, text=True, timeout=60,
            )
        except Exception:
            continue
        found = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", result.stderr)
        if not found:
            continue
        w, h, x, y = map(int, found[-1])
        if w * h >= 0.3 * width * height:   # a nearly black sample (fade) says nothing
            boxes.append((x, y, x + w, y + h))

    if not boxes:
        return None

    x1, y1 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x2, y2 = max(b[2] for b in boxes), max(b[3] for b in boxes)

    left, right, top, bottom = x1, width - x2, y1, height - y2
    if abs(left - right) > 0.04 * width or left + right < 0.03 * width:
        x1, x2 = 0, width
    if abs(top - bottom) > 0.04 * height or top + bottom < 0.03 * height:
        y1, y2 = 0, height

    if (x1, y1, x2, y2) == (0, 0, width, height):
        return None

    # H.264 needs even dimensions.
    cw, ch = (x2 - x1) // 2 * 2, (y2 - y1) // 2 * 2
    crop = f"{cw}:{ch}:{x1}:{y1}"
    print(f"Black bars found in {os.path.basename(video_path)}: cropping {width}x{height} → {cw}x{ch}")
    return crop


def evaluate_youtube_music_with_genai(music_path: str, topic: str, script_text: str) -> dict:
    """Evaluate YouTube-sourced music: checks for lyrics, topic fit, and voice compatibility."""
    client = _gemini_client()

    uploaded_file = client.files.upload(file=music_path)
    print(f"Uploaded YouTube music: {uploaded_file.name}")

    _wait_for_active(client, uploaded_file.name, label="YouTube music")

    prompt = f"""
    You are evaluating background music sourced from YouTube for a short-form vertical video.


    TOPIC: "{topic}"

    SCRIPT:
    \"\"\"{script_text}\"\"\"

    SCORING CRITERIA:

    1. Lyrics Check (has_lyrics: true/false)
       Does this audio contain ANY sung vocals or rapped/spoken lyrics?
       - true  → there are clear singing or rapping vocals in the music
       - false → purely instrumental, no vocals at all

    2. Topic Relevance (topic_score: 1–10)
       How well does this music match the video topic?
       9–10: Recognizable OST / soundtrack directly tied to the topic
       7–8 : Fits the mood and theme well
       5–6 : Loosely related
       1–4 : Wrong style or unrelated

    3. Voice Compatibility (voice_score: 1–10)
       Would this sit cleanly under narration without drowning it out?
       9–10: Perfect background, won't compete with narrator
       7–8 : Good, can work at low volume
       5–6 : Somewhat busy but usable
       1–4 : Too loud, too chaotic, or too distracting

    4. Blocked Anthem Check (is_league_anthem: true/false)
       true → this is the official anthem, theme or broadcast music of a sports league, tournament or
       broadcaster (UEFA Champions League anthem, FIFA anthem, Formula 1 theme, Premier League theme...),
       or a remix, cover or trap/phonk version of one. Their owners block videos that use them.
       Film, game and anime soundtracks do NOT count here.

    DECISION RULES:
    - "use"    → has_lyrics=false AND is_league_anthem=false AND topic_score >= 7 AND voice_score >= 6
    - "reject" → has_lyrics=true OR is_league_anthem=true OR topic_score < 7 OR voice_score < 6

    Return ONLY valid JSON, no markdown:
    {{
      "has_lyrics": <true|false>,
      "is_league_anthem": <true|false>,
      "topic_score": <1-10>,
      "voice_score": <1-10>,
      "decision": "use" | "reject",
      "reason": "<one short sentence>"
    }}
    """

    max_attempts = 5
    for attempt in range(1, max_attempts + 1):
        try:
            response = _require_text(client.models.generate_content(
                model=GEMINI_MUSIC_MODEL,
                contents=[uploaded_file, prompt],
                config={"response_mime_type": "application/json"},
            ))
            break
        except Exception as e:
            if isinstance(e, _EmptyReply):
                print(f"{e} (music eval), retrying... ({attempt}/{max_attempts})")
                time.sleep(5)
            elif "503" in str(e):
                print(f"Gemini 503 on music eval, retrying in 20s... ({attempt}/{max_attempts})")
                time.sleep(20)
            elif "429" in str(e):
                client, switched = _on_quota_hit(client, "music eval", attempt, e)
                if switched:
                    uploaded_file = _upload_and_wait(client, music_path, label="YouTube music")
            else:
                raise
        if attempt == max_attempts:
            raise RuntimeError("Gemini music eval failed after max retries.")

    raw_text = response.text if hasattr(response, "text") else str(response)

    try:
        clean_text = raw_text.strip()
        if not clean_text.startswith("{"):
            clean_text = clean_text[clean_text.find("{"):]
        if not clean_text.endswith("}"):
            clean_text = clean_text[:clean_text.rfind("}") + 1]
        return json.loads(clean_text)
    except Exception as e:
        print(f"Failed to parse YouTube music eval JSON: {e}")
        print("Raw:", raw_text)
        return {"has_lyrics": True, "topic_score": 0, "voice_score": 0, "decision": "reject", "reason": "parse error"}


def _clean_music_queries(value) -> list:
    """Normalise music_queries into a list of usable strings (accepts a bare string too)."""
    if not value:
        return []
    if isinstance(value, str):
        value = [value]
    cleaned = []
    for q in value:
        q = str(q).strip()
        if q and q.lower() not in ("null", "none"):
            cleaned.append(q)
    return cleaned


MUSIC_TRACKS_PER_QUERY = 2   # one too-busy first result used to throw away the whole query
INSTRUMENTAL_WORDS = ("instrumental", "no lyrics", "no vocals", "karaoke", "ost", "soundtrack",
                      "ambient", "beat", "no copyright", "background music")


def _instrumental_query(query):
    """Add "instrumental" to a query with no word that keeps singing out: a bare song
    name returns the song with vocals, and Gemini rejects it."""
    q = query.lower()
    return query if any(w in q for w in INSTRUMENTAL_WORDS) else f"{query} instrumental"


def _try_youtube_track(query, tried_ids, topic, script_text):
    """Download the next untried result of `query` and let Gemini judge it.
    Returns (path or None, downloaded): the path when approved, downloaded False when
    nothing new could be fetched, so the caller moves on to the next query."""
    yt_path = fetch_music_from_youtube(query, tried_ids)
    if not yt_path:
        return None, False

    print("Evaluating YouTube music with Gemini...")
    try:
        result = evaluate_youtube_music_with_genai(yt_path, topic, script_text)
        reason = result.get("reason", "")
        if result.get("is_league_anthem"):
            reason = f"league anthem, gets videos blocked. {reason}"
        elif result.get("decision") == "use":
            print(f"YouTube music approved: {reason}")
            return yt_path, True
        print(f"YouTube music rejected ({reason})")
    except Exception as e:
        print(f"Gemini music eval error: {e}")

    if os.path.exists(yt_path):
        os.remove(yt_path)
    return None, True


def _resolve_music(music_queries, music_prompt: str, topic: str, script_text: str) -> str | None:
    """Try the first results of each YouTube music query in order; only pay for ElevenLabs
    if every one is rejected."""
    queries = [_instrumental_query(q) for q in _clean_music_queries(music_queries)[:MAX_MUSIC_QUERIES]]
    tried_ids = set()

    for i, query in enumerate(queries, 1):
        for track in range(1, MUSIC_TRACKS_PER_QUERY + 1):
            print(f"Music candidate {i}/{len(queries)}, track {track}: '{query}'")
            path, downloaded = _try_youtube_track(query, tried_ids, topic, script_text)
            if path:
                return path
            if not downloaded:
                print("Music download failed, trying next query")
                break

    if queries:
        print("No YouTube music approved, falling back to ElevenLabs")
    return generate_music(music_prompt)


def _prepare_narration(script_text: str, voice_name: str, punch_words: list, sfx_seed: str):
    """Voice, word timestamps and tagged sound effects. Needs only the script, so it runs
    in the background while footage is searched. Returns (audio_path, words_data, tagged_sfx)."""
    print(f"Generating voice ({voice_name})...")
    audio_filename = f"narration_{random.randint(1000, 9999)}.mp3"
    audio_path = generate_voice(script_text, audio_filename, voice_name, LANGUAGE)

    print("Transcribing for scene sync...")
    if LANGUAGE == "es":
        print("Spanish detected, skipping subtitles.")
        words_data = None
    else:
        words_data = transcribe_audio_to_words(audio_path, LANGUAGE, script_text)

    tagged_sfx = []
    if config.SFX_ENABLED and any(t for _w, _n, t in punch_words):
        if words_data:
            words_data, tagged_sfx = _place_tagged_sfx(punch_words, words_data, audio_path, sfx_seed)
        else:
            print("No word timestamps, skipping tagged sound effects")
    return audio_path, words_data, tagged_sfx


def _subject_only(evaluation, shown):
    """True when a rejected video is clean, real footage of the subject that just shows
    none of the script items: worth keeping as a backup source instead of deleting."""
    share = evaluation.get("subject_share")
    return (evaluation.get("subject_present") is True and not shown
            and (evaluation.get("relevance_score") or 0) >= 7
            and (evaluation.get("technical_score") or 0) >= 6
            and (evaluation.get("hook_score") or 0) >= 5
            and not (isinstance(share, (int, float)) and share < MIN_SUBJECT_SHARE))


def _video_title(video_path):
    """The YouTube title saved next to a download, or the file name."""
    title_file = os.path.splitext(video_path)[0] + ".title.txt"
    if os.path.exists(title_file):
        with open(title_file) as tf:
            return tf.read().strip()
    return os.path.basename(video_path)


def _labeled_videos(uploaded_files, video_paths):
    """Contents for a multi-video call: a 'Video i' label right before each file.
    Without the labels Gemini has to guess which file is which, and it mixed them
    up: it described a shot from Video 0 and returned it as Video 1."""
    parts = []
    for i, (uf, vp) in enumerate(zip(uploaded_files, video_paths)):
        parts.append(f'Video {i}: "{_video_title(vp)}". The file right after this line is Video {i}.')
        parts.append(uf)
    return parts


def _frame_jpeg(video_path, t, crop=None):
    """One frame of a video as JPEG bytes (640 px wide), or None."""
    vf = (f"crop={crop}," if crop else "") + "scale=640:-2"
    try:
        out = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", f"{max(t, 0):.2f}", "-i", video_path,
             "-frames:v", "1", "-vf", vf, "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "4", "-"],
            capture_output=True, check=True,
        ).stdout
        return out or None
    except subprocess.CalledProcessError:
        return None


def _check_frames(client, checks, subject, look=None):
    """
    Independent look at real frames: for each check {"id", "frames": [jpeg bytes],
    "should_show": text}, does the footage really show it, cleanly?

    The edit plan's own visual_check is written by the same call that picked the
    timestamp, so it confirms itself; it said "Tsarukyan walking out" over a
    frame of a different fighter's bird coop. This call only sees the frames.
    Returns {id: {"ok", "shows", "problem"}}; a check Gemini skips counts as failed.
    Returns None when the call itself fails, so callers keep what they had
    instead of rejecting everything over an API error.
    `look` (the script's scene_query) lets it recognise characters it doesn't know by name.
    """
    from google.genai import types
    contents = []
    for c in checks:
        contents.append(f'CHECK {c["id"]}: should show: {c["should_show"]}')
        contents += [types.Part.from_bytes(data=f, mime_type="image/jpeg") for f in c["frames"] if f]
    contents.append(f"""
You are checking frames grabbed from source footage for a short video about: {subject}.
{_who_is_who(look)}
Each CHECK above has one or two frames and what they should show.

ok = true only when the frames show real footage (a filmed moment, broadcast, interview,
press conference, anime scene or game footage) of the subject or of what "should show" names.
ok = false when ANY of these is true:
- a person or character from a different story, or a different person than the subject who is
  not what "should show" names either. Side characters, objects and places that the "should show"
  text talks about (a dying guard, a crowd, a weapon) are fine.
- a news or recap channel graphic: headline banners, lower thirds, quote cards, tweet
  screenshots, or a photo placed inside a designed template
- burned-in captions that transcribe a narrator, host or commentator (small original
  dialogue subtitles of a show itself are fine)
- a host, YouTuber or commentator who is not the subject
- a logo bigger than a small corner bug: a channel watermark, or a studio or streaming logo card
  (Netflix, a studio name) over the picture. A small logo tucked in a corner is fine.
- a black screen, title card, intro, outro, end screen or subscribe screen
- "should show" includes what an editor claims the frame shows, and the main person, object or
  action of that claim is clearly not in the frames (ignore the claim's "no watermark / no text" parts)
Be strict. When unsure, ok = false.

overlay_only = true when ok is false ONLY because of a logo, watermark, caption box or text on top of the
picture, and the footage underneath is the right person or moment. Otherwise false.

Return ONLY JSON: {{"checks": [{{"id": "<id>", "ok": true, "overlay_only": false, "shows": "<what you actually see, under 12 words>", "problem": "<the rule it breaks, or empty>"}}]}}
""")
    for attempt in range(1, 6):
        try:
            response = _require_text(client.models.generate_content(
                model=GEMINI_CHECK_MODEL,
                contents=contents,
                config={"thinking_config": {"thinking_budget": 2048}, "response_mime_type": "application/json"},
            ))
            break
        except Exception as e:
            if isinstance(e, _EmptyReply) and attempt < 5:
                print(f"{e} (frame check), retrying... (attempt {attempt}/5)")
                time.sleep(3)
            elif "503" in str(e) and attempt < 5:
                print(f"Gemini 503 (frame check), retrying in 20s... (attempt {attempt}/5)")
                time.sleep(20)
            elif "429" in str(e) and attempt < 5:
                try:
                    client, _ = _on_quota_hit(client, "frame check", attempt, e)
                except GeminiDailyQuota as q:
                    print(f"{q} Keeping these picks unchecked.")
                    return None
            else:
                print(f"Frame check failed ({e}), keeping these picks unchecked")
                return None
    try:
        rows = json.loads(response.text)
        if isinstance(rows, dict):   # flash-lite sometimes returns the bare list without {"checks": ...}
            rows = rows.get("checks", [])
    except Exception as e:
        print(f"Frame check returned bad JSON ({e}), keeping these picks unchecked")
        return None
    # Gemini sometimes echoes the prompt label ("CHECK 0") instead of the bare id.
    results = {}
    for r in rows:
        if isinstance(r, dict):
            m = re.search(r"\d+", str(r.get("id", "")))
            results[m.group() if m else str(r.get("id"))] = r
    if not any(str(c["id"]) in results for c in checks):
        print(f"Frame check answered none of the checks ({len(rows)} rows), keeping these picks unchecked")
        return None
    return results


MIN_SUBJECT_SHARE = 0.3   # backups that show no script item still need to be mostly the subject
MIN_SUBJECT_SECONDS = 8   # a video that shows script items needs this much real subject footage


def _enforce_evaluation(evaluation, video_path, client, subject=None, look=None):
    """
    Apply the evaluation's own rules in code, then spot-check its evidence.

    Gemini approved a nine-minute news roundup that was mostly other fighters,
    because the subject appeared in it once. So: a low subject_share rejects,
    and the frames at the claimed evidence timestamps must really show the
    items. An item whose moment fails the check no longer counts as shown.
    """
    if evaluation.get("decision") != "post":
        return evaluation
    try:
        duration = _probe_duration(video_path)
    except Exception:
        duration = float("inf")
    # The editor uses a few seconds per clip, so a short stretch of the right moment is enough.
    # Seconds, not share: a news edit showed the phone incident in 21% of its runtime and was lost.
    share = evaluation.get("subject_share")
    if isinstance(share, (int, float)) and share * duration < MIN_SUBJECT_SECONDS:
        evaluation["decision"] = "reject"
        evaluation["reason"] = (f"subject on screen only {share * duration:.0f}s of the video. "
                                f"{evaluation.get('reason', '')}")
        return evaluation

    # A timestamp past the end has no frame to grab, so it can't prove anything either way.
    evidence = [e for e in evaluation.get("evidence") or []
                if isinstance(e, dict) and isinstance(e.get("at"), (int, float))
                and 0 <= e["at"] < duration - 1.5][:3]
    if not evidence:
        return evaluation
    checks = [{"id": str(k), "should_show": e.get("item", ""),
               "frames": [_frame_jpeg(video_path, e["at"]), _frame_jpeg(video_path, e["at"] + 1.5)]}
              for k, e in enumerate(evidence)]
    # The script's subject, not the video's own title: with the title as the subject,
    # "Lucy and David" passed as "Avida" because they are what the teaser is about.
    results = _check_frames(client, checks, subject or _video_title(video_path), look)
    if results is None:
        return evaluation
    passed = [e["item"] for k, e in enumerate(evidence) if results.get(str(k), {}).get("ok")]
    for k, e in enumerate(evidence):
        r = results.get(str(k))
        verdict = "unchecked" if r is None else ("ok" if r.get("ok") else "FAIL")
        print(f"   Spot check {e['at']:.0f}s '{e.get('item')}': {verdict} ({(r or {}).get('shows', 'no answer')})")
    if not passed:
        evaluation["decision"] = "reject"
        evaluation["reason"] = f"spot check failed, the claimed moments do not show the items. {evaluation.get('reason', '')}"
    else:
        # Only a real "no" removes an item; a check Gemini skipped proves nothing.
        failed = {e["item"] for k, e in enumerate(evidence)
                  if str(k) in results and not results[str(k)].get("ok")}
        evaluation["items_shown"] = [x for x in evaluation.get("items_shown") or [] if x not in failed]
    return evaluation


def evaluate_video_with_genai(video_path, script_text, script_items=None, subject=None, look=None):
    """Upload a video to Gemini and score it for relevance, hook potential, and technical quality.

    Also returns `script_items` (the concrete things the script talks about) and `items_shown`
    (the ones visible in this footage). Pass the first call's script_items back in later calls
    so every video is checked against the same list. `subject` and `look` (the script's
    specific_subject and scene_query) say who the footage must show.
    """
    client = _gemini_client()
    if script_items:
        items_rule = f"Use EXACTLY this list, copied word for word: {json.dumps(script_items)}"
    else:
        # Built while watching the first video, the list once held five phone-incident items
        # and nothing about the Messi gesture or the red card, so those clips failed "shows
        # none of the script items". The list must come from the script text alone.
        items_rule = ("Write the list from the SCRIPT TEXT ALONE, as if you had not seen the footage: up to 6 "
                      "items, 2-5 words each, one per distinct moment, event, object or place the script names, "
                      "covering the WHOLE script from first line to last (a countdown gets at least one item for "
                      "every numbered entry). Never spend two items on the same moment.")

    uploaded_file = client.files.upload(file=video_path)
    print(f"Uploaded file: {uploaded_file.name}")

    _wait_for_active(client, uploaded_file.name, label="Video")

    prompt = f"""
    You are an AI Video Editor Assistant.
    Evaluate whether this RAW SOURCE FOOTAGE is usable as background B-roll for a short-form video.
    
    Judge it on POTENTIAL as raw source footage — not as a finished edit.
    
    SCRIPT EXCERPT:
    \"\"\"{script_text}\"\"\"

    VIDEO TITLE: "{_video_title(video_path)}"
    The title decides which season or installment this is. Never decide it from the characters you
    think you see: you do not know a new season's cast, and you will mistake its characters for the
    old cast you know (every season 2 clip got called "David and Lucy from season 1"). If the title
    names the right season, the footage is that season.
    
    STEP 0 — REQUIRED SUBJECT (do this first):
    From the script, identify the CHARACTER or SHOW the footage must contain — not a specific state, form, or moment.
    State it internally as REQUIRED_SUBJECT before scoring.
    Characters the script only mentions from other media (a game, a manga, a movie) are not part of
    REQUIRED_SUBJECT: footage of the show can never contain them.
    Example: if the script is about Jax's abstraction, REQUIRED_SUBJECT = "Jax" — normal Jax, abstracted Jax, and scenes leading up to the abstraction ALL count. If the script is about Hange Zoë's hygiene, REQUIRED_SUBJECT = "Hange Zoë" — any footage showing Hange counts, regardless of the scene.
    {f"The video is about: {subject}" if subject else ""}
    {_who_is_who(look)}
    
    The footage must be raw source material — broadcast footage, official highlights, or documentary footage. It must NOT be someone else's YouTube video where they react to, comment on, or narrate over the clips.

    STEP 0.5 — CONTENT TYPE CHECK (do this before scoring):
    Determine if this is:
    A) Raw/official footage — broadcast clips, official highlights, documentary, raw gameplay footage. ALLOWED.
    B) Reaction/commentary video — a YouTuber or creator watches clips and reacts, talks to camera, or narrates with their own voice over the footage. REJECT IMMEDIATELY.
    C) Fan compilation with heavy custom editing, custom music, or a creator's voiceover throughout, or a side-by-side
       comparison (sub vs dub, before/after) with two pictures or labels on screen. REJECT IMMEDIATELY.
    D) Podcast/interview clip where someone is talking about the subject but not showing real action. REJECT IMMEDIATELY.
    E) News or recap channel video that is mostly template (headline banners, quote cards, tweet screenshots,
       photos placed inside graphics) with only a few seconds of real footage, or a roundup that covers several
       different stories or people. REJECT IMMEDIATELY.
       A news edit about THIS story that also shows real footage of it (several seconds at a time with no text
       over the picture) counts as A: for some incidents only news edits exist. Every clip is checked for text
       before use, so only its clean stretches get used. Name those stretches in evidence.

    If type B, C, D or E → set decision = "reject", technical_score = 1, and stop evaluating.

    STEP 0.7 — SCRIPT ITEMS:
    script_items = the concrete things the script talks about that footage could show: places, objects,
    events, forms (e.g. "Florida mansion", "Ibiza villa", "private jet", "activists painting the villa").
    {items_rule}
    items_shown = the script_items clearly visible somewhere in THIS footage. REQUIRED_SUBJECT alone on
    screen does not count as showing an item, unless the item is the subject in that exact state or place.
    evidence = for each item in items_shown, the timestamp in seconds of its clearest moment. These frames
    are grabbed and checked afterwards, so only list a moment you actually saw.

    STEP 0.8 — SUBJECT SHARE:
    subject_share = the fraction of the runtime (0.0-1.0) that shows real footage of REQUIRED_SUBJECT.
    Photos inside graphics, thumbnails, tweets and other people's segments do not count.

    EVALUATION (1-10):

    1. Visual-Script Alignment (relevance_score)
       - The footage MUST visibly contain REQUIRED_SUBJECT to score above 4.
       - Correct show but WRONG/MISSING character or subject → relevance_score 1-3, regardless of how cool it looks. (A clip of a different character does NOT count, even from the same series.)
       - REQUIRED_SUBJECT clearly on screen → 8-10. Briefly/partially present → 5-7.
       - Be forgiving on edit quality, NOT on whether the right subject is present.

    2. Usable Action / Hook Potential (hook_score)
       - 8-10: dynamic action, strong close-ups, intense moments featuring the subject.
       - 5-7: standard scenes, panning shots, average animation.
       - 1-4: black screens, text overlays, heavy-watermark fan-edits, static menus.

    3. Raw Technical Quality (technical_score)
       - 8-10: clean broadcast/official footage, minimal watermarks, clear enough to crop for phone.
       - 5-7: slightly blurry or minor subtitles/watermarks, still usable.
       - 1-4: heavily pixelated, ruined by editing/watermarks, has a creator's face or persistent voiceover, unwatchable,
         or burned-in captions that transcribe a narrator or commentator over most of the footage.

    DECISION RULES (apply in order):
    - "reject": content type is B, C, or D (reaction/commentary/podcast → automatic reject)
    - "reject": subject_present = false (subject not visible → automatic reject, no exceptions)
    - "reject": relevance_score <= 6  (subject barely visible, wrong character, or wrong show → reject)
    - "reject": technical_score <= 4
    - "reject": items_shown is empty (the subject is there, but nothing the script actually talks about)
    - "post":   items_shown is not empty AND relevance_score >= 7 AND hook_score >= 5 AND technical_score >= 5 AND subject_present = true
    - "revise": anything else / unsure
    
    OUTPUT FORMAT:
    Respond ONLY with valid JSON. No explanations, no markdown.
    
    {{
      "required_subject": "<the subject you identified>",
      "subject_present": <true|false>,
      "script_items": ["<item>", ...],
      "items_shown": ["<items from script_items visible in this footage>"],
      "evidence": [{{"item": "<an item from items_shown>", "at": <seconds>}}],
      "subject_share": <0.0-1.0>,
      "relevance_score": <1-10>,
      "hook_score": <1-10>,
      "technical_score": <1-10>,
      "decision": "post" | "revise" | "reject",
      "reason": "<1-2 sentences explaining the decision — what was or wasn't present, what rule triggered>"
    }}
    """

    max_attempts = 5
    for attempt in range(1, max_attempts + 1):
        try:
            response = _require_text(client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[uploaded_file, prompt],
                config={"thinking_config": {"thinking_budget": 8000}, "response_mime_type": "application/json"},
            ))
            break
        except Exception as e:
            if isinstance(e, _EmptyReply):
                print(f"{e}, retrying... (attempt {attempt}/{max_attempts})")
                time.sleep(5)
            elif "503" in str(e):
                print(f"Gemini 503, retrying in 20s... (attempt {attempt}/{max_attempts})")
                time.sleep(20)
            elif "429" in str(e):
                client, switched = _on_quota_hit(client, "evaluation", attempt, e)
                if switched:
                    uploaded_file = _upload_and_wait(client, video_path)
            else:
                raise
        if attempt == max_attempts:
            raise RuntimeError("Gemini failed after max retries.")

    raw_text = response.text if hasattr(response, "text") else str(response)

    try:
        clean_text = raw_text.strip()
        if not clean_text.startswith("{"):
            clean_text = clean_text[clean_text.find("{"):]
        if not clean_text.endswith("}"):
            clean_text = clean_text[:clean_text.rfind("}") + 1]
        return _enforce_evaluation(json.loads(clean_text), video_path, client, subject, look)
    except Exception as e:
        print(f"Failed to parse GenAI JSON: {e}")
        print("Raw response:", raw_text)
        return {
            "relevance_score": 0,
            "hook_score": 0,
            "technical_score": 0,
            "decision": "revise"
        }


def find_scene_with_gemini(video_path, query, script):
    """Ask Gemini to find the best matching timestamp in the video for the given visual query and script."""
    client = _gemini_client()

    info = ffmpeg.probe(video_path)
    video_stream = next(s for s in info["streams"] if s["codec_type"] == "video")
    video_duration = float(video_stream["duration"])

    uploaded_file = client.files.upload(file=video_path)
    print(f"Uploaded file: {uploaded_file.name}")

    _wait_for_active(client, uploaded_file.name, label="Video")

    prompt = f"""
    You are analyzing a video to find when a specific visual moment occurs.

    VIDEO DURATION: {video_duration} seconds

    USER QUERY:
    "{query}"

    VIDEO SCRIPT:
    "{script}"

    TASK:
    Find the BEST approximate timestamp where the query visually appears.

    IMPORTANT:
    - The timestamp does NOT need to be exact (±2–3 seconds is acceptable).
    - Use the script to find candidate moments, then refine visually.
    - The result must produce a GOOD 5-second clip (important).

    SEARCH STRATEGY:
    1. Identify 1–3 likely moments from the script.
    2. Compare them visually.
    3. Select the clearest and most usable moment.

    CLIP QUALITY RULES (CRITICAL):
    - The selected moment MUST allow at least 5 full seconds of usable footage.
    - Avoid picking moments too close to the end of the video.
    - Avoid intros, outros, fade-ins, fade-outs, and transitions.
    - Prefer moments in the middle of a scene (not scene boundaries).

    AVOID THESE RANGES:
    - First 3 seconds of the video (likely intro)
    - Last 8 seconds of the video (likely outro)
    - Only use these ranges if absolutely necessary.

    MATCHING RULES:
    - Focus primarily on visual similarity.
    - If multiple matches exist, pick the most visually clear one.
    - If no exact match exists, return the closest relevant moment.
    - Only return start=0 if the video is completely unrelated.

    TIMESTAMP RULES (CRITICAL):
    - All timestamps must be in SECONDS only.
    - Do NOT use minutes or mm:ss format.
    - NEVER output values like 1.30 or 2.10.
    - Convert properly:
      - 1 minute 30 seconds = 90.0
      - 2 minutes 10 seconds = 130.0

    BOUNDARY RULE:
    - Ensure: start + 5 <= {video_duration}
    - If the best moment is too close to the end(- 15 seconds), shift the start earlier to allow a 20-30 seconds.

    OUTPUT RULES:
    - Output ONLY valid JSON.
    - Do NOT include any explanation or text.
    - JSON must be the ONLY output.

    OUTPUT FORMAT:
    {{ "start": float, "end": float }}

    - end = start + 5
    - start must be within [0, {video_duration}]
    """

    max_attempts = 5
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[uploaded_file, prompt],
                config={"response_mime_type": "application/json"},
            )
            break
        except Exception as e:
            if "503" in str(e):
                print(f"Gemini 503, retrying in 20s... (attempt {attempt}/{max_attempts})")
                time.sleep(20)
            else:
                raise
        if attempt == max_attempts:
            raise RuntimeError("Gemini scene detection failed after max retries.")

    try:
        text = response.text
        if not text and response.candidates:
            text = response.candidates[0].content.parts[0].text

        if not text:
            raise ValueError("Empty response from Gemini")

        text = text.strip()

    except Exception as e:
        print("Gemini response error:", e)
        return None

    text = re.sub(r"```json|```", "", text).strip()

    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"\{.*?\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                pass

    print("Failed parsing:", text)
    return {"start": 0, "end": 0}


def _hook_text(title: str) -> str:
    """Title as shown on the hook card: no hashtags, no emoji."""
    title = re.sub(r"#\S+", "", title)
    title = re.sub(r"[\U0001F000-\U0001FFFF\u2600-\u27BF\uFE0F\u200D]", "", title)
    return " ".join(title.split())


def segment_by_sentences(words_data):
    """Split word-level timestamps into sentence segments on punctuation boundaries."""
    segments = []
    current = []

    for word, start, end in words_data:
        current.append((word, start, end))
        if word.rstrip().endswith(('.', '?', '!')):
            seg_start = current[0][1]
            seg_end = current[-1][2]
            seg_text = ' '.join(w for w, s, e in current)
            segments.append({
                "text": seg_text,
                "start": seg_start,
                "end": seg_end,
                "duration": seg_end - seg_start,
            })
            current = []

    if current:
        seg_start = current[0][1]
        seg_end = current[-1][2]
        seg_text = ' '.join(w for w, s, e in current)
        segments.append({
            "text": seg_text,
            "start": seg_start,
            "end": seg_end,
            "duration": seg_end - seg_start,
        })

    return segments


def _set_cut_durations(segments, tagged_sfx, total_dur):
    """
    Give each segment a "cut_duration": how long its clip stays on screen.

    Clips are laid end to end, so a cut lands at the sum of the clips before
    it. Each clip runs until the next segment's first word, so the pause
    between sentences is counted and cuts don't drift early. A reaction sound
    in that pause holds the shot until it ends, so the cut and its whoosh come
    after the reaction instead of on top of it.
    """
    boundary = 0.0
    for i, seg in enumerate(segments):
        if i + 1 < len(segments):
            nxt = segments[i + 1]
            end = nxt["start"]
            for s in tagged_sfx or []:
                if s["kind"] == "after" and seg["end"] - 0.01 <= s["time"] < nxt["end"]:
                    end = max(end, s["time"] + s["duration"])
        else:
            end = total_dur
        seg["cut_duration"] = max(0.1, end - boundary)
        boundary = end


def merge_short_segments(segments, min_duration):
    """Combine consecutive segments until each group is at least min_duration seconds."""
    merged = []
    buf = None
    for seg in segments:
        if buf is None:
            buf = {"text": seg["text"], "start": seg["start"], "end": seg["end"], "duration": seg["duration"]}
        else:
            buf["text"] += " " + seg["text"]
            buf["end"] = seg["end"]
            buf["duration"] = buf["end"] - buf["start"]
        if buf["duration"] >= min_duration:
            merged.append(buf)
            buf = None
    if buf is not None:
        if merged and buf["duration"] < min_duration:
            merged[-1]["text"] += " " + buf["text"]
            merged[-1]["end"] = buf["end"]
            merged[-1]["duration"] = merged[-1]["end"] - merged[-1]["start"]
        else:
            merged.append(buf)
    return merged


def _graphic_prompt_rules(allowed, max_cards):
    """Prompt section describing the on-screen graphic cards Gemini may place across the narration."""
    if not allowed:
        return "GRAPHICS: always return \"graphics\": []."
    shapes = {
        "stat": '{"type": "stat", "segment_index": <n>, "anchor_word": "<word>", "value": "<number as digits, e.g. 52 or $1.2M or 40%>", "label": "<3-6 words saying what the number is>"}',
        "versus": '{"type": "versus", "segment_index": <n>, "anchor_word": "<word>", "left": {"name": "<short>", "value": "<digits>"}, "right": {"name": "<short>", "value": "<digits>"}}',
        "list": '{"type": "list", "segment_index": <n>, "anchor_word": "<word>", "items": ["<2-5 words>", "<2-5 words>", "... 2 to 4 items"]}',
        "quote": '{"type": "quote", "segment_index": <n>, "anchor_word": "<word>", "text": "<the exact quoted words>", "author": "<who said it>"}',
    }
    lines = "\n".join(f"- {shapes[t]}" for t in allowed)
    return f"""════════════════════════════════════
STEP 6: ON-SCREEN GRAPHIC CARDS
════════════════════════════════════
A graphic card appears in the lower part of the screen for about 4 seconds, starting on the word that triggers it. Cards make the video feel produced, not reposted.
Cards are NOT tied to clips: a segment can have zero, one or several cards. Go through the narration word by word and add a card wherever the text contains something worth showing:
- a number or record → "stat"
- two things compared with numbers → "versus"
- several items, steps or reasons named in a row → "list"
- someone's actual quoted words → "quote"
Allowed shapes (use exactly these keys):
{lines}
RULES:
- Every value, name, item and quote MUST come from THAT segment's text. Never add facts, never round or convert numbers into new ones. Write numbers as digits even if the text spells them out ("fifty-two" → "52").
- `segment_index` = the segment whose text contains the anchor word. `anchor_word` = that exact word, where the card should appear (usually the number or the first item).
- A stat label uses the segment's own words. Never add a detail the line doesn't say (a season number, a year, a name).
- A list needs at least 2 items named in the text. One named thing is not a list: skip it.
- At most {max_cards} cards in total. Pick the strongest numbers and moments, skip the rest.
- Spacing: at least {MIN_CARD_GAP:.0f} seconds between cards (use the segment `start` times), and none in the first {HOOK_CLEAR_SECONDS:.0f} seconds, so the hook stays clean. Cards that break this get dropped anyway.
- Keep text short: labels up to 6 words, list items up to 5 words."""


_NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
    "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_SCALE_WORDS = {"hundred": 100, "thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000}


def _numbers_in_text(text):
    """All numbers mentioned in narration, whether written as digits or spelled out.

    Scripts spell numbers out for TTS ("fifty-two", "three hundred"), so a digit
    on screen has to be checked against the words. Returns a set of floats.
    """
    found = {float(d.replace(",", "")) for d in re.findall(r"\d[\d,]*(?:\.\d+)?", text)}
    total, current, in_number = 0, 0, False
    decimal_place = 0   # >0 after "point": each following digit word is the next decimal
    for word in re.findall(r"[a-z]+", text.lower().replace("-", " ")):
        if word == "point" and in_number:
            decimal_place = 1
        elif decimal_place and word in _NUMBER_WORDS and _NUMBER_WORDS[word] < 10:
            current += _NUMBER_WORDS[word] / 10 ** decimal_place
            decimal_place += 1
        elif word in _NUMBER_WORDS:
            current += _NUMBER_WORDS[word]
            in_number = True
        elif word in _SCALE_WORDS and in_number:
            decimal_place = 0
            scale = _SCALE_WORDS[word]
            if scale == 100:
                current *= 100
            else:
                total += current * scale
                current = 0
        elif word == "and" and in_number:
            continue
        else:
            if in_number:
                found.add(round(float(total + current), 6))
            total, current, in_number, decimal_place = 0, 0, False, 0
    if in_number:
        found.add(round(float(total + current), 6))
    return found


def _graphic_numbers_ok(values, segment_text):
    """True if every number shown on a graphic is a number the narration actually says."""
    spoken = _numbers_in_text(segment_text)
    for v in values:
        m = re.search(r"\d[\d,]*(?:\.\d+)?", str(v))
        if not m:
            continue
        num = float(m.group(0).replace(",", ""))
        # "1.2M" on screen vs "one point two million" spoken: also accept the scaled value
        scaled = {num * f for f in (1, 1_000, 1_000_000, 1_000_000_000)}
        if not (scaled & spoken):
            return False
    return True


def _label_numbers_ok(label, segment_text):
    """True if every number in a card's label is one the narration says. The value
    check alone let "10 / Episodes in Season 1" through: 10 was spoken, the 1 was made up."""
    spoken = _numbers_in_text(segment_text)
    return all(n in spoken for n in _numbers_in_text(label))


def _validate_layout(scene, full_allowed):
    """Force layout/focus_x into safe values; anything odd becomes the framed layout."""
    layout = scene.get("layout")
    if layout not in ("full", "framed") or not full_allowed:
        layout = "framed"
    try:
        focus_x = float(scene.get("focus_x", 0.5))
    except (TypeError, ValueError):
        focus_x = 0.5
    scene["layout"] = layout
    scene["focus_x"] = round(min(max(focus_x, 0.15), 0.85), 3)


def _validate_graphic(graphic, segment, allowed, index):
    """Return a cleaned graphic dict, or None if it is malformed, not allowed, or invents numbers."""
    if not graphic or not isinstance(graphic, dict) or segment is None:
        return None
    gtype = graphic.get("type")
    if gtype not in allowed:
        return None
    text = segment["text"]
    anchor = str(graphic.get("anchor_word", ""))
    try:
        if gtype == "stat":
            value, label = str(graphic["value"]).strip(), str(graphic["label"]).strip()
            if not value or not label or not _graphic_numbers_ok([value], text):
                raise ValueError("stat number not in narration")
            if not _label_numbers_ok(label, text):
                raise ValueError(f"label '{label}' has a number the narration doesn't say")
            clean = {"type": "stat", "value": value, "label": label}
        elif gtype == "versus":
            left, right = graphic["left"], graphic["right"]
            sides = [{"name": str(x["name"]).strip(), "value": str(x["value"]).strip()} for x in (left, right)]
            if not all(x["name"] and x["value"] for x in sides) or not _graphic_numbers_ok([x["value"] for x in sides], text):
                raise ValueError("versus number not in narration")
            clean = {"type": "versus", "left": sides[0], "right": sides[1]}
        elif gtype == "list":
            items = [str(i).strip() for i in graphic["items"] if str(i).strip()][:4]
            if len(items) < 2:
                raise ValueError("list needs 2+ items")
            clean = {"type": "list", "items": items}
        else:  # quote
            quote = str(graphic["text"]).strip().strip('"')
            if not quote:
                raise ValueError("empty quote")
            clean = {"type": "quote", "text": quote, "author": str(graphic.get("author", "")).strip()}
    except (KeyError, TypeError, ValueError) as e:
        print(f"Dropped graphic on segment {index} ({gtype}): {e}")
        return None
    clean["anchor_word"] = anchor
    return clean


def _fix_timestamps(text):
    """Gemini sometimes writes "start": 1:50 (mm:ss) instead of seconds, which breaks json.loads.
    Rewrite mm:ss and h:mm:ss values (quoted or bare) into plain seconds."""
    def to_seconds(m):
        parts = [float(p) for p in m[2].split(":")]
        seconds = 0.0
        for p in parts:
            seconds = seconds * 60 + p
        print(f"Fixed Gemini timestamp {m[2]} -> {seconds}s")
        return f"{m[1]}{seconds}"
    return re.sub(r'("start"\s*:\s*)"?(\d+(?::\d{1,2}(?:\.\d+)?){1,2})"?', to_seconds, text)


def _intro_ban(video_path, duration):
    """Seconds at the start of a source that may hold a channel intro or title card.

    A flat 10s ban pushed starts in a 70s news clip past the shot Gemini actually checked,
    so short videos get a shorter ban, and a file cut from the middle of a longer video
    (it starts mid-video) gets none.
    """
    if _read_source_meta(video_path).get("trim_start", 0) > 0:
        return 0.0
    return round(min(10.0, max(3.0, duration * 0.05)), 1)


def _outro_ban(duration, has_outro):
    """Seconds at the end of a source that may hold an outro. A flat 30s left a 41-second
    red card clip only seconds 3 to 9 to use, so short videos get a proportional ban."""
    return round(min(30.0, max(3.0, duration * 0.15)), 1) if has_outro else 0.0


def _clamp_backups(backups, video_durations, intro_bans, outro_bans):
    """Keep the edit plan's backup picks that point inside a video's usable range."""
    kept = []
    for b in backups or []:
        try:
            vi, start = int(b["video_index"]), float(b["start"])
        except (KeyError, TypeError, ValueError):
            continue
        if not 0 <= vi < len(video_durations):
            continue
        hi = video_durations[vi] - outro_bans[vi] - 2.0
        if intro_bans[vi] <= start <= hi:
            kept.append({"video_index": vi, "start": round(start, 2)})
    return kept[:2]


def _fix_minute_decimals(scenes, video_durations):
    """
    Gemini sometimes writes 3:32 as 3.32. When every start in the plan (picks and backups)
    is under 10 with a decimal part of .59 or less, and the videos are minutes long, the
    plan is in minutes.seconds: five picks inside the first five seconds of a five-minute
    video never happens. Unconverted, they were all clamped to the same intro-ban second
    and the Short played one title card five times.
    """
    spots = [s for s in scenes] + [b for s in scenes for b in s.get("backups") or [] if isinstance(b, dict)]
    try:
        values = [float(x["start"]) for x in spots]
    except (KeyError, TypeError, ValueError):
        return
    if (len(values) < 3 or max(video_durations, default=0) < 120
            or not all(0 <= v < 10 and round(v * 100) % 100 < 60 for v in values)):
        return
    for x in spots:
        v = float(x["start"])
        x["start"] = int(v) * 60 + round(v * 100) % 100
    print(f"Edit plan timestamps were minutes.seconds (e.g. {values[0]} = {scenes[0]['start']:.0f}s), converted")


def find_scenes_with_gemini(video_paths, script_segments, channel=None, video_items=None, look=None):
    """
    Upload all approved source videos to Gemini in one call.
    Returns a flat list of scenes: [{index, video_index, start}, ...]
    Gemini picks the best (video, timestamp) for each narration segment.
    """
    client = _gemini_client()

    video_durations = []
    valid_video_paths = []
    for vp in video_paths:
        try:
            info = ffmpeg.probe(vp)
            vs = next(s for s in info["streams"] if s["codec_type"] == "video")
            video_durations.append(float(vs["duration"]))
            valid_video_paths.append(vp)
        except Exception as e:
            print(f"Skipping bad video {vp}: {e}")
    video_paths = valid_video_paths

    if not video_paths:
        print("All source videos failed ffprobe, using fallback scene plan.")
        return [{"index": i, "video_index": 0, "start": 0.0} for i in range(len(script_segments))], [], [], [], client

    uploaded_files = []
    for i, vp in enumerate(video_paths):
        uf = client.files.upload(file=vp)
        print(f"Uploaded Video {i}: {uf.name}")
        uploaded_files.append(uf)

    pending = list(range(len(uploaded_files)))
    _poll_error_counts = [0] * len(uploaded_files)
    _poll_deadline = time.time() + 300
    while pending:
        time.sleep(2)
        still_pending = []
        for i in pending:
            try:
                fi = client.files.get(name=uploaded_files[i].name)
                _poll_error_counts[i] = 0
            except Exception as e:
                if any(code in str(e) for code in ("500", "INTERNAL", "503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED")):
                    _poll_error_counts[i] += 1
                    print(f"Gemini transient error polling video {i} ({_poll_error_counts[i]}/10), retrying...")
                    if _poll_error_counts[i] >= 10:
                        raise RuntimeError(f"Gemini video {i} stuck in PROCESSING with repeated transient errors") from e
                    still_pending.append(i)
                    continue
                else:
                    raise
            state = _state_name(fi)
            if state == "ACTIVE":
                print(f"Video {i} ACTIVE")
            elif state == "FAILED":
                raise RuntimeError(f"Video {i} failed to process on Gemini (corrupt or truncated upload)")
            else:
                still_pending.append(i)
        pending = still_pending
        if pending and time.time() > _poll_deadline:
            raise RuntimeError(f"Gemini videos {pending} still PROCESSING after 300s")

    n = len(script_segments)
    segments_json = json.dumps(
        [{"index": i, "text": s["text"], "start": round(s["start"], 2), "duration": round(s["duration"], 2)}
         for i, s in enumerate(script_segments)],
        indent=2
    )
    video_titles = [_video_title(vp) for vp in video_paths]

    channel = channel or DEFAULT_CHANNEL
    allowed_graphics = [t for t in channel.get("graphic_types", []) if t in GRAPHIC_TYPES]
    full_allowed = channel.get("allow_full_layout", True)
    narration_seconds = script_segments[-1]["end"] if script_segments else 0.0
    max_cards = max(1, round((narration_seconds - HOOK_CLEAR_SECONDS) / 10))
    graphic_rules = _graphic_prompt_rules(allowed_graphics, max_cards)

    # A file the fetcher cut (MAX_SOURCE_SECONDS) ends mid-video unless the cut reaches
    # the real end, so its final 30 seconds are real footage and should stay usable.
    has_outro = []
    for vp, dur in zip(video_paths, video_durations):
        meta = _read_source_meta(vp)
        source_duration = meta.get("source_duration")
        cut_end = meta.get("trim_start", 0) + dur
        has_outro.append(not (source_duration and source_duration > cut_end + 5))

    intro_bans = [_intro_ban(vp, dur) for vp, dur in zip(video_paths, video_durations)]
    outro_bans = [_outro_ban(dur, o) for dur, o in zip(video_durations, has_outro)]
    video_items = video_items or {}

    def _shows(vp):
        items = video_items.get(vp)
        return f", shows: {', '.join(items)}" if items else ""

    videos_info = "\n".join(
        f"  Video {i} - \"{video_titles[i]}\" (duration: {dur:.1f}s, usable from {intro_bans[i]:.1f}s "
        f"until {dur - outro_bans[i]:.1f}s{_shows(video_paths[i])})"
        for i, dur in enumerate(video_durations)
    )

    prompt = f"""
You are a professional short-form video editor cutting a TikTok / YouTube Short.
You have {len(video_paths)} source video(s) and a narration split into timed segments.
Your job: pick the single best (video, timestamp) for each segment so the final edit feels intentional, dynamic, and visually synced to the words.

SOURCE VIDEOS:
{videos_info}

{_who_is_who(look)}

NARRATION SEGMENTS (index / spoken text / duration in seconds):
{segments_json}

════════════════════════════════════
STEP 1 — UNDERSTAND THE SCRIPT
════════════════════════════════════
Read ALL segments together before doing anything else.
Identify: who or what is the main subject, what is the emotional arc, which segments are the hook, the reveal, and the payoff.

════════════════════════════════════
STEP 1.5 — TAG EACH SEGMENT WITH AN ENERGY TIER
════════════════════════════════════
For each segment assign one tier:
- HIGH → intense action, dramatic reveal, emotional peak, shocking fact (e.g. segment contains "ate", "destroyed", "explodes", exclamation marks, or the script's biggest moment)
- MID  → subject actively moving, reacting, or engaged in a scene (normal pacing)
- LOW  → calm explanation, context-setting, wide establishing shot moment

Use the segment text to drive this — you will use these tiers in Step 3 to vary pacing.
The first segment is ALWAYS treated as HIGH regardless of tier.

════════════════════════════════════
STEP 2 — SCAN EACH VIDEO FOR KEY MOMENTS
════════════════════════════════════
Watch each video and mentally catalogue the best visual moments and their timestamps.
For each moment you note, also tag it HIGH / MID / LOW so you can match tiers in Step 3.
Look for: decisive action shots, close-up reactions, dramatic slow-motion moments, and any footage that directly matches the script topic.
Note what each video is best suited for (e.g. "Video 0 has the actual fight", "Video 1 has emotional reactions").
This internal scan is what you draw from in Step 3 — do not skip it.

════════════════════════════════════
STEP 3 — PICK TIMESTAMPS (rules below)
════════════════════════════════════

HOOK MANDATE — segment 0 only:
The very first clip MUST be the single most visually striking shot across ALL your videos combined — the one shot that would stop someone mid-scroll. If you have multiple HIGH candidates, pick the one with the most intense visible action, expression, or motion. Do not settle for "pretty but calm."

FIRST-FRAME TIMING (segment 0, hard rule):
The striking action must ALREADY be on screen at `start`, not building toward it. Judge the shot by what the frame at `start` itself looks like, not by what happens later in the clip.
- If the impact, reveal, or peak expression happens at time t, return start = t - 0.3, never t - 2 or earlier.
- Reject any candidate whose first half second is wind-up: a character standing still before they move, a camera slowly pushing in, someone talking before the action.
- The first two seconds must MOVE: a cut, a camera move, or the subject moving. Reject held frames, slow pans over a still image, and dark, foggy, or washed-out frames. Bright and readable on a phone wins.
- Nothing may be mid-fade or mid-transition at `start`. The frame must be fully lit and fully readable from the very first frame.
- If your best candidate cannot satisfy this, use your second-best shot that can. An instantly readable good shot beats a great shot that starts slow.

ACTION PREFERENCE — all clips:
Always prefer shots where the subject is actively doing something (fighting, moving, reacting expressively, an event unfolding) over shots where the subject is standing still, posing, or walking slowly. A frame with visible motion always beats a static frame.

VISUAL-SCRIPT MATCHING (core rule):
- Each clip must visually SUPPORT what is being said in that segment.
- Reveal / surprise segment → a reaction shot, an impact visual, something with weight.
- Calm / explanatory segment → a clear mid-shot establishing what is being described.
- DO NOT assign generic-looking footage that has nothing to do with the narration text.
- NAMED OBJECT RULE: if the segment names a specific object, prop, weapon, or item (e.g. "the guitar", "his sword", "the case"), the frame at `start` MUST show that object visibly on screen — the subject merely being present is NOT enough. Scan specifically for the moment that object is in frame, even if it means a less "epic" shot. Only fall back to a generic shot of the subject if that object never appears anywhere in the footage.
- MOMENT RULE (beats every pacing and variety rule below): when a segment talks about a moment, event or
  item that a SOURCE VIDEO "shows" (see the list above), take that segment's clip from that video, at that
  moment. Several segments about the same moment may all come from the same video, in a row. Generic
  footage of the subject is only for segments that name no moment, or a moment no video shows.
- Before picking a timestamp, name the specific word or phrase in that segment's text the shot must visually support. If you cannot point to one, the segment is too vague to justify a specific action shot — fall back to a clear, on-topic shot of the subject rather than an unrelated "cool" moment. You will restate this connection in `relevance_note` below, so do not pick a timestamp you can't justify this way.

PACING RULE — energy alternation:
Use your tier tags to vary the edit rhythm. After a HIGH clip, prefer a MID or LOW clip next (not another HIGH). After two non-HIGH clips, return to HIGH. This prevents the edit from feeling like a wall of highlights with no breathing room.
Exception: the first two segments may both be HIGH if the script opens with a strong double-punch.

SHOT VARIETY — mandatory across the full edit:
- Never play the same footage twice: two clips from the same video must not overlap (each starts at least 5 seconds after the other).
- Mix shot distances: if segment N is a wide shot, segment N+1 should be a close-up or reaction — not another wide shot.
- MULTI-VIDEO RULE: use every available video at least once. Outside the MOMENT RULE, avoid using the same video more than 2 segments in a row.

WHY THESE BANS EXIST:
Every clip you pick plays silently under OUR OWN narration — the viewer never hears the source video's original audio. So the footage must read as genuine, raw material of the subject itself, not as "someone else's video." Anything that reveals a third party's presence — their commentary, their branding, their editing choices, their outro — breaks that illusion and makes the Short look like a screen-recording of someone else's content. Keep that goal in mind rather than pattern-matching the list below literally: the test is always "does this frame show the real subject, cleanly, with no trace of a third party's video wrapped around it?"

HARD BANS — never pick a timestamp that shows any of:
- A creator, commentator, YouTuber, or reactor speaking directly to camera ABOUT the subject (talking-head style) — this means someone OTHER than the subject reacting to or narrating over footage. It does NOT mean the subject themselves. If the person on screen IS the subject of this video (e.g. the athlete, character, or public figure the script is actually about) shown in real, authentic footage — an interview, press conference, broadcast moment — that is ALLOWED and can be used normally, since it's genuine footage of the subject, not third-party commentary.
- Static text screens, title cards, or sponsor segments
- Black screens, fade-ins, fade-outs, or scene transitions
- Burned-in subtitles or captions from the source (fansubs, translated dialogue lines at the bottom)
- Anything before a video's "usable from" time (channel intros, animated logos, title cards)
- Anything after a video's "usable until" time (outros, end screens, subscribe buttons, "thanks for watching" text).
- Big score graphics, stat boards or countdown timers over the picture (the small corner score bug of a live match broadcast is fine)
- Replay indicators ("REPLAY" / "INSTANT REPLAY" text on screen)
- Fan-art or AMV frames with heavy lens flares, desaturated overlays, or color-burn effects that obscure the subject
- Any frame where a large watermark, channel logo, or platform bug dominates the center of the image

CLIP SAFETY:
- Each clip will play for at least {MIN_CLIP_DURATION} seconds regardless of segment duration. The clip at `start` must have at least max(duration, {MIN_CLIP_DURATION}) + 1 second of usable footage remaining.
- If the best moment is too close to the end, shift `start` earlier to give breathing room.

════════════════════════════════════
STEP 4 — SELF-CHECK BEFORE OUTPUT
════════════════════════════════════
Before writing JSON, verify:
☐ Segment 0 is the single most visually striking shot available across all videos
☐ Every clip visually matches what its segment text is saying — you can name the exact word/phrase each shot supports
☐ Energy tiers alternate — no two consecutive HIGH clips after the opening pair
☐ All selected shots show the subject actively doing something (not just standing/posing)
☐ No two clips from the same video overlap
☐ Shot distances vary across the edit (wide → close-up → mid, etc.)
☐ No banned content in any selected timestamp, and every start is at or after its video's "usable from" time
☐ All start times are safe (enough footage remaining)
☐ Every available source video is used at least once
☐ Every segment that names a moment a video shows uses that video (MOMENT RULE)

════════════════════════════════════
STEP 5: LAYOUT PER SCENE
════════════════════════════════════
The final video is vertical 9:16. Each clip is shown one of two ways:
- "full": the clip is cropped to fill the whole vertical screen, keeping only the middle third of the width around `focus_x`.
- "framed": the whole landscape picture is shown in the middle with a backdrop above and below. Nothing is cut off.

Pick "full" ONLY when ALL of these are true for the frame at `start` and the following seconds:
- ONE subject (person, character, object) is the clear focus and fills a large part of the frame (close-up or medium shot)
- that subject stays roughly in place (no fast sideways running, no camera whip-pans)
- no important text, score, second person, or action sits near the left or right edges
Anything else (wide shots, two or more people interacting, landscapes, action spread across the frame) → "framed".
When unsure, ALWAYS choose "framed". A wrong "full" chops people in half; a wrong "framed" just looks normal.
`focus_x` = horizontal centre of the subject, 0.0 = left edge, 0.5 = centre, 1.0 = right edge. Required for "full".

{graphic_rules}

TIMESTAMP FORMAT: seconds only (e.g. 90.0 — never 1:30, and never 1.30 for a minute and thirty seconds)

VISUAL CHECK — required per scene:
For each scene, look at the exact frame at `start` and write a short `visual_check` string confirming what is actually visible there. It must explicitly rule out every HARD BAN: no watermark/logo dominating the frame, no text/title card, no third-party commentator/reactor talking about the subject, no replay indicator, no black screen or transition, not in the banned intro/outro window. Remember: the subject themselves appearing in real footage (interview, press conference, broadcast moment) is fine — only flag a "talking head" if it's someone OTHER than the subject. If you notice a genuine banned element while writing this, pick a different timestamp before outputting — do not describe a violation and keep the timestamp.

BACKUPS — required per scene:
Also give `backups`: up to 2 other (video_index, start) moments that would work for the same segment,
best first, each at least 5 seconds away from `start`. Every pick is checked on its real frames
afterwards, and a backup replaces a pick that fails, so only give moments you actually saw.

RELEVANCE NOTE — required per scene:
Also write a short `relevance_note` string: name the exact word or phrase from that segment's text, and one sentence on how the frame at `start` visually supports it. If you cannot honestly connect the frame to specific words in the segment, that is a signal to pick a different timestamp before outputting — do not write a vague or generic relevance_note and keep the timestamp.

OUTPUT: Return ONLY valid JSON, no explanation, no markdown.

{{
  "scenes": [
    {{"index": 0, "video_index": 0, "start": 12.5, "layout": "full", "focus_x": 0.42, "visual_check": "clear action shot of the subject, no watermark, no text, no third-party commentator, no replay indicator", "relevance_note": "segment says 'pulls out a sharp V-shaped guitar', frame shows him mid-draw pulling the guitar from its case", "backups": [{{"video_index": 1, "start": 40.0}}, {{"video_index": 0, "start": 71.5}}]}},
    {{"index": 1, "video_index": 1, "start": 8.0, "layout": "framed", "focus_x": 0.5, "visual_check": "clear mid-shot of the subject, no watermark, no text, no third-party commentator, no replay indicator", "relevance_note": "segment says 'strict old man who hates anything modern', frame shows him in a stern, traditional pose", "backups": [{{"video_index": 0, "start": 33.0}}]}},
    ...
  ],
  "graphics": [
    {{"type": "stat", "segment_index": 1, "anchor_word": "seventy", "value": "70", "label": "years playing the same song"}},
    ...
  ]
}}
"""

    contents = _labeled_videos(uploaded_files, video_paths) + [prompt]

    max_attempts = 5
    for attempt in range(1, max_attempts + 1):
        try:
            response = _require_text(client.models.generate_content(
                model=GEMINI_MODEL,
                contents=contents,
                config={
                    "thinking_config": {"thinking_budget": 24576},
                    "response_mime_type": "application/json",
                },
            ))
            break
        except Exception as e:
            if isinstance(e, _EmptyReply):
                print(f"{e} (edit plan), retrying... (attempt {attempt}/{max_attempts})")
                time.sleep(5)
            elif "503" in str(e):
                print(f"Gemini 503, retrying in 20s... (attempt {attempt}/{max_attempts})")
                time.sleep(20)
            elif "429" in str(e):
                client, switched = _on_quota_hit(client, "edit plan", attempt, e)
                if switched:
                    uploaded_files = [
                        _upload_and_wait(client, vp, label=f"Video {i}")
                        for i, vp in enumerate(video_paths)
                    ]
                    contents = _labeled_videos(uploaded_files, video_paths) + [prompt]
            else:
                raise
        if attempt == max_attempts:
            raise RuntimeError("Gemini scene detection failed after max retries.")

    text = _fix_timestamps(re.sub(r"```json|```", "", response.text).strip())
    print(f"Gemini multi-source edit plan:\n{text}\n")

    try:
        result = json.loads(text)
        scenes = sorted(result.get("scenes", []), key=lambda x: x["index"])
        _fix_minute_decimals(scenes, video_durations)

        validated = []
        for scene in scenes:
            vi = min(max(scene.get("video_index", 0), 0), len(video_paths) - 1)
            scene["video_index"] = vi
            dur = video_durations[vi]

            lo = intro_bans[vi]
            hi = dur - outro_bans[vi] - 2.0
            if hi < lo:
                # Video too short to honor both bans, so fall back to the old, looser bound.
                lo, hi = 0.0, max(dur - 2.0, 0.0)

            asked = float(scene.get("start", 0.0))
            scene["start"] = round(min(max(asked, lo), hi), 2)
            scene["backups"] = _clamp_backups(scene.get("backups"), video_durations, intro_bans, outro_bans)
            if abs(scene["start"] - asked) > 1.0:
                print(f"Scene {scene.get('index')}: Gemini start {asked:.1f}s is outside video {vi}'s usable range, "
                      f"moved to {scene['start']:.1f}s (Gemini did not check this frame)")
            _validate_layout(scene, full_allowed)
            validated.append(scene)

        graphics = []
        for g in result.get("graphics") or []:
            try:
                si = int(g.get("segment_index", -1))
            except (TypeError, ValueError, AttributeError):
                continue
            seg = script_segments[si] if 0 <= si < n else None
            clean = _validate_graphic(g, seg, allowed_graphics, si)
            if clean:
                clean["segment_index"] = si
                graphics.append(clean)
        print(f"{len(validated)} scenes planned across {len(video_paths)} video(s), {len(graphics)} graphic card(s) proposed")
        return validated, graphics, video_paths, uploaded_files, client
    except Exception as e:
        print(f"Failed to parse scene JSON: {e}\nRaw: {text}")
        fallback = []
        for i in range(n):
            vi = i % len(video_paths)
            dur = video_durations[vi]
            start = 10.0 + 15.0 * (i // len(video_paths))
            fallback.append({"index": i, "video_index": vi, "start": round(min(start, max(dur - 12.0, 0.0)), 2)})
        return fallback, [], video_paths, uploaded_files, client


def _verify_scenes(client, scenes, script_segments, video_paths, crops, subject, look=None):
    """
    Check every planned clip on its real frames and swap in a backup when it fails.

    Round 1 checks each scene's pick against the line and against what the plan
    claimed the frame shows, later rounds check the next backup of the scenes that
    failed. A scene with no passing candidate continues its nearest passing
    neighbour's footage from where that clip ends; only if that fails too does it
    reuse the neighbour's shot (the same shot twice beats a clip of another story).
    Starts are snapped to shot cuts here, so the frames checked are the frames used.
    """
    candidates = {s["index"]: [{"video_index": s["video_index"], "start": s["start"],
                                "layout": s.get("layout"), "focus_x": s.get("focus_x")}]
                  + [{**b, "layout": "framed"} for b in s.get("backups") or []]
                  for s in scenes}
    segment_by_index = dict(enumerate(script_segments))
    chosen, last_shows = {}, {}
    overlay_picks = {}   # scene -> first candidate that failed only for a logo/text overlay
    for rnd in range(3):
        todo = [s for s in scenes if s["index"] not in chosen and rnd < len(candidates[s["index"]])]
        if not todo:
            break
        checks, picks = [], {}
        for s in todo:
            c = dict(candidates[s["index"]][rnd])
            video = video_paths[c["video_index"]]
            c["start"] = _snap_to_shot_cut(video, c["start"], max_back=0.5 if s["index"] == 0 else 1.5)
            seg = segment_by_index.get(s["index"], {})
            mid = c["start"] + max(1.0, min(seg.get("duration", 4.0), 6.0) / 2)
            crop = crops.get(video)
            should = f'a shot for the line "{seg.get("text", "")}"'
            if rnd == 0 and s.get("visual_check"):
                # the plan's own claim: "Avida showing King a coat with a gold crown" passed
                # on a frame of her eye when only the line was checked
                should += f'. The editor claims the frame shows: {s["visual_check"]}'
            checks.append({"id": str(s["index"]), "should_show": should,
                           "frames": [_frame_jpeg(video, c["start"] + 0.3, crop), _frame_jpeg(video, mid, crop)]})
            picks[str(s["index"])] = c
        results = _check_frames(client, checks, subject, look)
        if results is None:
            # The check itself failed: keep the remaining first picks as they are.
            for s in todo:
                chosen.setdefault(s["index"], picks[str(s["index"])])
            break
        for sid, c in picks.items():
            r = results.get(sid)
            label = "pick" if rnd == 0 else f"backup {rnd}"
            verdict = "unchecked" if r is None else ("ok" if r.get("ok") else "FAIL")
            print(f"Scene {sid} {label} (video {c['video_index']} @ {c['start']:.1f}s): "
                  f"{verdict}, {(r or {}).get('shows', 'no answer')}")
            r = r or {"ok": True}   # a check Gemini skipped proves nothing, keep the pick
            if r.get("ok"):
                chosen[int(sid)] = c
            else:
                last_shows[int(sid)] = r.get("shows", "")
                if r.get("overlay_only") is True:
                    overlay_picks.setdefault(int(sid), c)

    # A shot of the right moment with a news logo on it beats another video's clean
    # footage: every gesture shot carried a Guardian logo, every scene fell back to the
    # Ireland clip, and the Short showed one red card seven times.
    for i, c in overlay_picks.items():
        if i not in chosen:
            print(f"Scene {i}: no clean shot, using video {c['video_index']} @ {c['start']:.1f}s "
                  f"(right moment, only a logo or text overlay on it)")
            chosen[i] = c

    chosen.update(_continue_neighbours(client, scenes, chosen, segment_by_index, video_paths, crops, subject, look))

    for s in scenes:
        i = s["index"]
        if i not in chosen and chosen:
            near = min(chosen, key=lambda k: abs(k - i))
            print(f"WARNING: scene {i} has no clean shot ({last_shows.get(i, '')}), reusing scene {near}'s shot")
            chosen[i] = dict(chosen[near])
        c = chosen.get(i)
        if c:
            s.update(video_index=c["video_index"], start=c["start"], snapped=True,
                     layout=c.get("layout") or "framed", focus_x=c.get("focus_x") or 0.5)
    if not chosen:
        print("WARNING: no planned shot passed the frame check, using Gemini's picks unchecked")
    _spread_overlaps(scenes, segment_by_index, video_paths)
    return scenes


def _spread_overlaps(scenes, segment_by_index, video_paths):
    """
    Last guard against playing the same footage twice: a clip that starts inside an
    earlier clip of the same video moves to the nearest free stretch of that video
    (right after a placed clip, or the very start). Five scenes clamped to one start
    once became five copies of the same title card. Only "move to where the earlier
    clip ends" gave up at the end of a 34-second source and kept the duplicate.
    """
    placed = {}   # video_index -> [(start, end)]
    for s in sorted(scenes, key=lambda s: s["index"]):
        seg = segment_by_index.get(s["index"], {})
        length = max(seg.get("cut_duration", seg.get("duration", 4.0)), MIN_CLIP_DURATION)
        spans = placed.setdefault(s["video_index"], [])
        duration = _probe_duration(video_paths[s["video_index"]])

        def free(t):
            return t + length <= duration and all(not (a - length < t < b) for a, b in spans)

        if not free(s["start"]) and spans:
            options = sorted({b for _a, b in spans} | {0.0}, key=lambda t: abs(t - s["start"]))
            fit = next((t for t in options if free(t)), None)
            if fit is not None:
                print(f"Scene {s['index']} overlapped an earlier clip, moved {s['start']:.1f}s -> {fit:.1f}s")
                s["start"] = round(fit, 2)
            else:
                print(f"WARNING: scene {s['index']} repeats footage, video {s['video_index']} is too short "
                      f"({duration:.0f}s) for every clip planned on it")
        spans.append((s["start"], s["start"] + length))


def _continue_neighbours(client, scenes, chosen, segment_by_index, video_paths, crops, subject, look):
    """
    For scenes with no passing candidate: keep playing the nearest passing scene's
    footage from where its clip ends (or, for a scene before it, the stretch just
    before it starts). Copying the neighbour's start played one shot twice in a row.
    Returns {scene index: candidate} for the continuations that pass the frame check.
    """
    seconds = {i: max(seg.get("cut_duration", seg.get("duration", 4.0)), MIN_CLIP_DURATION)
               for i, seg in segment_by_index.items()}
    fills, checks = {}, []
    for i in sorted(s["index"] for s in scenes if s["index"] not in chosen):
        placed = {**chosen, **fills}
        if not placed:
            break
        near = min(placed, key=lambda k: (abs(k - i), k > i))   # the scene before wins a tie
        base = placed[near]
        video = video_paths[base["video_index"]]
        if near < i:
            start = base["start"] + sum(seconds.get(k, 4.0) for k in range(near, i))
        else:
            start = base["start"] - sum(seconds.get(k, 4.0) for k in range(i, near))
        if start < 0 or start + seconds.get(i, 4.0) > _probe_duration(video):
            continue
        start = _snap_to_shot_cut(video, round(start, 2), max_back=0.3, max_forward=1.0)
        fills[i] = {"video_index": base["video_index"], "start": start, "layout": "framed",
                    "focus_x": 0.5, "from": near}
        seg = segment_by_index.get(i, {})
        crop = crops.get(video)
        mid = start + max(1.0, min(seg.get("duration", 4.0), 6.0) / 2)
        checks.append({"id": str(i), "should_show": f'a shot for the line "{seg.get("text", "")}"',
                       "frames": [_frame_jpeg(video, start + 0.3, crop), _frame_jpeg(video, mid, crop)]})
    if not fills:
        return {}
    results = _check_frames(client, checks, subject, look)
    passed = {}
    for i, c in fills.items():
        r = None if results is None else results.get(str(i))
        verdict = "unchecked" if r is None else ("ok" if r.get("ok") else "FAIL")
        print(f"Scene {i} continues scene {c['from']}'s footage (video {c['video_index']} @ {c['start']:.1f}s): "
              f"{verdict}, {(r or {}).get('shows', 'no answer')}")
        if r is None or r.get("ok"):
            passed[i] = c
    return passed


MIN_FULL_SHOT = 1.0       # a full-screen crop shorter than this before the first cut isn't worth it
CARD_SECONDS = 4.0        # how long a graphic card stays up (shorter if the next one comes sooner)
HOOK_CLEAR_SECONDS = 3.0  # no cards over the opening hook
MIN_CARD_GAP = 6.0        # minimum seconds between two cards starting


def _clip_layout(scene, clip_path, source_video, crop):
    """Layout info for one trimmed clip, with the full-screen guardrail applied.

    Gemini judged the shot at `start`, but the clip can cut to a different
    (often wider) shot a few seconds later. Full screen therefore only lasts
    until the first hard cut inside the clip, then Remotion switches to framed.
    """
    meta = {"layout": "framed", "focusX": 0.5}
    if scene.get("layout") != "full":
        return meta
    try:
        clip_dur = float(ffmpeg.probe(clip_path)["format"]["duration"])
        cuts = [c for c in _find_shot_cuts(clip_path, 0.0, clip_dur) if c > 0.1]
    except Exception as e:
        print(f"Cut check failed for {clip_path}, keeping it framed: {e}")
        return meta
    full_until = cuts[0] if cuts else clip_dur
    if full_until < MIN_FULL_SHOT:
        print(f"Clip {scene.get('index')}: full shot only lasts {full_until:.1f}s, using framed")
        return meta

    focus_x = scene.get("focus_x", 0.5)
    if crop:
        # Gemini saw the uncropped frame; re-express focus_x inside the cropped picture.
        try:
            src_w = next(st["width"] for st in ffmpeg.probe(source_video)["streams"] if st["codec_type"] == "video")
            cw, _, x, _ = map(int, crop.split(":"))
            focus_x = min(max((focus_x * src_w - x) / cw, 0.15), 0.85)
        except Exception:
            pass
    print(f"Clip {scene.get('index')}: full screen for {full_until:.1f}s (focus {focus_x:.2f})")
    return {"layout": "full", "focusX": round(focus_x, 3), "fullUntil": round(full_until, 2)}


def _same_word(spoken, anchor):
    a = spoken.strip(".,!?\"'…:;").lower()
    b = anchor.strip(".,!?\"'…:;").lower()
    if a == b:
        return True
    # "52" from Whisper vs "fifty-two" from Gemini (or the other way round)
    na, nb = _numbers_in_text(a), _numbers_in_text(b)
    return bool(na and na == nb)


def _time_graphic(graphic, segment, words_data):
    """Give a graphic absolute start/end times: it appears on its anchor word and stays CARD_SECONDS."""
    start = segment["start"] + 0.3
    anchor = graphic.get("anchor_word", "")
    for word, w_start, _ in words_data:
        if segment["start"] - 0.05 <= w_start <= segment["end"] and anchor and _same_word(word, anchor):
            start = w_start
            break
    timed = {k: v for k, v in graphic.items() if k not in ("anchor_word", "segment_index")}
    timed["start"] = round(start, 3)
    timed["end"] = round(start + CARD_SECONDS, 3)
    return timed


def _fit_graphic_windows(graphics):
    """Enforce card spacing: none over the hook, at least MIN_CARD_GAP between starts
    (earlier card wins), and each card ends before the next one starts."""
    spaced = []
    for g in sorted(graphics, key=lambda g: g["start"]):
        if g["start"] < HOOK_CLEAR_SECONDS:
            print(f"Dropped {g['type']} card at {g['start']:.1f}s (over the hook)")
        elif spaced and g["start"] - spaced[-1]["start"] < MIN_CARD_GAP:
            print(f"Dropped {g['type']} card at {g['start']:.1f}s (too close to the previous card)")
        else:
            spaced.append(g)
    graphics = spaced
    for cur, nxt in zip(graphics, graphics[1:]):
        cur["end"] = round(min(cur["end"], nxt["start"] - 0.1), 3)
    return [g for g in graphics if g["end"] - g["start"] >= 1.0]


def find_thumbnail_with_gemini(client, uploaded_files, video_paths, topic, subject, title=None):
    """
    Reuses the already-uploaded (ACTIVE) video files from find_scenes_with_gemini to pick
    the single best thumbnail frame across all footage, plus a short punchy hook broken
    into 1-3 colored lines (comic-thumbnail style, e.g. "PRIME" yellow / "SUKUNA" red).
    Returns {"video_index", "start", "hook_lines": [{"text", "color"}, ...]} or None.
    """
    if not uploaded_files or not video_paths:
        return None

    video_durations = []
    for vp in video_paths:
        try:
            info = ffmpeg.probe(vp)
            vs = next(s for s in info["streams"] if s["codec_type"] == "video")
            video_durations.append(float(vs["duration"]))
        except Exception:
            video_durations.append(0.0)

    prompt = f"""
You are picking the single YouTube Shorts / TikTok THUMBNAIL frame for this video — the static
image someone sees before they tap play. This is a separate job from editing the video itself.

TOPIC: {topic}
SUBJECT: {subject}
VIDEO TITLE: {title or topic}

Across all the source videos provided, find the ONE frame that would make someone stop
scrolling and tap: the most visually striking, dramatic, or emotionally loaded moment —
a clear expression, a dramatic pose, a strong silhouette. It does not need to match any
specific script segment, it just needs to be the single best-looking, clearest frame of
the main subject(s) available anywhere in the footage.

CROP SAFETY (important): this frame will be cropped from its original widescreen shape into
a tall 9:16 vertical thumbnail, centered horizontally, biased slightly toward the top. That
means the left and right edges of the frame get cut off, and a wide/far shot will lose most
of its width. Pick a frame where the main subject is horizontally centered (or close to it)
and large enough in frame that a centered vertical crop still keeps them fully visible and
not awkwardly sliced at the shoulders/arms. Avoid frames where the subject is off to one side,
very small/distant, or where two subjects are spread far apart horizontally.

HARD BANS — never pick a frame with:
- A watermark, channel logo, or platform bug dominating the frame
- Any text, title card, or caption baked into the footage
- A third-party commentator/reactor talking about the subject (someone other than the subject)
- Black screen, fade transition, or replay indicator
- The first 10 seconds or last 30 seconds of any video (intros/outros)

Also write a short HOOK, split into 1-3 short lines, comic-thumbnail style, 3 to 6 words
total, curiosity-driven. The hook MUST be about the TOPIC and SUBJECT above — name or clearly
reference the actual subject of THIS video. It must tease the same question or claim as the
VIDEO TITLE, never a different story (a title asking why A left B needs a hook about A leaving,
not about B's downfall). Do NOT reuse the wording from the format example
below; that is only a shape to copy, not content. Structure examples (do not copy the words):
"BIGGEST MISCONCEPTION / ABOUT [SUBJECT]", "[SUBJECT]: GOAT / OR OVERRATED", "THE ONLY / HOPE".
Give EACH line its own color from this palette only: "#FFFFFF" (white),
"#FFE000" (yellow), "#FF3B30" (red). Use color to emphasize the most dramatic word/line,
the way real viral reaction thumbnails do, don't make every line the same color.

OUTPUT: Return ONLY valid JSON, no explanation, no markdown.
{{"video_index": 0, "start": 12.5, "hook_lines": [{{"text": "LINE ONE", "color": "#FFE000"}}, {{"text": "LINE TWO", "color": "#FF3B30"}}]}}
"""

    contents = _labeled_videos(uploaded_files, video_paths) + [prompt]

    max_attempts = 5
    response = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = _require_text(client.models.generate_content(
                model=GEMINI_MODEL,
                contents=contents,
                config={"response_mime_type": "application/json"},
            ))
            break
        except Exception as e:
            if isinstance(e, _EmptyReply):
                print(f"{e} (thumbnail), retrying... (attempt {attempt}/{max_attempts})")
                time.sleep(5)
            elif "503" in str(e):
                print(f"Gemini 503 (thumbnail), retrying in 20s... (attempt {attempt}/{max_attempts})")
                time.sleep(20)
            elif "429" in str(e):
                try:
                    client, switched = _on_quota_hit(client, "thumbnail", attempt, e)
                except GeminiDailyQuota as q:
                    print(f"{q} Skipping the thumbnail.")
                    return None
                if switched:
                    uploaded_files = [
                        _upload_and_wait(client, vp, label=f"Video {i}")
                        for i, vp in enumerate(video_paths)
                    ]
                    contents = _labeled_videos(uploaded_files, video_paths) + [prompt]
            else:
                print(f"Thumbnail selection failed: {e}")
                return None

    if response is None:
        print("Thumbnail selection failed after max retries.")
        return None

    text = _fix_timestamps(re.sub(r"```json|```", "", response.text).strip())
    try:
        result = json.loads(text)
        vi = min(max(result.get("video_index", 0), 0), len(video_paths) - 1)
        dur = video_durations[vi]
        lo, hi = 10.0, max(dur - 30.0 - 2.0, 0.0)
        if hi < lo:
            lo, hi = 0.0, max(dur - 2.0, 0.0)
        start = round(min(max(result.get("start", 0.0), lo), hi), 2)

        ALLOWED_COLORS = {"#FFFFFF", "#FFE000", "#FF3B30"}
        hook_lines = []
        for line in result.get("hook_lines", [])[:3]:
            line_text = str(line.get("text", "")).strip().upper()
            if not line_text:
                continue
            color = str(line.get("color", "#FFFFFF")).strip().upper()
            if color not in ALLOWED_COLORS:
                color = "#FFFFFF"
            hook_lines.append({"text": line_text, "color": color})
        if not hook_lines:
            return None

        # Subject guard: warn loudly if the hook references none of the subject/topic words.
        # Catches the "PRIME SUKUNA on a MAPPA-director video" class of silent mismatch.
        STOPWORDS = {"the", "and", "for", "with", "his", "her", "why", "how", "who",
                     "was", "are", "about", "this", "that", "from", "into"}
        subject_words = {
            w for w in re.findall(r"[a-z0-9]+", f"{subject} {topic}".lower())
            if len(w) >= 3 and w not in STOPWORDS
        }
        hook_text = " ".join(l["text"] for l in hook_lines).lower()
        if subject_words and not any(w in hook_text for w in subject_words):
            print(f"Thumbnail hook may not match subject '{subject}': {hook_text!r} "
                  f"(no overlap with {sorted(subject_words)})")

        print(f"Thumbnail pick: video {vi} @ {start}s: {hook_lines}")
        return {"video_index": vi, "start": start, "hook_lines": hook_lines}
    except Exception as e:
        print(f"Failed to parse thumbnail JSON: {e}\nRaw: {text}")
        return None


def run_manual_pipeline(data):
    """Run the full pipeline from a MANUAL_DATA dict: download, evaluate, voice, music, subtitles, edit."""
    approved_videos, clip_paths, audio_path, music_path = [], [], None, None
    thumb_frame_path = None
    pipeline_ok = False
    try:
        TOPIC = data['topic']
        SUBJECT = data['specific_subject']
        YOUTUBE_QUERIES = data.get('youtube_queries', [])
        MUSIC_PROMPT = data.get('music_prompt', 'calm ambient cinematic instrumental music')
        MUSIC_QUERIES = data.get('music_queries') or data.get('music_query')
        CHANNEL = load_channel(data.get('channel'))
        VOICE_NAME = data.get('voice_name') or CHANNEL['voice_name']
        SCRIPT_TEXT, _punch_words = _strip_punch_markers(data['script'])
        _check_sfx_tags(_punch_words)

        print(f"PROCESSING MANUAL ORDER: {SUBJECT}")
        print(f"topic: {TOPIC}")
        print(f"   Script Length: {len(SCRIPT_TEXT)} chars")

        # Voice and Whisper only need the script, so they run while footage is searched
        print("Starting voice in background...")
        voice_executor = ThreadPoolExecutor(max_workers=1)
        voice_future = voice_executor.submit(
            _prepare_narration, SCRIPT_TEXT, VOICE_NAME, _punch_words, data.get("title") or TOPIC)

        print("Fetching visuals...")

        LOOK = data.get("scene_query")   # how the footage looks, for characters Gemini doesn't know
        rejected_videos = []
        backup_videos = []    # (score, path): good footage of the subject that shows no script item
        used_video_ids = set()
        MAX_SOURCE_VIDEOS = 3

        script_items = None   # concrete things the script talks about, fixed by the first evaluation
        video_items = {}      # approved video path -> script items it shows

        # Every query is searched first and the results ranked together, so the slow
        # download + Gemini check goes to the best videos overall, not two per query.
        pool = search_pool(YOUTUBE_QUERIES, used_video_ids)
        tried, failed_in_a_row = 0, 0
        for entry in pool:
            # Each query's best result is a "first pick" and is checked even past 3 approvals:
            # stopping at 3 once approved two red card clips before the gesture clip was tried.
            if len(approved_videos) >= MAX_SOURCE_VIDEOS_CAP or (
                    len(approved_videos) >= MAX_SOURCE_VIDEOS and not entry.get("_first_pick")):
                print(f"Reached {len(approved_videos)} approved videos.")
                break
            if tried >= MAX_CANDIDATES:
                print(f"Checked {tried} videos, stopping the search.")
                break
            if failed_in_a_row >= MAX_DOWNLOAD_FAILURES:
                print(f"{failed_in_a_row} downloads failed in a row, YouTube is probably blocking. Stopping the search.")
                break

            candidate_video = download_entry(entry, used_video_ids)
            entry["_path"] = candidate_video
            if not candidate_video or candidate_video in rejected_videos or candidate_video in approved_videos:
                failed_in_a_row += 1
                continue
            failed_in_a_row = 0
            tried += 1
            try:
                ffmpeg.probe(candidate_video)
            except Exception:
                print("Downloaded file is corrupt (ffprobe failed), skipping")
                rejected_videos.append(candidate_video)
                continue
            crop_overlays(candidate_video)   # cut fixed news banners and logos before Gemini sees it
            print(f"Evaluating video {tried}/{MAX_CANDIDATES} (score {entry['_score']}, "
                  f"found by {entry['_queries']} quer{'y' if entry['_queries'] == 1 else 'ies'})...")
            try:
                evaluation = evaluate_video_with_genai(candidate_video, SCRIPT_TEXT, script_items,
                                                       SUBJECT, LOOK) or {}
            except RuntimeError as e:
                print(f"Gemini evaluation failed: {e}, skipping")
                rejected_videos.append(candidate_video)
                continue

            if script_items is None and evaluation.get("script_items"):
                script_items = [str(x) for x in evaluation["script_items"]][:6]
                print(f"Script items to cover: {script_items}")
            known = {x.lower() for x in script_items or []}
            shown = [str(x) for x in evaluation.get("items_shown") or [] if str(x).lower() in known]

            reason = evaluation.get("reason", "")
            decision = evaluation.get("decision", "unknown")
            if decision == "post" and script_items and not shown:
                decision, reason = "reject", f"shows none of the script items. {reason}"
            if decision == "post":
                # numbered like the edit plan's video_index, so the logs line up
                print(f"Video {len(approved_videos)} approved! Shows {shown or 'n/a'}: {reason}")
                approved_videos.append(candidate_video)
                video_items[candidate_video] = shown
            elif _subject_only(evaluation, shown):
                score = sum(evaluation.get(k) or 0 for k in ("relevance_score", "hook_score", "technical_score"))
                print(f"Video kept as a backup (clean footage of the subject, but none of the script items): {reason}")
                backup_videos.append((score, candidate_video, entry.get("_query")))
            else:
                print(f"Video rejected ({decision}): {reason}")
                rejected_videos.append(candidate_video)

        # Sports scripts are told to use off-pitch footage (training, arrivals) because match
        # moments are blocked, so "shows none of the script items" rejected four long, clean
        # Ronaldo training videos and the whole Short came from one 34-second clip. A backup
        # only fills a slot the real matches left empty.
        # Each query names one moment, so a backup from a query no other pick came from goes
        # first: by score alone, two red card clips beat the only Messi gesture clip. Among
        # those, the earlier query wins: prompts list the script's moments first, filler last.
        backup_videos.sort(key=lambda b: b[0], reverse=True)
        used_queries = {e.get("_query") for e in pool if e.get("_path") in approved_videos}
        query_rank = {q: i for i, q in enumerate(YOUTUBE_QUERIES)}
        while backup_videos and len(approved_videos) < MAX_SOURCE_VIDEOS:
            fresh = sorted((b for b in backup_videos if b[2] not in used_queries),
                           key=lambda b: query_rank.get(b[2], len(query_rank)))
            pick = (fresh or backup_videos)[0]
            backup_videos.remove(pick)
            used_queries.add(pick[2])
            print(f"Using backup video {len(approved_videos)} (general footage of the subject): {_video_title(pick[1])}")
            approved_videos.append(pick[1])
            video_items[pick[1]] = []
        rejected_videos += [path for _score, path, _q in backup_videos]

        if script_items:
            covered = {x.lower() for shown in video_items.values() for x in shown}
            missing = [x for x in script_items if x.lower() not in covered]
            if missing:
                print(f"WARNING: no approved footage shows {missing}. Those lines will get loosely related shots; "
                      f"add a YouTube query for each next time.")

        for path in rejected_videos:
            if path in approved_videos:
                continue
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass
            _remove_sidecars(path)

        if not approved_videos:
            print("All queries failed. No suitable video found.")
            return False

        print(f"{len(approved_videos)} video(s) approved for editing.")

        # Kick off music resolution immediately, since it has no dependencies on voice/scene
        print("Starting music in background...")
        executor = ThreadPoolExecutor(max_workers=1)
        music_future = executor.submit(_resolve_music, MUSIC_QUERIES, MUSIC_PROMPT, TOPIC, SCRIPT_TEXT)

        # Voice must be done before scene finding so Whisper timestamps drive the cuts
        print("Waiting for voice...")
        audio_path, words_data, tagged_sfx = voice_future.result()
        voice_executor.shutdown(wait=False)

        clip_paths = []
        clip_meta = []      # per clip: layout, focusX, fullUntil (aligned with clip_paths)
        graphics = []       # narration graphics with absolute start/end times
        thumb_hook_lines = None
        if words_data is not None and len(words_data) > 0:
            script_segments = segment_by_sentences(words_data)
            script_segments = merge_short_segments(script_segments, MIN_SEGMENT_DURATION)
            while len(script_segments) > MAX_CLIPS:
                shortest = min(range(len(script_segments)), key=lambda i: script_segments[i]["duration"])
                m = shortest - 1 if shortest > 0 else 0
                a, b = script_segments[m], script_segments[m + 1]
                script_segments[m] = {"text": a["text"] + " " + b["text"], "start": a["start"], "end": b["end"], "duration": b["end"] - a["start"]}
                script_segments.pop(m + 1)
            _set_cut_durations(script_segments, tagged_sfx, _probe_duration(audio_path))
            print(f"{len(script_segments)} clips planned, analyzing {len(approved_videos)} video(s)...")
            scenes, graphic_plan, valid_videos, uploaded_files, gemini_client = find_scenes_with_gemini(approved_videos, script_segments, CHANNEL, video_items, LOOK)

            if len(scenes) < len(script_segments):
                print(f"Gemini returned {len(scenes)} scenes for {len(script_segments)} segments, using available scenes only")
            crops = {v: _detect_crop(v) for v in valid_videos}
            print("Checking every planned shot on its real frames...")
            scenes = _verify_scenes(gemini_client, scenes, script_segments, valid_videos, crops, SUBJECT, LOOK)
            for scene, segment in zip(scenes, script_segments):
                vi = min(scene.get("video_index", 0), len(valid_videos) - 1)
                source_video = valid_videos[vi]
                # The hook must open on the action, so it may only back up a little.
                start = scene["start"] if scene.get("snapped") else _snap_to_shot_cut(
                    source_video, scene["start"], max_back=0.5 if scene["index"] == 0 else 1.5)
                clip_path = f"clip_{scene['index']}_{uuid.uuid4().hex[:6]}.mp4"
                success = trim_video_to_end(
                    input_file=source_video,
                    output_file=clip_path,
                    ai_start=start,
                    prepad=0.0,
                    max_duration=max(segment["cut_duration"], MIN_CLIP_DURATION),
                    crop=crops[source_video],
                )
                if success is not False and os.path.exists(clip_path):
                    clip_paths.append(clip_path)
                    clip_meta.append(_clip_layout(scene, clip_path, source_video, crops[source_video]))

            if words_data:
                graphics = [_time_graphic(g, script_segments[g["segment_index"]], words_data) for g in graphic_plan]
            graphics = _fit_graphic_windows(graphics)
            print(f"Graphics: {[(g['type'], g['start']) for g in graphics] or 'none'}")

            print("Picking thumbnail frame...")
            thumb = find_thumbnail_with_gemini(gemini_client, uploaded_files, valid_videos, TOPIC, SUBJECT,
                                               data.get("title"))
            if thumb:
                frame_path = os.path.join(DATA_DIR, f"thumb_frame_{uuid.uuid4().hex[:6]}.jpg")
                thumb_video = valid_videos[thumb["video_index"]]
                thumb_crop = crops.get(thumb_video)
                try:
                    subprocess.run(
                        ["ffmpeg", "-y", "-ss", str(thumb["start"]),
                         "-i", thumb_video,
                         *(["-vf", f"crop={thumb_crop}"] if thumb_crop else []),
                         "-frames:v", "1", "-update", "1", "-q:v", "2", frame_path],
                        check=True, capture_output=True,
                    )
                    thumb_frame_path, thumb_hook_lines = frame_path, thumb["hook_lines"]
                except subprocess.CalledProcessError as e:
                    print(f"Thumbnail frame extraction failed: {e.stderr.decode()[-300:]}")

        if not clip_paths:
            # Spanish, or transcription failed
            print("Falling back to single-scene Gemini search...")
            fallback_video = next(
                (v for v in approved_videos if not _ffprobe_fails(v)), None
            )
            if not fallback_video:
                raise RuntimeError("No usable approved videos, all failed ffprobe.")
            scene = find_scene_with_gemini(fallback_video, data.get("scene_query"), SCRIPT_TEXT)
            if scene and not (scene["start"] == 0 and scene["end"] == 0):
                clip_path = f"trimmed_scene_{uuid.uuid4().hex[:6]}.mp4"
                start = _snap_to_shot_cut(fallback_video, scene["start"], max_back=0.5)
                trim_video_to_end(fallback_video, clip_path, start, prepad=0.02, max_duration=61.0,
                                  crop=_detect_crop(fallback_video))
                clip_paths = [clip_path]
            else:
                clip_paths = [fallback_video]

        print("Waiting for music generation...")
        music_path = music_future.result()
        executor.shutdown(wait=False)
        if not music_path:
            print("Music generation failed, continuing without music.")

        # Named after the title: SUBJECT is a long fact list that made filenames unreadable
        safe_name = re.sub(r'[^A-Za-z0-9]+', '_', _hook_text(data.get("title", "")) or SUBJECT).strip('_')[:60]
        final_filename = f"Short_{safe_name}_{random.randint(10, 99)}.mp4"

        # The thumbnail is one frame, so render it alongside the main video instead of after it
        thumb_executor = ThreadPoolExecutor(max_workers=1)
        thumb_future = None
        if thumb_frame_path and os.path.exists(thumb_frame_path):
            thumb_filename = os.path.splitext(final_filename)[0] + ".png"
            thumb_future = thumb_executor.submit(render_thumbnail, thumb_frame_path, thumb_hook_lines, thumb_filename)

        print("Starting video editing...")
        final_path = merge_audio_video(
            video_paths=clip_paths,
            audio_path=audio_path,
            output_name=final_filename,
            shorts_cap=True,
            music_path=music_path,
            music_lufs=MUSIC_LUFS,
            words_data=words_data,
            tagged_sfx=tagged_sfx,
            clip_meta=clip_meta,
            graphics=graphics,
            theme=CHANNEL["theme"],
            frame_background=CHANNEL["frame_background"],
            hook_text=_hook_text(data.get("hook") or data.get("title", "")),
        )

        print(f"\nDONE! Saved to: {final_path}")

        if thumb_future:
            try:
                thumb_png = thumb_future.result()
                thumb_executor.shutdown(wait=False)
                if EMBED_THUMBNAIL_FRAME:
                    append_thumbnail_frame(final_path, thumb_png, THUMBNAIL_FRAME_DURATION, THUMBNAIL_FRAME_POSITION)
            except Exception as e:
                print(f"Thumbnail render failed: {e}")
            finally:
                os.remove(thumb_frame_path)

        pipeline_ok = True
        return True

    except GeminiDailyQuota as e:
        print(f"\nSTOPPED: {e}")
    except KeyError as e:
        print(f"Missing Key in JSON: {e}")
    except Exception as e:
        print(f"Pipeline Error: {e}")
        traceback.print_exc()
    finally:
        # Only on success: a crash leaves the clips, narration and music on disk
        # so the render can be retried without re-downloading or re-paying for TTS.
        if CLEANUP_FILES and pipeline_ok:
            to_delete = {audio_path, music_path, thumb_frame_path} | set(approved_videos) | set(clip_paths)
            for path in approved_videos:
                if path:
                    _remove_sidecars(path)
            for path in to_delete:
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except Exception:
                        pass


if __name__ == "__main__":
    if MANUAL_DATA:
        run_manual_pipeline(MANUAL_DATA)
    else:
        print("Please paste your JSON into the MANUAL_DATA variable.")
