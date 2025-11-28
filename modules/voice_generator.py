import os
from elevenlabs import ElevenLabs
from config import DATA_DIR

AUDIO_DIR = os.path.join(DATA_DIR, "audio")
os.makedirs(AUDIO_DIR, exist_ok=True)

# ------------------------------------------------------------
# 🔑 ELEVENLABS CONFIG (PUT YOUR KEYS HERE)
# ------------------------------------------------------------
ELEVENLABS_API_KEYS = [
    "sk_1fb956bf6e7460a0335243fd9853a31e80aef1ae2d8fb6f5",
    "sk_5afd3099309442d3c90105eff526b87e715bbbd3c4097669",
    # Add fresh keys here if previous ones are banned/empty
]

if not ELEVENLABS_API_KEYS:
    raise RuntimeError("No ElevenLabs API keys configured!")


# ------------------------------------------------------------

def _try_generate(api_key, text, output_path, voice_id):
    """Attempts generation with one specific key."""
    print(f"🔑 Trying key: {api_key[:8]}...")
    client = ElevenLabs(api_key=api_key)

    try:
        audio_stream = client.text_to_speech.convert(
            text=text,
            voice_id=voice_id,
            # Multilingual v2 or Turbo v2.5 MUST be used for Russian
            model_id="eleven_multilingual_v2",
            output_format="mp3_44100_128",
            voice_settings={
                "stability": 0.40,
                "similarity_boost": 0.80,
                "style": 0.5,
                "use_speaker_boost": True
            }
        )

        with open(output_path, "wb") as f:
            for chunk in audio_stream:
                f.write(chunk)

        return True
    except Exception as e:
        print(f"⚠️ Key failed: {e}")
        return False


def generate_voice(script_text: str, filename: str, voice_id: str) -> str:
    output_path = os.path.join(AUDIO_DIR, filename)

    # Loop through keys until one works
    for key in ELEVENLABS_API_KEYS:
        if _try_generate(key, script_text, output_path, voice_id):
            print(f"✅ Saved -> {output_path}")
            return output_path

    raise RuntimeError("❌ All ElevenLabs keys failed (Quota exceeded or Banned).")