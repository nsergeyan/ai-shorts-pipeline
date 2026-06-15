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
    from modules.music_generator import generate_music
    from modules.newvoice import generate_voice
    from modules.video_editor import merge_audio_video
    from modules.transcriber import transcribe_audio_to_words
except ImportError as e:
    print(f"Error importing modules: {e}")
    sys.exit(1)
# ---------------- CONFIG ---------------- #
API_KEY = "tlk_10XHM2C2H2GGKR2WKS0JP3J4G4WY"
LANGUAGE = "en"
MUSIC_VOLUME = 0.05
SUBTITLES_POSITION = "top"
CLEANUP_FILES = True
CLIP_DURATION = 60.0
MODEL_OPTIONS = ["visual", "audio"]
SLEEP_INTERVAL = 5
# ---------------------------------------- #

MANUAL_DATA = {
  "topic": "unexpected character detail",
  "specific_subject": "Toge Inumaki speaks only in rice-ball ingredients so his Cursed Speech doesn't accidentally command people",
  "youtube_queries": [
    "Jujutsu Kaisen Inumaki cursed speech blast away Hanami fight",
    "Jujutsu Kaisen Toge Inumaki saying salmon scene",
    "Jujutsu Kaisen Inumaki commands cursed spirits exorcise scene"
  ],
  "twelvelabs_query": "Boy with white hair and a high collar covering his mouth, snake-like markings on his cheeks, opening his mouth to shout, a visible shockwave blasting forward and knocking back a monster, then him coughing",
  "music_mood": "curious",
  "music_prompt": "Upbeat lo-fi hip hop instrumental, warm Rhodes piano, light percussion, playful and curious mood, medium tempo 90 BPM, relaxed anime trivia background, no lyrics, exclude: heavy bass, exclude: aggressive elements",
  "voice_name": "Hamid",
  "script": "[curious] You know that quiet guy in Jujutsu Kaisen who only says random words like salmon and bonito flakes? [pauses] People think it is just a weird quirk. It is not. [excited] Toge has a power called Cursed Speech. Any word he says can become a command that forces people to obey. And here is the scary part. He cannot turn it off. [whispering] So if he said something normal, like go away, he might actually hurt someone. [matter-of-fact] That is why he sticks to safe rice-ball words. [playfully] Imagine ordering lunch and accidentally controlling the chef. [pauses] So... what happens if he ever loses his temper?"
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

    # get video duration
    info = ffmpeg.probe(input_file)

    video_stream = next(
        s for s in info["streams"]
        if s["codec_type"] == "video"
    )

    video_duration = float(video_stream["duration"])

    # compute safe start
    clip_start = max(float(ai_start) - prepad, 0.0)
    clip_start = min(clip_start, video_duration - 0.001)

    # compute clip end safely
    clip_end = min(clip_start + max_duration, video_duration)
    clip_duration = clip_end - clip_start

    if clip_duration <= 0:
        print("⚠️ Invalid clip duration. Skipping.")
        return False

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

def evaluate_music_with_genai(music_path, script_text):
    client = genai.Client(api_key="AIzaSyALxc3KaH3Bkt-zvV88guhk7vOxOhzZp_I")

    # Upload music file
    uploaded_file = client.files.upload(file=music_path)
    print(f"Uploaded music: {uploaded_file.name}")

    # Wait until ACTIVE
    file_info = client.files.get(name=uploaded_file.name)
    while file_info.state != "ACTIVE":
        print(f"Music state: {file_info.state}, waiting...")
        time.sleep(2)
        file_info = client.files.get(name=uploaded_file.name)

    print("Music file ACTIVE ✅")

    # 🔥 PROMPT (this is the important part)
    prompt = f"""
    You are a short-form content audio expert.

    Your job is to evaluate how well this MUSIC fits the SCRIPT.

    IMPORTANT RULES:
    - Focus ONLY on the audio provided.
    - Do NOT assume visuals.
    - Judge vibe, energy, and emotional tone.
    - Consider this is for TikTok / YouTube Shorts.

    SCRIPT:
    \"\"\"{script_text}\"\"\"

    SCORING CRITERIA:

    1. Mood Match (mood_score: 1–10)
       Does the music emotionally match the script?

       9–10: Perfect emotional alignment
       7–8 : Good fit
       5–6 : Neutral / usable
       3–4 : Slight mismatch
       1–2 : Completely wrong mood

    2. Energy & Engagement (energy_score: 1–10)
       Is the music engaging for short-form content?

       Consider:
       - buildup
       - rhythm
       - loopability
       - modern feel

    3. Voice Compatibility (voice_score: 1–10)
       Would this music sit well under narration?

       Consider:
       - not too loud or chaotic
       - not distracting
       - supports storytelling
    DECISION RULES:

    - "post"
      mood_score >= 7 AND energy_score >= 7 AND voice_score >= 7

    - "revise"
      usable but not optimal

    - "reject"
      wrong vibe OR distracting OR unusable

    OUTPUT FORMAT:
    Return ONLY JSON.

    {{
      "mood_score": <1-10>,
      "energy_score": <1-10>,
      "voice_score": <1-10>,
      "decision": "post" | "revise" | "reject"
    }}
    """

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[uploaded_file, prompt]
    )

    raw_text = response.text if hasattr(response, "text") else str(response)

    try:
        clean_text = raw_text.strip()
        if not clean_text.startswith("{"):
            clean_text = clean_text[clean_text.find("{"):]
        if not clean_text.endswith("}"):
            clean_text = clean_text[:clean_text.rfind("}") + 1]
        return json.loads(clean_text)
    except Exception as e:
        print(f"⚠️ Failed to parse music JSON: {e}")
        print("Raw:", raw_text)
        return {
            "mood_score": 0,
            "energy_score": 0,
            "voice_score": 0,
            "decision": "revise"
        }

def evaluate_video_with_genai(video_path, script_text):
    client = genai.Client(api_key="AIzaSyALxc3KaH3Bkt-zvV88guhk7vOxOhzZp_I")
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
        You are an AI Video Editor Assistant. 
        Your job is to evaluate if this RAW SOURCE FOOTAGE is usable as background B-roll for a short-form video.

        Do NOT judge this as a final, edited TikTok/Reel. Judge it based on its POTENTIAL.

        SCRIPT EXCERPT:
        \"\"\"{script_text}\"\"\"
        
        THe video has to be only with actual footages it means no subsccribe to chanel, no promotions in between stuff. Just raw moments

        EVALUATION GUIDELINES (1-10 Scale):

        1. Visual-Script Alignment (relevance_score)
           Since this is raw anime footage, be highly forgiving. 
           - If the video shows the correct character (Levi Ackerman) or the correct show (Attack on Titan), give it an 8-10. 
           - It does NOT need to show literal insomnia or the exact actions in the script. Thematic atmosphere, the character's face, or general action is perfectly acceptable for background B-roll.
           - Only score below 5 if it is the wrong show, wrong character entirely, or completely unrelated to the anime.

        2. Usable Action / Hook Potential (hook_score)
           Does this raw footage contain cool, dynamic, or interesting scenes we could *use* to make a hook?
           - 8-10: Contains great action scenes, cool character close-ups, or intense moments.
           - 5-7: Standard talking scenes, panning shots, average animation.
           - 1-4: Mostly black screens, text overlays, fan-edits with heavy watermarks, or unusable static menus.

        3. Raw Technical Quality (technical_score)
           Is the footage visually clear enough to be cropped for a phone screen?
           - 8-10: Clean footage, minimal watermarks, acceptable visual clarity.
           - 5-7: Slightly blurry or has minor subtitles/watermarks, but usable.
           - 1-4: Extremely pixelated, completely ruined by heavy editing/watermarks, or unwatchable.

        DECISION RULES:
        - "post":   relevance_score >= 5 AND hook_score >= 5 AND technical_score >= 5
        - "reject": relevance_score <= 4 OR technical_score <= 4
        - "revise": Use this if you are unsure.

        OUTPUT FORMAT:
        Respond ONLY with valid JSON. No explanations, no markdown blocks.

        {{
          "relevance_score": <1-10>,
          "hook_score": <1-10>,
          "technical_score": <1-10>,
          "decision": "post" | "revise" | "reject"
        }}
    """

    # Send request with 503 retry
    attempt = 0
    while True:
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[uploaded_file, prompt]
            )
            break
        except Exception as e:
            if "503" in str(e):
                attempt += 1
                print(f"⚠️ Gemini 503, retrying in 20s... (attempt {attempt})")
                time.sleep(20)
            else:
                raise

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


def find_scene_with_gemini(video_path, query, script):
    client = genai.Client(api_key="AIzaSyALxc3KaH3Bkt-zvV88guhk7vOxOhzZp_I")
    # AIzaSyALxc3KaH3Bkt-zvV88guhk7vOxOhzZp_I
    # WORKING AIzaSyBovTpWVnz7JU2jeiusfRlnWYWb-x8vgEw
    #AIzaSyDTsvk17wwE-r-YEjwsI_HhAOsXh7rzn4Q

    info = ffmpeg.probe(video_path)
    video_stream = next(s for s in info["streams"] if s["codec_type"] == "video")
    video_duration = float(video_stream["duration"])

    uploaded_file = client.files.upload(file=video_path)
    print(f"Uploaded file: {uploaded_file.name}")

    file_info = client.files.get(name=uploaded_file.name)
    while file_info.state != "ACTIVE":
        print(f"File state: {file_info.state}, waiting...")
        time.sleep(2)
        file_info = client.files.get(name=uploaded_file.name)

    print("File ACTIVE ✅")

    prompt = f"""
    You are analyzing a video to find when a specific visual moment occurs.

    VIDEO DURATION: {video_duration} seconds

    USER QUERY:
    "{query}"

    VIDEO SCRIPT:
    "{script}"

    TASK:
    Find the BEST approximate timestamp where the query visually appears.

    IMPORTANT:
    - The timestamp does NOT need to be exact (±2–3 seconds is acceptable).
    - Use the script to find candidate moments, then refine visually.
    - The result must produce a GOOD 5-second clip (important).

    SEARCH STRATEGY:
    1. Identify 1–3 likely moments from the script.
    2. Compare them visually.
    3. Select the clearest and most usable moment.

    CLIP QUALITY RULES (CRITICAL):
    - The selected moment MUST allow at least 5 full seconds of usable footage.
    - Avoid picking moments too close to the end of the video.
    - Avoid intros, outros, fade-ins, fade-outs, and transitions.
    - Prefer moments in the middle of a scene (not scene boundaries).

    AVOID THESE RANGES:
    - First 3 seconds of the video (likely intro)
    - Last 8 seconds of the video (likely outro)
    - Only use these ranges if absolutely necessary.

    MATCHING RULES:
    - Focus primarily on visual similarity.
    - If multiple matches exist, pick the most visually clear one.
    - If no exact match exists, return the closest relevant moment.
    - Only return start=0 if the video is completely unrelated.

    TIMESTAMP RULES (CRITICAL):
    - All timestamps must be in SECONDS only.
    - Do NOT use minutes or mm:ss format.
    - NEVER output values like 1.30 or 2.10.
    - Convert properly:
      - 1 minute 30 seconds = 90.0
      - 2 minutes 10 seconds = 130.0

    BOUNDARY RULE:
    - Ensure: start + 5 <= {video_duration}
    - If the best moment is too close to the end(- 15 seconds), shift the start earlier to allow a 20-30 seconds.

    OUTPUT RULES:
    - Output ONLY valid JSON.
    - Do NOT include any explanation or text.
    - JSON must be the ONLY output.

    OUTPUT FORMAT:
    {{ "start": float, "end": float }}

    - end = start + 5
    - start must be within [0, {video_duration}]
    """

    attempt = 0
    while True:
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[uploaded_file, prompt]
            )
            break
        except Exception as e:
            if "503" in str(e):
                attempt += 1
                print(f"⚠️ Gemini 503, retrying in 20s... (attempt {attempt})")
                time.sleep(20)
            else:
                raise

    try:
        text = response.text
        if not text and response.candidates:
            text = response.candidates[0].content.parts[0].text

        if not text:
            raise ValueError("Empty response from Gemini")

        text = text.strip()

    except Exception as e:
        print("Gemini response error:", e)
        print("Full response:", response)
        return None
    print("Raw model output:", text)

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
        MUSIC_PROMPT = data.get('music_prompt', 'calm ambient cinematic instrumental music')
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

            if evaluation and evaluation.get("decision") == "post" or evaluation.get("decision") == "revise":
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

        scene = find_scene_with_gemini(original_video, data.get("twelvelabs_query"), SCRIPT_TEXT)
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
        print(f"🎵 Generating music with ElevenLabs...")
        music_path = generate_music(MUSIC_PROMPT)
        if not music_path:
            print("⚠️ Music generation failed, continuing without music.")

        # 5️⃣ VOICE
        print(f"🗣️ Generating voice ({VOICE_NAME})...")
        audio_filename = f"narration_{random.randint(1000, 9999)}.mp3"
        audio_path = generate_voice(SCRIPT_TEXT, audio_filename, VOICE_NAME, LANGUAGE)

        # 6️⃣ SUBTITLES
        print(f"📝 Generating word-level subtitles...")
        if LANGUAGE == "es":
            print("🇪🇸 Spanish detected — skipping subtitles.")
            words_data = None
        else:
            words_data = transcribe_audio_to_words(audio_path, LANGUAGE)

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
            words_data=words_data,
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
