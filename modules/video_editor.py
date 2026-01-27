import os
import sys
import random
from typing import List, Union, Optional

# ---------------------------------------------------------
# 1. FIX: Auto-detect ImageMagick on macOS
# ---------------------------------------------------------
import moviepy.config as mp_config

if sys.platform == "darwin":
    possible_paths = [
        "/opt/homebrew/bin/magick",
        "/usr/local/bin/magick",
        "/opt/homebrew/bin/convert",
        "/usr/local/bin/convert",
    ]
    for p in possible_paths:
        if os.path.exists(p):
            # Prefer magick over convert
            binary = p if "magick" in p else p
            mp_config.change_settings({"IMAGEMAGICK_BINARY": binary})
            break

from moviepy.editor import (
    VideoFileClip,
    AudioFileClip,
    TextClip,
    CompositeVideoClip,
    CompositeAudioClip,
    concatenate_videoclips,
    vfx
)

try:
    from moviepy.audio.fx.all import audio_loop, volumex
except ImportError:
    audio_loop = None
    volumex = None

from config import DATA_DIR

FINAL_DIR = os.path.join(DATA_DIR, "final")
os.makedirs(FINAL_DIR, exist_ok=True)


# ----------------------- Helper functions ----------------------- #

def _make_vertical_9x16(clip, target_w=1080, target_h=1920, bg_color=(0, 0, 0)):
    w, h = clip.size
    src_ratio = w / h
    tgt_ratio = target_w / target_h

    if src_ratio > tgt_ratio:
        new_w = target_w
        new_h = int(new_w / src_ratio)
    else:
        new_h = target_h
        new_w = int(new_h * src_ratio)

    resized = clip.resize((new_w, new_h))
    return resized.on_color(size=(target_w, target_h), color=bg_color, pos=("center", "center"))


def _loop_video_to_duration(clip, target_duration: float):
    if clip.duration and clip.duration >= target_duration:
        return clip.subclip(0, target_duration)
    return clip.fx(vfx.loop, duration=target_duration).subclip(0, target_duration)


def _loop_audio_to_duration(audio_clip, target_duration: float):
    if audio_clip.duration and audio_clip.duration >= target_duration:
        return audio_clip.subclip(0, target_duration)

    if audio_loop:
        return audio_clip.fx(audio_loop, duration=target_duration).subclip(0, target_duration)

    import math
    n = math.ceil(target_duration / audio_clip.duration)
    clips = [audio_clip.set_start(i * audio_clip.duration) for i in range(n)]
    return CompositeAudioClip(clips).subclip(0, target_duration)


def _trim_clips_to_total_duration(clips: List[VideoFileClip], total_duration: float) -> List[VideoFileClip]:
    """
    ✅ THE LOGIC YOU ASKED FOR:
    If we have a 5-minute video and need 1 minute, pick a RANDOM 1-minute chunk.
    """
    if not clips: return []

    # Scenario 1: We have a single long background video (the 5min download)
    if len(clips) == 1:
        c = clips[0]
        if c.duration > total_duration:
            # Calculate the latest possible start time
            max_start_time = c.duration - total_duration

            # Pick a random start time
            random_start = random.uniform(0, max_start_time)
            random_end = random_start + total_duration

            print(f"🎲 RANDOM CUT: Selecting video segment from {int(random_start)}s to {int(random_end)}s")
            return [c.subclip(random_start, random_end)]

    # Scenario 2: Video is shorter than audio, or multiple clips (Fallback)
    total_source = sum(c.duration for c in clips)

    if total_source < total_duration:
        extended = []
        accum = 0
        for c in clips:
            if accum >= total_duration: break
            needed = total_duration - accum
            if c.duration >= needed:
                extended.append(c.subclip(0, needed))
                accum += needed
            else:
                looped = _loop_video_to_duration(c, needed)
                extended.append(looped)
                accum += needed
        return extended

    ratio = total_duration / total_source
    processed = []
    for c in clips:
        new_dur = c.duration * ratio
        processed.append(c.subclip(0, new_dur))
    return processed


def _make_subtitle_clips(subtitles_data, video_size, position="center"):
    w_vid, h_vid = video_size
    clips = []
    fontsize = int(h_vid * 0.06)

    if position == 'bottom':
        pos_arg = ('center', int(h_vid * 0.75))
    elif position == 'top':
        margin_from_top = int(h_vid * 0.12)
        pos_arg = ('center', margin_from_top)
    else:
        pos_arg = ('center', 'center')

    font_path = "/System/Library/Fonts/Arial.ttf"

    for start, end, txt in subtitles_data:
        dur = end - start
        if dur <= 0: continue

        txt_clip = TextClip(
            txt.upper(),
            fontsize=fontsize,
            color='white',
            font=font_path,
            method='caption',
            size=(int(w_vid * 0.75), None),
            stroke_color='black',
            stroke_width=4,
            align='center'
        )

        txt_clip = txt_clip.set_start(start).set_duration(dur).set_position(pos_arg)
        clips.append(txt_clip)

    return clips


def merge_audio_video(
        video_paths: Union[str, List[str]],
        audio_path: str,
        output_name: str = "final_short.mp4",
        vertical: bool = False,
        target_w: int = 1080,
        target_h: int = 1920,
        shorts_cap: bool = True,
        cap_seconds: float = 82,
        music_path: Optional[str] = None,
        music_volume: float = 0.01,
        subtitles_data: Optional[list] = None,
        subtitles_position: str = "bottom",
        subtitles_text: Optional[str] = None
):
    print("\n🎬  Starting Video Editor...")

    voice_audio = AudioFileClip(audio_path)

    if isinstance(video_paths, str):
        video_paths = [video_paths]

    # 1. Load Clips and MUTE them immediately
    raw_clips = [VideoFileClip(p).without_audio() for p in video_paths]

    # 2. Vertical Crop
    if vertical:
        raw_clips = [_make_vertical_9x16(c, target_w, target_h) for c in raw_clips]

    # 3. Calculate Durations
    final_dur = voice_audio.duration
    if shorts_cap:
        final_len = min(final_dur, cap_seconds)
        if final_len < final_dur:
            voice_audio = voice_audio.subclip(0, final_len)
        final_dur = final_len

    # 4. Trim/Concat Video (THIS CALLS THE RANDOM LOGIC)
    clips_ready = _trim_clips_to_total_duration(raw_clips, final_dur)

    if len(clips_ready) > 1:
        video = concatenate_videoclips(clips_ready, method="compose")
    else:
        video = clips_ready[0]

    video = _loop_video_to_duration(video, final_dur)

    # 5. Subtitles
    if subtitles_data:
        try:
            subs = _make_subtitle_clips(subtitles_data, video.size, subtitles_position)
            if subs:
                video = CompositeVideoClip([video] + subs)
        except Exception as e:
            print(f"⚠️ Subtitle generation failed: {e}")

    # 6. Music Mixing
    final_audio = voice_audio
    if music_path:
        try:
            bg_music = AudioFileClip(music_path)
            if volumex:
                bg_music = bg_music.fx(volumex, music_volume)

            # Random music start logic (Optional bonus)
            if bg_music.duration > final_dur:
                start_m = random.uniform(0, bg_music.duration - final_dur)
                bg_music = bg_music.subclip(start_m, start_m + final_dur)
            else:
                bg_music = _loop_audio_to_duration(bg_music, final_dur)

            final_audio = CompositeAudioClip([voice_audio, bg_music])
        except Exception as e:
            print(f"⚠️ Music failed: {e}")

    video = video.set_audio(final_audio)

    out_path = os.path.join(FINAL_DIR, output_name)
    video.write_videofile(
        out_path,
        codec="libx264",
        audio_codec="aac",
        fps=30,
        logger=None
    )

    voice_audio.close()
    for c in raw_clips: c.close()

    print(f"✅  Saved: {out_path}")
    return out_path
