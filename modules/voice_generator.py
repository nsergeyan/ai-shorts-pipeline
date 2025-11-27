# modules/voice_generator.py
import os
from elevenlabs import ElevenLabs
from config import DATA_DIR

AUDIO_DIR = os.path.join(DATA_DIR, "audio")
os.makedirs(AUDIO_DIR, exist_ok=True)

# ------------------------------------------------------------
# MULTI-KEY SUPPORT (NO ENV VARS)
# ------------------------------------------------------------

# Put ALL your ElevenLabs API keys here, in priority order.
ELEVENLABS_API_KEYS = [
    "sk_1fb956bf6e7460a0335243fd9853a31e80aef1ae2d8fb6f5",
    "sk_5afd3099309442d3c90105eff526b87e715bbbd3c4097669",
    "sk_ad89ecd4f4c8344b204aaf03f52eaf2dfce346bfab650438"
]

if not ELEVENLABS_API_KEYS:
    raise RuntimeError("No ElevenLabs API keys configured in ELEVENLABS_API_KEYS.")

# PRE-MADE VOICES (no limit, free to use)
VOICES = {
    "hamid": "yr43K8H5LoTp6S1QFSGg",   # NAME IS MAT
}

# Tuned for TikTok-style narration: energetic but still natural
DEFAULT_VOICE_SETTINGS = {
    "stability": 0.45,        # a bit more stable = fewer weird artifacts
    "similarity_boost": 0.85,  # clearer, closer to original voice
    "style": 0.9,             # more expressive / energetic
    "use_speaker_boost": True
}


def _try_generate_with_key(
    api_key: str,
    script_text: str,
    output_path: str,
    voice_id: str,
    voice_settings: dict
) -> bool:
    """
    Try generating audio with a single API key.
    Returns True on success, False on failure.
    """
    client = ElevenLabs(api_key=api_key)
    print(f"🔑 Trying ElevenLabs key: {api_key[:8]}...")

    tmp_path = output_path + ".partial"

    try:
        audio_stream = client.text_to_speech.convert(
            text=script_text.strip(),          # avoid leading/trailing whitespace
            voice_id=voice_id,
            model_id="eleven_turbo_v2_5",
            voice_settings=voice_settings,
            # Lower initial latency; doesn't change pacing inside speech, but
            # reduces "dead air" at the start of the clip.
            optimize_streaming_latency="3",
        )

        # Write to temp file first; only rename on full success
        with open(tmp_path, "wb") as f:
            for chunk in audio_stream:
                f.write(chunk)

        os.replace(tmp_path, output_path)
        print(f"✅ Success with key {api_key[:8]}..., saved → {output_path}")
        return True

    except Exception as e:
        # Clean up partial on error
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        print(f"⚠️ ElevenLabs error with key {api_key[:8]}...: {e}")
        return False


def generate_voice(
    script_text: str,
    filename: str = "narration.mp3",
    voice: str = "hamid",
    voice_settings: dict | None = None
) -> str:

    output_path = os.path.join(AUDIO_DIR, filename)
    voice_id = VOICES.get(voice, VOICES["hamid"])

    effective_settings = {**DEFAULT_VOICE_SETTINGS, **(voice_settings or {})}

    print(f"🎙️ Generating with '{voice}' voice...")

    # Try each key in order until one works
    for api_key in ELEVENLABS_API_KEYS:
        ok = _try_generate_with_key(
            api_key=api_key,
            script_text=script_text,
            output_path=output_path,
            voice_id=voice_id,
            voice_settings=effective_settings,
        )
        if ok:
            return output_path

        print("⏭️ Switching to next ElevenLabs key...")

    # If all keys failed:
    raise RuntimeError("All ElevenLabs API keys failed. Check quotas and validity.")


if __name__ == "__main__":
    # Example test
    test_script = (
        "Yo Leo, what's good my brother from Moldova? "
        "You're an absolute legend, and you know it. "
        "Keep grinding, keep winning, and keep proving everyone wrong. "
        "We gotta link up soon, grab some placinte and a glass of wine, "
        "and talk about the next big move."
    )

    generate_voice(test_script, filename="message_for_leo.mp3", voice="hamid")