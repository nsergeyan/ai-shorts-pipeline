import os
import random
import sys
import json
import itertools
import time

# --- ADD MODULES PATH ---
sys.path.append(os.path.join(os.path.dirname(__file__), "modules"))

try:
    from modules.gameplay_fetcher import fetch_gameplay_by_search
    from modules.music_fetcher import fetch_random_music
    from modules.voice_generator import generate_voice
    from modules.video_editor import merge_audio_video
    from modules.transcriber import transcribe_audio_to_groups
except ImportError as e:
    print(f"Error importing modules: {e}")
    sys.exit(1)

# ==============================================================================
# 1. CONFIGURATION
# ==============================================================================

LANGUAGE = "en"
MUSIC_VOLUME = 0.03
SUBTITLES_POSITION = "top"
CLEANUP_FILES = True

# ==============================================================================
# 2. MANUAL INPUT SECTION
# ==============================================================================

# PASTE YOUR JSON HERE 👇
MANUAL_DATA = { "topic": "The Real Purpose of the Culling Game Barriers", "specific_subject": "Jujutsu Kaisen", "youtube_queries": ["jjk tengen explaining scene" ], "music_mood": "Jujutsu Kaisen OST glitchy psychological tension", "voice_name": "Hamid", "script": "Wait, did you realize the Culling Game wasn't actually about finding a winner? Everyone assumes it’s a battle royale, but the barrier rules are way more sinister. Kenjaku didn't care who lived or died; he just needed the players to release massive amounts of cursed energy within those specific zones. The barriers weren't meant to keep people in, they were actually acting as a giant stomach. Basically, the constant fighting 'pre-digested' the players' energy to prep Japan for the merger. So every time a character won a fight, they were actually just helping Kenjaku cook the entire country. The whole tournament was just a giant grocery run for the end of the world. Follow for more." }

# ==============================================================================
# 3. THE PIPELINE
# ==============================================================================

def run_manual_pipeline(data):
    try:
        # 1. Unpack Data
        TOPIC = data['topic']
        SUBJECT = data['specific_subject']
        YOUTUBE_QUERIES = data.get('youtube_queries', [])
        MUSIC_QUERY = data.get('music_mood', 'ambient')
        VOICE_NAME = data.get('voice_name', 'hamid')
        SCRIPT_TEXT = data['script']

        print(f"📋 PROCESSING MANUAL ORDER: {SUBJECT}")
        print(f"   Script Length: {len(SCRIPT_TEXT)} chars")

        # 2. VISUALS
        print(f"🎮 Fetching visuals...")
        video_paths = fetch_gameplay_by_search(
            search_queries=YOUTUBE_QUERIES,
            max_videos=1,
            retry_searches=5,
            used_video_ids=set()
        )

        if not video_paths:
            print("❌ No visuals found. Check your YouTube queries.")
            return False

        # 3. MUSIC
        print(f"🎵 Fetching music...")
        music_path = fetch_random_music(search_query=MUSIC_QUERY)

        # 4. VOICE
        print(f"🗣️ Generating voice ({VOICE_NAME})...")
        audio_filename = f"narration_{random.randint(1000, 9999)}.mp3"
        audio_path = generate_voice(SCRIPT_TEXT, audio_filename, VOICE_NAME, LANGUAGE)

        # 5. SUBTITLES
        print(f"📝 Generating subtitles...")
        subtitle_data = transcribe_audio_to_groups(audio_path, 2, LANGUAGE)

        # 6. EDIT
        final_filename = f"Short_{SUBJECT.replace(' ', '_')}_{random.randint(10, 99)}.mp4"
        print(f"🎬 Starting video editing...")

        final_path = merge_audio_video(
            video_paths=video_paths,
            audio_path=audio_path,
            output_name=final_filename,
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

        return True

    except KeyError as e:
        print(f"❌ Missing Key in JSON: {e}")
    except Exception as e:
        print(f"❌ Pipeline Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    if MANUAL_DATA:
        run_manual_pipeline(MANUAL_DATA)
    else:
        print("Please paste your JSON into the MANUAL_DATA variable.")