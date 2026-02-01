import os
import numpy as np
from moviepy.editor import ColorClip, AudioClip

# Import your function
from modules.video_editor import merge_audio_video, FINAL_DIR

TMP_DIR = "tmp_test"
os.makedirs(TMP_DIR, exist_ok=True)

# -------------------------------------------------
# 1. Create MOCK BACKGROUND VIDEO (10 seconds)
# -------------------------------------------------
bg_video_path = os.path.join(TMP_DIR, "mock_bg.mp4")

bg_clip = ColorClip(
    size=(1920, 1080),
    color=(30, 30, 30),
    duration=20
).set_fps(30)

bg_clip.write_videofile(
    bg_video_path,
    codec="libx264",
    fps=30,
    audio=False,
    logger=None
)

bg_clip.close()

# -------------------------------------------------
# 2. Create MOCK VOICE AUDIO (6 seconds)
# -------------------------------------------------
audio_path = os.path.join(TMP_DIR, "mock_voice.wav")

def make_tone(t):
    return 0.3 * np.sin(2 * np.pi * 440 * t)

voice_audio = AudioClip(
    make_tone,
    duration=18,
    fps=44100
)

voice_audio.write_audiofile(
    audio_path,
    fps=44100,
    logger=None
)

voice_audio.close()

# -------------------------------------------------
# 3. Run your CTA test
# -------------------------------------------------
output = merge_audio_video(
    video_paths=bg_video_path,
    audio_path=audio_path,
    output_name="cta_test_output.mp4",
    vertical=False,
    shorts_cap=False,   # IMPORTANT: disable cap so CTA logic is clear
    cta_path="/Users/nareksergeyan/YOutuber/Green_Screen_Footage_for_Follow_Button_Boost_Your_Video_Engagement_1080P.mp4"
)

print("\n🎯 TEST COMPLETE")
print(f"Output video: {output}")
print("Expected timeline:")
print("0s–6s   : background + voice")
print("6s–14s  : CTA visible (8 seconds)")