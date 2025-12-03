import os

OLLAMA_MODEL = "qwen2.5:14b"

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