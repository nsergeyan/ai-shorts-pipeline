import os
import sys
import random
import time

# Allow imports from modules/
sys.path.append(os.path.join(os.path.dirname(__file__), "modules"))

try:
    from modules.script_generator import generate_dynamic_script
    from modules.gameplay_fetcher import fetch_gameplay_by_search
    from modules.music_fetcher import fetch_random_music
    from modules.voice_generator import generate_voice
    from modules.video_editor import merge_audio_video
    from modules.transcriber import transcribe_audio_to_groups
except ImportError as e:
    print(f"Error importing modules: {e}")
    sys.exit(1)

# ==============================================================================
# ⚙️ CONFIGURATION
# ==============================================================================

# 1. CHOOSE LANGUAGE ("en" or "ru")
LANGUAGE = "ru"

if LANGUAGE == "ru":
    # --- RUSSIAN MODE ---
    TOPIC = "Аластор (Отель Хазбин): Пугающие факты"

    # Research in English gives better results, AI will translate
    GOOGLE_RESEARCH_QUERY = "Alastor Hazbin Hotel facts lore theories"

    # Video Search
    YOUTUBE_GAMEPLAY_QUERY = "Hazbin Hotel Alastor moments 4k"

    # PUT YOUR RUSSIAN ELEVENLABS VOICE ID HERE
    # (You can find it in ElevenLabs -> VoiceLab -> ID)
    VOICE_ID = "2EiwWnXFnvU5JabPnv8n"  # Example: Clyde (Deep) or find a Russian one

else:
    # --- ENGLISH MODE ---
    TOPIC = "Alastor from Hazbin Hotel: Scary Facts"
    GOOGLE_RESEARCH_QUERY = "Alastor Hazbin Hotel interesting facts"
    YOUTUBE_GAMEPLAY_QUERY = "Alastor Hazbin Hotel moments 4k"

    # English Voice ID (Hamid/Mat)
    VOICE_ID = "yr43K8H5LoTp6S1QFSGg"

# --- SHARED SETTINGS ---
MUSIC_QUERY = "Dark cabaret instrumental no lyrics"
MUSIC_VOLUME = 0.06

OUTPUT_FILE = "final_short.mp4"
SUBTITLES_POSITION = "center"
CLEANUP_FILES = True


# ==============================================================================

def run_pipeline():
    print(f"\n🚀 STARTING PIPELINE IN [{LANGUAGE.upper()}] MODE")
    print(f"📝 Topic: {TOPIC}")

    # 1. SCRIPT
    script = generate_dynamic_script(
        topic=TOPIC,
        research_query=GOOGLE_RESEARCH_QUERY,
        language=LANGUAGE
    )
    print(f"\n📜 SCRIPT:\n{script}\n")

    # 2. GAMEPLAY
    print(f"🎮 Fetching background video: '{YOUTUBE_GAMEPLAY_QUERY}'")
    video_paths = fetch_gameplay_by_search(YOUTUBE_GAMEPLAY_QUERY, max_videos=1)
    if not video_paths:
        print("❌ No video found.")
        return

    # 3. VOICE (ElevenLabs)
    print(f"🗣️  Generating Voice ID: {VOICE_ID}...")
    audio_path = generate_voice(script, "narration.mp3", voice_id=VOICE_ID)

    # 4. SUBTITLES (Whisper)
    print("👂 Transcribing for perfect sync...")
    subtitle_data = transcribe_audio_to_groups(audio_path, words_per_group=2)

    # 5. MUSIC
    print(f"🎵 Fetching music: '{MUSIC_QUERY}'")
    music_path = fetch_random_music(search_query=MUSIC_QUERY)

    # 6. EDIT
    print("\n🎬  Editing video...")
    final_path = merge_audio_video(
        video_paths,
        audio_path,
        OUTPUT_FILE,
        vertical=True,
        shorts_cap=True,
        music_path=music_path,
        music_volume=MUSIC_VOLUME,
        subtitles_data=subtitle_data,
        subtitles_position=SUBTITLES_POSITION
    )

    print(f"\n✅ DONE! Saved to: {final_path}")

    # 7. CLEANUP
    if CLEANUP_FILES:
        if os.path.exists(audio_path): os.remove(audio_path)
        if music_path and os.path.exists(music_path): os.remove(music_path)
        for v in video_paths:
            if os.path.exists(v): os.remove(v)


if __name__ == "__main__":
    run_pipeline()