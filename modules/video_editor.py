import os
import sys
import random
from typing import List, Union, Optional
import uuid

import numpy as np
from PIL import Image, ImageDraw, ImageFont
# ---------------------------------------------------------
# 1. FIX: Auto-detect ImageMagick on macOS
# ---------------------------------------------------------
import moviepy.config as mp_config


import re

from moviepy.audio.AudioClip import AudioClip
from moviepy.video.VideoClip import ImageClip, ColorClip, VideoClip

CYRILLIC_RE = re.compile(r'[\u0400-\u04FF]')

def contains_cyrillic(text: str) -> bool:
    return bool(CYRILLIC_RE.search(text))


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
def chroma_key_green_dominance(clip, threshold=45):
    """
    Proper MoviePy-compatible green-dominance chroma key.
    Returns RGB clip + mask (no RGBA frames).
    """

    def make_rgb(frame):
        return frame[:, :, :3]

    def make_mask(frame):
        frame = frame.astype(np.float32)
        r = frame[:, :, 0]
        g = frame[:, :, 1]
        b = frame[:, :, 2]

        # green dominance → transparent
        mask = ~((g > r + threshold) & (g > b + threshold))

        # MoviePy mask must be float 0..1
        return mask.astype(np.float32)

    rgb = clip.fl_image(make_rgb)

    mask = VideoClip(
        make_frame=lambda t: make_mask(clip.get_frame(t)),
        ismask=True,
        duration=clip.duration
    ).set_fps(clip.fps)

    return rgb.set_mask(mask)
def load_cta_clip(
    cta_path: str,
    target_size: tuple,
    duration: Optional[float] = None,
    green_screen: bool = True
):
    cta = VideoFileClip(cta_path).without_audio()

    # Resize CTA to match video
    cta = cta.resize(height=int(target_size[1] * 0.5))
    cta = cta.set_position(("center", "bottom"))

    # Remove green background
    if green_screen:
        cta = chroma_key_green_dominance(cta, threshold=45)

    if duration:
        cta = cta.subclip(0, min(duration, cta.duration))

    return cta


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


def _create_text_image(text: str, video_size: tuple, font_path: str, fontsize: int):
    w_vid, h_vid = video_size
    img = Image.new('RGBA', (w_vid, h_vid), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Auto-scale: Shrink font if text is wider than 85% of screen
    max_width = int(w_vid * 0.85)
    current_fontsize = fontsize

    while current_fontsize > 20:
        font = ImageFont.truetype(font_path, current_fontsize)
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        if tw <= max_width:
            break
        current_fontsize -= 5

    font = ImageFont.truetype(font_path, current_fontsize)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    # Position at TOP (12% down)
    x = (w_vid - tw) / 2
    y = int(h_vid * 0.12)

    # Draw Outline
    for dx in range(-4, 5):
        for dy in range(-4, 5):
            draw.text((x + dx, y + dy), text, font=font, fill="black")

    # Draw Main Text
    draw.text((x, y), text, font=font, fill="white")

    temp_path = f"temp_sub_{uuid.uuid4().hex}.png"
    img.save(temp_path)
    return temp_path


def _render_word_highlight_image(words_in_line, active_idx, video_size, fontsize):
    """Render a line of words with the active word in yellow using Pillow."""
    w_vid, h_vid = video_size
    img = Image.new('RGBA', (w_vid, h_vid), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    font_path = "/System/Library/Fonts/Helvetica.ttc"
    font = ImageFont.truetype(font_path, fontsize)

    space_w = draw.textbbox((0, 0), " ", font=font)[2]
    word_widths = [draw.textbbox((0, 0), w, font=font)[2] - draw.textbbox((0, 0), w, font=font)[0]
                   for w in words_in_line]
    total_w = sum(word_widths) + space_w * (len(words_in_line) - 1)

    max_w = int(w_vid * 0.9)
    if total_w > max_w:
        fontsize = int(fontsize * (max_w / total_w))
        font = ImageFont.truetype(font_path, fontsize)
        space_w = draw.textbbox((0, 0), " ", font=font)[2]
        word_widths = [draw.textbbox((0, 0), w, font=font)[2] - draw.textbbox((0, 0), w, font=font)[0]
                       for w in words_in_line]
        total_w = sum(word_widths) + space_w * (len(words_in_line) - 1)

    x = (w_vid - total_w) / 2
    y = int(h_vid * 0.10)

    for i, (word, ww) in enumerate(zip(words_in_line, word_widths)):
        color = "#FFE000" if i == active_idx else "white"
        for dx in range(-3, 4):
            for dy in range(-3, 4):
                draw.text((x + dx, y + dy), word, font=font, fill="black")
        draw.text((x, y), word, font=font, fill=color)
        x += ww + space_w

    temp_path = f"temp_wh_{uuid.uuid4().hex}.png"
    img.save(temp_path)
    return temp_path


def _make_word_highlight_clips(words_data, video_size, words_per_line=3):
    """
    words_data: [(word, start, end)]
    Groups words into lines and renders each word's highlight frame.
    Cleans up temp PNG files after creating clips.
    """
    h_vid = video_size[1]
    fontsize = int(h_vid * 0.065)
    clips = []
    temp_files = []

    lines = [words_data[i:i + words_per_line] for i in range(0, len(words_data), words_per_line)]

    for line in lines:
        words_in_line = [w for w, s, e in line]
        for active_idx, (word, start, end) in enumerate(line):
            dur = end - start
            if dur <= 0:
                continue
            img_path = _render_word_highlight_image(words_in_line, active_idx, video_size, fontsize)
            temp_files.append(img_path)
            clip = ImageClip(img_path).set_start(start).set_duration(dur).set_position((0, 0))
            clips.append(clip)

    # Clean up temp PNGs
    for f in temp_files:
        try:
            os.remove(f)
        except:
            pass

    return clips


def _make_subtitle_clips(subtitles_data, video_size, position="top"):
    w_vid, h_vid = video_size
    clips = []
    fontsize = int(h_vid * 0.06)

    FONT_EN = "/System/Library/Fonts/Arial.ttf"
    FONT_RU = "/opt/homebrew/share/fonts/dejavu/DejaVuSans.ttf"
    if not os.path.exists(FONT_RU):
        FONT_RU = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"

    for start, end, txt in subtitles_data:
        dur = end - start
        if dur <= 0: continue

        if contains_cyrillic(txt):
            # Use Pillow for Russian (Auto-scales and stays at TOP)
            img_path = _create_text_image(txt.upper(), video_size, FONT_RU, fontsize)
            txt_clip = ImageClip(img_path).set_start(start).set_duration(dur).set_position((0,0))
        else:
            # English uses standard MoviePy TextClip at TOP
            pos_arg = ('center', int(h_vid * 0.12))
            txt_clip = TextClip(
                txt.upper(),
                fontsize=fontsize,
                color='white',
                font=FONT_EN,
                method='caption',
                size=(int(w_vid * 0.85), None),
                stroke_color='black',
                stroke_width=4,
                align='center'
            ).set_start(start).set_duration(dur).set_position(pos_arg)

        clips.append(txt_clip)
    return clips

cta_path = "/Users/nareksergeyan/YOutuber/Green_Screen_Footage_for_Follow_Button_Boost_Your_Video_Engagement_1080P.mp4"
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
        words_data: Optional[list] = None,
        cta_path=cta_path,
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
    CTA_DURATION = 8
    final_dur = voice_audio.duration
    if shorts_cap:
        max_voice_len = cap_seconds - CTA_DURATION
        final_len = min(final_dur, max_voice_len)

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

    # 4.5 CTA (OVERLAY LAST 8 SECONDS)
    # 4.5 CTA (OVERLAY LAST 8 SECONDS)
    if cta_path:
        cta_clip = load_cta_clip(
            cta_path=cta_path,
            target_size=video.size,
            duration=CTA_DURATION,
            green_screen=True
        ).set_start(final_dur - CTA_DURATION)

        # Move CTA a bit up from bottom
        cta_clip = cta_clip.set_position(("center", video.size[1] - cta_clip.h - 100))

        video = CompositeVideoClip(
            [video, cta_clip],
            size=video.size
        )

    # 5. Subtitles
    if words_data:
        try:
            subs = _make_word_highlight_clips(words_data, video.size)
            if subs:
                video = CompositeVideoClip([video] + subs)
        except Exception as e:
            print(f"⚠️ Word highlight generation failed: {e}")
    elif subtitles_data:
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


