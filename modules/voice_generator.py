# modules/voice_generator.py
import os
import torch
from TTS.api import TTS
from TTS.tts.configs.xtts_config import XttsConfig
from TTS.tts.models.xtts import XttsAudioConfig, XttsArgs
from TTS.config.shared_configs import BaseDatasetConfig
from config import DATA_DIR

# Allow Coqui classes for PyTorch 2.6+ unpickling
if hasattr(torch, "serialization") and hasattr(torch.serialization, "add_safe_globals"):
    torch.serialization.add_safe_globals([XttsConfig, XttsAudioConfig, XttsArgs, BaseDatasetConfig])

AUDIO_DIR = os.path.join(DATA_DIR, "audio")
os.makedirs(AUDIO_DIR, exist_ok=True)


def generate_voice(script_text: str, language="en", speaker="Damien Black", filename="narration.wav"):
    print("🎙️  Loading Coqui XTTS v2 model …")
    tts = TTS(model_name="tts_models/multilingual/multi-dataset/xtts_v2", progress_bar=False)

    output_path = os.path.join(AUDIO_DIR, filename)
    print(f"🎧  Generating voice audio with speaker: {speaker}")
    try:
        tts.tts_to_file(
            text=script_text,
            speaker=speaker,
            language=language,
            file_path=output_path,
            temperature=0.9,
            repetition_penalty=1.2,  # must be FLOAT for your transformers version
        )
    except ValueError as e:
        if "repetition_penalty" in str(e).lower():
            print("⚠️ repetition_penalty error — retrying with 1.05")
            tts.tts_to_file(
                text=script_text,
                speaker=speaker,
                language=language,
                file_path=output_path,
                temperature=0.9,
                repetition_penalty=1.05,
            )
        else:
            raise

    print(f"✅  Voice saved to: {output_path}")
    return output_path