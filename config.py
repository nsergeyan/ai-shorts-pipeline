import os
from dotenv import load_dotenv

load_dotenv()

OLLAMA_MODEL = "gemma2:27b"

#max shorts lenght for video
VIDEO_LENGTH_SEC = 60

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
GAMEPLAY_DIR = os.path.join(DATA_DIR, "gameplay")
MUSIC_DIR = os.path.join(DATA_DIR, "music")
FINAL_DIR = os.path.join(DATA_DIR, "final")
AUDIO_DIR = os.path.join(DATA_DIR, "audio")

for d in [GAMEPLAY_DIR, MUSIC_DIR, FINAL_DIR, AUDIO_DIR]:
    os.makedirs(d, exist_ok=True)

# API Keys — set these in a .env file (see .env.example)
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")

# Gemini  key rotation
_gemini_raw = os.getenv("GEMINI_API_KEYS", os.getenv("GEMINI_API_KEY", ""))
GEMINI_API_KEYS = [k.strip() for k in _gemini_raw.split(",") if k.strip()]
GEMINI_API_KEY = GEMINI_API_KEYS[0] if GEMINI_API_KEYS else ""