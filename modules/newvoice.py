import os
import re
import subprocess
from elevenlabs.client import ElevenLabs
from config import DATA_DIR, ELEVENLABS_API_KEY

AUDIO_DIR = os.path.join(DATA_DIR, "audio")
os.makedirs(AUDIO_DIR, exist_ok=True)

ELEVENLABS_API_KEYS = [ELEVENLABS_API_KEY] if ELEVENLABS_API_KEY else []

if not ELEVENLABS_API_KEYS:
    raise RuntimeError("ELEVENLABS_API_KEY is not set. Add it to your .env file.")

VOICES = {
    "hamid": "yr43K8H5LoTp6S1QFSGg",
    "Molodoy": "YjESejviApN7SHrbfnA2",
    "spanish_guy": "nR2KQXVwn2zMK8FALNCh",
}


def clean_text_for_speech(text: str) -> str:
    """Normalize whitespace and line breaks before sending text to ElevenLabs."""
    text = text.replace("\n", " ").replace("\r", " ")
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def change_audio_speed(input_path: str, output_path: str, speed: float = 1.1):
    """Use FFmpeg atempo filter to change the playback speed of an audio file."""
    subprocess.run([
        "ffmpeg",
        "-y",
        "-i", input_path,
        "-filter:a", f"atempo={speed}",
        output_path
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _try_generate_with_key(
        api_key: str,
        script_text: str,
        output_path: str,
        voice_id: str,
        lang: str
) -> bool:
    """Attempt to generate TTS audio with a single ElevenLabs API key. Returns True on success."""
    client = ElevenLabs(api_key=api_key)
    print(f"🔑 Using key: {api_key[:6]}... for Language: {lang.upper()}")

    tmp_path = output_path + ".partial"
    final_fast_path = output_path.replace(".mp3", "_fast.mp3")

    if lang in ["ru", "es"]:
        model_id = "eleven_multilingual_v2"
        voice_settings = {
            "stability": 0.7,
            "similarity_boost": 0.8,
            "style": 0.2,
            "use_speaker_boost": True,
        }
    else:
        model_id = "eleven_v3"
        voice_settings = {
            "stability": 0.9
        }

    try:
        cleaned_text = clean_text_for_speech(script_text)

        audio_stream = client.text_to_speech.convert(
            text=cleaned_text,
            voice_id=voice_id,
            model_id=model_id,
            voice_settings=voice_settings,
            output_format="mp3_44100_128"
        )

        with open(tmp_path, "wb") as f:
            for chunk in audio_stream:
                f.write(chunk)

        os.replace(tmp_path, output_path)

        change_audio_speed(output_path, final_fast_path, speed=1.1)
        os.replace(final_fast_path, output_path)

        print(f"⚡ FAST version ready → {output_path}")
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
        lang: str = "en"
) -> str:
    """Generate narration audio via ElevenLabs and save to AUDIO_DIR. Raises if all keys fail."""
    output_path = os.path.join(AUDIO_DIR, filename)
    voice_id = VOICES.get(voice, VOICES["hamid"])

    print(f"🎙️ Generating voice '{voice}' ({lang})...")

    for api_key in ELEVENLABS_API_KEYS:
        if _try_generate_with_key(
            api_key=api_key,
            script_text=script_text,
            output_path=output_path,
            voice_id=voice_id,
            lang=lang
        ):
            return output_path

        print("⏭️ Switching key...")

    raise RuntimeError("All ElevenLabs keys failed.")


if __name__ == "__main__":
    print("🧪 Starting High-Speed V3 Test...\n")

    test_script ="[disgusted] Have you ever looked closely at Caine from The Amazing Digital Circus? [leans in] He is literally just a floating mouth with eyes inside. Naturally, you would think his teeth are made of hard bone, like a normal skeleton. [dramatic pause] But the creator revealed a secret that makes him incredibly creepy. Gooseworx confirmed that Caine’s teeth are actually soft and squishy. They feel just like marshmallows. [shuddering] If you touch his teeth, they bend. Which is kind of wild, right? Imagine a giant mouth made of soft jelly grabbing you. [curiously] What other terrifying secrets is the circus hiding?"


    try:
        for i in range(1, 3):
            path = generate_voice(
                script_text=test_script,
                filename=f"test_option_{i}.mp3",
                voice="hamid",
                lang="en"
            )
            print(f"🎧 Option {i} ready: {path}")

    except Exception as e:
        print(f"❌ Test Failed: {e}")