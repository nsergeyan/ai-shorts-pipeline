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
    from modules.newvoice import generate_voice
    from modules.video_editor import merge_audio_video
    from modules.transcriber import transcribe_audio_to_groups
except ImportError as e:
    print(f"Error importing modules: {e}")
    sys.exit(1)
# ---------------- CONFIG ---------------- #
API_KEY = "tlk_10XHM2C2H2GGKR2WKS0JP3J4G4WY"
LANGUAGE = "en"
MUSIC_VOLUME = 0.03
SUBTITLES_POSITION = "top"
CLEANUP_FILES = True
CLIP_DURATION = 60.0
MODEL_OPTIONS = ["visual", "audio"]
SLEEP_INTERVAL = 5
# ---------------------------------------- #

MANUAL_DATA = {
"topic": "Attack on Titan",
"specific_subject": "Levi Ackerman's severe insomnia",
"youtube_queries": [
"Levi Ackerman season three part one Attack on Titan"
],
"twelvelabs_query": "Close up of Levi Ackerman looking extremely tired and annoyed while sitting indoors.",
"music_mood": "melancholy acoustic anime instrumental no lyrics",
"voice_name": "Hamid",
"script": "[excitedly] Did you know humanity's strongest soldier has a terrible secret about his health? [pauses] We know Levi Ackerman is flawless in combat. But the creator revealed a really sad detail about his daily life. [whispering] Levi actually suffers from severe insomnia. He only sleeps for two to three hours a day! [sighs] And it gets worse. He does not even sleep in a normal bed. He just sits in a chair and sleeps in his daily clothes. Which is kind of wild. Imagine fighting giant monsters all day on a tiny chair nap. [playfully] Follow for more secrets!"
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
    You are acting as a short-form video content reviewer.

    Your job is to evaluate how well the VIDEO matches the SCRIPT excerpt.

    IMPORTANT GUIDELINES:
    - Judge ONLY what is visually or audibly present in the clip.
    - Do NOT invent events that are not shown.
    - HOWEVER, you MAY give partial credit if the visuals clearly support the script's topic, characters, objects, or situation.
    - Do NOT be overly strict about literal action matching. Contextual relevance is acceptable.
    - Be fair and balanced when scoring.

    SCRIPT EXCERPT:
    \"\"\"{script_text}\"\"\"

    SCORING CRITERIA:

    1. Visual–Script Alignment (relevance_score: 1–10)
       Evaluate how well the visuals support the meaning or context of the script.

       9–10: Visuals clearly depict or strongly support the script
       7–8 : Visuals are contextually relevant but not exact
       5–6 : Partially related elements present
       3–4 : Weak or indirect connection
       1–2 : No meaningful relation

    2. First 2-Second Hook (hook_score: 1–10)
       Evaluate whether the opening is visually or audibly engaging enough to stop scrolling.

       Consider:
       - Motion
       - Visual intensity
       - Curiosity
       - Audio impact
       - Emotional trigger

    3. Technical Quality (technical_score: 1–10)
       Evaluate production quality:
       - Animation smoothness
       - Editing and pacing
       - Audio clarity
       - Visual effects quality

    DECISION RULES:

    - "post"
      relevance_score >= 6 AND hook_score >= 7 AND technical_score >= 8

    - "reject"
      Visuals are largely unrelated OR technical quality is very poor.
    OUTPUT FORMAT:
    Respond ONLY with valid JSON. No explanation.

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
    You are performing precise visual scene matching in a video timeline.

    VIDEO METADATA
    - Total video duration: {video_duration} seconds
    - The returned timestamps MUST stay within this duration.

    USER DESCRIPTION
    "{query}"

    VIDEO SCRIPT
    "{script}"

    TASK
    Scan the entire video and identify the segment that best visually matches the user description.

    MATCHING RULES
    1. Focus primarily on VISUAL similarity.
    2. Consider:
       - foreground actions
       - background activity
       - small movements
       - brief appearances
    3. Even if the element appears briefly or in the background, it can still be a valid match.
    4. If multiple matches exist, return the segment with the STRONGEST visual correspondence.
    5. Return a tight segment around the best match.

    FALLBACK RULE
    If the visual element described in "{query}" cannot be found:
    - Use the SCRIPT to estimate the most likely visual moment.
    - If the script also provides no reasonable hint, return:
      {{ "start": 0, "end": 0 }}

    TIMESTAMP RULES
    - Use float seconds relative to the full video timeline.
    - start and end MUST be numeric floats.
    - start MUST be >= 0
    - end MUST be <= {video_duration}
    - end MUST be greater than start
    - DO NOT use MM:SS format.
    - DO NOT use strings.
    - DO NOT include quotes around numbers.

    VALID EXAMPLE
    {{ "start": 257.0, "end": 259.5 }}

    INVALID EXAMPLES
    {{ "start": 4:17, "end": 4:18 }}
    {{ "start": "4:17", "end": "4:18" }}
    {{ "start": "257", "end": "259" }}

    OUTPUT RULES
    Return ONLY valid JSON.
    No markdown.
    No explanation.
    No additional text.

    FORMAT
    {{ "start": <seconds>, "end": <seconds> }}

    If no confident match exists:
    {{ "start": 0, "end": 0 }}
    """

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[uploaded_file, prompt]
    )

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
        print(f"🎵 Fetching music...")
        music_attempts = 0
        max_music_attempts = 3
        music_path = None

        while music_attempts < max_music_attempts:
            music_results = fetch_music_by_search(
                queries=[MUSIC_QUERY],
                max_tracks=1
            )

            if not music_results:
                print("❌ No music found.")
                break

            candidate_music = music_results[0]
            music_attempts += 1

            print(f"🎧 Evaluating music attempt {music_attempts}...")

            music_eval = evaluate_music_with_genai(candidate_music, SCRIPT_TEXT)

            if music_eval["decision"] in ["post", "revise"]:
                print("✅ Music approved!")
                music_path = candidate_music
                break
            else:
                print("❌ Music rejected, retrying...")

        if not music_path:
            print("⚠️ No good music found, continuing without music.")

        # 5️⃣ VOICE
        print(f"🗣️ Generating voice ({VOICE_NAME})...")
        audio_filename = f"narration_{random.randint(1000, 9999)}.mp3"
        audio_path = generate_voice(SCRIPT_TEXT, audio_filename, VOICE_NAME, LANGUAGE)

        # 6️⃣ SUBTITLES
        print(f"📝 Generating subtitles...")
        if LANGUAGE == "es":
            print("🇪🇸 Spanish detected — skipping subtitles.")
            subtitle_data = None
        else:
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
