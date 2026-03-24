import os
import re
from elevenlabs import ElevenLabs
from config import DATA_DIR

AUDIO_DIR = os.path.join(DATA_DIR, "audio")
os.makedirs(AUDIO_DIR, exist_ok=True)

ELEVENLABS_API_KEYS = [
    "sk_c8339c458c9b24371a53c7d5636f139359c30f8b661796a7"
]

if not ELEVENLABS_API_KEYS:
    raise RuntimeError("No ElevenLabs API keys configured.")

VOICES = {
    "hamid": "yr43K8H5LoTp6S1QFSGg",
    "Molodoy": "YjESejviApN7SHrbfnA2",
    "spanish_guy": "nR2KQXVwn2zMK8FALNCh",
}


def clean_text_for_speech(text: str) -> str:
    """Removes newlines to prevent awkward pauses in both languages."""
    text = text.replace("\n", " ").replace("\r", " ")
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _try_generate_with_key(
        api_key: str,
        script_text: str,
        output_path: str,
        voice_id: str,
        lang: str
) -> bool:
    client = ElevenLabs(api_key=api_key)
    print(f"🔑 Using key: {api_key[:8]}... for Language: {lang.upper()}")

    tmp_path = output_path + ".partial"

    # --- DYNAMIC SETTINGS BASED ON LANGUAGE ---
    if lang == "ru":
        # RUSSIAN SETTINGS
        model_id = "eleven_multilingual_v2"
        voice_settings = {
            "stability": 0.75,
            "similarity_boost": 0.8,
            "style": 0.3,
            "use_speaker_boost": True,
            "speed": 1.07
        }
        latency_opt = "1"

    elif lang == "es":
        # SPANISH SETTINGS (similar to Russian: slower/higher quality)
        model_id = "eleven_multilingual_v2"
        voice_settings = {
            "stability": 0.7,
            "similarity_boost": 0.75,
            "style": 0.0,
            "use_speaker_boost": True,
            "speed": 0.95
        }
        latency_opt = "1"

    else:
        # DEFAULT TO ENGLISH SETTINGS
        model_id = "eleven_multilingual_v2"
        voice_settings = {
            "stability": 0.75,
            "similarity_boost": 0.8,
            "style": 0.55,
            "use_speaker_boost": True,
        }
        latency_opt = "1"

    try:
        cleaned_text = clean_text_for_speech(script_text)

        audio_stream = client.text_to_speech.convert(
            text=cleaned_text,
            voice_id=voice_id,
            model_id=model_id,
            voice_settings=voice_settings,
            optimize_streaming_latency=latency_opt
        )

        with open(tmp_path, "wb") as f:
            for chunk in audio_stream:
                f.write(chunk)

        os.replace(tmp_path, output_path)
        print(f"✅ Success. Saved → {output_path}")
        return True

    except Exception as e:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        print(f"⚠️ Error: {e}")
        return False


def generate_voice(
        script_text: str,
        filename: str = "narration.mp3",
        voice: str = "hamid",
        lang: str = "en"  # <--- ADDED LANG PARAMETER
) -> str:
    output_path = os.path.join(AUDIO_DIR, filename)
    voice_id = VOICES.get(voice, VOICES["hamid"])

    print(f"🎙️ Generating voice '{voice}' ({lang})...")

    for api_key in ELEVENLABS_API_KEYS:
        ok = _try_generate_with_key(
            api_key=api_key,
            script_text=script_text,
            output_path=output_path,
            voice_id=voice_id,
            lang=lang
        )
        if ok:
            return output_path
        print("⏭️ Switching key...")

    raise RuntimeError("All ElevenLabs keys failed.")



if __name__ == "__main__":
    SUBJECT = "api key test"
    VOICE_NAME = "Molodoy"
    LANGUAGE = "ru"

    script = "Это было."
    audio_filename = f"narration_{SUBJECT.replace(' ', '_')}.mp3"

    print("🧪 Starting ElevenLabs test...\n")

    try:
        audio_path = generate_voice(
            script_text=script,
            filename=audio_filename,
            voice=VOICE_NAME,
            lang=LANGUAGE
        )

        if os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
            print("\n✅ TEST PASSED")
            print(f"🎧 Audio file created: {audio_path}")
        else:
            print("\n❌ TEST FAILED: File missing or empty")

    except Exception as e:
        print("\n❌ TEST FAILED WITH ERROR")
        print(e)