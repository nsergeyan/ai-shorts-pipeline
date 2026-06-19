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
    from modules.music_generator import generate_music
    from modules.newvoice import generate_voice
    from modules.video_editor import merge_audio_video
    from modules.transcriber import transcribe_audio_to_words
except ImportError as e:
    print(f"Error importing modules: {e}")
    sys.exit(1)
# ---------------- CONFIG ---------------- #
LANGUAGE = "en"
MUSIC_VOLUME = 0.07
SUBTITLES_POSITION = "top"
CLEANUP_FILES = True
CLIP_DURATION = 60.0
SLEEP_INTERVAL = 5
# ---------------------------------------- #

MANUAL_DATA = {
"topic": "Jujutsu Kaisen",
"specific_subject": "The horrifying taste of Suguru Geto's cursed spirit manipulation",
"youtube_queries": [
  "jujutsu kaisen official geto swallowing curse MAPPA",
  "jujutsu kaisen hidden inventory creditless raw Geto",
  "jujutsu kaisen suguru geto curse manipulation AMV",
  "jujutsu kaisen season two episode two geto curse clip",
  "jujutsu kaisen suguru geto tribute best moments",
  "jujutsu kaisen geto swallowing curse 4K HD remaster"
],
"scene_query": "Teenage Suguru Geto with long dark hair looking exhausted and disgusted, holding a small dark glowing orb of cursed energy near his mouth, dark shadowy background.",
"music_mood": "mysterious",
"music_prompt": "dark atmospheric trap, ninety BPM, eerie koto plucks, punchy bass, solo piano with strings, quiet tension under the hook, builds through the payload, hits hardest with a distorted bass drop on the turn around twenty seconds, anime short-form video background, no lyrics, exclude: upbeat pop, cheerful flutes",
"voice_name": "Hamid",
"script": "[curious] Suguru Geto hides a horrifying physical secret about his powers that the anime barely touches on. [thoughtful] We all know he consumes cursed spirits to control them. [sighs] It looks as easy as swallowing a piece of candy. [nervous] But the actual taste is pure torture. Geto canonically stated that every single time he absorbs a curse, [appalled] it tastes exactly like swallowing a wet rag that was just used to wipe up VOMIT. [laughs] Imagine eating thousands of those just to do your job! [curious] Knowing this absolute nightmare flavor, do you finally understand why he went completely evil?"
}

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
    while file_info.state != "ACTIVE":
        print(f"Music state: {file_info.state}, waiting...")
        time.sleep(2)
        file_info = client.files.get(name=uploaded_file.name)

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

def evaluate_video_with_genai(video_path, script_text):
    """Upload a video to Gemini and score it for relevance, hook potential, and technical quality."""
    client = _gemini_client()

    # Upload video
    uploaded_file = client.files.upload(file=video_path)
    print(f"Uploaded file: {uploaded_file.name}")

    # Wait until file is ACTIVE
    file_info = client.files.get(name=uploaded_file.name)
    while file_info.state != "ACTIVE":
        print(f"File state: {file_info.state}, waiting...")
        time.sleep(2)
        file_info = client.files.get(name=uploaded_file.name)
    print("File is ACTIVE ✅")

    # Build prompt
    prompt = f"""
    You are an AI Video Editor Assistant.
    Evaluate whether this RAW SOURCE FOOTAGE is usable as background B-roll for a short-form video.
    
    Judge it on POTENTIAL as raw source footage — not as a finished edit.
    
    SCRIPT EXCERPT:
    \"\"\"{script_text}\"\"\"
    
    STEP 0 — REQUIRED SUBJECT (do this first):
    From the script, identify the ESSENTIAL subject the footage must show. This is usually a specific named character, and may also include a specific object, location, or action central to the script.
    State it internally as REQUIRED_SUBJECT before scoring.
    Example: if the script is about Hange Zoë's hygiene, REQUIRED_SUBJECT = "Hange Zoë" (the footage must actually show Hange, not just the show in general).
    
    The footage must contain ONLY real source moments — no "subscribe" cards, no promos, no reaction-cam overlays. Raw clips only.
    
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
       - 8-10: clean, minimal watermarks, clear enough to crop for phone.
       - 5-7: slightly blurry or minor subtitles/watermarks, still usable.
       - 1-4: heavily pixelated, ruined by editing/watermarks, unwatchable.
    
    DECISION RULES (apply in order):
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
      "decision": "post" | "revise" | "reject"
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
    while file_info.state != "ACTIVE":
        print(f"File state: {file_info.state}, waiting...")
        time.sleep(2)
        file_info = client.files.get(name=uploaded_file.name)

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


def find_scenes_with_gemini(video_paths, script_segments):
    """
    Upload all approved source videos to Gemini in one call.
    Returns a flat list of scenes: [{index, video_index, start}, ...]
    Gemini picks the best (video, timestamp) for each narration segment.
    """
    client = _gemini_client()

    video_durations = []
    for vp in video_paths:
        info = ffmpeg.probe(vp)
        vs = next(s for s in info["streams"] if s["codec_type"] == "video")
        video_durations.append(float(vs["duration"]))

    uploaded_files = []
    for i, vp in enumerate(video_paths):
        uf = client.files.upload(file=vp)
        print(f"📤 Uploaded Video {i}: {uf.name}")
        uploaded_files.append(uf)

    pending = list(range(len(uploaded_files)))
    while pending:
        time.sleep(2)
        still_pending = []
        for i in pending:
            fi = client.files.get(name=uploaded_files[i].name)
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
    videos_info = "\n".join(
        f"  Video {i} (duration: {dur:.1f}s)"
        for i, dur in enumerate(video_durations)
    )

    prompt = f"""
You are a professional video editor. You have {len(video_paths)} source video(s) and a narration script split into segments.
Your job is to build the most visually engaging edit by choosing the right clip from the right video for each segment.

SOURCE VIDEOS (in the order they were provided above):
{videos_info}

NARRATION SEGMENTS:
{segments_json}

INSTRUCTIONS:
For each narration segment, pick the BEST matching timestamp from any of the source videos.

RULES:
- For each segment assign a video_index (0 to {len(video_paths) - 1}) and a start time in seconds
- The clip starting at `start` must have at least `duration` seconds of usable footage remaining in that video
- Avoid the first 3 seconds and last 8 seconds of any video (intros/outros)
- Prefer dynamic action shots, close-ups, and visually interesting moments
- Vary which video you pull from across segments when possible — visual diversity keeps viewers engaged
- If one video is clearly superior for a segment, use it — do not force variety at the cost of quality

TIMESTAMP FORMAT: seconds only (e.g. 90.0, not 1:30)

OUTPUT: Return ONLY valid JSON — no explanation, no markdown.

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
                contents=contents
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
        return validated
    except Exception as e:
        print(f"⚠️ Failed to parse scene JSON: {e}\nRaw: {text}")
        return [{"index": i, "video_index": 0, "start": 0.0} for i in range(n)]


def run_manual_pipeline(data):
    """Run the full pipeline from a MANUAL_DATA dict — download, evaluate, voice, music, subtitles, edit."""
    try:
        TOPIC = data['topic']
        SUBJECT = data['specific_subject']
        YOUTUBE_QUERIES = data.get('youtube_queries', [])
        MUSIC_PROMPT = data.get('music_prompt', 'calm ambient cinematic instrumental music')
        VOICE_NAME = data.get('voice_name', 'hamid')
        SCRIPT_TEXT = data['script']

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
            print(f"🔍 Evaluating video...")
            evaluation = evaluate_video_with_genai(candidate_video, SCRIPT_TEXT)

            if evaluation and evaluation.get("decision") == "post" and evaluation.get("subject_present", False):
                print(f"✅ Video {i + 1} approved!")
                approved_videos.append(candidate_video)
                if len(approved_videos) >= MAX_SOURCE_VIDEOS:
                    print(f"🎯 Reached {MAX_SOURCE_VIDEOS} approved videos — skipping remaining queries.")
                    break
            else:
                print(f"❌ Video rejected: {evaluation.get('decision') if evaluation else 'unknown'}")
                rejected_videos.append(candidate_video)

        for path in rejected_videos:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass

        if not approved_videos:
            print("❌ All queries failed. No suitable video found.")
            return False

        print(f"✅ {len(approved_videos)} video(s) approved for editing.")

        # Kick off music generation immediately — it has no dependencies on voice/scene
        print(f"🎵 Starting music generation in background...")
        executor = ThreadPoolExecutor(max_workers=1)
        music_future = executor.submit(generate_music, MUSIC_PROMPT)

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
            print(f"🎬 {len(script_segments)} sentence segments — analyzing {len(approved_videos)} video(s)...")
            scenes = find_scenes_with_gemini(approved_videos, script_segments)

            if len(scenes) < len(script_segments):
                print(f"⚠️ Gemini returned {len(scenes)} scenes for {len(script_segments)} segments — using available scenes only")
            for scene, segment in zip(scenes, script_segments):
                vi = scene.get("video_index", 0)
                source_video = approved_videos[vi]
                clip_path = f"clip_{scene['index']}_{uuid.uuid4().hex[:6]}.mp4"
                success = trim_video_to_end(
                    input_file=source_video,
                    output_file=clip_path,
                    ai_start=scene["start"],
                    prepad=0.0,
                    max_duration=segment["duration"],
                )
                if success is not False and os.path.exists(clip_path):
                    clip_paths.append(clip_path)

        if not clip_paths:
            # Fallback for Spanish or failed transcription
            print("🤖 Falling back to single-scene Gemini search...")
            scene = find_scene_with_gemini(approved_videos[0], data.get("scene_query"), SCRIPT_TEXT)
            if scene and not (scene["start"] == 0 and scene["end"] == 0):
                clip_path = f"trimmed_scene_{uuid.uuid4().hex[:6]}.mp4"
                trim_video_to_end(approved_videos[0], clip_path, scene["start"], prepad=0.02, max_duration=61.0)
                clip_paths = [clip_path]
            else:
                clip_paths = [approved_videos[0]]

        print(f"🎵 Waiting for music generation...")
        music_path = music_future.result()
        executor.shutdown(wait=False)
        if not music_path:
            print("⚠️ Music generation failed, continuing without music.")

        final_filename = f"Short_{SUBJECT.replace(' ', '_')}_{random.randint(10, 99)}.mp4"
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
            subtitles_position=SUBTITLES_POSITION
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
