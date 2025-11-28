import os
import sys
import random
from typing import List, Union, Optional

# --- ImageMagick Fix for Mac ---
import moviepy.config as mp_config

if sys.platform == "darwin":
    possible_paths = ["/opt/homebrew/bin/convert", "/usr/local/bin/convert"]
    for p in possible_paths:
        if os.path.exists(p):
            mp_config.change_settings({"IMAGEMAGICK_BINARY": p})
            break
# -------------------------------

from moviepy.editor import (
    VideoFileClip, AudioFileClip, TextClip, CompositeVideoClip,
    CompositeAudioClip, concatenate_videoclips, vfx
)

try:
    from moviepy.audio.fx.all import audio_loop, volumex
except ImportError:
    audio_loop = None
    volumex = None

from config import DATA_DIR

FINAL_DIR = os.path.join(DATA_DIR, "final")
os.makedirs(FINAL_DIR, exist_ok=True)


# --- Helpers ---

def _make_vertical_9x16(clip, target_w=1080, target_h=1920):
    """Streamer style: Blur BG + Full Center"""
    bg = clip.resize(height=target_h)
    bg = bg.crop(x1=bg.w / 2 - target_w / 2, width=target_w, height=target_h)
    bg = bg.fx(vfx.colorx, 0.3)  # Darken BG

    main = clip.resize(width=target_w)
    return CompositeVideoClip([bg, main.set_position("center")], size=(target_w, target_h))


def _loop_video(clip, duration):
    if clip.duration >= duration: return clip.subclip(0, duration)
    return clip.fx(vfx.loop, duration=duration).subclip(0, duration)


def _trim_clips(clips, duration):
    if not clips: return []
    if clips[0].duration > duration + 10:
        start = random.uniform(0, clips[0].duration - duration)
        return [clips[0].subclip(start, start + duration)]
    return [_loop_video(clips[0], duration)]


def _loop_audio(audio, duration):
    if audio.duration >= duration: return audio.subclip(0, duration)
    n = int(duration / audio.duration) + 1
    return concatenate_videoclips([audio] * n).subclip(0, duration)


# --- Subtitles ---

def _make_subtitle_clips(subtitles_data, video_size, position="center"):
    w_vid, h_vid = video_size
    clips = []
    fontsize = int(h_vid * 0.045)  # 4.5% height

    if position == 'bottom':
        pos = ('center', int(h_vid * 0.70))
    elif position == 'top':
        pos = ('center', int(h_vid * 0.20))
    else:
        pos = ('center', 'center')

    # Arial is safer for Russian than Impact
    font_name = "Arial"

    for start, end, txt in subtitles_data:
        dur = end - start
        if dur <= 0: continue

        # White text, Black outline
        txt_clip = TextClip(
            txt.upper(), fontsize=fontsize, color='white', font=font_name,
            method='caption', size=(int(w_vid * 0.85), None),
            stroke_color='black', stroke_width=3, align='center'
        )
        txt_clip = txt_clip.set_start(start).set_duration(dur).set_position(pos)
        clips.append(txt_clip)
    return clips


# --- Pipeline ---

def merge_audio_video(
        video_paths, audio_path, output_name, vertical=True,
        target_w=1080, target_h=1920, shorts_cap=True, cap_seconds=59.0,
        music_path=None, music_volume=0.01, subtitles_data=None, subtitles_position="center"
):
    print("\n🎬  Starting Video Editor...")
    voice_audio = AudioFileClip(audio_path)

    raw_clips = [VideoFileClip(p) for p in (video_paths if isinstance(video_paths, list) else [video_paths])]
    if vertical:
        raw_clips = [_make_vertical_9x16(c, target_w, target_h) for c in raw_clips]

    final_len = min(voice_audio.duration, cap_seconds) if shorts_cap else voice_audio.duration
    voice_audio = voice_audio.subclip(0, final_len)

    clips_ready = _trim_clips(raw_clips, final_len)
    video = concatenate_videoclips(clips_ready, method="compose") if len(clips_ready) > 1 else clips_ready[0]
    video = _loop_video(video, final_len)

    if subtitles_data:
        try:
            subs = _make_subtitle_clips(subtitles_data, video.size, subtitles_position)
            if subs: video = CompositeVideoClip([video] + subs)
        except Exception as e:
            print(f"⚠️ Subs failed: {e}")

    final_audio = voice_audio
    if music_path:
        try:
            bg = AudioFileClip(music_path)
            if volumex: bg = bg.fx(volumex, music_volume)
            # Manual loop fallback for music if audio_loop fails
            bg = _loop_audio(bg, final_len)
            final_audio = CompositeAudioClip([voice_audio, bg])
        except Exception as e:
            print(f"⚠️ Music failed: {e}")

    video = video.set_audio(final_audio)
    out_path = os.path.join(FINAL_DIR, output_name)
    video.write_videofile(out_path, codec="libx264", audio_codec="aac", fps=30, logger=None)

    voice_audio.close()
    for c in raw_clips: c.close()
    return out_path