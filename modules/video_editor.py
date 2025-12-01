# modules/video_editor.py
import os
import sys
from typing import List, Union, Optional

# ---------------------------------------------------------
# 1. FIX: Auto-detect ImageMagick on macOS
# ---------------------------------------------------------
import moviepy.config as mp_config

if sys.platform == "darwin":
    # Common paths where Homebrew puts ImageMagick
    possible_paths = [
        "/opt/homebrew/bin/convert",  # Apple Silicon (M1/M2/etc)
        "/usr/local/bin/convert",  # Intel Mac
    ]

    binary_found = False
    for p in possible_paths:
        if os.path.exists(p):
            mp_config.change_settings({"IMAGEMAGICK_BINARY": p})
            print(f"✅ Configured ImageMagick: {p}")
            binary_found = True
            break

    if not binary_found:
        print("⚠️  WARNING: ImageMagick 'convert' binary not found in standard paths.")
        print("    Please run: brew install imagemagick")

# ---------------------------------------------------------

from moviepy.editor import (
    VideoFileClip,
    AudioFileClip,
    TextClip,
    CompositeVideoClip,
    CompositeAudioClip,
    concatenate_videoclips,
    vfx
)

# Try to import audio effects (location varies slightly by sub-version)
try:
    from moviepy.audio.fx.all import audio_loop, volumex
except ImportError:
    audio_loop = None
    volumex = None

from config import DATA_DIR

FINAL_DIR = os.path.join(DATA_DIR, "final")
os.makedirs(FINAL_DIR, exist_ok=True)


# ----------------------- Helper functions ----------------------- #

def _cut_to_duration(clip, duration: float):
    """Trim clip to at most `duration` seconds (no looping)."""
    if not getattr(clip, "duration", None):
        return clip
    if clip.duration <= duration:
        return clip
    return clip.subclip(0, duration)


def _make_vertical_9x16(clip, target_w=1080, target_h=1920, bg_color=(0, 0, 0)):
    """
    Resize the clip to fit inside a vertical 9:16 frame WITHOUT cropping.
    Adds black bars (letterboxing/pillarboxing) as needed.
    """
    w, h = clip.size
    src_ratio = w / h
    tgt_ratio = target_w / target_h

    # Scale to fit completely inside target while preserving aspect ratio
    if src_ratio > tgt_ratio:
        # Source is relatively wider -> match width, height will be smaller
        new_w = target_w
        new_h = int(new_w / src_ratio)
    else:
        # Source is relatively taller -> match height, width will be smaller
        new_h = target_h
        new_w = int(new_h * src_ratio)

    resized = clip.resize((new_w, new_h))

    # Pad to exact target size with background color (black by default)
    return resized.on_color(
        size=(target_w, target_h),
        color=bg_color,
        pos=("center", "center")
    )


def _loop_video_to_duration(clip, target_duration: float):
    """Loop video clip logic."""
    if clip.duration and clip.duration >= target_duration:
        return clip.subclip(0, target_duration)
    # vfx.loop in 1.0.3 works well
    return clip.fx(vfx.loop, duration=target_duration).subclip(0, target_duration)


def _loop_audio_to_duration(audio_clip, target_duration: float):
    """Loop audio clip logic."""
    if audio_clip.duration and audio_clip.duration >= target_duration:
        return audio_clip.subclip(0, target_duration)

    if audio_loop:
        return audio_clip.fx(audio_loop, duration=target_duration).subclip(0, target_duration)

    # Manual loop fallback
    import math
    n = math.ceil(target_duration / audio_clip.duration)
    clips = [audio_clip.set_start(i * audio_clip.duration) for i in range(n)]
    return CompositeAudioClip(clips).subclip(0, target_duration)


def _trim_clips_to_total_duration(clips: List[VideoFileClip], total_duration: float) -> List[VideoFileClip]:
    """Logic to combine multiple clips to match exact voice duration."""
    if not clips: return []

    total_source = sum(c.duration for c in clips)

    # If total footage is less than needed, loop clips
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

    # Proportional trim if we have excess footage
    ratio = total_duration / total_source
    processed = []
    for c in clips:
        new_dur = c.duration * ratio
        processed.append(c.subclip(0, new_dur))
    return processed


# ----------------------- Subtitles (Whisper Ready) ----------------------- #

def _make_subtitle_clips(subtitles_data, video_size, position="center"):
    """
    Creates clips from EXACT timestamps provided by Whisper.
    subtitles_data: List of (start, end, text)
    """
    w_vid, h_vid = video_size
    clips = []

    # Huge font for impact
    fontsize = int(h_vid * 0.08)

    # Position logic
    if position == 'bottom':
        # 75% down
        pos_arg = ('center', int(h_vid * 0.75))
    elif position == 'top':
        # 20% down
        margin_from_top = int(h_vid * 0.08)  # smaller = closer to top
        pos_arg = ('center', margin_from_top)
    else:
        # Dead center
        pos_arg = ('center', 'center')

    # Font choice (Impact is standard for Shorts)
    font_name = "Impact"
    # If Impact fails on your mac, change to "Arial-Bold"

    for start, end, txt in subtitles_data:
        dur = end - start
        if dur <= 0: continue

        # Create Text
        txt_clip = TextClip(
            txt.upper(),
            fontsize=fontsize,
            color='white',
            font=font_name,
            method='caption',
            size=(int(w_vid * 0.85), None),
            stroke_color='black',
            stroke_width=4,
            align='center'
        )

        txt_clip = txt_clip.set_start(start).set_duration(dur).set_position(pos_arg)
        clips.append(txt_clip)

    return clips


# ----------------------- Main Pipeline ----------------------- #

def merge_audio_video(
        video_paths: Union[str, List[str]],
        audio_path: str,
        output_name: str = "final_short.mp4",
        vertical: bool = False,
        target_w: int = 1080,
        target_h: int = 1920,
        shorts_cap: bool = True,
        cap_seconds: float = 59.0,
        music_path: Optional[str] = None,
        music_volume: float = 0.01,
        subtitles_data: Optional[list] = None,  # Timestamps from Whisper
        subtitles_position: str = "bottom",
        # keep legacy arg for compatibility, but ignore it
        subtitles_text: Optional[str] = None
):
    print("\n🎬  Starting Video Editor...")

    voice_audio = AudioFileClip(audio_path)

    if isinstance(video_paths, str):
        video_paths = [video_paths]

    # 1. Load Clips
    raw_clips = [VideoFileClip(p) for p in video_paths]

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

    # 4. Trim/Concat Video
    clips_ready = _trim_clips_to_total_duration(raw_clips, final_dur)

    if len(clips_ready) > 1:
        video = concatenate_videoclips(clips_ready, method="compose")
    else:
        video = clips_ready[0]

    video = _loop_video_to_duration(video, final_dur)

    # 5. Subtitles (Updated logic)
    if subtitles_data:
        try:
            # We now pass the LIST of timestamps, not raw text
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
            bg_music = _loop_audio_to_duration(bg_music, final_dur)
            final_audio = CompositeAudioClip([voice_audio, bg_music])
        except Exception as e:
            print(f"⚠️ Music failed: {e}")

    video = video.set_audio(final_audio)

    # 7. Export
    out_path = os.path.join(FINAL_DIR, output_name)
    video.write_videofile(
        out_path,
        codec="libx264",
        audio_codec="aac",
        fps=30,
        logger=None
    )

    # Close handles
    voice_audio.close()
    for c in raw_clips: c.close()

    print(f"✅  Saved: {out_path}")
    return out_path