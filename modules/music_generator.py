import os
import random
from elevenlabs.client import ElevenLabs
from config import MUSIC_DIR, ELEVENLABS_API_KEY

MUSIC_LENGTH_MS = 90_000  # 90 seconds


def generate_music(prompt: str) -> str | None:
    """Generate instrumental music via ElevenLabs and save to MUSIC_DIR."""
    os.makedirs(MUSIC_DIR, exist_ok=True)

    client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

    filename = f"music_{random.randint(10000, 99999)}.mp3"
    output_path = os.path.join(MUSIC_DIR, filename)

    print(f"🎼 Generating music with ElevenLabs...")
    print(f"   Prompt: {prompt}")

    try:
        audio_stream = client.music.compose(
            prompt=prompt,
            music_length_ms=MUSIC_LENGTH_MS,
            force_instrumental=True,
            output_format="mp3_44100_128",
        )

        with open(output_path, "wb") as f:
            for chunk in audio_stream:
                f.write(chunk)

        if os.path.exists(output_path) and os.path.getsize(output_path) > 5000:
            size_mb = os.path.getsize(output_path) / (1024 * 1024)
            print(f"✅ Music generated: {filename} ({size_mb:.2f} MB)")
            return output_path

    except Exception as e:
        print(f"❌ ElevenLabs music generation failed: {e}")
        if os.path.exists(output_path):
            os.remove(output_path)

    # Returns None so the pipeline can continue without music
    return None


if __name__ == "__main__":
    test_prompt = "Epic orchestral cinematic music, dark and dramatic tension, slow build-up with strings and brass, anime battle lore atmosphere"
    path = generate_music(test_prompt)
    if path:
        print(f"🎧 Saved to: {path}")
    else:
        print("❌ Music generation failed")
