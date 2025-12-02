import os
import sys

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

# 1. CHOOSE LANGUAGE ("en" or "ru" or "es)
LANGUAGE = "ru"

MUSIC_QUERY = "metro 2033 soundtrack"
MUSIC_VOLUME = 0.04

if LANGUAGE == "ru":
    # --- RUSSIAN MODE ---
    TOPIC = "Арк Рейдерс Новый зимный апдейт"
    GOOGLE_RESEARCH_QUERY = "Arc raiders  winter update news"

    # Video Search (анимации / геймплей по SCP-096)
    YOUTUBE_GAMEPLAY_QUERY = "ARC RAIDERS no comentery gameplay 10 min"

    # Name of the voice from VOICES in modules/voice_generator.py
    # VOICES = {"hamid": "...", "Alan": "...", "Molodoy": "..."}
    VOICE_NAME = "Molodoy"   # or "Alan"

elif LANGUAGE == "es":
    TOPIC = "La próxima actualización de invierno de Arc Raiders"
    GOOGLE_RESEARCH_QUERY = "Arc raiders new winter update coming"
    YOUTUBE_GAMEPLAY_QUERY = "ARC RAIDERS no comentery gameplay 10 min"
    VOICE_NAME = "spanish_guy"  # Or use placeholder until real voice added

else:
    # --- ENGLISH MODE ---
    TOPIC = "scp 999, interesting facts"
    GOOGLE_RESEARCH_QUERY = "SCP-999 The Tickle Monster facts and lore"
    YOUTUBE_GAMEPLAY_QUERY = "scp 999 animation, footages"
    VOICE_NAME = "hamid"

# --- SHARED SETTINGS ---
OUTPUT_FILE = "final_short.mp4"
SUBTITLES_POSITION = "top"
CLEANUP_FILES = True


# ==============================================================================
# PIPELINE
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

    # 3. MUSIC
    print(f"🎵 Fetching music: '{MUSIC_QUERY}'")
    music_path = fetch_random_music(search_query=MUSIC_QUERY)

    # 4. VOICE (ElevenLabs) -- UPDATED CALL SIGNATURE
    print(f"🗣️  Generating voice: {VOICE_NAME}...")
    audio_path = generate_voice(
        script_text=script,
        filename="narration.mp3",
        voice=VOICE_NAME,
        lang=LANGUAGE    # "ru" or "en" – matches your LANGUAGE setting
    )

    # 5. SUBTITLES (Whisper) -- PASS LANGUAGE FOR BETTER ACCURACY
    print("👂 Transcribing for perfect sync...")
    subtitle_data = transcribe_audio_to_groups(
        audio_path,
        words_per_group=2,
        language=LANGUAGE
    )

    # 6. EDIT
    print("\n🎬  Editing video...")
    final_path = merge_audio_video(
        video_paths=video_paths,
        audio_path=audio_path,
        output_name=OUTPUT_FILE,
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
        if os.path.exists(audio_path):
            os.remove(audio_path)
        if music_path and os.path.exists(music_path):
            os.remove(music_path)
        for v in video_paths:
            if os.path.exists(v):
                os.remove(v)


if __name__ == "__main__":
    run_pipeline()