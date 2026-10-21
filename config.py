import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
VIDEO_MATERIAL_DIR = os.path.join(DATA_DIR, "video_material")
MUSIC_DIR = os.path.join(DATA_DIR, "music")
FINAL_DIR = os.path.join(DATA_DIR, "final")
AUDIO_DIR = os.path.join(DATA_DIR, "audio")
THUMBNAIL_DIR = os.path.join(DATA_DIR, "thumbnails")

for d in [VIDEO_MATERIAL_DIR, MUSIC_DIR, FINAL_DIR, AUDIO_DIR, THUMBNAIL_DIR]:
    os.makedirs(d, exist_ok=True)

# Per-channel look and voice (channels/<name>.json), picked by MANUAL_DATA["channel"]
CHANNELS_DIR = os.path.join(BASE_DIR, "channels")

CTA_PATH = os.path.join(BASE_DIR, "Green_Screen_Footage_for_Follow_Button_Boost_Your_Video_Engagement_1080P.mp4")

# API keys: set these in a .env file (see .env.example)
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")

# Comma-separated list, rotated on quota errors. GEMINI_API_KEY (singular) also works.
_gemini_raw = os.getenv("GEMINI_API_KEYS", os.getenv("GEMINI_API_KEY", ""))
GEMINI_API_KEYS = [k.strip() for k in _gemini_raw.split(",") if k.strip()]

# --- Tagged sound effects (ported from animationer) --------------------------
# One folder per tag under SFX_LIBRARY_DIR. The folder names ARE the allowed
# tags, and the code picks the file inside a folder, never the script. The
# script names a tag with *word:tag*. Plain *word* keeps the old punch sounds,
# and the cut whooshes/flash stay in data/sfx.
#
# Two kinds, and the KIND fixes the timing:
#   picture  plays on the tagged word, under the voice. Sounds that belong to
#            a thing on screen.
#   after    plays after the sentence, in a pause spliced into the narration,
#            so it never covers a word. Reactions to what was just said.
#
# Files are played as they are, so they must be TRIMMED (start at -50 dB, end
# at -60 dB so bell decays survive). Folders starting with _ or . are ignored.
SFX_ENABLED = True
SFX_LIBRARY_DIR = os.path.join(DATA_DIR, "sfx_library")
SFX_PICTURE_TAGS = ("pop", "hit", "boom", "suspense", "fight", "money",
                    "correct", "wrong", "celebrate", "join", "leave")
SFX_AFTER_TAGS = ("shock", "sad", "dumb", "awkward", "sus", "meme")

# Limits, so the sounds stay punctuation and do not turn into a laugh track.
# Scaled down from animationer's 3-minute videos to a 45-60s Short. Going over
# SFX_MAX_TAGGED, SFX_MAX_AFTER or SFX_MAX_RARE stops the run before any
# download or API call; fewer than SFX_MIN_TAGGED and the spacing only warn.
# Cuts are not tagged: the code puts a whoosh or flash on every cut itself.
SFX_MIN_TAGGED = 2                 # tagged sounds per video, both kinds
SFX_MAX_TAGGED = 4
SFX_MAX_AFTER = 2                  # "after" reactions per video
SFX_RARE_TAGS = ("meme", "sus")    # work because they are rare
SFX_MAX_RARE = 1
SFX_MIN_AFTER_GAP_SECONDS = 10.0   # between two reactions

# Timing, in seconds.
SFX_AFTER_GAP = 0.15               # silence between the last word and a reaction
SFX_MAX_SECONDS = 2.5              # longer sounds are cut, with a fade (Angel is 18s)
SFX_FADE_SECONDS = 0.3

# Sounds with a human voice in them. They always play after the line, in a
# pause, whatever their tag: a voice on top of the narrator is mush.
SFX_VOICE_FILES = ("Nope sound effect.mp3", "YEET - Sound Effect HD.mp3")

# The music dips by this much while a tagged effect plays, ramping over
# SFX_DUCK_RAMP_SECONDS each side, so the bed never buries the effect.
SFX_MUSIC_DUCK_DB = 8.0
SFX_DUCK_RAMP_SECONDS = 0.15

# How far below the narration each kind sits, in dB, measured against the
# sound's loudest moment (ebur128 momentary max) so a 0.3s click and a 2s
# crowd land comparably. First guess, tune by ear: raise a number to push
# that kind back, lower it to bring it forward.
SFX_UNDER_DB = {"picture": 6.0, "after": 1.0}
