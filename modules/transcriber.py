import whisper
import os
import warnings

# Suppress standard warnings to keep output clean
warnings.filterwarnings("ignore")

# Load the model once. "base" is a good balance of speed and accuracy.
# If you want it faster (but slightly dumber), use "tiny".
# If you want it perfect (but slower), use "small" or "medium".
print("⏳ Loading Whisper AI model (this happens once)...")
model = whisper.load_model("base")


def transcribe_audio_to_groups(audio_path, words_per_group=2):
    """
    Listens to the audio and groups words with exact timestamps.
    Returns: List of (start, end, text)
    """
    if not os.path.exists(audio_path):
        print(f"❌ Audio file not found: {audio_path}")
        return []

    print(f"👂 Transcribing audio for perfect sync: {os.path.basename(audio_path)}...")

    # Transcribe with word-level timestamps
    result = model.transcribe(audio_path, word_timestamps=True)

    final_groups = []
    current_group_words = []
    group_start = 0.0

    # Flatten all words from all segments
    all_words = []
    for segment in result['segments']:
        for word in segment['words']:
            all_words.append(word)

    # Group words into chunks (e.g., 2 words at a time)
    for i, word in enumerate(all_words):
        if not current_group_words:
            group_start = word['start']

        current_group_words.append(word['word'].strip())

        # If group is full OR it's the last word OR there is a long pause
        is_last_word = (i == len(all_words) - 1)
        is_full = (len(current_group_words) >= words_per_group)

        # Check for pauses (if next word is > 0.5s away, break the chunk)
        next_word_dist = 0
        if not is_last_word:
            next_word_dist = all_words[i + 1]['start'] - word['end']

        if is_full or is_last_word or next_word_dist > 0.5:
            group_end = word['end']
            text = " ".join(current_group_words)

            # Clean up punctuation
            text = text.replace(" ,", ",").replace(" .", ".").replace(" !", "!").replace(" ?", "?")

            final_groups.append((group_start, group_end, text))
            current_group_words = []

    print(f"✅ Transcription done: {len(final_groups)} subtitle chunks generated.")
    return final_groups