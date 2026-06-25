import os
import re
import subprocess
from elevenlabs.client import ElevenLabs
from elevenlabs.types import DialogueInput
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

    try:
        cleaned_text = clean_text_for_speech(script_text)

        if lang in ["ru", "es"]:
            audio_stream = client.text_to_speech.convert(
                text=cleaned_text,
                voice_id=voice_id,
                model_id="eleven_multilingual_v2",
                output_format="mp3_44100_192",
            )
        else:
            audio_stream = client.text_to_dialogue.convert(
                inputs=[DialogueInput(text=cleaned_text, voice_id=voice_id)],
                output_format="mp3_44100_192",
            )

        with open(tmp_path, "wb") as f:
            for chunk in audio_stream:
                f.write(chunk)

        os.replace(tmp_path, output_path)

        # Speed up 1.2x via FFmpeg atempo
        sped_path = output_path + ".fast.mp3"
        subprocess.run(
            ["ffmpeg", "-y", "-i", output_path, "-filter:a", "atempo=1.2", sped_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True
        )
        os.replace(sped_path, output_path)

        print(f"✅ Voice ready → {output_path}")
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

    test_script ="Have you ever wondered what Sukuna's cursed fingers actually taste like? They look like dry, old meat, but the real answer is much stranger. [surprised] According to the official fanbook, these fingers taste exactly like soap! Yes, you heard that right. They are covered in grave wax, which smells and tastes just like household soap. [curious] This means when Yuji swallows one, his mouth gets squeaky clean, even if the curse is deadly. [laughs] It is so weird because they look like rotten beef jerky. [chuckles] Would you eat a soapy finger to gain absolute power? Tell me below!"
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