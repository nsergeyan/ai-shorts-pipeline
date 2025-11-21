# modules/video_editor.py
import os
from moviepy.video.io.VideoFileClip import VideoFileClip
from moviepy.audio.io.AudioFileClip import AudioFileClip
from moviepy.audio.AudioClip import CompositeAudioClip
from config import DATA_DIR

FINAL_DIR = os.path.join(DATA_DIR, "final")
os.makedirs(FINAL_DIR, exist_ok=True)


def merge_audio_video(video_path: str, audio_path: str, output_name="final_short.mp4"):
    print("\n🎬  Combining gameplay + narration...")
    video = VideoFileClip(video_path)
    audio = AudioFileClip(audio_path)

    # Trim or loop gameplay to match narration length
    if video.duration > audio.duration:
        video = video.subclipped(0, audio.duration)
    elif video.duration < audio.duration and video.duration > 0:
        n_loops = int(audio.duration / video.duration) + 1
        video = video.loop(n_loops).subclipped(0, audio.duration)

    final_audio = CompositeAudioClip([audio])
    video = video.with_audio(final_audio)

    output_path = os.path.join(FINAL_DIR, output_name)
    video.write_videofile(
        output_path,
        codec="libx264",
        audio_codec="aac",
        fps=30,
        logger=None,
    )
    print(f"✅  Final video saved to: {output_path}")
    return output_path