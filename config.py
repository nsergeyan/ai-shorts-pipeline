import os

# LLM model (llama3.1:8b recommended)
OLLAMA_MODEL = "llama3.1:8b"

# Download FULL videos so we can pick random segments
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