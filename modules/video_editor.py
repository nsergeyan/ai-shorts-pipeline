# modules/video_editor.py
import os
import random
from typing import List, Union, Optional

from moviepy.video.io.VideoFileClip import VideoFileClip
from moviepy.audio.io.AudioFileClip import AudioFileClip
from moviepy.audio.AudioClip import AudioClip as BaseAudioClip, CompositeAudioClip
# noinspection PyUnresolvedReferences
from moviepy import vfx, CompositeVideoClip

from config import DATA_DIR

# For audio effects (used only for looping, not volume)
try:
    from moviepy.audio.fx import all as afx  # type: ignore
except Exception:
    afx = None

FINAL_DIR = os.path.join(DATA_DIR, "final")
os.makedirs(FINAL_DIR, exist_ok=True)


# ----------------------- Helper functions ----------------------- #

def _resize_clip(clip, *, width=None, height=None):
    """Version-safe resize."""
    if hasattr(clip, "resized"):
        return clip.resized(width=width, height=height)
    if hasattr(clip, "resize"):
        return clip.resize(width=width, height=height)
    return clip.fx(vfx.resize, width=width, height=height)


def _crop_clip(clip, x1, y1, x2, y2):
    """Version-safe crop."""
    if hasattr(clip, "cropped"):
        return clip.cropped(x1=x1, y1=y1, x2=x2, y2=y2)
    if hasattr(clip, "crop"):
        return clip.crop(x1=x1, y1=y1, x2=x2, y2=y2)
    return clip.fx(vfx.crop, x1=x1, y1=y1, x2=x2, y2=y2)


def _subclip_safe(clip, start, end):
    """Version-safe subclip/subclipped for both video and audio clips."""
    if hasattr(clip, "subclipped"):
        return clip.subclipped(start, end)
    if hasattr(clip, "subclip"):
        return clip.subclip(start, end)
    raise AttributeError("Neither subclip nor subclipped found on clip object.")


def _cut_to_duration(clip, duration: float):
    """Trim clip to at most `duration` seconds (no looping)."""
    if not getattr(clip, "duration", None):
        return clip
    if clip.duration <= duration:
        return clip
    return _subclip_safe(clip, 0, duration)


# modules/video_editor.py
def _trim_clips_to_total_duration(clips: List[VideoFileClip], total_duration: float) -> List[VideoFileClip]:
    """Trim list of clips to sum up to total_duration."""
    if not clips:
        return []

    # First, check if we have enough total duration
    total_available = sum(max(c.duration or 0, 0.1) for c in clips)

    # If we don't have enough footage, loop the clips first
    if total_available < total_duration:
        # Loop individual clips to make up the difference
        extended_clips = []
        accumulated_duration = 0

        for clip in clips:
            if accumulated_duration >= total_duration:
                break

            remaining_needed = total_duration - accumulated_duration

            if clip.duration >= remaining_needed:
                # Clip is long enough, just trim it
                trimmed = _subclip_safe(clip, 0, remaining_needed)
                extended_clips.append(trimmed)
                accumulated_duration += remaining_needed
            else:
                # Need to loop this clip
                looped = _loop_to_duration(clip, remaining_needed)
                extended_clips.append(looped)
                accumulated_duration += looped.duration

        return extended_clips

    # If we have enough footage, proceed with proportional trimming
    durations = [max(c.duration or 0, 0.1) for c in clips]  # Prevent division by zero
    total_clip_duration = sum(durations)

    if total_clip_duration == 0:
        raise ValueError("All input clips have zero duration.")

    ratio = total_duration / total_clip_duration
    result = []

    elapsed = 0
    for clip in clips[:-1]:
        new_dur = max(clip.duration * ratio, 0.1)  # Minimum 0.1s per clip
        if new_dur <= clip.duration:
            result.append(_subclip_safe(clip, 0, new_dur))
        else:
            # If somehow we need more than clip duration, loop it
            looped = _loop_to_duration(clip, new_dur)
            result.append(looped)
        elapsed += new_dur

    last_clip = clips[-1]
    remaining = max(total_duration - elapsed, 0.1)
    if remaining <= last_clip.duration:
        result.append(_subclip_safe(last_clip, 0, remaining))
    else:
        # Loop the last clip if needed
        looped = _loop_to_duration(last_clip, remaining)
        result.append(looped)

    return result


def _make_vertical_9x16(clip, target_w=1080, target_h=1920):
    """Scale & center-crop a single clip to 9:16."""
    src_ratio = clip.w / clip.h
    tgt_ratio = target_w / target_h

    if src_ratio > tgt_ratio:
        # Video is "wider" than 9:16 → fit height, crop width
        resized = _resize_clip(clip, height=target_h)
        excess_w = max(0, resized.w - target_w)
        x1 = excess_w / 2
        x2 = x1 + target_w
        return _crop_clip(resized, x1, 0, x2, target_h)
    else:
        # Video is "taller" or equal → fit width, crop height
        resized = _resize_clip(clip, width=target_w)
        excess_h = max(0, resized.h - target_h)
        y1 = excess_h / 2
        y2 = y1 + target_h
        return _crop_clip(resized, 0, y1, target_w, y2)


def _loop_to_duration(clip, target_duration: float):
    """Loop video clip if too short using vfx.loop (no concatenate needed)."""
    if not getattr(clip, "duration", None):
        return clip

    # If already longer or equal, just trim
    if clip.duration >= target_duration:
        return _cut_to_duration(clip, target_duration)

    # Try vfx.loop first (MoviePy 2.x)
    try:
        looped = clip.fx(vfx.loop, duration=target_duration)
        return _cut_to_duration(looped, target_duration)
    except Exception:
        pass

    # Fallback for 1.x or older
    import math
    num_loops = math.ceil(target_duration / clip.duration)
    try:
        looped = clip.fx(vfx.loop, n=num_loops)
        return _cut_to_duration(looped, target_duration)
    except Exception:
        # Manual looping fallback
        clips = []
        t_curr = 0
        while t_curr < target_duration:
            if hasattr(clip, "with_start"):
                c = clip.with_start(t_curr)
            else:
                c = clip.set_start(t_curr)
            clips.append(c)
            t_curr += clip.duration

        looped = CompositeVideoClip(clips, size=clip.size if hasattr(clip, "size") else None)
        return _cut_to_duration(looped, target_duration)


def _loop_audio_to_duration(audio_clip, target_duration: float):
    """Loop an audio clip to at least target_duration, then trim."""
    if not getattr(audio_clip, "duration", None):
        return audio_clip

    # If already longer or equal, just trim
    if audio_clip.duration >= target_duration:
        return _cut_to_duration(audio_clip, target_duration)

    # Prefer audio_loop effect if available
    if afx is not None and hasattr(afx, "audio_loop"):
        try:
            # Use fx form; this should work on any AudioClip
            looped = audio_clip.fx(afx.audio_loop, duration=target_duration)
            return _cut_to_duration(looped, target_duration)
        except Exception as e:
            print(f"⚠️ audio.fx.audio_loop failed, falling back to manual loop: {e}")

    # Manual looping fallback
    import math
    num_loops = math.ceil(target_duration / audio_clip.duration)
    try:
        looped = audio_clip.fx(afx.audio_loop, n=num_loops) if afx and hasattr(afx, "audio_loop") else None
        if looped:
            return _cut_to_duration(looped, target_duration)
    except Exception:
        pass

    # Final fallback: manual composition
    clips = []
    t_curr = 0
    while t_curr < target_duration:
        if hasattr(audio_clip, "with_start"):
            c = audio_clip.with_start(t_curr)
        else:
            c = audio_clip.set_start(t_curr)
        clips.append(c)
        t_curr += audio_clip.duration

    looped = CompositeAudioClip(clips)
    return _cut_to_duration(looped, target_duration)


def _scale_volume(audio_clip, volume: float):
    """
    Apply a volume multiplier to any AudioClip by wrapping its get_frame.
    Compatible with MoviePy 1.x.
    """
    if audio_clip is None:
        return None
    if volume == 1.0:
        return audio_clip

    # Try clip.volumex if it exists
    if hasattr(audio_clip, "volumex"):
        try:
            return audio_clip.volumex(volume)
        except Exception as e:
            print(f"⚠️ clip.volumex failed: {e}")

    # Fallback: manual AudioClip wrapping (MoviePy 1.x style)
    try:
        if not hasattr(audio_clip, "get_frame"):
            print("⚠️ audio_clip has no get_frame; cannot scale volume.")
            return audio_clip

        dur = getattr(audio_clip, "duration", None)
        if dur is None:
            print("⚠️ audio_clip has no duration; cannot scale volume.")
            return audio_clip

        fps = getattr(audio_clip, "fps", 44100)
        nchannels = getattr(audio_clip, "nchannels", 2)  # default to stereo

        def make_frame(t):
            return volume * audio_clip.get_frame(t)

        # For MoviePy 1.x: create empty clip and override get_frame
        scaled = BaseAudioClip(duration=dur, fps=fps)
        scaled.get_frame = make_frame
        scaled.nchannels = nchannels  # ← ADD THIS
        return scaled

    except Exception as e:
        print(f"⚠️ Manual volume scaling failed: {e}")
        return audio_clip


# ----------------------- Main function ----------------------- #

def merge_audio_video(
        video_paths: Union[str, List[str]],
        audio_path: str,
        output_name: str = "final_short.mp4",
        vertical: bool = False,
        target_w: int = 1080,
        target_h: int = 1920,
        shorts_cap: bool = True,
        cap_seconds: float = 59.0,
        # Background music
        music_path: Optional[str] = None,
        music_volume: float = 0.01,
):
    print("\n🎬  Starting Video Editor...")

    # Voice-over (main audio)
    voice_audio = AudioFileClip(audio_path)

    # Handle single path vs list
    if isinstance(video_paths, str):
        video_paths = [video_paths]

    print(f"🎬  Processing {len(video_paths)} clip(s)...")

    # 1. Prepare clips (Crop + Resize)
    base_clips = []
    for path in video_paths:
        clip = VideoFileClip(path)
        if vertical:
            clip = _make_vertical_9x16(clip, target_w, target_h)
        base_clips.append(clip)

    # 2. Match Duration to Voice Audio
    final_len = voice_audio.duration
    if shorts_cap:
        final_len = min(final_len, cap_seconds)
        print(f"⏱️  Capping duration to {final_len:.2f}s")

    # 3. Trim clips proportionally to match exact duration
    processed_clips = _trim_clips_to_total_duration(base_clips, final_len)

    # 4. Combine Clips into a sequence
    if len(processed_clips) > 1:
        sequence = []
        current_time = 0
        for clip in processed_clips:
            if hasattr(clip, "with_start"):  # MoviePy 2.x
                c = clip.with_start(current_time)
            else:  # MoviePy 1.x
                c = clip.set_start(current_time)
            sequence.append(c)
            current_time += clip.duration

        video = CompositeVideoClip(sequence, size=processed_clips[0].size)
    else:
        video = processed_clips[0]

    # 5. Ensure video duration matches exactly
    video = _loop_to_duration(video, final_len)

    # Trim voice to match (double-check)
    voice_final = _cut_to_duration(voice_audio, final_len)

    # 6. Optional background music
    music_final = None
    music_raw = None
    if music_path:
        try:
            music_raw = AudioFileClip(music_path)
            print(f"🎵  Adding background music (volume={music_volume}): {music_path}")

            # Scale the raw file's volume FIRST
            music_scaled = _scale_volume(music_raw, music_volume)

            # Loop and trim to final length
            music_final = _loop_audio_to_duration(music_scaled, final_len)

        except Exception as e:
            print(f"⚠️  Failed to load or process background music: {e}")
            music_final = None

    # 7. Combine Audio (voice + optional music)
    audio_clips = [voice_final]
    if music_final is not None:
        audio_clips.append(music_final)

    final_audio = CompositeAudioClip(audio_clips)

    # Attach audio to video
    if hasattr(video, "with_audio"):
        video = video.with_audio(final_audio)
    else:
        video = video.set_audio(final_audio)

    # Debug info
    print(f"🎤 Narration Duration: {voice_audio.duration:.2f}s")
    print(f"📹 Video Duration: {video.duration:.2f}s")
    print(f"🎧 Final Audio Duration: {final_audio.duration:.2f}s")

    # 8. Write
    output_path = os.path.join(FINAL_DIR, output_name)
    video.write_videofile(
        output_path,
        codec="libx264",
        audio_codec="aac",
        fps=30,
        logger=None,
    )

    # Cleanup
    try:
        voice_audio.close()
        if music_raw is not None:
            music_raw.close()
        for c in base_clips:
            c.close()
    except Exception:
        pass

    print(f"✅  Final video saved to: {output_path}")
    return output_path
