"""
Clip maker: cut a teaser out of a video you already have, so people go looking
for the full version of it.

You drag a video in, set its path below, and Gemini watches the whole thing and
picks the moment that leaves a viewer with an unanswered question: the hook is
inside the clip, the answer is not. That moment gets trimmed, transcribed,
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
    "source_video_path": "/Users/nareksergeyan/PycharmProjects/animationer/output/is_ai_really_dangerous/final.mp4",
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


def _enforce_duration(start: float, end: float, target: float, video_duration: float,
                      payoff: float | None = None):
    """Gemini often returns a span far shorter than asked for, and nothing used to
    check it, so a 30s request could render as 8s. Anchor on the start it picked
    (that is where the hook begins) and force the clip to run `target` long,
    sliding it back only if it would overrun the video."""
    span = end - start
    if abs(span - target) > target * 0.2:
        target = min(target, video_duration)
        start = max(0.0, min(start, video_duration - target))
        end = start + target
        print(f"📏 Gemini returned {span:.1f}s, forcing to {end - start:.1f}s")

    if payoff is not None and 0 < payoff < end:
        # Stretching the clip must never swallow the answer, that is the entire
        # point of a teaser. Slide the whole window back instead of shortening it.
        shift = min(end - payoff, start)
        if shift > 0:
            start -= shift
            end -= shift
            print(f"🔒 Pulled back {shift:.1f}s to end before the payoff at {payoff:.1f}s")
    return start, end


def _validate_candidate(cand: dict, video_duration: float):
    """Normalize one candidate into usable numbers, or None if it is unusable."""
    try:
        start = max(0.0, _parse_ts(cand.get("start", 0.0)))
        end = _parse_ts(cand["end"])
    except (KeyError, TypeError, ValueError):
        return None
    if end <= start or start >= video_duration:
        return None
    try:
        payoff = _parse_ts(cand["payoff_at"])
    except (KeyError, TypeError, ValueError):
        payoff = None
    return {"cand": cand, "start": start, "end": min(end, video_duration), "payoff": payoff}


def _pick_candidate(candidates: list, target: float, video_duration: float):
    """Gemini ranks three candidates and the code used to always take the first
    one, so a bad top pick sank the whole clip. Walk the ranking instead and take
    the highest one that is actually a teaser: right length, and ending before
    the video hands over the answer (`payoff_at` after `end`). Loosen the bar
    only if nothing clears it."""
    parsed = [v for v in (_validate_candidate(c, video_duration) for c in candidates) if v]
    if not parsed:
        return None

    def open_loop(c):
        return c["payoff"] is not None and c["payoff"] > c["end"]

    def right_length(c):
        return abs((c["end"] - c["start"]) - target) <= target * 0.15

    checks = [
        (lambda c: open_loop(c) and right_length(c), "open loop, right length"),
        (open_loop, "open loop"),
        (right_length, "right length"),
    ]
    for test, label in checks:
        for rank, c in enumerate(parsed, 1):
            if test(c):
                print(f"✅ Using candidate #{rank} ({label})")
                return c
    print("⚠️ No candidate cleared the checks, falling back to the top pick")
    return parsed[0]


def find_best_clip_with_gemini(video_path: str, target_duration: float = 30.0):
    """Ask Gemini for the moment that leaves a cold viewer needing the rest of
    the video, and cut before the answer. Returns (start, end) in seconds."""
    client = _gemini_client()

    info = ffmpeg.probe(video_path)
    video_stream = next(s for s in info["streams"] if s["codec_type"] == "video")
    video_duration = float(video_stream["duration"])

    uploaded_file = _upload_and_wait(client, video_path, label="source video")

    prompt = f"""
    You are cutting a TEASER out of this video. It gets posted as a standalone
    short, and it has exactly one job: the viewer must finish it still needing the
    answer, so they go and look for the full video. A clip that satisfies them has
    failed. Watch and listen to the whole video first.

    VIDEO DURATION: {video_duration:.1f} seconds
    TARGET CLIP LENGTH: {target_duration:.0f} seconds (hard requirement, not a suggestion)

    THE SHAPE YOU ARE LOOKING FOR (ONE continuous segment, no cuts):
    1. Second 0 to 2: a cold open that works with zero context. A question, a
       number, a contrarian claim, a threat, a name plus stakes. No "so", "and
       then", "as I said", no pronoun referring to something earlier. The first
       words carry the hook.
    2. Middle: the stakes get bigger or the situation gets stranger. New
       information every few seconds, no restating what was already said.
    3. The last line: the question is still open. Cut on the setup, on the "but
       here is the problem", on the claim before the evidence. The moment the
       video starts answering, you are already past your end point.

    DISQUALIFIED:
    - Anything that resolves itself. If the clip contains both the question and
      the answer, the viewer has no reason to search for the video.
    - Intro, outro, channel plugs, "in this video I'll show you", "subscribe",
      sponsor reads.
    - Slow setup, list filler, recap, a calm or static transitional passage.
    - A hook that only makes sense if you already watched the earlier part.
    - Anything in the last 5 seconds of the video.

    HARD RULES:
    - end - start MUST be between {target_duration * 0.85:.0f} and {target_duration * 1.15:.0f} seconds.
      A shorter span is a failed answer.
    - `start` sits on the first word of a sentence, `end` on the last word of a
      sentence. Never mid-sentence or mid-motion.
    - `payoff_at` is where the video actually answers the open question, and it
      MUST be greater than `end`. If you cannot name a payoff that comes later,
      the pick is wrong: choose a different moment.
    - Timestamps may be MM:SS or plain seconds, whichever you are confident in.
    - Ensure: 0 <= start, end <= {video_duration:.1f}, end > start.

    Give THREE candidates ranked best first, judged on one thing only: how badly
    someone who saw just the clip needs to know what happens next.

    OUTPUT: Return ONLY valid JSON, no markdown, no explanation.
    {{"candidates": [
      {{"start": <timestamp>, "end": <timestamp>, "payoff_at": <timestamp>,
        "hook": "<the opening line, quoted from the video>",
        "open_question": "<the question the viewer is left with, in their words>",
        "reason": "<one short sentence on why they need the full video>"}}
    ]}}
    """

    max_attempts = 5
    response = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[uploaded_file, prompt],
                config={"thinking_config": {"thinking_budget": 8000}, "response_mime_type": "application/json"},
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
        payoff = c.get("payoff_at", "?")
        print(f"   {i}. {c_start:.1f}s → {c_end:.1f}s ({c_end - c_start:.1f}s, "
              f"payoff at {payoff})  {str(c.get('hook', ''))[:70]}")

    pick = _pick_candidate(candidates, target_duration, video_duration)
    if pick is None:
        raise RuntimeError(f"No usable clip candidate in Gemini's answer: {text[:300]}")

    best = pick["cand"]
    start, end = _enforce_duration(
        pick["start"], pick["end"], target_duration, video_duration, pick["payoff"]
    )

    print(f"✂️ Picked {start:.1f}s → {end:.1f}s ({end - start:.1f}s): {best.get('reason', '')}")
    if best.get("open_question"):
        print(f"❓ Leaves them asking: {best['open_question']}")
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
