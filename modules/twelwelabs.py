import subprocess
import uuid
from twelvelabs import TwelveLabs
from twelvelabs.indexes import IndexesCreateRequestModelsItem

# ---------------- CONFIG ---------------- #
API_KEY = "tlk_10XHM2C2H2GGKR2WKS0JP3J4G4WY"
VIDEO_PATH = "/Users/nareksergeyan/YOutuber/data/gameplay/YTDown.com_YouTube_Jujutsu-Kaisen-Gojo-Satoru-cute-funny-mo_Media_bTh-98ITp_E_001_720p.mp4"
QUERY_TEXT = "gojo satoru with food"
CLIP_DURATION = 40.0  # seconds
OUTPUT_FILE = "gojofoodclip.mp4"
MODEL_NAME = "marengo3.0"          # valid TwelveLabs model
MODEL_OPTIONS = ["visual", "audio"] # valid options for marengo3.0
SLEEP_INTERVAL = 5                 # seconds while waiting for indexing
# ---------------------------------------- #

def main():
    # 1️⃣ Initialize client
    client = TwelveLabs(api_key=API_KEY)
    print("✅ Initialized TwelveLabs client")

    # 2️⃣ Create a unique index name to avoid conflicts
    index_name = f"murder_drones_index_{uuid.uuid4().hex[:6]}"
    index = client.indexes.create(
        index_name=index_name,
        models=[
            IndexesCreateRequestModelsItem(
                model_name=MODEL_NAME,
                model_options=MODEL_OPTIONS
            )
        ]
    )
    print("✅ Created index:", index.id)

    # 3️⃣ Upload video
    with open(VIDEO_PATH, "rb") as vid_file:
        task = client.tasks.create(
            index_id=index.id,
            video_file=vid_file
        )

    print("⏳ Upload task started, video ID:", task.video_id)

    # 4️⃣ Wait for indexing to complete
    task_status = client.tasks.wait_for_done(
        task_id=task.id,
        sleep_interval=SLEEP_INTERVAL
    )
    print("✅ Indexing done:", task_status.status)

    # 5️⃣ Search for scene
    results = client.search.query(
        index_id=index.id,
        query_text=QUERY_TEXT,
        search_options=MODEL_OPTIONS
    )

    results_list = list(results)  # Convert SyncPager to list

    if not results_list:
        print("⚠️ No results found for query:", QUERY_TEXT)
        return

    # Use first result
    match = results_list[0]
    start_time = match.start
    print(f"✅ Found scene: start={start_time:.2f}s end={match.end:.2f}s score={match.score}")

    # 6️⃣ Cut clip with ffmpeg
    subprocess.run([
        "ffmpeg",
        "-i", VIDEO_PATH,
        "-ss", str(start_time),
        "-t", str(CLIP_DURATION),
        "-c", "copy",
        OUTPUT_FILE
    ], check=True)

    print(f"🎬 Clip saved as: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()