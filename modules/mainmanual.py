import json
import os
import random
import re
import sys
import time
import uuid
import subprocess
from google import genai
import ffmpeg
sys.path.append(os.path.join(os.path.dirname(__file__), "modules"))

try:
    from modules.gameplay_fetcher import fetch_gameplay_by_search
    from modules.music_fetcher import fetch_music_by_search
    from modules.voice_generator import generate_voice
    from modules.video_editor import merge_audio_video
    from modules.transcriber import transcribe_audio_to_groups
except ImportError as e:
    print(f"Error importing modules: {e}")
    sys.exit(1)


# ---------------- CONFIG ---------------- #
API_KEY = "tlk_10XHM2C2H2GGKR2WKS0JP3J4G4WY"
LANGUAGE = "en"
MUSIC_VOLUME = 0.025
SUBTITLES_POSITION = "top"
CLEANUP_FILES = True
CLIP_DURATION = 60.0  # seconds for TwelveLabs-trimmed scene
MODEL_NAME = "marengo3.0"
MODEL_OPTIONS = ["visual", "audio"]
SLEEP_INTERVAL = 5
# ---------------------------------------- #

# PASTE YOUR JSON HERE
MANUAL_DATA = {
  "topic": "Invincible",
  "specific_subject": "Kirkman gave all Viltrumites mustaches because his own dad had a mustache",
  "youtube_queries": [
    "invincible viltrumates fighting",
      "invicnible omniman moments"
  ],
  "twelvelabs_query": "Omni-Man Nolan Grayson mustache face close up talking scene",
  "music_mood": "tiktok phonk viral music",
  "voice_name": "Hamid",
  "script": "Every male Viltrumite has a mustache. Omni-Man. Thragg. Conquest. Kregg. All of them. Fans spent years wondering why this entire alien warrior race all had the same facial hair. Is it cultural? Ceremonial? Religious? Robert Kirkman finally admitted the real reason. He gave Viltrumites mustaches because his own father had one. That's it. That's the whole reason. The most feared alien conquerors in the universe all look like Kirkman's dad. An entire galactic empire's aesthetic was decided because one comic book writer thought his father's mustache looked cool. Every Viltrumite is just Kirkman's dad cosplay. Follow for more Invincible secrets!"
}


def trim_video_to_end(
    input_file,
    output_file,
    ai_start,
    prepad=0.02,
    max_duration=61.0
):
    """
    Trims video starting a bit before AI-found timestamp and goes up to max_duration seconds,
    but not beyond the actual video length.
    Prevents freezing or looping.
    """
    import subprocess
    import ffmpeg

    # get video duration
    info = ffmpeg.probe(input_file)
    video_duration = float(info['format']['duration'])

    # compute safe start
    clip_start = max(float(ai_start) - prepad, 0.0)

    # compute clip end safely
    clip_end = min(clip_start + max_duration, video_duration)
    clip_duration = clip_end - clip_start

    subprocess.run([
        "ffmpeg",
        "-ss", str(clip_start),
        "-i", input_file,
        "-t", str(clip_duration),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-c:a", "aac",
        "-movflags", "+faststart",
        output_file
    ], check=True)

    print(f"🎬 Trimmed clip saved: {output_file} ({clip_duration:.2f}s from {clip_start:.2f}s to {clip_end:.2f}s)")



def evaluate_video_with_genai(video_path, script_text):
    client = genai.Client(api_key="AIzaSyDTsvk17wwE-r-YEjwsI_HhAOsXh7rzn4Q")
    #AIzaSyALxc3KaH3Bkt-zvV88guhk7vOxOhzZp_I
    #WORKING AIzaSyBovTpWVnz7JU2jeiusfRlnWYWb-x8vgEw
    #AIzaSyDTsvk17wwE-r-YEjwsI_HhAOsXh7rzn4Q

    # Upload video
    uploaded_file = client.files.upload(file=video_path)
    print(f"Uploaded file: {uploaded_file.name}")

    # Wait until file is ACTIVE
    file_info = client.files.get(name=uploaded_file.name)
    while file_info.state != "ACTIVE":
        print(f"File state: {file_info.state}, waiting...")
        time.sleep(2)
        file_info = client.files.get(name=uploaded_file.name)
    print("File is ACTIVE ✅")

    # Build prompt
    prompt = f"""
    You are acting as a short-form content editor.

    You judge the video based on what is clearly visible, but you MAY give partial credit if the visuals **contextually support** the script, even if exact actions aren’t shown. Do NOT invent unseen events, but allow for implied relevance.

    Script excerpt:
    \"\"\"{script_text}\"\"\"

    Evaluation Rules:
    1. Core Visual Proof Check
       - Give partial credit if the scene includes the relevant character, objects, or context, even if the exact action isn’t literally shown.
    2. Visual-Script Alignment (1–10)
       - Higher if visuals contextually support the script.
    3. First 2-Second Hook (1–10)
       - Assess visual and audio engagement, not necessarily direct relevance.
    4. Technical Quality (1–10)
       - Animation smoothness, effects, audio clarity.
    5. Posting Decision
       - "post" if relevance_score >= 6, hook_score >= 7, technical_score >= 8
       - Otherwise: "revise" or "reject"
    Respond ONLY with valid JSON:
    {{
      "relevance_score": <1-10>,
      "hook_score": <1-10>,
      "technical_score": <1-10>,
      "decision": "post" | "revise" | "reject"
    }}
    """

    # Send request
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[uploaded_file, prompt]
    )

    # Ensure we have the text string
    raw_text = response.text if hasattr(response, "text") else str(response)

    try:
        # Clean up extra characters
        clean_text = raw_text.strip()
        if not clean_text.startswith("{"):
            clean_text = clean_text[clean_text.find("{"):]
        if not clean_text.endswith("}"):
            clean_text = clean_text[:clean_text.rfind("}") + 1]
        return json.loads(clean_text)
    except Exception as e:
        print(f"⚠️ Failed to parse GenAI JSON: {e}")
        print("Raw response:", raw_text)
        return {
            "relevance_score": 0,
            "hook_score": 0,
            "technical_score": 0,
            "decision": "revise"
        }


def find_scene_with_gemini(video_path, query):
    client = genai.Client(api_key="AIzaSyDTsvk17wwE-r-YEjwsI_HhAOsXh7rzn4Q")
    # AIzaSyALxc3KaH3Bkt-zvV88guhk7vOxOhzZp_I
    # WORKING AIzaSyBovTpWVnz7JU2jeiusfRlnWYWb-x8vgEw
    #AIzaSyDTsvk17wwE-r-YEjwsI_HhAOsXh7rzn4Q

    uploaded_file = client.files.upload(file=video_path)
    print(f"Uploaded file: {uploaded_file.name}")

    file_info = client.files.get(name=uploaded_file.name)
    while file_info.state != "ACTIVE":
        print(f"File state: {file_info.state}, waiting...")
        time.sleep(2)
        file_info = client.files.get(name=uploaded_file.name)

    print("File ACTIVE ✅")

    prompt = f"""
    You are analyzing a full video timeline.

    Your task:
    Find the segment that best matches the following query:

    "{query}"

    Important:
    First, understand the nature of the query.

    - If the query describes a specific action or moment (e.g., something happens, appears, moves, drops, says something, etc.), treat this as a precise event detection task and return the exact moment it occurs.

    - If the query describes a scene type, character appearance, facial expression, or general visual situation (e.g., close-up of a character, someone talking, emotional reaction, etc.), treat this as a semantic scene search task and return the segment that best visually matches the description.

    Rules:
    - The event or scene may occur briefly.
    - It may happen in the background.
    - Search the ENTIRE video carefully.
    - Do NOT assume it happens at the start.
    - Do NOT guess.
    - Do NOT fabricate matches.

    Selection guidelines:
    - Return a tight segment around the best match.
    - Typical duration should be:
      - 1–8 seconds for specific actions
      - 3–15 seconds for general scenes
    - If multiple matches exist, return the clearest and most relevant one.

    If no strong and confident match exists, return 0,0.

    Timestamps:
    - Use float seconds relative to the full video timeline.

    Return ONLY valid JSON.
    No markdown.
    No explanations.
    No extra text.

    Format:
    {{
      "start": <seconds>,
      "end": <seconds>
    }}

    If not confidently found:
    {{
      "start": 0,
      "end": 0
    }}
    """

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[uploaded_file, prompt]
    )

    text = response.text.strip()
    print("Raw model output:", text)

    # remove markdown fences
    text = re.sub(r"```json|```", "", text).strip()

    try:
        return json.loads(text)
    except:
        # extract JSON block if extra text exists
        match = re.search(r"\{.*?\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except:
                pass

    print("Failed parsing:", text)
    return {"start": 0, "end": 0}


def run_manual_pipeline(data):
    try:
        # 1️⃣ Unpack Data
        TOPIC = data['topic']
        SUBJECT = data['specific_subject']
        YOUTUBE_QUERIES = data.get('youtube_queries', [])
        MUSIC_QUERY = data.get('music_mood', 'ambient')
        VOICE_NAME = data.get('voice_name', 'hamid')
        SCRIPT_TEXT = data['script']

        print(f"📋 PROCESSING MANUAL ORDER: {SUBJECT}")
        print(f"topic: {TOPIC}")
        print(f"   Script Length: {len(SCRIPT_TEXT)} chars")

        # 2️⃣ VISUALS - Download and evaluate with retry
        print(f"🎮 Fetching visuals...")

        video_attempts = 0
        max_attempts = len(YOUTUBE_QUERIES)
        original_video = None

        for i, query in enumerate(YOUTUBE_QUERIES):
            print(f"📌 Attempt {i + 1}: Searching YouTube for query: '{query}'")
            video_paths = fetch_gameplay_by_search(
                search_queries=[query],  # use the current query
                max_videos=1,
                retry_searches=5,
                used_video_ids=set()
            )
            if not video_paths:
                print("❌ No visuals found. Check your YouTube queries.")
                return False

            candidate_video = video_paths[0]
            video_attempts += 1
            print(f"📌 Attempt {video_attempts}: Evaluating video...")

            evaluation = evaluate_video_with_genai(candidate_video, SCRIPT_TEXT)

            if evaluation and evaluation.get("decision") == "post":
                print("✅ Video approved by GenAI!")
                original_video = candidate_video
                break
            else:
                print(f"❌ Video rejected by GenAI: {evaluation.get('decision') if evaluation else 'unknown'}")
                if video_attempts >= max_attempts:
                    print("❌ Maximum attempts reached. Stopping pipeline.")
                    return False
                print("🔁 Retrying with next video...")

        print("🤖 Searching scene with Gemini...")

        scene = find_scene_with_gemini(original_video, data.get("twelvelabs_query"))
        print(scene)

        if scene["start"] == 0 and scene["end"] == 0:
            print("⚠️ No scene found. Using full video.")
            trimmed_video = original_video
        else:
            # compute safe start
            ai_start = scene["start"]

            # output file
            trimmed_video = f"trimmed_scene_{uuid.uuid4().hex[:6]}.mp4"

            # call your method
            trim_video_to_end(
                input_file=original_video,
                output_file=trimmed_video,
                ai_start=ai_start,
                prepad=0.02,  # same as your previous prepad
                max_duration=61.0  # max clip length
            )

        # 4️⃣ MUSIC
        print(f"🎵 Fetching music...")
        music_results = fetch_music_by_search(queries=[MUSIC_QUERY], max_tracks=1)
        music_path = music_results[0] if music_results else None

        # 5️⃣ VOICE
        print(f"🗣️ Generating voice ({VOICE_NAME})...")
        audio_filename = f"narration_{random.randint(1000, 9999)}.mp3"
        audio_path = generate_voice(SCRIPT_TEXT, audio_filename, VOICE_NAME, LANGUAGE)

        # 6️⃣ SUBTITLES
        print(f"📝 Generating subtitles...")
        subtitle_data = transcribe_audio_to_groups(audio_path, 2, LANGUAGE)

        # 7️⃣ EDIT
        final_filename = f"Short_{SUBJECT.replace(' ', '_')}_{random.randint(10, 99)}.mp4"
        print(f"🎬 Starting video editing...")
        final_path = merge_audio_video(
            video_paths=[trimmed_video],
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

        # 8️⃣ CLEANUP
        if CLEANUP_FILES:
            for path in [audio_path, music_path, original_video, trimmed_video]:
                if path and os.path.exists(path):
                    os.remove(path)

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
