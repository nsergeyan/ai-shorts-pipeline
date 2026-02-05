import os
import random
import sys
import uuid
import subprocess

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

# --- TwelveLabs ---
from twelvelabs import TwelveLabs
from twelvelabs.indexes import IndexesCreateRequestModelsItem

# ---------------- CONFIG ---------------- #
API_KEY = "tlk_10XHM2C2H2GGKR2WKS0JP3J4G4WY"
LANGUAGE = "en"
MUSIC_VOLUME = 0.02
SUBTITLES_POSITION = "top"
CLEANUP_FILES = True
CLIP_DURATION = 60.0  # seconds for TwelveLabs-trimmed scene
MODEL_NAME = "marengo3.0"
MODEL_OPTIONS = ["visual", "audio"]
SLEEP_INTERVAL = 5
# ---------------------------------------- #

# PASTE YOUR JSON HERE
MANUAL_DATA = {
"topic": "JJK Hidden Details",
"specific_subject": "The Junpei Opening Trick",
"youtube_queries": [
"Jujutsu Kaisen Season 1 Opening 1 Junpei scene",
"Junpei Yoshino death scene Yuji reaction",
"Yuji and Junpei school roof scene"
],
"twelvelabs_query": "Junpei Yoshino in Jujutsu High uniform smiling in the opening",
"music_mood": "Sad and emotional piano JJK OST",
"voice_name": "Hamid",
"script": "Have you ever felt betrayed by an anime opening? In the first season of JJK, we see Junpei Yoshino wearing a Jujutsu High uniform. He is standing with Yuji and the others, looking happy. Most fans thought he would join the team and become a main character. But here is the crazy part: Gege Akutami did this on purpose to trick us! Junpei never actually joins the school. He dies shortly after meeting Yuji. The animators literally lied to us just to make the tragedy hurt even more. That is pure evil! Follow for more."
}


def trim_video_flexible(input_file, output_file, ai_start, ai_end, narration_duration, prepad=3.0, max_clip_duration=60.0):
    """
    Trims video to include the AI-found scene, with optional prepad before start,
    but ensures clip fits narration duration and does not exceed max_clip_duration.
    """
    clip_start = max(ai_start - prepad, 0.0)
    clip_end = min(ai_end, clip_start + max_clip_duration, clip_start + narration_duration)
    clip_duration = clip_end - clip_start

    subprocess.run([
        "ffmpeg",
        "-i", input_file,
        "-ss", str(clip_start),
        "-t", str(clip_duration),
        "-c", "copy",
        output_file
    ], check=True)

    return clip_start, clip_end


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

        # 2️⃣ VISUALS - Download first video from YouTube
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
        original_video = video_paths[0]

        # 3️⃣ Use TwelveLabs to find scene
        print(f"🤖 Uploading video to TwelveLabs for scene search...")
        client = TwelveLabs(api_key=API_KEY)
        index_name = f"manual_index_{uuid.uuid4().hex[:6]}"
        index = client.indexes.create(
            index_name=index_name,
            models=[IndexesCreateRequestModelsItem(model_name=MODEL_NAME, model_options=MODEL_OPTIONS)]
        )
        with open(original_video, "rb") as f:
            task = client.tasks.create(index_id=index.id, video_file=f)
        client.tasks.wait_for_done(task.id, sleep_interval=SLEEP_INTERVAL)

        # Query the scene
        results = client.search.query(
            index_id=index.id,
            query_text=data.get("twelvelabs_query"),
            search_options=MODEL_OPTIONS
        )
        # After TwelveLabs scene is found:
        results_list = list(results)
        if not results_list:
            print("⚠️ No scene found in video. Using full video instead.")
            trimmed_video = original_video
        else:
            match = results_list[0]
            # Go 3 seconds earlier if possible
            start_time = max(match.start - 3, 0.0)
            # Clip end = either max 90s or original video end
            import ffmpeg
            video_duration = float(ffmpeg.probe(original_video)['format']['duration'])
            end_time = min(start_time + 90.0, video_duration)
            duration = end_time - start_time

            print(f"✅ Scene found: start={match.start:.2f}s, using clip {start_time:.2f}-{end_time:.2f}s")

            trimmed_video = f"trimmed_scene_{uuid.uuid4().hex[:6]}.mp4"
            subprocess.run([
                "ffmpeg",
                "-i", original_video,
                "-ss", str(start_time),
                "-t", str(duration),
                "-c", "copy",
                trimmed_video
            ], check=True)
            print(f"🎬 Trimmed clip saved as: {trimmed_video}")

        # 4️⃣ MUSIC
        print(f"🎵 Fetching music...")
        music_path = fetch_random_music(search_query=MUSIC_QUERY)

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
