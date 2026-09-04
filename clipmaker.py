"""
Clip maker: cut the single most interesting moment out of a video you already
have, to use as a promo/teaser clip for it.

You drag a video in, set its path below, and Gemini watches the whole thing
and picks the best continuous highlight. That moment gets trimmed, transcribed,
and rendered through the same Remotion pipeline as main.py, so the output has
the same blurred/contained 9:16 layout, the same word-highlighted subtitles,
and the same follow-button CTA. The subtitles are transcribed from the video's
own original audio (kept as-is), not AI narration, there is no generated
script, voice, or music here.

This file does not modify main.py, it only imports two small Gemini helpers
from it (the client rotation + file upload/poll logic).

Usage:
    source .venv/bin/activate
    python clipmaker.py
"""
import json
import os
import random
import re
import subprocess
import time
import traceback
import uuid

import ffmpeg

from config import AUDIO_DIR
from main import _gemini_client, _upload_and_wait
from modules.transcriber import transcribe_audio_to_words
from modules.video_editor import merge_audio_video

CLIP_MAKER_DATA = {
    # Drag your video in (anywhere on disk) and paste its path here.
    "source_video_path": "/Users/nareksergeyan/PycharmProjects/animationer/output/how_money_laundering_works/final.mp4",
    # Target length in seconds for the promo clip. Gemini can shift a few
    # seconds either way to land on a clean start/end.
    "clip_duration": 30,
}


def _parse_ts(value) -> float:
    """Gemini timestamps video natively in MM:SS. Accept that or plain seconds
    rather than forcing it to do the conversion arithmetic itself."""
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if ":" in text:
        parts = [float(p) for p in text.split(":")]
        return sum(p * 60 ** i for i, p in enumerate(reversed(parts)))
    return float(text)


def _enforce_duration(start: float, end: float, target: float, video_duration: float):
    """Gemini often returns a span far shorter than asked for, and nothing used to
    check it, so a 30s request could render as 8s. Anchor on the start it picked
    (that is where the hook begins) and force the clip to run `target` long,
    sliding it back only if it would overrun the video."""
    span = end - start
    if abs(span - target) <= target * 0.2:
        return start, end
    target = min(target, video_duration)
    new_start = max(0.0, min(start, video_duration - target))
    new_end = new_start + target
    print(f"📏 Gemini returned {span:.1f}s, forcing to {new_end - new_start:.1f}s")
    return new_start, new_end


def find_best_clip_with_gemini(video_path: str, target_duration: float = 30.0):
    """Ask Gemini to find the single most interesting continuous moment in the
    video, for use as a promo/teaser clip. Returns (start, end) in seconds."""
    client = _gemini_client()

    info = ffmpeg.probe(video_path)
    video_stream = next(s for s in info["streams"] if s["codec_type"] == "video")
    video_duration = float(video_stream["duration"])

    uploaded_file = _upload_and_wait(client, video_path, label="source video")

    prompt = f"""
    You are cutting a promo clip out of this video to post as a standalone short on
    social media, a teaser/trailer cut. Watch and listen to the whole video first.

    VIDEO DURATION: {video_duration:.1f} seconds
    TARGET CLIP LENGTH: {target_duration:.0f} seconds (hard requirement, not a suggestion)

    TASK:
    Find the single most interesting, exciting, or intriguing continuous moment in
    this video, the kind of moment that would make someone stop scrolling and want
    to watch the full video. It must be ONE continuous segment, no cuts.
    Judge it on both what is on screen and what is being said.

    WHAT MAKES A GOOD PICK:
    - It opens on a line that works cold, with zero setup: a question, a bold claim,
      a reveal, a surprising fact. Someone hearing it with no context wants the answer.
    - The payoff happens INSIDE the clip. Do not end right before the reveal.
    - It is a complete thought: starts at the top of a sentence, ends at the end of one,
      not mid-sentence or mid-motion.

    WHAT MAKES A BAD PICK:
    - Intro, outro, channel plugs, "in this video I'll show you", "subscribe".
    - Setup with no payoff, list filler, a calm or static transitional passage.
    - Anything in the last 5 seconds of the video.

    HARD RULES:
    - end - start MUST be between {target_duration * 0.85:.0f} and {target_duration * 1.15:.0f} seconds.
      A shorter span is a failed answer.
    - Timestamps may be MM:SS or plain seconds, whichever you are confident in.
    - Ensure: 0 <= start, end <= {video_duration:.1f}, end > start.

    Give THREE candidates ranked best first, so you actually compare options
    instead of returning the first thing you notice.

    OUTPUT: Return ONLY valid JSON, no markdown, no explanation.
    {{"candidates": [
      {{"start": <timestamp>, "end": <timestamp>,
        "hook": "<the opening line, quoted from the video>",
        "reason": "<one short sentence on why this stops the scroll>"}}
    ]}}
    """

    max_attempts = 5
    response = None
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
                print(f"⚠️ Gemini 429, rotating key... (attempt {attempt}/{max_attempts})")
                client = _gemini_client()
                uploaded_file = _upload_and_wait(client, video_path, label="source video")
                time.sleep(5)
            else:
                raise
        if attempt == max_attempts:
            raise RuntimeError("Gemini clip search failed after max retries.")

    text = re.sub(r"```json|```", "", response.text).strip()
    try:
        result = json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise RuntimeError(f"Failed to parse clip JSON from Gemini: {text[:300]}")
        result = json.loads(match.group(0))

    candidates = result.get("candidates") or [result]  # tolerate a flat answer
    print("🎬 Gemini's candidates:")
    for i, c in enumerate(candidates[:3], 1):
        try:
            c_start, c_end = _parse_ts(c.get("start", 0)), _parse_ts(c.get("end", 0))
        except Exception:
            continue
        print(f"   {i}. {c_start:.1f}s → {c_end:.1f}s ({c_end - c_start:.1f}s)  {str(c.get('hook', ''))[:70]}")

    best = candidates[0]
    start = max(0.0, _parse_ts(best.get("start", 0.0)))
    try:
        end = min(video_duration, _parse_ts(best["end"]))
    except (KeyError, TypeError, ValueError):
        end = min(video_duration, start + target_duration)
    if end <= start:
        end = min(video_duration, start + target_duration)

    start, end = _enforce_duration(start, end, target_duration, video_duration)

    print(f"✂️ Picked {start:.1f}s → {end:.1f}s ({end - start:.1f}s): {best.get('reason', '')}")
    return start, end


def _trim_clip(input_path: str, output_path: str, start: float, end: float):
    """Cut [start, end] out of the source video, keeping its original audio."""
    duration = max(end - start, 1.0)
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-ss", str(start), "-i", input_path, "-t", str(duration),
            "-c:v", "libx264", "-preset", "veryfast",
            "-c:a", "aac", "-movflags", "+faststart",
            output_path,
        ],
        check=True,
    )


def _extract_audio(video_path: str, output_path: str):
    """Pull the audio track out of a clip so it can be transcribed and used
    as the Remotion audio track (background clips in the render are muted)."""
    subprocess.run(
        ["ffmpeg", "-y", "-i", video_path, "-vn", "-acodec", "libmp3lame", "-q:a", "4", output_path],
        check=True,
    )


def run_clip_maker(data: dict) -> bool:
    """Cut the single most interesting moment out of a video and render it
    with the same layout, subtitles, and CTA as main.py's pipeline."""
    source_video_path = data.get("source_video_path")
    target_duration = data.get("clip_duration", 30)
    clip_path, extracted_audio_path = None, None

    try:
        if not source_video_path:
            raise RuntimeError("Set source_video_path in CLIP_MAKER_DATA to your video's path.")
        if not os.path.exists(source_video_path):
            raise RuntimeError(f"source_video_path does not exist: {source_video_path}")
        try:
            ffmpeg.probe(source_video_path)
        except Exception as e:
            raise RuntimeError(f"source_video_path failed ffprobe: {e}")

        print(f"📎 Source video: {source_video_path}")
        print("🤖 Finding the best moment to promote this video...")
        start, end = find_best_clip_with_gemini(source_video_path, target_duration)

        clip_path = f"clip_maker_trim_{uuid.uuid4().hex[:6]}.mp4"
        print(f"✂️ Trimming {end - start:.1f}s...")
        _trim_clip(source_video_path, clip_path, start, end)

        extracted_audio_path = os.path.join(AUDIO_DIR, f"clip_maker_audio_{uuid.uuid4().hex[:6]}.mp3")
        _extract_audio(clip_path, extracted_audio_path)

        print("📝 Transcribing the clip's own audio for subtitles...")
        words_data = transcribe_audio_to_words(extracted_audio_path, None)
        if not words_data:
            print("⚠️ No speech detected in this clip, rendering without subtitles.")

        base = os.path.splitext(os.path.basename(source_video_path))[0]
        output_filename = f"Promo_{base}_{random.randint(10, 99)}.mp4"

        print("🎬 Rendering with the same layout and subtitles as main.py...")
        final_path = merge_audio_video(
            video_paths=[clip_path],
            audio_path=extracted_audio_path,
            output_name=output_filename,
            vertical=True,
            shorts_cap=True,
            words_data=words_data or None,
            subtitles_position="top",
        )

        print(f"\n✅ DONE! Saved to: {final_path}")
        return True

    except Exception as e:
        print(f"❌ Clip maker error: {e}")
        traceback.print_exc()
        return False
    finally:
        for path in (clip_path, extracted_audio_path):
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass


if __name__ == "__main__":
    if not CLIP_MAKER_DATA.get("source_video_path"):
        print("Set source_video_path in CLIP_MAKER_DATA to your dragged-in video's path, then rerun.")
    else:
        run_clip_maker(CLIP_MAKER_DATA)
