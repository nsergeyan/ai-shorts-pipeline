# modules/voice_generator.py
import os
from elevenlabs import ElevenLabs
from config import DATA_DIR

AUDIO_DIR = os.path.join(DATA_DIR, "audio")
os.makedirs(AUDIO_DIR, exist_ok=True)

ELEVENLABS_API_KEY = "sk_1fb956bf6e7460a0335243fd9853a31e80aef1ae2d8fb6f5" # ← put your real key

# PRE-MADE VOICES (no limit, free to use)
VOICES = {
    "hamid":   "yr43K8H5LoTp6S1QFSGg",   # NAME IS MAT
}

client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

def generate_voice(
    script_text: str,
    filename: str = "narration.mp3",
    voice: str = "hamid"                  # ← using hamid (great for TikTok)
) -> str:

    output_path = os.path.join(AUDIO_DIR, filename)
    voice_id = VOICES.get(voice, VOICES["hamid"])

    print(f"🎙️ Generating with '{voice}' voice...")

    audio = client.text_to_speech.convert(
        text=script_text,
        voice_id=voice_id,
        model_id="eleven_turbo_v2_5",
        voice_settings={
            "stability": 0.25,        # Lower for more emotion/variation
            "similarity_boost": 0.5,  # Higher for clearer voice
            "style": 0.4,            # Higher for more expressive style
            "use_speaker_boost": True
        }
    )

    with open(output_path, "wb") as f:
        for chunk in audio:
            f.write(chunk)

    print(f"✅ Saved → {output_path}")
    return output_path


if __name__ == "__main__":
    # Message for Leo!
    test_script = "Yo Leo! What's good my brother from Moldova? Just wanted to say you're an absolute legend. Keep grinding and making moves out there. We need to link up soon, maybe grab some placinte and wine. Stay solid bro!"

    generate_voice(test_script, filename="message_for_leo.mp3", voice="hamid")