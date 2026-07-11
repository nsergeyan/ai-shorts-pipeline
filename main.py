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
from sympy.parsing.sympy_parser import null

subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])

from config import GEMINI_API_KEYS

if not GEMINI_API_KEYS:
    raise RuntimeError("GEMINI_API_KEYS is not set. Add it to your .env file.")

_key_pool = itertools.cycle(GEMINI_API_KEYS)

def _gemini_client():
    """Return a Gemini client using the next API key in the rotation pool."""
    key = next(_key_pool)
    print(f"🔑 Gemini key: {key[:8]}...")
    return genai.Client(api_key=key)
try:
    from modules.gameplay_fetcher import fetch_gameplay_by_search
    from modules.music_generator import generate_music, fetch_music_from_youtube
    from modules.newvoice import generate_voice
    from modules.video_editor import merge_audio_video
    from modules.transcriber import transcribe_audio_to_words
except ImportError as e:
    print(f"Error importing modules: {e}")
    sys.exit(1)
# ---------------- CONFIG ---------------- #
LANGUAGE = "en"
MUSIC_VOLUME = 0.08
SUBTITLES_POSITION = "top"
CLEANUP_FILES = True
CLIP_DURATION = 60.0
SLEEP_INTERVAL = 5
MIN_CLIP_DURATION = 3.0
MIN_SEGMENT_DURATION = 10.0
MAX_CLIPS = 5
# ---------------------------------------- #

MANUAL_DATA ={
  "series": "tadc",
  "topic": "Where Jax actually ended up — the finale gave the abstracted monsters an aquarium, and Jax got his lost friends back",
  "specific_subject": "The Aquarium and abstracted Jax's fate in Episode 9 'Remember'",
  "youtube_queries": [
    "tadc finale jax aquarium scene",
    "jax abstraction saddest moment digital circus",
    "abstracted jax edit",
    "digital circus episode 9 ending scene",
    "tadc remember ending english dub",
    "the amazing digital circus remember official"
  ],
  "scene_query": "A dark glowing aquarium wall inside a colorful circus tent, huge smooth black creatures covered in tiny multicolored glowing eyes swimming slowly like squids behind the glass, while a small jester girl in a red and blue hat and a chess piece character watch them quietly from the floor",
  "music_mood": "emotional",
  "music_query": "digital days amazing digital circus instrumental",
  "music_prompt": "Soft emotional lo-fi orchestral, seventy BPM, gentle music box notes over warm ambient synth pads and a slow muffled underwater heartbeat pulse; begins quiet and heavy under the hook, swells gently at the reveal, then blooms into a bittersweet warm chord as the friends reunite, fading out unresolved on the final question; short-form video background, no lyrics, exclude: aggressive trap drums, cheerful circus brass",
  "voice_name": "Hamid",
  "script": "[sad] Everyone cried about Jax in the Digital Circus finale... but almost nobody talks about where he ended up. When someone abstracts, they turn into a monster... *FOREVER!* There is no cure. [gulps] So what did the circus do with Jax? [surprised] *LISTEN!* They built him an aquarium. He now swims around like a giant squid, calm and quiet in the dark. [chuckles] And before the tank was ready? Kinger kept him in a pillow fort. [sorrowful] But here's the part that hurts. Inside that water, Jax is finally back with Ribbit and Kaufmo. The two friends he lost. So... sad ending, or his happiest one?"
}

def _strip_punch_markers(script: str):
    """Strip *word* markers from script. Returns (clean_script, [word, ...]).
    The word content (e.g. BUT!) stays in the script for TTS emphasis; only * is removed."""
    import re
    punch_words = []
    def _replace(m):
        word = m.group(1)
        punch_words.append(word.strip("!?.,;:").lower())
        return word
    clean_script = re.sub(r'\*([^*]+)\*', _replace, script)
    return clean_script, punch_words


def _match_punch_times(punch_words: list, words_data: list) -> list:
    """Match punch words to Whisper timestamps in script order."""
    times = []
    remaining = list(punch_words)
    for word, start, _end in words_data:
        if not remaining:
            break
        clean = word.strip(".,!?\"'—…").lower()
        if clean == remaining[0]:
            times.append(round(start, 3))
            remaining.pop(0)
    return times


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
    max_duration=61.0
):
    """
    Trims video starting a bit before AI-found timestamp and goes up to max_duration seconds,
    but not beyond the actual video length.
    Prevents freezing or looping.
    """

    # get video duration
    info = ffmpeg.probe(input_file)

    video_stream = next(
        s for s in info["streams"]
        if s["codec_type"] == "video"
    )

    video_duration = float(video_stream["duration"])

    # compute safe start
    clip_start = max(float(ai_start) - prepad, 0.0)
    clip_start = min(clip_start, video_duration - 0.001)

    # compute clip end safely
    clip_end = min(clip_start + max_duration, video_duration)
    clip_duration = clip_end - clip_start

    if clip_duration <= 0:
        print("⚠️ Invalid clip duration. Skipping.")
        return False

    subprocess.run([
        "ffmpeg",
        "-ss", str(clip_start),
        "-i", input_file,
        "-t", str(clip_duration),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-c:a", "aac",
        "-movflags", "+faststart",
        output_file
    ], check=True)

    print(f"🎬 Trimmed clip saved: {output_file} ({clip_duration:.2f}s from {clip_start:.2f}s to {clip_end:.2f}s)")

def evaluate_music_with_genai(music_path, script_text):
    """Upload generated music to Gemini and score it for mood, energy, and voice compatibility."""
    client = _gemini_client()

    # Upload music file
    uploaded_file = client.files.upload(file=music_path)
    print(f"Uploaded music: {uploaded_file.name}")

    # Wait until ACTIVE
    file_info = client.files.get(name=uploaded_file.name)
    _poll_errors = 0
    while file_info.state != "ACTIVE":
        print(f"Music state: {file_info.state}, waiting...")
        time.sleep(2)
        try:
            file_info = client.files.get(name=uploaded_file.name)
            _poll_errors = 0
        except Exception as e:
            if "500" in str(e) or "INTERNAL" in str(e):
                _poll_errors += 1
                print(f"⚠️ Gemini 500 during file poll ({_poll_errors}/10), retrying...")
                if _poll_errors >= 10:
                    raise RuntimeError("Gemini file stuck in PROCESSING with repeated 500s — skipping") from e
            else:
                raise

    print("Music file ACTIVE ✅")

    prompt = f"""
    You are a short-form content audio expert.

    Your job is to evaluate how well this MUSIC fits the SCRIPT.

    IMPORTANT RULES:
    - Focus ONLY on the audio provided.
    - Do NOT assume visuals.
    - Judge vibe, energy, and emotional tone.
    - Consider this is for TikTok / YouTube Shorts.

    SCRIPT:
    \"\"\"{script_text}\"\"\"

    SCORING CRITERIA:

    1. Mood Match (mood_score: 1–10)
       Does the music emotionally match the script?

       9–10: Perfect emotional alignment
       7–8 : Good fit
       5–6 : Neutral / usable
       3–4 : Slight mismatch
       1–2 : Completely wrong mood

    2. Energy & Engagement (energy_score: 1–10)
       Is the music engaging for short-form content?

       Consider:
       - buildup
       - rhythm
       - loopability
       - modern feel

    3. Voice Compatibility (voice_score: 1–10)
       Would this music sit well under narration?

       Consider:
       - not too loud or chaotic
       - not distracting
       - supports storytelling
    DECISION RULES:

    - "post"
      mood_score >= 7 AND energy_score >= 7 AND voice_score >= 7

    - "revise"
      usable but not optimal

    - "reject"
      wrong vibe OR distracting OR unusable

    OUTPUT FORMAT:
    Return ONLY JSON.

    {{
      "mood_score": <1-10>,
      "energy_score": <1-10>,
      "voice_score": <1-10>,
      "decision": "post" | "revise" | "reject"
    }}
    """

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[uploaded_file, prompt]
    )

    raw_text = response.text if hasattr(response, "text") else str(response)

    try:
        clean_text = raw_text.strip()
        if not clean_text.startswith("{"):
            clean_text = clean_text[clean_text.find("{"):]
        if not clean_text.endswith("}"):
            clean_text = clean_text[:clean_text.rfind("}") + 1]
        return json.loads(clean_text)
    except Exception as e:
        print(f"⚠️ Failed to parse music JSON: {e}")
        print("Raw:", raw_text)
        return {
            "mood_score": 0,
            "energy_score": 0,
            "voice_score": 0,
            "decision": "revise"
        }

def evaluate_youtube_music_with_genai(music_path: str, topic: str, script_text: str) -> dict:
    """Evaluate YouTube-sourced music: checks for lyrics, topic fit, and voice compatibility."""
    client = _gemini_client()

    uploaded_file = client.files.upload(file=music_path)
    print(f"Uploaded YouTube music: {uploaded_file.name}")

    file_info = client.files.get(name=uploaded_file.name)
    _poll_errors = 0
    while file_info.state != "ACTIVE":
        print(f"Music state: {file_info.state}, waiting...")
        time.sleep(2)
        try:
            file_info = client.files.get(name=uploaded_file.name)
            _poll_errors = 0
        except Exception as e:
            if "500" in str(e) or "INTERNAL" in str(e):
                _poll_errors += 1
                if _poll_errors >= 10:
                    raise RuntimeError("Gemini file stuck in PROCESSING") from e
            else:
                raise

    print("YouTube music file ACTIVE ✅")

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

    DECISION RULES:
    - "use"    → has_lyrics=false AND topic_score >= 7 AND voice_score >= 6
    - "reject" → has_lyrics=true OR topic_score < 7 OR voice_score < 6

    Return ONLY valid JSON, no markdown:
    {{
      "has_lyrics": <true|false>,
      "topic_score": <1-10>,
      "voice_score": <1-10>,
      "decision": "use" | "reject",
      "reason": "<one short sentence>"
    }}
    """

    max_attempts = 5
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[uploaded_file, prompt]
            )
            break
        except Exception as e:
            if "503" in str(e):
                print(f"⚠️ Gemini 503 on music eval, retrying in 20s... ({attempt}/{max_attempts})")
                time.sleep(20)
            elif "429" in str(e):
                print(f"⚠️ Gemini 429 on music eval, rotating key... ({attempt}/{max_attempts})")
                client = _gemini_client()
                time.sleep(5)
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
        print(f"⚠️ Failed to parse YouTube music eval JSON: {e}")
        print("Raw:", raw_text)
        return {"has_lyrics": True, "topic_score": 0, "voice_score": 0, "decision": "reject", "reason": "parse error"}


def _resolve_music(music_query: str | None, music_prompt: str, topic: str, script_text: str) -> str | None:
    """Try YouTube music first if a query is given; fall back to ElevenLabs generation."""
    if music_query and str(music_query).strip().lower() not in ("null", "none", ""):
        yt_path = fetch_music_from_youtube(music_query)
        if yt_path:
            print(f"🔍 Evaluating YouTube music with Gemini...")
            try:
                result = evaluate_youtube_music_with_genai(yt_path, topic, script_text)
                decision = result.get("decision", "reject")
                reason = result.get("reason", "")
                if decision == "use":
                    print(f"✅ YouTube music approved — {reason}")
                    return yt_path
                else:
                    print(f"❌ YouTube music rejected ({reason}) — falling back to ElevenLabs")
            except Exception as e:
                print(f"⚠️ Gemini music eval error: {e} — falling back to ElevenLabs")
            if os.path.exists(yt_path):
                os.remove(yt_path)
        else:
            print("⚠️ YouTube music download failed — falling back to ElevenLabs")

    return generate_music(music_prompt)


def evaluate_video_with_genai(video_path, script_text):
    """Upload a video to Gemini and score it for relevance, hook potential, and technical quality."""
    client = _gemini_client()

    # Upload video
    uploaded_file = client.files.upload(file=video_path)
    print(f"Uploaded file: {uploaded_file.name}")

    # Wait until file is ACTIVE
    file_info = client.files.get(name=uploaded_file.name)
    _poll_errors = 0
    while file_info.state != "ACTIVE":
        print(f"File state: {file_info.state}, waiting...")
        time.sleep(2)
        try:
            file_info = client.files.get(name=uploaded_file.name)
            _poll_errors = 0
        except Exception as e:
            if "500" in str(e) or "INTERNAL" in str(e):
                _poll_errors += 1
                print(f"⚠️ Gemini 500 during file poll ({_poll_errors}/10), retrying...")
                if _poll_errors >= 10:
                    raise RuntimeError("Gemini file stuck in PROCESSING with repeated 500s — skipping") from e
            else:
                raise
    print("File is ACTIVE ✅")

    # Build prompt
    prompt = f"""
    You are an AI Video Editor Assistant.
    Evaluate whether this RAW SOURCE FOOTAGE is usable as background B-roll for a short-form video.
    
    Judge it on POTENTIAL as raw source footage — not as a finished edit.
    
    SCRIPT EXCERPT:
    \"\"\"{script_text}\"\"\"
    
    STEP 0 — REQUIRED SUBJECT (do this first):
    From the script, identify the CHARACTER or SHOW the footage must contain — not a specific state, form, or moment.
    State it internally as REQUIRED_SUBJECT before scoring.
    Example: if the script is about Jax's abstraction, REQUIRED_SUBJECT = "Jax" — normal Jax, abstracted Jax, and scenes leading up to the abstraction ALL count. If the script is about Hange Zoë's hygiene, REQUIRED_SUBJECT = "Hange Zoë" — any footage showing Hange counts, regardless of the scene.
    
    The footage must be raw source material — broadcast footage, official highlights, or documentary footage. It must NOT be someone else's YouTube video where they react to, comment on, or narrate over the clips.

    STEP 0.5 — CONTENT TYPE CHECK (do this before scoring):
    Determine if this is:
    A) Raw/official footage — broadcast clips, official highlights, documentary, raw gameplay footage. ALLOWED.
    B) Reaction/commentary video — a YouTuber or creator watches clips and reacts, talks to camera, or narrates with their own voice over the footage. REJECT IMMEDIATELY.
    C) Fan compilation with heavy custom editing, custom music, or a creator's voiceover throughout. REJECT IMMEDIATELY.
    D) Podcast/interview clip where someone is talking about the subject but not showing real action. REJECT IMMEDIATELY.

    If type B, C, or D → set decision = "reject", technical_score = 1, and stop evaluating.

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
       - 1-4: heavily pixelated, ruined by editing/watermarks, has a creator's face or persistent voiceover, unwatchable.

    DECISION RULES (apply in order):
    - "reject": content type is B, C, or D (reaction/commentary/podcast → automatic reject)
    - "reject": subject_present = false (subject not visible → automatic reject, no exceptions)
    - "reject": relevance_score <= 6  (subject barely visible, wrong character, or wrong show → reject)
    - "reject": technical_score <= 4
    - "post":   relevance_score >= 7 AND hook_score >= 5 AND technical_score >= 5 AND subject_present = true
    - "revise": anything else / unsure
    
    OUTPUT FORMAT:
    Respond ONLY with valid JSON. No explanations, no markdown.
    
    {{
      "required_subject": "<the subject you identified>",
      "subject_present": <true|false>,
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
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[uploaded_file, prompt],
                config={"thinking_config": {"thinking_budget": 8000}},
            )
            break
        except Exception as e:
            if "503" in str(e):
                print(f"⚠️ Gemini 503, retrying in 20s... (attempt {attempt}/{max_attempts})")
                time.sleep(20)
            elif "429" in str(e):
                print(f"⚠️ Gemini 429 quota hit, rotating key... (attempt {attempt}/{max_attempts})")
                client = _gemini_client()
                time.sleep(5)
            else:
                raise
        if attempt == max_attempts:
            raise RuntimeError("Gemini failed after max retries.")

    raw_text = response.text if hasattr(response, "text") else str(response)

    try:
        # Clean up extra characters
        clean_text = raw_text.strip()
        if not clean_text.startswith("{"):
            clean_text = clean_text[clean_text.find("{"):]
        if not clean_text.endswith("}"):
            clean_text = clean_text[:clean_text.rfind("}") + 1]
        return json.loads(clean_text)
    except Exception as e:
        print(f"⚠️ Failed to parse GenAI JSON: {e}")
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

    file_info = client.files.get(name=uploaded_file.name)
    _poll_errors = 0
    while file_info.state != "ACTIVE":
        print(f"File state: {file_info.state}, waiting...")
        time.sleep(2)
        try:
            file_info = client.files.get(name=uploaded_file.name)
            _poll_errors = 0
        except Exception as e:
            if "500" in str(e) or "INTERNAL" in str(e):
                _poll_errors += 1
                print(f"⚠️ Gemini 500 during file poll ({_poll_errors}/10), retrying...")
                if _poll_errors >= 10:
                    raise RuntimeError("Gemini file stuck in PROCESSING with repeated 500s — skipping") from e
            else:
                raise

    print("File ACTIVE ✅")

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
                model="gemini-2.5-flash",
                contents=[uploaded_file, prompt]
            )
            break
        except Exception as e:
            if "503" in str(e):
                print(f"⚠️ Gemini 503, retrying in 20s... (attempt {attempt}/{max_attempts})")
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


def find_scenes_with_gemini(video_paths, script_segments):
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
            print(f"⚠️ Skipping bad video {vp}: {e}")
    video_paths = valid_video_paths

    if not video_paths:
        print("⚠️ All source videos failed ffprobe — using fallback scene plan.")
        return [{"index": i, "video_index": 0, "start": 0.0} for i in range(len(script_segments))], []

    uploaded_files = []
    for i, vp in enumerate(video_paths):
        uf = client.files.upload(file=vp)
        print(f"📤 Uploaded Video {i}: {uf.name}")
        uploaded_files.append(uf)

    pending = list(range(len(uploaded_files)))
    _poll_error_counts = [0] * len(uploaded_files)
    while pending:
        time.sleep(2)
        still_pending = []
        for i in pending:
            try:
                fi = client.files.get(name=uploaded_files[i].name)
                _poll_error_counts[i] = 0
            except Exception as e:
                if "500" in str(e) or "INTERNAL" in str(e):
                    _poll_error_counts[i] += 1
                    print(f"⚠️ Gemini 500 polling video {i} ({_poll_error_counts[i]}/10), retrying...")
                    if _poll_error_counts[i] >= 10:
                        raise RuntimeError(f"Gemini video {i} stuck in PROCESSING with repeated 500s") from e
                    still_pending.append(i)
                    continue
                else:
                    raise
            if fi.state == "ACTIVE":
                print(f"Video {i} ACTIVE ✅")
            else:
                still_pending.append(i)
        pending = still_pending

    n = len(script_segments)
    segments_json = json.dumps(
        [{"index": i, "text": s["text"], "duration": round(s["duration"], 2)}
         for i, s in enumerate(script_segments)],
        indent=2
    )
    video_titles = []
    for vp in video_paths:
        title_file = os.path.splitext(vp)[0] + ".title.txt"
        if os.path.exists(title_file):
            with open(title_file) as tf:
                video_titles.append(tf.read().strip())
        else:
            video_titles.append(os.path.basename(vp))

    videos_info = "\n".join(
        f"  Video {i} — \"{video_titles[i]}\" (duration: {dur:.1f}s)"
        for i, dur in enumerate(video_durations)
    )

    prompt = f"""
You are a professional short-form video editor cutting a TikTok / YouTube Short.
You have {len(video_paths)} source video(s) and a narration split into timed segments.
Your job: pick the single best (video, timestamp) for each segment so the final edit feels intentional, dynamic, and visually synced to the words.

SOURCE VIDEOS:
{videos_info}

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

ACTION PREFERENCE — all clips:
Always prefer shots where the subject is actively doing something (fighting, moving, reacting expressively, an event unfolding) over shots where the subject is standing still, posing, or walking slowly. A frame with visible motion always beats a static frame.

VISUAL-SCRIPT MATCHING (core rule):
- Each clip must visually SUPPORT what is being said in that segment.
- Reveal / surprise segment → a reaction shot, an impact visual, something with weight.
- Calm / explanatory segment → a clear mid-shot establishing what is being described.
- DO NOT assign generic-looking footage that has nothing to do with the narration text.

PACING RULE — energy alternation:
Use your tier tags to vary the edit rhythm. After a HIGH clip, prefer a MID or LOW clip next (not another HIGH). After two non-HIGH clips, return to HIGH. This prevents the edit from feeling like a wall of highlights with no breathing room.
Exception: the first two segments may both be HIGH if the script opens with a strong double-punch.

SHOT VARIETY — mandatory across the full edit:
- Never use two consecutive segments from the exact same timestamp range (clips must be at least 20 seconds apart within the same video).
- Mix shot distances: if segment N is a wide shot, segment N+1 should be a close-up or reaction — not another wide shot.
- MULTI-VIDEO RULE: If you have multiple source videos, you MUST use every available video at least once. Never use the same video more than 2 segments in a row. Spread usage as evenly as possible.

HARD BANS — never pick a timestamp that shows any of:
- A creator, commentator, or presenter speaking directly to camera (talking-head style)
- Static text screens, title cards, or sponsor segments
- Black screens, fade-ins, fade-outs, or scene transitions
- The first 10 seconds of any video (channel intros, animated logos, title cards)
- The last 30 seconds of any video (outros, end screens, subscribe buttons, "thanks for watching" text)
- Score overlays, countdown timers, or match clocks visible in frame
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
☐ Every clip visually matches what its segment text is saying
☐ Energy tiers alternate — no two consecutive HIGH clips after the opening pair
☐ All selected shots show the subject actively doing something (not just standing/posing)
☐ No two consecutive clips are from the same timestamp range in the same video
☐ Shot distances vary across the edit (wide → close-up → mid, etc.)
☐ No banned content in any selected timestamp
☐ All start times are safe (enough footage remaining)
☐ Every available source video is used at least once
☐ No single video is used more than 2 times in a row

TIMESTAMP FORMAT: seconds only (e.g. 90.0 — never 1:30)

OUTPUT: Return ONLY valid JSON, no explanation, no markdown.

{{
  "scenes": [
    {{"index": 0, "video_index": 0, "start": 12.5}},
    {{"index": 1, "video_index": 1, "start": 8.0}},
    ...
  ]
}}
"""

    contents = uploaded_files + [prompt]

    max_attempts = 5
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=contents,
                config={"thinking_config": {"thinking_budget": 24576}},
            )
            break
        except Exception as e:
            if "503" in str(e):
                print(f"⚠️ Gemini 503, retrying in 20s... (attempt {attempt}/{max_attempts})")
                time.sleep(20)
            elif "429" in str(e):
                print(f"⚠️ Gemini 429, rotating key... (attempt {attempt}/{max_attempts})")
                client = _gemini_client()
                time.sleep(5)
            else:
                raise
        if attempt == max_attempts:
            raise RuntimeError("Gemini scene detection failed after max retries.")

    text = re.sub(r"```json|```", "", response.text).strip()
    print(f"🤖 Gemini multi-source edit plan:\n{text}\n")

    try:
        result = json.loads(text)
        scenes = sorted(result.get("scenes", []), key=lambda x: x["index"])
        validated = []
        for scene in scenes:
            vi = min(max(scene.get("video_index", 0), 0), len(video_paths) - 1)
            scene["video_index"] = vi
            max_start = max(video_durations[vi] - 2.0, 0.0)
            scene["start"] = round(min(max(scene.get("start", 0.0), 0.0), max_start), 2)
            validated.append(scene)
        print(f"✂️ {len(validated)} scenes planned across {len(video_paths)} video(s)")
        return validated, video_paths
    except Exception as e:
        print(f"⚠️ Failed to parse scene JSON: {e}\nRaw: {text}")
        return [{"index": i, "video_index": 0, "start": 0.0} for i in range(n)], video_paths


def run_manual_pipeline(data):
    """Run the full pipeline from a MANUAL_DATA dict — download, evaluate, voice, music, subtitles, edit."""
    try:
        TOPIC = data['topic']
        SUBJECT = data['specific_subject']
        YOUTUBE_QUERIES = data.get('youtube_queries', [])
        MUSIC_PROMPT = data.get('music_prompt', 'calm ambient cinematic instrumental music')
        MUSIC_QUERY = data.get('music_query', None)
        VOICE_NAME = data.get('voice_name', 'hamid')
        SCRIPT_TEXT, _punch_words = _strip_punch_markers(data['script'])

        print(f"📋 PROCESSING MANUAL ORDER: {SUBJECT}")
        print(f"topic: {TOPIC}")
        print(f"   Script Length: {len(SCRIPT_TEXT)} chars")

        print(f"🎮 Fetching visuals...")

        approved_videos = []
        rejected_videos = []
        MAX_SOURCE_VIDEOS = 3

        for i, query in enumerate(YOUTUBE_QUERIES):
            print(f"📌 Query {i + 1}/{len(YOUTUBE_QUERIES)}: '{query}'")
            video_paths = fetch_gameplay_by_search(
                search_queries=[query],
                max_videos=1,
                retry_searches=5,
                used_video_ids=set()
            )
            if not video_paths:
                print(f"❌ No results for query '{query}', skipping...")
                continue

            candidate_video = video_paths[0]
            try:
                ffmpeg.probe(candidate_video)
            except Exception:
                print(f"⚠️ Downloaded file is corrupt (ffprobe failed) — skipping")
                rejected_videos.append(candidate_video)
                continue
            print(f"🔍 Evaluating video...")
            try:
                evaluation = evaluate_video_with_genai(candidate_video, SCRIPT_TEXT)
            except RuntimeError as e:
                print(f"⚠️ Gemini evaluation failed for query '{query}': {e} — skipping")
                rejected_videos.append(candidate_video)
                continue

            reason = evaluation.get("reason", "") if evaluation else ""
            if evaluation and evaluation.get("decision") == "post":
                print(f"✅ Video {i + 1} approved! — {reason}")
                approved_videos.append(candidate_video)
                if len(approved_videos) >= MAX_SOURCE_VIDEOS:
                    print(f"🎯 Reached {MAX_SOURCE_VIDEOS} approved videos — skipping remaining queries.")
                    break
            else:
                decision = evaluation.get("decision") if evaluation else "unknown"
                print(f"❌ Video rejected ({decision}) — {reason}")
                rejected_videos.append(candidate_video)

        for path in rejected_videos:
            if path in approved_videos:
                continue
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass

        if not approved_videos:
            print("❌ All queries failed. No suitable video found.")
            return False

        print(f"✅ {len(approved_videos)} video(s) approved for editing.")

        # Kick off music resolution immediately — it has no dependencies on voice/scene
        print(f"🎵 Starting music in background...")
        executor = ThreadPoolExecutor(max_workers=1)
        music_future = executor.submit(_resolve_music, MUSIC_QUERY, MUSIC_PROMPT, TOPIC, SCRIPT_TEXT)

        # Voice must come before scene finding so Whisper timestamps drive the cuts
        print(f"🗣️ Generating voice ({VOICE_NAME})...")
        audio_filename = f"narration_{random.randint(1000, 9999)}.mp3"
        audio_path = generate_voice(SCRIPT_TEXT, audio_filename, VOICE_NAME, LANGUAGE)

        print(f"📝 Transcribing for scene sync...")
        if LANGUAGE == "es":
            print("🇪🇸 Spanish detected — skipping subtitles.")
            words_data = None
        else:
            words_data = transcribe_audio_to_words(audio_path, LANGUAGE)

        clip_paths = []
        if words_data is not None and len(words_data) > 0:
            script_segments = segment_by_sentences(words_data)
            script_segments = merge_short_segments(script_segments, MIN_SEGMENT_DURATION)
            while len(script_segments) > MAX_CLIPS:
                shortest = min(range(len(script_segments)), key=lambda i: script_segments[i]["duration"])
                m = shortest - 1 if shortest > 0 else 0
                a, b = script_segments[m], script_segments[m + 1]
                script_segments[m] = {"text": a["text"] + " " + b["text"], "start": a["start"], "end": b["end"], "duration": b["end"] - a["start"]}
                script_segments.pop(m + 1)
            print(f"🎬 {len(script_segments)} clips planned — analyzing {len(approved_videos)} video(s)...")
            scenes, valid_videos = find_scenes_with_gemini(approved_videos, script_segments)

            if len(scenes) < len(script_segments):
                print(f"⚠️ Gemini returned {len(scenes)} scenes for {len(script_segments)} segments — using available scenes only")
            for scene, segment in zip(scenes, script_segments):
                vi = min(scene.get("video_index", 0), len(valid_videos) - 1)
                source_video = valid_videos[vi]
                clip_path = f"clip_{scene['index']}_{uuid.uuid4().hex[:6]}.mp4"
                success = trim_video_to_end(
                    input_file=source_video,
                    output_file=clip_path,
                    ai_start=scene["start"],
                    prepad=0.0,
                    max_duration=max(segment["duration"], MIN_CLIP_DURATION),
                )
                if success is not False and os.path.exists(clip_path):
                    clip_paths.append(clip_path)

        if not clip_paths:
            # Fallback for Spanish or failed transcription
            print("🤖 Falling back to single-scene Gemini search...")
            fallback_video = next(
                (v for v in approved_videos if not _ffprobe_fails(v)), None
            )
            if not fallback_video:
                raise RuntimeError("No usable approved videos — all failed ffprobe.")
            scene = find_scene_with_gemini(fallback_video, data.get("scene_query"), SCRIPT_TEXT)
            if scene and not (scene["start"] == 0 and scene["end"] == 0):
                clip_path = f"trimmed_scene_{uuid.uuid4().hex[:6]}.mp4"
                trim_video_to_end(fallback_video, clip_path, scene["start"], prepad=0.02, max_duration=61.0)
                clip_paths = [clip_path]
            else:
                clip_paths = [fallback_video]

        print(f"🎵 Waiting for music generation...")
        music_path = music_future.result()
        executor.shutdown(wait=False)
        if not music_path:
            print("⚠️ Music generation failed, continuing without music.")

        safe_subject = SUBJECT.replace(' ', '_')[:80]
        final_filename = f"Short_{safe_subject}_{random.randint(10, 99)}.mp4"
        punch_times = _match_punch_times(_punch_words, words_data) if (words_data and _punch_words) else []
        if punch_times:
            print(f"👊 Punch SFX at: {punch_times}")

        print(f"🎬 Starting video editing...")
        final_path = merge_audio_video(
            video_paths=clip_paths,
            audio_path=audio_path,
            output_name=final_filename,
            vertical=True,
            shorts_cap=True,
            music_path=music_path,
            music_volume=MUSIC_VOLUME,
            words_data=words_data,
            subtitles_position=SUBTITLES_POSITION,
            punch_times=punch_times,
        )

        print(f"\n✅ DONE! Saved to: {final_path}")

        if CLEANUP_FILES:
            to_delete = {audio_path, music_path} | set(approved_videos) | set(clip_paths)
            for path in to_delete:
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except Exception:
                        pass

        return True

    except KeyError as e:
        print(f"❌ Missing Key in JSON: {e}")
    except Exception as e:
        print(f"❌ Pipeline Error: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    if MANUAL_DATA:
        run_manual_pipeline(MANUAL_DATA)
    else:
        print("Please paste your JSON into the MANUAL_DATA variable.")
