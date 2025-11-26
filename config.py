# config.py
import os

# LLM model
OLLAMA_MODEL = "gpt-oss:latest"
DEFAULT_GAME = "ARC Raiders"

# How many seconds from each downloaded video to keep
VIDEO_LENGTH_SEC = 60  # set 0 or None to download full videos

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
GAMEPLAY_DIR = os.path.join(DATA_DIR, "gameplay")
os.makedirs(GAMEPLAY_DIR, exist_ok=True)

MUSIC_DIR = os.path.join(DATA_DIR, "music")
os.makedirs(MUSIC_DIR, exist_ok=True)