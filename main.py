import os
import random
import sys
import requests
import json
import time

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

# ==============================================================================
# 1. CONFIGURATION
# ==============================================================================

LANGUAGE = "ru"  # "en", "es", "ru"

MY_NICHES = [
    "SCP",
    "Hazbin Hotel",
    "Metro 2033",
    "Helluva Boss"
]

MODEL_NAME = "gemma2:27b"
MUSIC_VOLUME = 0.05
SUBTITLES_POSITION = "top"
CLEANUP_FILES = True


# ==============================================================================
# 2. THE PRODUCER AGENT
# ==============================================================================

def generate_idea_from_niche(broad_niche, language="en"):
    print(f"\n🧠 PRODUCER ({MODEL_NAME}): Analyzing '{broad_niche}'...")

    # Context helps Gemma know what to search for
    if broad_niche in ["Helluva Boss", "Hazbin Hotel", "Arcane"]:
        visual_type = "TV Show"
        visual_hint = "trailer clips best moments"
    else:
        visual_type = "Video Game"
        visual_hint = "gameplay no hud cinematic"

    prompt = f"""
    Role: Content Strategist.
    Universe: "{broad_niche}" ({visual_type})
    Language: "{language}"

    TASK:
    1. List 10 MAJOR characters/entities.
    2. Pick ONE at random. (Avoid obscure ones, but don't just pick the main hero).
    3. Generate a video plan.

    STRICT RULES:
    - **NO HALLUCINATIONS:** Do not invent names.
    - **TITLE:** Clickbait title in {language}.
    - **GOOGLE QUERY:** MUST BE IN ENGLISH. Format: "Universe Character wiki lore".
    - **VISUALS:** Use "{visual_hint}".

    Return JSON ONLY:
    {{
        "topic": "Title in {language}",
        "specific_subject": "The Exact Character Name",
        "google_query": "{broad_niche} [CHARACTER NAME] wiki fandom lore",
        "youtube_query": "{broad_niche} [CHARACTER NAME] {visual_hint}",
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
                    "temperature": 0.8,  # High variety
                    "num_ctx": 4096
                }
            },
            timeout=120
        )
        if response.status_code != 200: return None
        return json.loads(response.json().get("response", ""))
    except Exception as e:
        print(f"❌ AI Error: {e}")
        return None


# ==============================================================================
# 3. THE PIPELINE
# ==============================================================================

def run_pipeline_for_idea(idea_data):
    # Unpack
    TOPIC = idea_data['topic']
    SUBJECT = idea_data['specific_subject']

    # CLEAN QUERY (Force English for better results)
    GOOGLE_QUERY = idea_data['google_query'].replace("English query:", "").strip()

    YT_QUERY = idea_data['youtube_query']
    MUSIC_QUERY = idea_data['music_mood']
    VOICE_NAME = idea_data['voice_name']

    print(f"📋 PLAN: {SUBJECT}")
    print(f"   Title: {TOPIC}")
    print(f"   Search: {GOOGLE_QUERY}")

    # 1. SCRIPT
    # 🛑 CRITICAL FIX: We pass 'SUBJECT', not 'TOPIC'
    # This ensures the AI writes about "Hunter", not about "The Path of Despair".
    script = generate_dynamic_script(
        topic=SUBJECT,
        research_query=GOOGLE_QUERY,
        language=LANGUAGE
    )

    if not script or len(script) < 100:
        print("❌ Script generation failed (too short). Skipping.")
        return

    print(f"\n📜 SCRIPT:\n{script}...\n")

    # 2. GAMEPLAY
    print(f"🎮 Fetching video: '{YT_QUERY}'")
    video_paths = fetch_gameplay_by_search(YT_QUERY, max_videos=1)
    if not video_paths:
        print("❌ No video found. Skipping.")
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
    subtitle_data = transcribe_audio_to_groups(audio_path, 2, LANGUAGE)

    # 6. EDIT
    final_filename = f"Short_{SUBJECT.replace(' ', '_')}_{random.randint(100, 999)}.mp4"
    print(f"🎬 Editing '{final_filename}'...")

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


# ==============================================================================
# 4. MAIN LOOP
# ==============================================================================

if __name__ == "__main__":
    print(f"🚀 STARTING AI STUDIO")
    print(f"🌍 Language: {LANGUAGE.upper()}")
    print(f"🤖 Model: {MODEL_NAME}")

    # Batch Count
    try:
        count = int(input("\nHow many videos? (Enter number): "))
    except:
        count = 1

    for i in range(count):
        print(f"\n=== 🎬 VIDEO {i + 1}/{count} ===")

        niche = random.choice(MY_NICHES)
        plan = generate_idea_from_niche(niche, LANGUAGE)

        if plan:
            run_pipeline_for_idea(plan)
        else:
            print("⚠️ AI Plan failed.")

        if i < count - 1:
            time.sleep(5)

    print("\n🏁 Finished.")