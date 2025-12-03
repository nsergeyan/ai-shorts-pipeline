import os
import random
import sys
import requests
import json

# --- ADD MODULES PATH ---
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

# ==========================;====================================================
# 1. CONFIGURATION (JUST EDIT THIS PART)
# ==============================================================================

# Choose your language: "en", "es", or "ru"
LANGUAGE = "en"

# List the BROAD topics you want videos about. 
# The AI will pick specific details (e.g. "SCP" -> "SCP-096")
MY_NICHES = [
    "SCP",
    "Hazbin Hotel",
    "Metro 2033",
    "Helluva Boss"
]

# System Settings
MODEL_NAME = "gemma2:27b"
MUSIC_VOLUME = 0.04
SUBTITLES_POSITION = "top"
CLEANUP_FILES = True


# ==============================================================================
# 2. THE PRODUCER AGENT (GENERATES THE PLAN)
# ==============================================================================

def generate_idea_from_niche(broad_niche, language="en"):
    print(f"\n🧠 PRODUCER ({MODEL_NAME}): Analyzing '{broad_niche}'...")

    prompt = f"""
    Role: Senior Content Strategist.
    Universe: "{broad_niche}"
    Language: "{language}"

    TASK:
    1. List 50 MAJOR characters/entities from {broad_niche}.
    2. Pick ONE at random.
    3. Generate a video plan.

    STRICT RULES FOR TITLE:
    - **NO EMOJIS.**
    - **NO CLICKBAIT WORDS:** Do not use "SHOCK", "SECRET REVEALED", "OMG".
    - **STYLE:** Write a clean, interesting title (e.g., "The Tragedy of Alastor", "Why Artyom Survived", "Lucifer's True Power").
    
    STRICT RULES FOR CONTENT:
    - No hallucinations.
    - Visuals: TV Show -> Trailers. Game -> Gameplay.
    - Music: Instrumental Only.

    Return JSON ONLY:
    {{
        "topic": "Clean interesting title in {language}",
        "specific_subject": "The exact name of the character",
        "google_query": "{broad_niche} [SUB-TOPIC] lore facts",
        "youtube_query": "English query for visuals",
        "music_mood": "Instrumental Background Music",
        "voice_name": "hamid" (en), "spanish_guy" (es), or "Molodoy" (ru)
    }}
    """

    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": MODEL_NAME,
                "prompt": prompt,
                "format": "json",
                "stream": False,
                "options": {
                    "temperature": 0.8,
                    "num_ctx": 4096
                }
            },
            timeout=60
        )
        if response.status_code != 200: return None
        return json.loads(response.json().get("response", ""))
    except Exception as e:
        print(f"❌ AI Error: {e}")
        return None


# ==============================================================================
# 3. THE PRODUCTION PIPELINE (MAKES THE VIDEO)
# ==============================================================================

def run_pipeline_for_idea(idea_data):
    # Unpack the AI's plan
    TOPIC = idea_data['topic']
    SUBJECT = idea_data['specific_subject']  # Used for filename
    GOOGLE_QUERY = idea_data['google_query']
    YT_QUERY = idea_data['youtube_query']
    MUSIC_QUERY = idea_data['music_mood']
    VOICE_NAME = idea_data['voice_name']

    print(f"📋 EXECUTING PLAN: {SUBJECT}")
    print(f"   Title: {TOPIC}")
    print(f"   Visuals: {YT_QUERY}")
    print(f"   Music: {MUSIC_QUERY}")

    # 1. SCRIPT
    # The generate_dynamic_script function uses GOOGLE_QUERY to find the lore
    script = generate_dynamic_script(
        topic=TOPIC,
        research_query=GOOGLE_QUERY,
        language=LANGUAGE
    )
    print(f"\n📜 SCRIPT GENERATED:\n{script}...\n")

    # 2. GAMEPLAY
    print(f"🎮 Fetching video: '{YT_QUERY}'")
    video_paths = fetch_gameplay_by_search(YT_QUERY, max_videos=1)
    if not video_paths:
        print("❌ No video found. Skipping this idea.")
        return

    # 3. MUSIC
    print(f"🎵 Fetching music: '{MUSIC_QUERY}'")
    music_path = fetch_random_music(search_query=MUSIC_QUERY)

    # 4. VOICE
    print(f"🗣️ Generating voice: {VOICE_NAME}...")
    audio_filename = f"narration_{SUBJECT.replace(' ', '_')}.mp3"
    audio_path = generate_voice(
        script_text=script,
        filename=audio_filename,
        voice=VOICE_NAME,
        lang=LANGUAGE
    )

    # 5. SUBTITLES
    print("👂 Transcribing...")
    subtitle_data = transcribe_audio_to_groups(
        audio_path,
        words_per_group=2,
        language=LANGUAGE
    )

    # 6. EDIT
    final_filename = f"Short_{SUBJECT.replace(' ', '_')}.mp4"
    print(f"\n🎬 Editing '{final_filename}'...")

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

    print(f"\n✅ VIDEO DONE! Saved to: {final_path}")

    # 7. CLEANUP
    if CLEANUP_FILES:
        if os.path.exists(audio_path): os.remove(audio_path)
        if music_path and os.path.exists(music_path): os.remove(music_path)
        for v in video_paths:
            if os.path.exists(v): os.remove(v)


# ==============================================================================
# 4. MAIN LOOP
# ==============================================================================

if __name__ == "__main__":


    print(f"🚀 STARTING SINGLE VIDEO JOB")
    print(f"🌍 Language: {LANGUAGE.upper()}")
    print(f"🤖 Model: {MODEL_NAME}")

    # 1. Pick ONE random niche
    niche = random.choice(MY_NICHES)

    print(f"\n----------------------------------------------------")
    print(f"🎲 ROLLED RANDOM NICHE: {niche}")
    print(f"----------------------------------------------------")

    # 2. Generate the idea
    ai_plan = generate_idea_from_niche(niche, language=LANGUAGE)

    # 3. Make the video
    if ai_plan:
        run_pipeline_for_idea(ai_plan)
    else:
        print(f"⚠️ AI Error. Could not make video.")

    print("\n🏁 JOB FINISHED. Script stopping.")