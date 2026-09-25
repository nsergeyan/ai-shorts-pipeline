import os
import re
import subprocess
from elevenlabs.client import ElevenLabs
from elevenlabs.types import DialogueInput, ModelSettingsResponseModel
from config import DATA_DIR, ELEVENLABS_API_KEY

AUDIO_DIR = os.path.join(DATA_DIR, "audio")
os.makedirs(AUDIO_DIR, exist_ok=True)

# The US regional endpoint serves the good eleven_v3 render. The global default
# (api.elevenlabs.io) returns a flat/robotic voice for this account, matching the
# website only when we hit this host. Confirmed by capturing the web app's request.
ELEVENLABS_BASE_URL = "https://api.us.elevenlabs.io"

ELEVENLABS_API_KEYS = [ELEVENLABS_API_KEY] if ELEVENLABS_API_KEY else []

if not ELEVENLABS_API_KEYS:
    raise RuntimeError("ELEVENLABS_API_KEY is not set. Add it to your .env file.")

VOICES = {
    "animatoryoung": "xlnOCsItpCGtYrgUKVqx",
    "hamid": "yr43K8H5LoTp6S1QFSGg",
    "Molodoy": "YjESejviApN7SHrbfnA2",
    "spanish_guy": "nR2KQXVwn2zMK8FALNCh",
}

# Speed boost applied after TTS. Set to 1.0 to disable.
SPEED_MULTIPLIER = 1.1

OUTPUT_FORMAT = "mp3_44100_192"


def _output_bitrate_k() -> int:
    """
    Bitrate for the atempo re-encode, read off the requested output format.

    Without an explicit -b:a, ffmpeg re-encodes at its own default, measured at
    64kbps, silently discarding most of the quality we paid ElevenLabs for.
    """
    tail = OUTPUT_FORMAT.rsplit("_", 1)[-1]
    return int(tail) if tail.isdigit() else 192


def _measured_bitrate_k(path: str) -> int:
    """Actual bitrate of a finished file, in kbps, via ffprobe."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=bit_rate",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True,
    )
    return round(int(out.stdout.strip()) / 1000)


def _verify_bitrate(path: str) -> None:
    """
    Refuse to hand back narration that lost quality on the way out.

    The atempo re-encode silently produced 64kbps for months because ffmpeg
    falls back to its own default when -b:a is missing. Nothing downstream
    notices: the render still succeeds and the final mp4 still reports ~192k,
    because AAC happily re-encodes ruined audio. So the check has to live here,
    on the mp3, right after the last step that can damage it.
    """
    expected = _output_bitrate_k()
    actual = _measured_bitrate_k(path)

    # 20% of slack: mp3 bitrate is an average over frames and lands a little
    # under target on quiet passages. A real regression is a third of target,
    # not a few percent.
    if actual < expected * 0.8:
        raise RuntimeError(
            f"Narration came out at {actual}kbps but should be {expected}kbps "
            f"({path}). Something re-encoded it without -b:a. Refusing to "
            f"continue rather than render a video with degraded audio."
        )

    print(f"🔊 Audio quality OK: {actual}kbps")


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
    client = ElevenLabs(api_key=api_key, base_url=ELEVENLABS_BASE_URL)
    print(f"🔑 Using key: {api_key[:6]}... for Language: {lang.upper()}")

    tmp_path = output_path + ".partial"

    try:
        cleaned_text = clean_text_for_speech(script_text)

        if lang in ["ru", "es"]:
            audio_stream = client.text_to_speech.convert(
                text=cleaned_text,
                voice_id=voice_id,
                model_id="eleven_multilingual_v2",
                output_format=OUTPUT_FORMAT,
            )
        else:
            audio_stream = client.text_to_dialogue.convert(
                inputs=[DialogueInput(text=cleaned_text, voice_id=voice_id)],
                model_id="eleven_v3",
                settings=ModelSettingsResponseModel(stability=0.5),
                output_format=OUTPUT_FORMAT,
            )

        with open(tmp_path, "wb") as f:
            for chunk in audio_stream:
                f.write(chunk)

        os.replace(tmp_path, output_path)

        if SPEED_MULTIPLIER != 1.0:
            sped_path = output_path + ".fast.mp3"
            subprocess.run(
                ["ffmpeg", "-y", "-i", output_path, "-filter:a",
                 f"atempo={SPEED_MULTIPLIER}",
                 "-b:a", f"{_output_bitrate_k()}k", sped_path],
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
        voice: str = "animatoryoung",
        lang: str = "en"
) -> str:
    """Generate narration audio via ElevenLabs and save to AUDIO_DIR. Raises if all keys fail."""
    output_path = os.path.join(AUDIO_DIR, filename)
    voice_lookup = {name.lower(): vid for name, vid in VOICES.items()}
    voice_id = voice_lookup.get(voice.lower(), VOICES["animatoryoung"])

    print(f"🎙️ Generating voice '{voice}' ({lang})...")

    for api_key in ELEVENLABS_API_KEYS:
        if _try_generate_with_key(
            api_key=api_key,
            script_text=script_text,
            output_path=output_path,
            voice_id=voice_id,
            lang=lang
        ):
            # Deliberately outside _try_generate_with_key: a quality failure is
            # not a key failure, so it must not roll over to the next key or be
            # reported as one. It should stop the run and say why.
            _verify_bitrate(output_path)
            return output_path

        print("⏭️ Switching key...")

    raise RuntimeError("All ElevenLabs keys failed.")


if __name__ == "__main__":
    # Speed boost off for the test, so you hear exactly what ElevenLabs sent.
    # Each take also gets a sped-up copy next to it, so you can A/B whether
    # atempo itself is what makes the voice sound bad.
    PIPELINE_SPEED = SPEED_MULTIPLIER    # read it before overriding below
    SPEED_MULTIPLIER = 1.0

    TEST_TAKES = 1

    # Tagged, so the test exercises v3 emotion handling and not just clarity.
    test_script = (
        "[excited] A referee just gave a player a red card... by ACCIDENT. [curious] This is François Letexier, the man who refereed the Euro twenty twenty four final. Last Sunday, Marseille played PSG. In the first half, Marseille captain Timothy Weah made a late tackle. The referee reached into his pocket and pulled out... red. [slows down] Weah looked completely shocked. Then the referee smiled, put it away, showed yellow, and said sorry for the scare. [sarcastic] Funny story, right? [gasps] *BUT!* In the second half, Weah fouled again. Second yellow. This time the red was REAL. [deadpan] The referee was just forty five minutes early."
    )

    try:
        for i in range(1, TEST_TAKES + 1):
            raw = generate_voice(
                script_text=test_script,
                filename=f"test_take{i}_raw.mp3",
                voice="animatoryoung",
                lang="en"
            )

            sped = raw.replace("_raw.mp3", "_sped.mp3")
            subprocess.run(
                ["ffmpeg", "-y", "-i", raw, "-filter:a",
                 f"atempo={PIPELINE_SPEED}",
                 "-b:a", f"{_output_bitrate_k()}k", sped],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True
            )

            print(f"🎧 take {i}: {raw}")
            print(f"           {sped}  ({PIPELINE_SPEED}x)")

        print(f"\nListen to raw vs sped. If raw is good and sped is bad, "
              f"atempo is the problem.")
        print(f"Open {AUDIO_DIR}")

    except Exception as e:
        print(f"❌ Test Failed: {e}")