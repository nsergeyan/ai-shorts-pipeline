import os
from dotenv import load_dotenv

load_dotenv()


#max shorts length for video
VIDEO_LENGTH_SEC = 60

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
VIDEO_MATERIAL_DIR = os.path.join(DATA_DIR, "video_material")
MUSIC_DIR = os.path.join(DATA_DIR, "music")
FINAL_DIR = os.path.join(DATA_DIR, "final")
AUDIO_DIR = os.path.join(DATA_DIR, "audio")
THUMBNAIL_DIR = os.path.join(DATA_DIR, "thumbnails")

for d in [VIDEO_MATERIAL_DIR, MUSIC_DIR, FINAL_DIR, AUDIO_DIR, THUMBNAIL_DIR]:
    os.makedirs(d, exist_ok=True)

CTA_PATH = os.path.join(BASE_DIR, "Green_Screen_Footage_for_Follow_Button_Boost_Your_Video_Engagement_1080P.mp4")

# API Keys — set these in a .env file (see .env.example)
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")

# Gemini  key rotation
_gemini_raw = os.getenv("GEMINI_API_KEYS", os.getenv("GEMINI_API_KEY", ""))
GEMINI_API_KEYS = [k.strip() for k in _gemini_raw.split(",") if k.strip()]
GEMINI_API_KEY = GEMINI_API_KEYS[0] if GEMINI_API_KEYS else ""